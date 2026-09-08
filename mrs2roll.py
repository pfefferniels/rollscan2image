#!/usr/bin/env python3
"""Prepare an MRS scan for Craig Sapp's roll-image-parser.

tiff2holes was written for the Stanford scans and is calibrated for them
throughout: it wants an uncompressed 24-bit RGB TIFF about 300 dpi, at least
4096 columns wide (analyzeTrackerBarSpacing indexes the first 4096 columns of
the centroid histogram unconditionally), the roll running down the image with
bass at column 0, and holes brighter than the paper.  Its thresholds are
absolute pixel counts tuned at that scale, so the honest way in is to hand it
an image in its own units rather than to retune the thresholds.

An MRS scan is none of those things: 8-bit, 2048 samples across, and about
123 dpi across against 127 dpi along, so the pixels are not square either.
This resamples it onto a square-pixel 300 dpi grid, using the roll's own
tracker-hole spacing as the across-roll ruler, and centres the paper in a
4096-column frame.

The across-roll scale is measured, not assumed: the tracker grid is recovered
from the scan by a comb fit over the holes, restricted to the compass the roll
actually plays.  The along-roll scale is the transport's design step of 0.2 mm
per line, which Debrunner states and the colour scan's reported length confirms
to within 0.04 %.

The across axis is also straightened.  The camera's tracker columns do not sit
on a straight grid: they run about half a pitch in from where one puts them at
either paper edge, which is enough for roll-image-parser, whose grid is straight
by construction, to read an expression track as its neighbour.  The departure is
an odd cubic about the middle of the sensor, so it is fitted from the roll's own
columns and undone while resampling.  `--no-straighten` leaves it in place.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mrs2image import RollScan, FlatField, sibling_settings_csv  # noqa: E402

MM_PER_INCH = 25.4
NOMINAL_LINES_PER_MM = 5.0  # transport step of both MRS sensors
TARGET_DPI = 300.0  # what tiff2holes is calibrated for
TARGET_WIDTH = 4096  # the width its tracker-spacing FFT assumes
BLOCK_ROWS = 4000
MIN_CELL_MASS = 200  # histogram mass below which a column is dust, not a track
GRID_REFINEMENTS = 3  # passes of fit, reassign indices, fit again


@dataclass(frozen=True)
class PaperBand:
    """The columns the roll paper occupies, and how steady it is."""

    left: int
    right: int
    wander: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def centre(self) -> float:
        return (self.left + self.right) / 2


@dataclass(frozen=True)
class TrackGrid:
    """The tracker-hole grid, recovered from the holes themselves."""

    pitch: float  # columns between neighbouring tracks
    phase: float  # column of the grid line at index 0
    coherence: float  # 0..1; how tightly the holes sit on the grid
    tracks_seen: int
    pitch_error: float  # standard error of the pitch, in columns
    residual: float  # rms distance of a track centre from the grid, in columns


@dataclass(frozen=True)
class Barrel:
    """Cubic distortion of the across-roll axis, odd about the sensor centre."""

    centre: float  # source column the distortion is symmetric about
    k3: float  # a track at true offset p from the centre is imaged at p + k3 p^3
    pitch: float  # track pitch at the centre, in source columns
    rms: float  # rms of the track centres about the cubic, in columns
    linear_rms: float  # the same about a straight grid

    def image_of(self, columns: np.ndarray) -> np.ndarray:
        """Where the camera puts the tracks that belong at these columns."""
        offset = columns - self.centre
        return self.centre + offset + self.k3 * offset**3

    def edge_shift(self, band: PaperBand) -> tuple[float, float]:
        """Displacement at either paper edge, in track pitches."""
        edges = np.array([band.left, band.right], dtype=float) - self.centre
        return tuple(self.k3 * edges**3 / self.pitch)


@dataclass(frozen=True)
class Calibration:
    band: PaperBand
    grid: TrackGrid
    straighten: bool  # whether a barrel was asked for
    barrel: Barrel | None  # whether one could be measured
    across_px_per_mm: float
    along_px_per_mm: float
    track_pitch_mm: float

    @property
    def across_dpi(self) -> float:
        return self.across_px_per_mm * MM_PER_INCH

    @property
    def along_dpi(self) -> float:
        return self.along_px_per_mm * MM_PER_INCH


def track_pitch_mm(scan: RollScan) -> float:
    """Track spacing in mm, from the roll type recorded in the trailer."""
    roll = scan.metadata.get("Rolltype", {})
    try:
        first = float(roll["First Track"])
        last = float(roll["Last Track"])
        count = int(roll["Number Of Tracks"])
    except (KeyError, ValueError) as error:
        raise SystemExit(
            "no [Rolltype] track geometry in the trailer; pass --track-pitch"
        ) from error
    return (last - first) / (count - 1)


def _hole_mask(block: np.ndarray, gains: np.ndarray | None, threshold: float):
    grey = block.mean(axis=2)
    if gains is not None:
        grey = grey * gains
    return grey > threshold


def find_paper_band(scan: RollScan, gains, paper_max) -> PaperBand:
    lefts, rights = [], []
    for line in np.linspace(0.05, 0.95, 12) * scan.geometry.lines:
        start = int(line)
        block = scan.lines(start, min(start + 40, scan.geometry.lines))
        grey = block.mean(axis=2)
        if gains is not None:
            grey = grey * gains
        dark = np.flatnonzero(np.median(grey, axis=0) < paper_max)
        if len(dark) > scan.geometry.samples // 4:
            lefts.append(int(dark[0]))
            rights.append(int(dark[-1]))
    if not lefts:
        raise SystemExit("could not locate the paper edges")
    wander = max(max(lefts) - min(lefts), max(rights) - min(rights))
    return PaperBand(int(np.median(lefts)), int(np.median(rights)), wander)


def hole_histogram(scan: RollScan, band: PaperBand, gains, hole_min) -> np.ndarray:
    """How often a hole's across-roll centre falls in each column."""
    width = scan.geometry.samples
    hist = np.zeros(width)
    inset = 4
    for start in range(0, scan.geometry.lines, BLOCK_ROWS):
        stop = min(start + BLOCK_ROWS, scan.geometry.lines)
        mask = _hole_mask(scan.lines(start, stop), gains, hole_min)
        mask[:, : band.left + inset] = False
        mask[:, band.right - inset :] = False
        padded = np.zeros((mask.shape[0], width + 2), dtype=bool)
        padded[:, 1:-1] = mask
        edge = np.diff(padded.astype(np.int8), axis=1)
        _, opens = np.nonzero(edge == 1)
        _, closes = np.nonzero(edge == -1)
        np.add.at(hist, np.rint((opens + closes - 1) / 2).astype(int), 1)
    return hist


