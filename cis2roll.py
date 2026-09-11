#!/usr/bin/env python3
"""Prepare a CIS scan for Craig Sapp's roll-image-parser.

tiff2holes was written for the Stanford scans and is calibrated for them
throughout: it wants an uncompressed 24-bit RGB TIFF about 300 dpi, at least
4096 columns wide (analyzeTrackerBarSpacing indexes the first 4096 columns of
the centroid histogram unconditionally), the roll running down the image with
bass at column 0, and holes brighter than the paper.  Its thresholds are
absolute pixel counts tuned at that scale, so the honest way in is to hand it
an image in its own units rather than to retune the thresholds.

A CIS scan is none of those things: one bit per pixel, run-length coded, and
clocked at a different resolution along the roll than across it, so the pixels
are not square either.  This resamples it onto a square-pixel 300 dpi grid and
centres the paper in a 4096-column frame.  Both scales come from the header,
and the tracker pitch they imply is measured back off the holes and reported
as a check on them.

Two things need care beyond the resampling.  The sensor is wider than the roll
and sees the scanner bed beside it, which reads as paper and would otherwise be
measured as part of the roll; the paper is taken to be the widest run of columns
dark on nearly every line, and everything outside it is painted as background.
And a one-bit scan carries isolated lit pixels that an eight-bit one would have
averaged away, which tiff2holes counts as dust; a 3x3 opening removes them.

The scan is written as it was read.  If the roll comes out with the bass on the
right or running up the image, say so with --mirror or --rotate.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cis2image import BLOCK_LINES, PAPER, FormatError, Scan, Spec  # noqa: E402
from mrs2roll import PaperBand, add_run_centres, comb_fit, occupied_cells  # noqa: E402

MM_PER_INCH = 25.4
TARGET_DPI = 300.0  # what tiff2holes is calibrated for
TARGET_WIDTH = 4096  # the width its tracker-spacing FFT assumes
BLOCK_ROWS = 4000
BACKGROUND = 255  # brightness tiff2holes reads as not-paper
EDGE_MARGIN = 16  # columns kept beyond the paper, on top of its wander
SAMPLE_BLOCKS = 24  # places along the roll the paper is measured at
SAMPLE_LINES = 64
FINEST_TRACKS_PER_INCH = 12.5  # bracket for the tracker pitch search
COARSEST_TRACKS_PER_INCH = 5.5


@dataclass(frozen=True)
class Source:
    """The scan as tiff2holes should see it: bass at column 0, roll running down."""

    scan: Scan
    despeckle: bool
    flip_lines: bool
    flip_columns: bool

    def lines(self, first: int, last: int) -> np.ndarray:
        """Lines [first, last), True where light reached the sensor."""
        if self.flip_lines:
            total = self.scan.header.lines
            block = self._read(total - last, total - first)[::-1]
        else:
            block = self._read(first, last)
        return block[:, ::-1] if self.flip_columns else block

    def _read(self, first: int, last: int) -> np.ndarray:
        if not self.despeckle:
            return self.scan.rows("holes", first, last)
        # the opening needs a line of context on each side, or a punch that
        # straddles a block boundary comes out notched
        top = max(0, first - 1)
        bottom = min(self.scan.header.lines, last + 1)
        return open3(self.scan.rows("holes", top, bottom))[first - top : last - top]


@dataclass(frozen=True)
class Calibration:
    band: PaperBand
    pitch: float  # source columns between neighbouring tracker tracks
    coherence: float  # 0..1; how tightly the holes sit on the grid
    tracks_seen: int
    speckle: float  # share of lit pixels the opening removes
    across_dpi: float
    along_dpi: float


def _neighbourhood(mask: np.ndarray):
    """The nine one-pixel shifts of `mask`, with False beyond its border."""
    padded = np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), dtype=bool)
    padded[1:-1, 1:-1] = mask
    rows, columns = mask.shape
    for down in range(3):
        for across in range(3):
            yield padded[down : down + rows, across : across + columns]


def open3(mask: np.ndarray) -> np.ndarray:
    """3x3 opening: drop whatever is narrower than three pixels either way.

    Punches are twenty pixels and more across at these resolutions, so this
    takes out the scan's isolated lit pixels and leaves the music alone."""
    eroded = np.ones_like(mask)
    for view in _neighbourhood(mask):
        eroded &= view
    grown = np.zeros_like(mask)
    for view in _neighbourhood(eroded):
        grown |= view
    return grown


