#!/usr/bin/env python3
"""Convert MRS piano-roll scanner files (.mrs, .mrsc) to TIFF or PNG.

The scanner writes two rasters per roll: a monochrome backlit scan (.mrs) and
a colour reflective scan (.mrsc).  Both use the same container:

    bytes 0..123    ASCII header, three fixed-width fields
    then            "$%09d" chunk marker, chunk payload, "$%09d", ...
    then            "$999999999"
    then (.mrs)     INI trailer with soundtrack and roll-type metadata

A chunk is one scan line in .mrsc and 1000 scan lines in .mrs; Datasize in the
header counts the markers as well as the pixels.

The scanner's own delivered PNG is the .mrsc put through three steps, which
--like-png reproduces (93 % of pixels bit-identical on WR0225_02, none off by
more than one level): the trilinear sensor's colour rows are registered by
advancing green by MRSC_SpatialCorrOfOneColor lines and red by twice that,
which costs the last 2 x 9 lines; the parabolic across-track brightness curve
from the settings CSV is divided out; and the result is mirrored across the
roll.  The two rasters share the along-roll step and the across-roll
orientation, but not the across-roll resolution.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HEADER_BYTES = 124
MARKER_BYTES = 10
MARKER = re.compile(rb"\$[0-9]{9}")
END_MARKER = b"$999999999"
BLOCK_LINES = 2000


class FormatError(Exception):
    """The file does not follow the MRS container layout."""


@dataclass(frozen=True)
class ScanHeader:
    head_size: int
    date: str
    version: str
    scan_number: int
    data_size: int

    @classmethod
    def parse(cls, raw: bytes) -> "ScanHeader":
        text = raw[:HEADER_BYTES].decode("latin-1")
        fields = re.match(
            r"Headsize in Bytes = (\d{10}) "
            r"Date = ([\d.]+), MRS \w+ Nr = (\S+), Scan Number = (\d{10});"
            r"Datasize in Bytes = (\d{10})",
            text,
        )
        if fields is None:
            raise FormatError(f"unrecognised header: {text!r}")
        return cls(
            head_size=int(fields[1]),
            date=fields[2],
            version=fields[3],
            scan_number=int(fields[4]),
            data_size=int(fields[5]),
        )


@dataclass(frozen=True)
class Geometry:
    samples: int  # pixels across the roll
    channels: int
    lines: int  # scan lines along the roll
    chunk_lines: int  # scan lines between two chunk markers

    @property
    def line_bytes(self) -> int:
        return self.samples * self.channels

    def line_offset(self, line: int) -> int:
        return (
            HEADER_BYTES
            + MARKER_BYTES
            + line * self.line_bytes
            + (line // self.chunk_lines) * MARKER_BYTES
        )


@dataclass(frozen=True)
class FlatField:
    """Parabolic across-track brightness curve measured by the scanner."""

    a: float
    b: float
    c: float

    def gains(self, samples: int) -> np.ndarray:
        x = np.arange(samples, dtype=np.float64)
        curve = self.a * x * x + self.b * x + self.c
        if curve.min() <= 0:
            raise FormatError("brightness curve is not positive over the sensor")
        return curve.max() / curve

    @classmethod
    def from_settings_csv(cls, path: Path) -> "FlatField | None":
        """The scanner spells the setting "Courve"; keep its spelling."""
        if _settings_flag(path, "MRSC_Brightness_Correction_Enable") is not True:
            return None
        terms = [
            _settings_value(path, f"MRSC_Brightness_Courve_{k}") for k in "ABC"
        ]
        if any(t is None for t in terms):
            return None
        return cls(*terms)


def _divisors(n: int) -> list[int]:
    small = [d for d in range(1, int(n**0.5) + 1) if n % d == 0]
    return sorted(set(small + [n // d for d in small]))


def _detect_line_bytes(
    data: memoryview, chunk_bytes: int, channels: int, data_start: int
) -> int:
    """Pick the scan-line length: the shortest chunk divisor whose successive
    lines actually resemble each other.

    A chunk holds a whole number of scan lines, so the line length divides it.
    .mrsc leaves only one candidate; .mrs chunks a thousand lines at a time."""
    candidates = [
        d for d in _divisors(chunk_bytes) if 256 <= d <= 65536 and d % channels == 0
    ]
    if not candidates:
        raise FormatError(f"no plausible line length divides {chunk_bytes}")
    if len(candidates) == 1:
        return candidates[0]

    window = np.frombuffer(
        data[data_start : data_start + 4 * 1024 * 1024], dtype=np.uint8
    ).astype(np.float32)

    def similarity(stride: int) -> float:
        rows = window[: len(window) // stride * stride].reshape(-1, stride)
        if len(rows) < 8:
            return -1.0
        a, b = rows[:-1], rows[1:]
        a = a - a.mean(axis=1, keepdims=True)
        b = b - b.mean(axis=1, keepdims=True)
        norm = np.sqrt((a * a).sum(1) * (b * b).sum(1))
        return float(np.median((a * b).sum(1) / np.where(norm > 0, norm, 1)))

    scores = {d: similarity(d) for d in candidates}
    best = max(scores.values())
    return min(d for d, s in scores.items() if s >= 0.9 * best)


class RollScan:
    """Random access to the scan lines of one .mrs/.mrsc file."""

    def __init__(self, path: Path, channels: int | None = None):
        self.path = path
        self._file = open(path, "rb")
        try:
            raw = self._file.read(HEADER_BYTES + 64)
            self.header = ScanHeader.parse(raw)
            self.channels = channels or (3 if path.suffix.lower() == ".mrsc" else 1)
            self.geometry = self._read_geometry()
            self.metadata = self._read_trailer()
        except Exception:
            self._file.close()
            raise

    def _read_geometry(self) -> Geometry:
        size = self.path.stat().st_size
        head = memoryview(self._read_at(0, min(8 << 20, size)))
        markers = [m.start() for m in itertools.islice(MARKER.finditer(head), 2)]
        if len(markers) < 2 or markers[0] != HEADER_BYTES:
            raise FormatError("chunk markers not found where expected")
        chunk_bytes = markers[1] - markers[0] - MARKER_BYTES
        line_bytes = _detect_line_bytes(
            head, chunk_bytes, self.channels, HEADER_BYTES + MARKER_BYTES
        )
        # Datasize spans the opening and closing markers too; between the
        # chunks sit as many separators as there are chunk boundaries.
        payload = self.header.data_size - 2 * MARKER_BYTES
        chunks = -(-payload // (chunk_bytes + MARKER_BYTES))
        lines = (payload - (chunks - 1) * MARKER_BYTES) // line_bytes
        return Geometry(
            samples=line_bytes // self.channels,
            channels=self.channels,
            lines=lines,
            chunk_lines=chunk_bytes // line_bytes,
        )

    def _read_trailer(self) -> dict[str, dict[str, str]]:
        size = self.path.stat().st_size
        tail = self._read_at(max(0, size - (1 << 20)), 1 << 20)
        end = tail.rfind(END_MARKER)
        if end < 0:
            return {}
        text = tail[end + len(END_MARKER) :].decode("latin-1")
        text = re.sub(r"^Def\.size in Bytes = \d{10}", "", text)
        sections: dict[str, dict[str, str]] = {}
        current = sections.setdefault("", {})
        for row in re.sub(r"(\[[^\]\r\n]+\])", r"\r\n\1\r\n", text).splitlines():
            row = row.strip()
            if row.startswith("[") and row.endswith("]"):
                current = sections.setdefault(row[1:-1], {})
            elif "=" in row:
                key, _, value = row.partition("=")
                current[key.strip()] = value.strip()
        return {k: v for k, v in sections.items() if v}

    def _read_at(self, offset: int, count: int) -> bytes:
        self._file.seek(offset)
        return self._file.read(count)

    def lines(self, start: int, stop: int) -> np.ndarray:
        """Scan lines [start, stop) as (n, samples, channels) uint8."""
        g = self.geometry
        pieces, line = [], start
        while line < stop:
            chunk_end = (line // g.chunk_lines + 1) * g.chunk_lines
            upto = min(stop, chunk_end)
            raw = self._read_at(g.line_offset(line), (upto - line) * g.line_bytes)
            if len(raw) != (upto - line) * g.line_bytes:
                raise FormatError(f"file ends inside line range {line}..{upto}")
            pieces.append(np.frombuffer(raw, dtype=np.uint8))
            line = upto
        return np.concatenate(pieces).reshape(stop - start, g.samples, g.channels)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "RollScan":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass(frozen=True)
class Pipeline:
    """Post-processing applied to raw scan lines, in the scanner's own order."""

    channel_lag: tuple[int, ...] = ()  # extra lines to advance each channel
    flat_field: FlatField | None = None
    mirror: bool = False

    @property
    def lead(self) -> int:
        return max(self.channel_lag, default=0)

    def apply(self, block: np.ndarray) -> np.ndarray:
        """block holds `n + lead` lines; returns the first n, processed."""
        n = len(block) - self.lead
        if self.channel_lag:
            block = np.stack(
                [block[lag : lag + n, :, c] for c, lag in enumerate(self.channel_lag)],
                axis=2,
            )
        else:
            block = block[:n]
        if self.flat_field is not None:
            gains = self.flat_field.gains(block.shape[1])[None, :, None]
            block = np.floor(block * gains).clip(0, 255).astype(np.uint8)
        if self.mirror:
            block = block[:, ::-1]
        return block