MAX_UNUSED_RUN = 6  # empty tracks that may interrupt the played compass


def comb_fit(hist: np.ndarray, search: tuple[float, float]) -> tuple[float, float, float]:
    """The pitch at which the hole centres in `hist` line up best.

    Maximising |sum w exp(2 pi i x / p)| is a circular-mean fit, so it uses
    every hole rather than a handful of detected peaks, and it does not need
    to know which tracks the roll actually uses."""
    columns = np.flatnonzero(hist).astype(float)
    weights = hist[hist > 0]
    if weights.sum() < 1000:
        raise SystemExit("too few holes to measure the tracker grid")

    def coherence(period: float) -> float:
        return abs(np.sum(weights * np.exp(2j * np.pi * columns / period))) / weights.sum()

    coarse = np.arange(search[0], search[1], 0.002)
    pitch = coarse[np.argmax([coherence(p) for p in coarse])]
    fine = np.arange(pitch - 0.02, pitch + 0.02, 0.00005)
    scores = np.array([coherence(p) for p in fine])
    pitch = float(fine[scores.argmax()])
    angle = np.angle(np.sum(weights * np.exp(2j * np.pi * columns / pitch)))
    return pitch, float((-angle / (2 * np.pi)) * pitch % pitch), float(scores.max())


def played_compass(hist: np.ndarray, pitch: float, phase: float) -> tuple[int, int]:
    """Column range of the longest unbroken run of tracks the roll plays.

    A roll only pins down the grid where it uses it, and a straight comb over the
    whole paper reads low because the camera bends the columns inwards at both
    edges (see `measure_barrel`), so the pitch is remeasured over this range."""
    cells = np.array(occupied_cells(hist, pitch, phase))
    if len(cells) < 4:
        return 0, len(hist)
    breaks = np.flatnonzero(np.diff(cells) > MAX_UNUSED_RUN + 1)
    runs = np.split(cells, breaks + 1)
    best = max(runs, key=lambda r: sum(cell_mass(hist, pitch, phase, k) for k in r))
    lo = int(phase + pitch * (best[0] - 0.5))
    hi = int(phase + pitch * (best[-1] + 0.5)) + 1
    return max(0, lo), min(len(hist), hi)