def sample_blocks(scan: Scan):
    """Short blocks of lines spread along the roll."""
    last = max(0, scan.header.lines - SAMPLE_LINES)
    for start in np.linspace(0, last, SAMPLE_BLOCKS):
        first = int(start)
        yield scan.rows("holes", first, min(first + SAMPLE_LINES, scan.header.lines))


def dark_runs(lit: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Start and end column of every run that is dark more often than not."""
    edges = np.flatnonzero(np.diff(np.r_[False, lit <= 0.5, False]))
    return edges[0::2], edges[1::2] - 1


def widest_dark_run(lit: np.ndarray) -> tuple[int, int] | None:
    """First and last column of the longest such run."""
    starts, ends = dark_runs(lit)
    if not starts.size:
        return None
    widest = int(np.argmax(ends - starts))
    return int(starts[widest]), int(ends[widest])


def run_around(lit: np.ndarray, anchor: int) -> tuple[int, int] | None:
    """Extent of the dark run holding `anchor`.

    Anchored just inside the paper, this follows the edge even where a track
    that stays open across the whole block splits the paper in two."""
    starts, ends = dark_runs(lit)
    holding = np.flatnonzero((starts <= anchor) & (ends >= anchor))
    if not holding.size:
        return None
    return int(starts[holding[0]]), int(ends[holding[0]])


def find_paper_band(source: Source) -> PaperBand:
    """The columns the roll occupies, and how far its edges wander.

    A column under the paper is dark on nearly every line, since a track of
    punches is open only briefly.  The bed beside the roll is dark too, so the
    paper is the widest such run rather than the first one."""
    blocks = []
    total = np.zeros(source.scan.header.pixels)
    counted = 0
    for block in sample_blocks(source.scan):
        if source.flip_columns:
            block = block[:, ::-1]
        total += block.sum(axis=0)
        counted += block.shape[0]
        blocks.append(block.mean(axis=0))
    overall = widest_dark_run(total / counted) if counted else None
    if overall is None:
        raise FormatError("could not find the roll paper in the scan")

    left, right = overall
    inset = 8
    lefts = [run[0] for run in (run_around(lit, left + inset) for lit in blocks) if run]
    rights = [run[1] for run in (run_around(lit, right - inset) for lit in blocks) if run]
    wander = max(max(lefts) - min(lefts), max(rights) - min(rights)) if lefts and rights else 0
    return PaperBand(left, right, wander)


def speckle_share(source: Source) -> float:
    """Share of the lit pixels that the opening removes, over sampled lines."""
    if not source.despeckle:
        return 0.0
    lit = removed = 0
    for block in sample_blocks(source.scan):
        lit += int(block.sum())
        removed += int((block & ~open3(block)).sum())
    return removed / lit if lit else 0.0


def hole_histogram(source: Source, band: PaperBand) -> np.ndarray:
    """How often a hole's across-roll centre falls in each column."""
    lines = source.scan.header.lines
    hist = np.zeros(source.scan.header.pixels)
    inset = 4
    for start in range(0, lines, BLOCK_LINES):
        mask = source.lines(start, min(start + BLOCK_LINES, lines))
        mask[:, : band.left + inset] = False
        mask[:, band.right - inset :] = False
        add_run_centres(hist, mask)
    return hist


def calibrate(source: Source) -> Calibration:
    header = source.scan.header
    band = find_paper_band(source)
    hist = hole_histogram(source, band)
    bracket = (header.dpi / FINEST_TRACKS_PER_INCH, header.dpi / COARSEST_TRACKS_PER_INCH)
    pitch, phase, coherence = comb_fit(hist, bracket)
    return Calibration(
        band=band,
        pitch=pitch,
        coherence=coherence,
        tracks_seen=len(occupied_cells(hist, pitch, phase)),
        speckle=speckle_share(source),
        across_dpi=float(header.dpi),
        along_dpi=header.along_dpi,
    )


@dataclass(frozen=True)
class Frame:
    """The output image, and where the scan's columns land in it."""

    rows: int
    width: int
    columns: int  # source columns after the across-roll rescale
    offset: int  # output column that rescaled source column 0 lands on
    keep: tuple[int, int]  # rescaled source columns to copy; the rest is background
    x_scale: float
    y_scale: float

    @classmethod
    def plan(cls, cal: Calibration, scan: Scan, dpi: float, width: int) -> "Frame":
        x_scale = dpi / cal.across_dpi
        y_scale = dpi / cal.along_dpi
        margin = cal.band.wander + EDGE_MARGIN
        keep = (max(0, cal.band.left - margin) * x_scale,
                min(scan.header.pixels, cal.band.right + 1 + margin) * x_scale)
        centre = (cal.band.left + cal.band.right + 1) / 2 * x_scale
        return cls(
            rows=int(round(scan.header.lines * y_scale)),
            width=width,
            columns=int(round(scan.header.pixels * x_scale)),
            offset=int(round(width / 2 - centre)),
            keep=(int(round(keep[0])), int(round(keep[1]))),
            x_scale=x_scale,
            y_scale=y_scale,
        )

    @property
    def span(self) -> tuple[int, int]:
        """Output columns the scan is copied into, clipped to the frame."""
        return (max(0, self.keep[0] + self.offset),
                min(self.width, self.keep[1] + self.offset))


def resample(source: Source, frame: Frame, out: np.ndarray) -> None:
    """Fill `out` with the scan on the square-pixel grid, paper centred.

    Both axes go through one BOX resize, which area-averages; re-thresholding
    at a half keeps the hard edges a one-bit scan has and no others."""
    from PIL import Image

    lines = source.scan.header.lines
    dst0, dst1 = frame.span
    src0, src1 = dst0 - frame.offset, dst1 - frame.offset
    for first in range(0, frame.rows, BLOCK_ROWS):
        last = min(first + BLOCK_ROWS, frame.rows)
        top = first / frame.y_scale
        # rounding the row count up can put the last block a fraction of a
        # line past the scan, which PIL refuses
        bottom = min(last / frame.y_scale, lines)
        read0, read1 = max(0, int(np.floor(top))), min(lines, int(np.ceil(bottom)))
        block = source.lines(read0, read1)
        scaled = Image.fromarray(block.astype(np.uint8) * 255).resize(
            (frame.columns, last - first),
            Image.BOX,
            box=(0, top - read0, block.shape[1], bottom - read0),
        )
        lit = np.asarray(scaled) >= 128
        plane = np.full((last - first, frame.width), BACKGROUND, dtype=np.uint8)
        plane[:, dst0:dst1] = np.where(lit[:, src0:src1], BACKGROUND, PAPER)
        out[first:last] = plane[:, :, None]


@contextmanager
def rgb_tiff(path: Path, rows: int, cols: int, dpi: float):
    """An uncompressed 24-bit RGB TIFF in one strip, memory-mapped for writing."""
    import tifffile

    image = tifffile.memmap(
        str(path),
        shape=(rows, cols, 3),
        dtype=np.uint8,
        photometric="rgb",
        planarconfig="contig",
        resolution=(dpi, dpi),
        resolutionunit="INCH",
        rowsperstrip=rows,
        software="cis2roll",
        metadata=None,
        extratags=[(274, "H", 1, 1, True)],  # Orientation: first row at the top
    )
    try:
        yield image
        image.flush()
    finally:
        del image


def report(source: Source, cal: Calibration, frame: Frame) -> str:
    scan = source.scan
    h, b = scan.header, cal.band
    paper = b.width + 1
    pitch_in = cal.pitch / cal.across_dpi
    target_dpi = cal.along_dpi * frame.y_scale
    lines = [
        f"file          {scan.path.name}",
        f"source        {h.lines} lines x {h.pixels} pixels, "
        f"{cal.across_dpi:g} dpi across, {cal.along_dpi:g} dpi along"
        + ("; the early header states no across dpi, so that figure is assumed "
           "and the across scale rests on it" if h.spec is Spec.EARLY else ""),
        f"paper band    columns {b.left}..{b.right} ({paper} px = "
        f"{paper / cal.across_dpi:.3f} in), wander {b.wander} px",
        f"tracker grid  pitch {cal.pitch:.3f} px = {pitch_in:.4f} in = "
        f"{pitch_in * MM_PER_INCH:.3f} mm ({1 / pitch_in:.2f} tracks/in), "
        f"coherence {cal.coherence:.3f}, {cal.tracks_seen} tracks occupied",
        "despeckle     "
        + (f"3x3 opening, {cal.speckle * 100:.2f}% of lit pixels removed"
           if source.despeckle else "off"),
        f"roll tempo    {h.tempo} as printed, i.e. {h.tempo / 10:.1f} ft/min; "
        f"tiff2holes wants setTPQ({round(h.tempo * target_dpi / 50)}) for that"
        if h.tempo else "roll tempo    not recorded in the header",
        f"scale         x {frame.x_scale:.5f}, y {frame.y_scale:.5f}",
        f"output        {frame.rows} rows x {frame.width} cols, "
        f"paper {paper * frame.x_scale:.0f} px, "
        f"tracker spacing {cal.pitch * frame.x_scale:.3f} px",
        f"frame columns {frame.span[0]}..{frame.span[1] - 1} carry the scan",
    ]
    return "\n".join(lines)


def parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help=".CIS")
    parser.add_argument("output", type=Path, nargs="?", help=".tif")
    parser.add_argument("--dpi", type=float, default=TARGET_DPI)
    parser.add_argument("--width", type=int, default=TARGET_WIDTH)
    parser.add_argument("--rotate", action="store_true",
                        help="turn by 180 degrees: the view on the piano")
    parser.add_argument("--mirror", action="store_true",
                        help="mirror across the roll, for a scan with the bass on the right")
    parser.add_argument("--no-despeckle", action="store_true",
                        help="keep the scan's isolated lit pixels")
    parser.add_argument("--dry-run", action="store_true", help="calibrate and stop")
    return parser.parse_args(argv)


def convert(args) -> int:
    scan = Scan.read(args.input)
    source = Source(
        scan=scan,
        despeckle=not args.no_despeckle,
        flip_lines=args.rotate,
        flip_columns=args.rotate ^ args.mirror,
    )
    if scan.header.mirrored or scan.header.reversed:
        print("note: the header marks this scan mirrored or reversed; "
              "check which way the roll comes out", file=sys.stderr)

    cal = calibrate(source)
    frame = Frame.plan(cal, scan, args.dpi, args.width)
    print(report(source, cal, frame))
    if args.dry_run or not args.output:
        return 0
    if frame.width < 4096:
        print(f"note: {frame.width} columns is narrower than the 4096 tiff2holes "
              "assumes for its tracker-spacing transform", file=sys.stderr)

    with rgb_tiff(args.output, frame.rows, frame.width, args.dpi) as image:
        resample(source, frame, image)
    print(f"wrote {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return convert(args)
    except (FormatError, ValueError, OSError) as error:
        print(f"cis2roll: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