@dataclass(frozen=True)
class Resolution:
    across_dpi: float
    along_dpi: float
    across_source: str
    along_source: str


def paper_edges(scan: RollScan, line: int, gains: np.ndarray | None) -> tuple[int, int]:
    """First and last sample covered by paper, from a 50-line median.

    The reflective sensor darkens towards both ends, so the margins only read
    as margins once the flat field is applied."""
    block = scan.lines(line, min(line + 50, scan.geometry.lines)).mean(axis=2)
    profile = np.median(block, axis=0)
    if gains is not None:
        profile = profile * gains
    threshold = (profile.min() + profile.max()) / 2
    dark = np.flatnonzero(profile < threshold)
    if len(dark) < scan.geometry.samples // 4:
        raise FormatError(f"no paper band visible at line {line}")
    return int(dark[0]), int(dark[-1])


DEFAULT_DPI = 127.0  # 5 lines/mm, the nominal step of both MRS sensors


def estimate_resolution(
    scan: RollScan, csv_path: Path, flat_field: FlatField | None
) -> Resolution:
    length_mm, along_source = scanned_length_mm(scan, csv_path)
    if length_mm:
        along = scan.geometry.lines / length_mm * 25.4
    else:
        along, along_source = DEFAULT_DPI, "assumed"

    width_mm, width_source = paper_width_mm(scan)
    if not width_mm:
        return Resolution(along, along, "assumed", along_source)
    gains = flat_field.gains(scan.geometry.samples) if flat_field else None
    probes = np.linspace(0.2, 0.8, 5) * scan.geometry.lines
    widths = [hi - lo for lo, hi in (paper_edges(scan, int(p), gains) for p in probes)]
    across = float(np.median(widths)) / width_mm * 25.4
    return Resolution(across, along, f"paper edges vs {width_source}", along_source)