def cell_mass(hist: np.ndarray, pitch: float, phase: float, k: int) -> float:
    """Holes in track cell k, or 0 if the cell falls outside the sensor."""
    centre = phase + pitch * k
    lo, hi = int(centre - pitch / 2), int(centre + pitch / 2) + 1
    if lo < 0 or hi > len(hist):
        return 0.0
    total = float(hist[lo:hi].sum())
    return total if total >= MIN_CELL_MASS else 0.0


def occupied_cells(hist: np.ndarray, pitch: float, phase: float) -> list[int]:
    """The grid cells that carry holes, in track-index order."""
    return [k for k in range(-4, int(len(hist) / pitch) + 4) if cell_mass(hist, pitch, phase, k)]


def measure_track_grid(hist: np.ndarray, search: tuple[float, float]) -> TrackGrid:
    pitch, phase, _ = comb_fit(hist, search)
    lo, hi = played_compass(hist, pitch, phase)
    trimmed = np.zeros_like(hist)
    trimmed[lo:hi] = hist[lo:hi]
    pitch, phase, coherence = comb_fit(trimmed, search)
    error, residual = pitch_uncertainty(trimmed, pitch, phase)
    return TrackGrid(
        pitch,
        phase,
        coherence,
        len(occupied_cells(trimmed, pitch, phase)),
        error,
        residual,
    )


def pitch_uncertainty(hist: np.ndarray, pitch: float, phase: float) -> tuple[float, float]:
    """Standard error of the pitch, from how far each track centre sits off it.

    The comb gives no error bar of its own, so this measures the same grid a
    second way — one centroid per occupied cell, regressed on the integer track
    index — and reports the scatter about that line.  A low-mass track beside a
    much heavier one has its centroid pulled toward the neighbour, so the
    scatter is partly the estimator's and the error bar is, if anything,
    conservative."""
    cells = occupied_cells(hist, pitch, phase)
    if len(cells) < 4:
        return float("nan"), float("nan")
    index = np.array(cells, dtype=float)
    centre = np.array([cell_centroid(hist, pitch, phase, k) for k in cells])
    mass = np.array([cell_mass(hist, pitch, phase, k) for k in cells])
    root = np.sqrt(mass)
    design = np.vstack([np.ones_like(index), index]).T * root[:, None]
    offset, slope = np.linalg.lstsq(design, centre * root, rcond=None)[0]
    residual = centre - (offset + slope * index)
    n = len(index)
    weight = mass / mass.sum()
    spread = (weight * (index - (weight * index).sum()) ** 2).sum() * n
    variance = (weight * residual**2).sum() * n / (n - 2)
    return float(np.sqrt(variance / spread)), float(np.sqrt((weight * residual**2).sum()))