def paper_width_mm(scan: RollScan) -> tuple[float | None, str]:
    """Nominal paper width, from this file's trailer or from a sibling .mrs."""
    value = scan.metadata.get("Rolltype", {}).get("Roll Width")
    if value:
        return float(value), "Roll Width in trailer"
    for sibling in sorted(scan.path.parent.glob("*.mrs")):
        with RollScan(sibling) as other:
            value = other.metadata.get("Rolltype", {}).get("Roll Width")
        if value:
            return float(value), f"Roll Width in {sibling.name}"
    return None, ""


def scanned_length_mm(scan: RollScan, csv_path: Path) -> tuple[float | None, str]:
    """Physical length of this raster, from whichever sibling file records it."""
    if scan.geometry.channels == 3:
        metres = _settings_value(csv_path, "MRSC_Length")
        return (metres * 1000.0, "MRSC_Length") if metres else (None, "")
    rec = scan.path.with_suffix(".rec")
    if rec.exists():
        text = rec.read_text(encoding="latin-1", errors="replace")[:2000]
        playtime = re.search(r"^Playtime=(\d+)", text, re.M)
        speed = re.search(r"^ConversionSpeed=([\d.]+)mm/s", text, re.M)
        if playtime and speed:
            return int(playtime[1]) / 1000 * float(speed[1]), "playtime x speed (.rec)"
    return None, ""


def sibling_settings_csv(path: Path) -> Path:
    """The scanner writes one settings CSV per scan session."""
    stem = path.stem.split("_I_")[0]
    return path.with_name(stem + ".csv")


@dataclass(frozen=True)
class Layout:
    """How the scan lines are laid out in the output image."""

    lines: int
    samples: int
    channels: int
    horizontal: bool  # roll runs left to right, as in the scanner's own PNG

    @property
    def shape(self) -> tuple[int, ...]:
        plane = (self.samples, self.lines) if self.horizontal else (self.lines, self.samples)
        return plane if self.channels == 1 else plane + (self.channels,)

    def orient(self, block: np.ndarray) -> np.ndarray:
        if self.channels == 1:
            block = block[..., 0]
        return block.swapaxes(0, 1) if self.horizontal else block

    def place(self, image: np.ndarray, block: np.ndarray, at: int) -> None:
        oriented = self.orient(block)
        count = oriented.shape[1] if self.horizontal else oriented.shape[0]
        if self.horizontal:
            image[:, at : at + count] = oriented
        else:
            image[at : at + count] = oriented


def fill(image: np.ndarray, scan: RollScan, span: range, pipeline: Pipeline,
         layout: Layout) -> None:
    lead = pipeline.lead
    for at in range(0, len(span), BLOCK_LINES):
        first = span.start + at
        count = min(BLOCK_LINES, len(span) - at)
        block = pipeline.apply(scan.lines(first, first + count + lead))
        if layout.channels == 3 and block.shape[2] == 1:
            block = np.repeat(block, 3, axis=2)
        layout.place(image, block, at)


def write_tiff(path: Path, scan: RollScan, span: range, pipeline: Pipeline,
               layout: Layout, resolution: Resolution) -> None:
    import tifffile

    res = (
        (resolution.along_dpi, resolution.across_dpi)
        if layout.horizontal
        else (resolution.across_dpi, resolution.along_dpi)
    )
    image = tifffile.memmap(
        str(path),
        shape=layout.shape,
        dtype=np.uint8,
        photometric="rgb" if layout.channels == 3 else "minisblack",
        planarconfig="contig" if layout.channels == 3 else None,
        resolution=res,
        resolutionunit="INCH",
        rowsperstrip=layout.shape[0],
        software="mrs2image",
        metadata=None,
        extratags=[(274, "H", 1, 1, True)],  # Orientation: first row at the top
    )
    try:
        fill(image, scan, span, pipeline, layout)
        image.flush()
    finally:
        del image


def write_png(path: Path, scan: RollScan, span: range, pipeline: Pipeline,
              layout: Layout) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    image = np.empty(layout.shape, dtype=np.uint8)
    fill(image, scan, span, pipeline, layout)
    Image.fromarray(image).save(path)


def describe(scan: RollScan, resolution: Resolution) -> str:
    g, h = scan.geometry, scan.header
    lines = [
        f"file          {scan.path.name}",
        f"scanner       MRS {h.version}, scan #{h.scan_number}, {h.date}",
        f"declared data {h.data_size} bytes",
        f"raster        {g.lines} lines x {g.samples} samples x {g.channels} channel(s)",
        f"line length   {g.line_bytes} bytes; chunk marker every {g.chunk_lines} line(s)",
        f"across        {resolution.across_dpi:.1f} dpi ({resolution.across_source})",
        f"along         {resolution.along_dpi:.1f} dpi ({resolution.along_source})",
    ]
    lines += [
        f"[{section}] {key} = {value}"
        for section, entries in scan.metadata.items()
        for key, value in entries.items()
        if value and not key.startswith("Track ")
    ]
    return "\n".join(lines)


def parse_span(text: str | None, total: int) -> range:
    if not text:
        return range(total)
    first, _, last = text.partition(":")
    start = int(first) if first else 0
    stop = int(last) if last else total
    if not 0 <= start < stop <= total:
        raise ValueError(f"line range {text} lies outside 0:{total}")
    return range(start, stop)