def cell_centroid(hist: np.ndarray, pitch: float, phase: float, k: int) -> float:
    centre = phase + pitch * k
    lo, hi = int(centre - pitch / 2), int(centre + pitch / 2) + 1
    window = hist[lo:hi]
    return float((window * np.arange(lo, hi)).sum() / window.sum())


def hole_columns(hist: np.ndarray, gap: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """The hole histogram's peaks as (centre, mass), one per tracker column.

    Grouping runs of the histogram finds the columns where they actually are,
    which a grid of cells cannot do once a track sits half a pitch off its cell."""
    filled = np.flatnonzero(hist)
    runs = np.split(filled, np.flatnonzero(np.diff(filled) > gap) + 1)
    peaks = [
        (float((run * hist[run]).sum() / hist[run].sum()), float(hist[run].sum()))
        for run in runs
        if hist[run].sum() >= MIN_CELL_MASS
    ]
    centre, mass = map(np.asarray, zip(*peaks)) if peaks else (np.empty(0), np.empty(0))
    return centre, mass


def cubic_grid(index, centre, mass, origin) -> tuple[float, float, float]:
    """Weighted least-squares fit of `base + slope x + cubic x^3`, x = index - origin."""
    x = index - origin
    root = np.sqrt(mass)
    design = np.vstack([np.ones_like(x), x, x**3]).T * root[:, None]
    return tuple(np.linalg.lstsq(design, centre * root, rcond=None)[0])


def track_indices(centre, base, slope, cubic, origin, span) -> np.ndarray | None:
    """Track index of each column centre, by inverting the fitted grid."""
    index = np.linspace(span[0] - 3, span[1] + 3, 8000)
    model = base + slope * (index - origin) + cubic * (index - origin) ** 3
    if not np.all(np.diff(model) > 0):
        return None  # a grid that doubles back is not one to read indices off
    return np.rint(np.interp(centre, model, index))


def measure_barrel(hist: np.ndarray, band: PaperBand, pitch: float) -> Barrel | None:
    """Fit a cubic across-roll distortion to the tracker columns.

    roll-image-parser assumes a straight tracker grid, which is what the Stanford
    scans deliver.  This camera images the tracks about half a pitch in from where
    a straight grid puts them at either paper edge, enough to read an expression
    track as its neighbour, and the cubic is odd about the middle of the sensor as
    radial distortion is.

    A roll is its own and only ruler here, so this returns None unless the roll
    punches near both paper edges: one that keeps to the middle cannot measure
    the ends, and a cubic extrapolated from the middle would do harm."""
    centre, mass = hole_columns(hist)
    reach = band.width / 4
    if len(centre) < 8 or centre.min() > band.left + reach or centre.max() < band.right - reach:
        return None

    index = np.concatenate([[0.0], np.cumsum(np.rint(np.diff(centre) / pitch))])
    origin = float(np.average(index, weights=mass))
    for _ in range(GRID_REFINEMENTS):
        base, slope, cubic = cubic_grid(index, centre, mass, origin)
        refined = track_indices(centre, base, slope, cubic, origin, (index.min(), index.max()))
        if refined is None:
            return None
        index = refined
    base, slope, cubic = cubic_grid(index, centre, mass, origin)

    def rms(residual: np.ndarray) -> float:
        return float(np.sqrt(np.average(residual**2, weights=mass)))

    straight = np.polyfit(index, centre, 1, w=np.sqrt(mass))
    return Barrel(
        centre=base,
        k3=cubic / slope**3,
        pitch=slope,
        rms=rms(centre - (base + slope * (index - origin) + cubic * (index - origin) ** 3)),
        linear_rms=rms(centre - np.polyval(straight, index)),
    )


def calibrate(scan: RollScan, gains, paper_max, hole_min, pitch_mm, straighten) -> Calibration:
    band = find_paper_band(scan, gains, paper_max)
    hist = hole_histogram(scan, band, gains, hole_min)
    rough = band.width / 105.0, band.width / 98.0  # 100 tracks, generous bracket
    grid = measure_track_grid(hist, rough)
    barrel = measure_barrel(hist, band, grid.pitch) if straighten else None
    pitch = barrel.pitch if barrel else grid.pitch
    return Calibration(
        band=band,
        grid=grid,
        straighten=straighten,
        barrel=barrel,
        across_px_per_mm=pitch / pitch_mm,
        along_px_per_mm=NOMINAL_LINES_PER_MM,
        track_pitch_mm=pitch_mm,
    )


@dataclass(frozen=True)
class Frame:
    """The source window that maps onto the output image."""

    left: float  # source column mapped to output column 0
    right: float  # source column mapped to output column `width`
    width: int
    rows: int
    x_scale: float
    y_scale: float

    @classmethod
    def plan(cls, cal: Calibration, lines: int, dpi: float, width: int) -> "Frame":
        target = dpi / MM_PER_INCH
        x_scale = target / cal.across_px_per_mm
        y_scale = target / cal.along_px_per_mm
        span = width / x_scale  # source columns that fill the frame
        left = cal.band.centre - span / 2
        return cls(left, left + span, width, int(round(lines * y_scale)), x_scale, y_scale)


def column_map(frame: Frame, barrel: Barrel | None, samples: int):
    """Source column to sample for each output column, as index and weight."""
    wanted = np.linspace(frame.left, frame.right, frame.width, endpoint=False)
    if barrel is not None:
        wanted = barrel.image_of(wanted)
    lower = np.clip(np.floor(wanted), 0, samples - 2).astype(int)
    return lower, np.clip(wanted - lower, 0.0, 1.0).astype(np.float32)


def resample(scan: RollScan, frame: Frame, gains, barrel, out: np.ndarray) -> None:
    """Fill `out` (rows, width) with the scan resampled onto the square grid.

    The rows scale by themselves; the columns go through `column_map`, which is
    a plain stretch when there is no barrel to undo and bends when there is."""
    from PIL import Image

    samples = scan.geometry.samples
    lower, weight = column_map(frame, barrel, samples)
    for first in range(0, frame.rows, BLOCK_ROWS):
        last = min(first + BLOCK_ROWS, frame.rows)
        top = first / frame.y_scale
        # rounding the row count up can put the last block a fraction of a
        # line past the scan, which PIL refuses
        bottom = min(last / frame.y_scale, scan.geometry.lines)
        src0 = max(0, int(np.floor(top)) - 2)
        src1 = min(scan.geometry.lines, int(np.ceil(bottom)) + 2)
        block = scan.lines(src0, src1).mean(axis=2)
        if gains is not None:
            block = block * gains
        source = Image.fromarray(np.clip(block, 0, 255).astype(np.uint8))
        lines = np.asarray(
            source.resize(
                (samples, last - first),
                Image.BILINEAR,
                box=(0, top - src0, samples, bottom - src0),
            ),
            dtype=np.float32,
        )
        out[first:last] = np.rint(
            lines[:, lower] * (1.0 - weight) + lines[:, lower + 1] * weight
        )


def write_rgb_tiff(path: Path, plane: np.ndarray, dpi: float) -> None:
    import tifffile

    rows, cols = plane.shape
    image = tifffile.memmap(
        str(path),
        shape=(rows, cols, 3),
        dtype=np.uint8,
        photometric="rgb",
        planarconfig="contig",
        resolution=(dpi, dpi),
        resolutionunit="INCH",
        rowsperstrip=rows,
        software="mrs2roll",
        metadata=None,
        extratags=[(274, "H", 1, 1, True)],
    )
    try:
        for first in range(0, rows, BLOCK_ROWS):
            last = min(first + BLOCK_ROWS, rows)
            image[first:last] = plane[first:last, :, None]
        image.flush()
    finally:
        del image


def barrel_lines(cal: Calibration) -> list[str]:
    if not cal.straighten:
        return ["barrel        straightening off; the camera's distortion is left in place"]
    if cal.barrel is None:
        return ["barrel        not measured; the holes do not reach both paper edges"]
    bar = cal.barrel
    bass, treble = bar.edge_shift(cal.band)
    return [
        f"barrel        k3 {bar.k3:+.4e} /px^2 about column {bar.centre:.1f}, "
        f"pitch {bar.pitch:.3f} px at the centre",
        f"              track centres {bar.rms:.2f} px off the cubic "
        f"against {bar.linear_rms:.2f} px off a straight grid; "
        f"paper edges shift {bass:+.2f} and {treble:+.2f} pitches",
    ]


def report(scan: RollScan, cal: Calibration, frame: Frame) -> str:
    g, b = cal.grid, cal.band
    return "\n".join(
        [
            f"source        {scan.geometry.lines} lines x {scan.geometry.samples} samples",
            f"paper band    columns {b.left}..{b.right} ({b.width} px), wander {b.wander} px",
            f"tracker grid  pitch {g.pitch:.3f} +/- {g.pitch_error:.3f} px, "
            f"coherence {g.coherence:.3f}, {g.tracks_seen} tracks occupied, "
            f"grid residual {g.residual:.2f} px",
            *barrel_lines(cal),
            f"track pitch   {cal.track_pitch_mm:.5f} mm (nominal, from the roll trailer)",
            f"across        {cal.across_px_per_mm:.3f} px/mm = {cal.across_dpi:.1f} dpi "
            f"(+/- {cal.across_dpi * g.pitch_error / g.pitch:.1f} from the pitch alone; "
            f"the nominal mm above is the larger unknown)",
            f"along         {cal.along_px_per_mm:.4f} px/mm = {cal.along_dpi:.2f} dpi "
            f"(0.2 mm/line design step)",
            f"scale         x {frame.x_scale:.5f}, y {frame.y_scale:.5f}",
            f"output        {frame.rows} rows x {frame.width} cols, "
            f"paper {b.width * frame.x_scale:.0f} px, "
            f"tracker spacing {g.pitch * frame.x_scale:.3f} px",
            f"source window columns {frame.left:.1f}..{frame.right:.1f}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help=".mrs or .mrsc")
    parser.add_argument("output", type=Path, nargs="?", help=".tif")
    parser.add_argument("--dpi", type=float, default=TARGET_DPI)
    parser.add_argument("--width", type=int, default=TARGET_WIDTH)
    parser.add_argument("--track-pitch", type=float, help="mm, overrides the trailer")
    parser.add_argument("--paper-max", type=float, default=150.0,
                        help="brightness below which a sample is paper")
    parser.add_argument("--hole-min", type=float, default=170.0,
                        help="brightness above which a sample is a hole")
    parser.add_argument("--no-straighten", action="store_true",
                        help="leave the camera's across-roll distortion in place")
    parser.add_argument("--dry-run", action="store_true", help="calibrate and stop")
    args = parser.parse_args(argv)

    with RollScan(args.input) as scan:
        gains = None
        if scan.geometry.channels == 3:
            flat = FlatField.from_settings_csv(sibling_settings_csv(args.input))
            gains = flat.gains(scan.geometry.samples) if flat else None
        pitch_mm = args.track_pitch or track_pitch_mm(scan)
        cal = calibrate(scan, gains, args.paper_max, args.hole_min, pitch_mm,
                        not args.no_straighten)
        frame = Frame.plan(cal, scan.geometry.lines, args.dpi, args.width)
        print(report(scan, cal, frame))
        if args.dry_run or not args.output:
            return 0
        if frame.left < 0 or frame.right > scan.geometry.samples:
            print(
                f"note: the {args.width}-column frame reaches past the sensor; "
                "edges will be clamped",
                file=sys.stderr,
            )
        plane = np.zeros((frame.rows, frame.width), dtype=np.uint8)
        resample(scan, frame, gains, cal.barrel, plane)
        write_rgb_tiff(args.output, plane, args.dpi)
        print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