def build_pipeline(args, scan: RollScan, csv_path: Path,
                   flat: FlatField | None) -> Pipeline:
    lag = args.channel_lag
    if lag is None:
        lag = int(_settings_value(csv_path, "MRSC_SpatialCorrOfOneColor") or 0)
    register = (args.register or args.like_png) and scan.geometry.channels == 3
    return Pipeline(
        # The sensor's three colour rows sit one lag apart, red trailing blue.
        channel_lag=(2 * lag, lag, 0) if register and lag else (),
        flat_field=flat if (args.like_png or args.flat_field) else None,
        mirror=args.mirror or args.like_png,
    )


def parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?", help=".tif or .png")
    parser.add_argument("--info", action="store_true", help="describe the scan and exit")
    parser.add_argument("--lines", metavar="A:B", help="convert only these scan lines")
    parser.add_argument(
        "--like-png",
        action="store_true",
        help="reproduce the scanner's own PNG: colour registration, "
        "flat-field correction and mirroring",
    )
    parser.add_argument("--flat-field", action="store_true", help="flat-field only")
    parser.add_argument(
        "--register", action="store_true", help="colour registration only"
    )
    parser.add_argument("--mirror", action="store_true", help="mirror across the roll")
    parser.add_argument(
        "--channel-lag",
        type=int,
        default=None,
        help="line offset between the sensor's colour rows "
        "(default: MRSC_SpatialCorrOfOneColor from the settings CSV)",
    )
    parser.add_argument("--rgb", action="store_true", help="expand mono to three channels")
    parser.add_argument(
        "--horizontal", action="store_true", help="roll runs left to right (like the PNG)"
    )
    parser.add_argument("--dpi", help="override as ACROSS,ALONG")
    return parser.parse_args(argv)


def convert(args) -> int:
    csv_path = sibling_settings_csv(args.input)
    flat = FlatField.from_settings_csv(csv_path) if csv_path.exists() else None
    with RollScan(args.input) as scan:
        if scan.geometry.channels == 1:
            flat = None  # the curve describes the colour sensor only
        if args.dpi:
            across, along = (float(v) for v in args.dpi.split(","))
            resolution = Resolution(across, along, "given", "given")
        else:
            resolution = estimate_resolution(scan, csv_path, flat)

        if args.info or not args.output:
            print(describe(scan, resolution))
            return 0

        pipeline = build_pipeline(args, scan, csv_path, flat)
        span = parse_span(args.lines, scan.geometry.lines - pipeline.lead)
        layout = Layout(
            lines=len(span),
            samples=scan.geometry.samples,
            channels=3 if (args.rgb or scan.geometry.channels == 3) else 1,
            horizontal=args.horizontal,
        )

        suffix = args.output.suffix.lower()
        if suffix in (".tif", ".tiff"):
            write_tiff(args.output, scan, span, pipeline, layout, resolution)
        elif suffix == ".png":
            write_png(args.output, scan, span, pipeline, layout)
        else:
            raise ValueError(f"unsupported output format: {suffix}")

        print(
            f"wrote {args.output} "
            f"({len(span)} lines x {scan.geometry.samples} samples"
            f"{', mirrored' if pipeline.mirror else ''}"
            f"{', flat-fielded' if pipeline.flat_field else ''}"
            f"{', colour-registered' if pipeline.channel_lag else ''})"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return convert(args)
    except (FormatError, ValueError, OSError) as error:
        print(f"mrs2image: {error}", file=sys.stderr)
        return 1


def _settings_field(csv_path: Path, name: str) -> str | None:
    """The Value column of one DateTime/Group/Variable/Value settings row."""
    if not csv_path.exists():
        return None
    rows = (r.split(";") for r in csv_path.read_text(encoding="latin-1").splitlines())
    return next((r[3] for r in rows if len(r) > 3 and r[2] == name), None)


def _settings_value(csv_path: Path, name: str) -> float | None:
    field = _settings_field(csv_path, name)
    return float(field) if field else None


def _settings_flag(csv_path: Path, name: str) -> bool | None:
    field = _settings_field(csv_path, name)
    return field.strip().lower() == "true" if field else None


if __name__ == "__main__":
    sys.exit(main())
