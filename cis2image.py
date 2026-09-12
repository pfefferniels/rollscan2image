#!/usr/bin/env python3
"""Convert rollscanners CIS piano-roll scans (.CIS) to TIFF or PNG.

The rollscanners group's contact image sensor scanners write a 1-bit scan,
run-length coded, in the layout R. Stibbons described in 2003:

    bytes 0..31     title, space padded
    bytes 34..35    status word: scanner type, twin array, bi-colour, ...
    bytes 36..51    twin-array separation, dpi, pixels per line, twin-array
                    changeover, tempo, lines per inch, line count
    then, per line  one run sequence per channel, each a list of 16-bit run
                    lengths that starts with a dark run and adds up to the
                    pixels per line, followed by one status word

Files written before that carry the earlier layout P. Knobloch described in
2002, whose 40-byte description covers the six bytes the later one spends on
the status word, twin-array separation and resolution:

    bytes 0..39     description, space padded
    bytes 40..51    pixels per line, reserved, tempo, lines per inch, line count

The two agree from byte 40 on, so an early file is one whose bytes 34..39 are
still text.  Such a file names neither its scanner nor its resolution, and
following CISREPORT it is read as a stepper scan at EARLY_DPI.

The channels are the holes, the second array of a twin scanner, and the
printing seen by a bi-colour scanner.  Lines are stored in scanning order, so
line 0 is the leader and the printing reads upside down; --rotate turns the
image into the view of the roll on the piano.  Encoder-clocked scans are
written line for line without re-clocking, and the two arrays of a twin
scanner are not stitched.
"""

from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path

import numpy as np

HEADER = struct.Struct("<32s2xHHHHHHHI")
EARLY_HEADER = struct.Struct("<40sHHHHI")
BLOCK_LINES = 2048
OVERRUN = 1 << 15
PAPER = 170
CHANNELS = ("holes", "twin", "ink", "composite")

# An early file states no resolution, so CISREPORT takes one "from the Scan
# Width". Two sensors are attested. Seven of Stibbons' own Duo-Art scans measure
# 203.7 +/- 0.3 dpi against that roll type's 0.11111 in track pitch, which is the
# 8 dots/mm of a fax sensor rather than the round 200 PlaySK assumes; the wider
# module is the DynaImage A3, whose 300 dpi the later files state outright.
EARLY_SENSORS = {2432: 203, 3648: 300}
EARLY_BED_INCHES = 12.16  # only for a width neither sensor explains


class FormatError(Exception):
    """The file does not follow the CIS layout."""


class Spec(Enum):
    """Which published header layout a file follows."""

    CURRENT = "Stibbons 2003"
    EARLY = "Knobloch 2002"


class Scanner(IntEnum):
    UNKNOWN = 0
    FREE_RUN = 1
    POSITION_ENCODER = 2
    SHAFT_ENCODER = 3
    STEPPER = 4
    DELTA_MODE_4 = 5

    @classmethod
    def _missing_(cls, value: object) -> "Scanner":
        return cls.UNKNOWN

    @property
    def clocked(self) -> bool:
        return self in (Scanner.POSITION_ENCODER, Scanner.SHAFT_ENCODER)


def early_dpi(pixels: int) -> int:
    """Across-roll resolution of a scan that does not state one, from its width."""
    return EARLY_SENSORS.get(pixels, round(pixels / EARLY_BED_INCHES))


def is_early_layout(raw: bytes) -> bool:
    """Whether the header is the 2002 one, whose description runs to byte 39.

    The reserved word is written as zero and falls inside that description, so
    FIXCIS.BAS tells the layouts apart by reading it. Knobloch warns that a
    description could be cut short with a NUL, which would defeat that test, so
    a header whose bytes 34..39 are still text is taken as early too. No later
    file can look early either way: text there means 8224 dpi or more."""
    reserved = struct.unpack_from("<H", raw, 32)[0]
    return reserved != 0 or all(0x20 <= byte < 0x7F for byte in raw[34:40])


@dataclass(frozen=True)
class Header:
    title: str
    scanner: Scanner
    speed_doubling: bool
    twin_array: bool
    bicolour: bool
    encoder_division: int
    mirrored: bool
    reversed: bool
    twin_separation_mils: int
    dpi: int
    pixels: int
    changeover: int
    tempo: int
    lpi: int
    lines: int
    spec: Spec

    @classmethod
    def parse(cls, raw: bytes) -> "Header":
        if len(raw) < HEADER.size:
            raise FormatError(f"file shorter than the {HEADER.size}-byte header")
        return cls._early(raw) if is_early_layout(raw) else cls._current(raw)

    @classmethod
    def _current(cls, raw: bytes) -> "Header":
        fields = HEADER.unpack_from(raw)
        title, status, separation, dpi, pixels, changeover, tempo, lpi, lines = fields
        return cls(
            title=title.decode("latin-1").rstrip(" \0"),
            scanner=Scanner(status & 0xF),
            speed_doubling=bool(status & (1 << 4)),
            twin_array=bool(status & (1 << 5)),
            bicolour=bool(status & (1 << 6)),
            encoder_division=2 ** ((status >> 8) & 0xF),
            mirrored=bool(status & (1 << 12)),
            reversed=bool(status & (1 << 13)),
            twin_separation_mils=separation,
            dpi=dpi,
            pixels=pixels,
            changeover=changeover,
            tempo=tempo,
            lpi=lpi,
            lines=lines,
            spec=Spec.CURRENT,
        )

    @classmethod
    def _early(cls, raw: bytes) -> "Header":
        description, pixels, _reserved, tempo, lpi, lines = EARLY_HEADER.unpack_from(raw)
        return cls(
            title=description.decode("latin-1").rstrip(" \0"),
            scanner=Scanner.STEPPER,
            speed_doubling=False,
            twin_array=False,
            bicolour=False,
            encoder_division=1,
            mirrored=False,
            reversed=False,
            twin_separation_mils=0,
            dpi=early_dpi(pixels),
            pixels=pixels,
            changeover=0,
            tempo=tempo,
            lpi=lpi,
            lines=lines,
            spec=Spec.EARLY,
        )

    @property
    def channels(self) -> tuple[str, ...]:
        twin = ("twin",) if self.twin_array else ()
        ink = ("ink",) if self.bicolour else ()
        return ("holes",) + twin + ink

    @property
    def along_dpi(self) -> float:
        """Nominal line spacing; an encoder scanner's lines are not evenly spaced."""
        return self.lpi / self.encoder_division


@dataclass(frozen=True)
class Scan:
    """One CIS file with every run sequence located, ready to render by channel."""

    path: Path
    header: Header
    words: np.ndarray
    starts: np.ndarray
    ends: np.ndarray

    @classmethod
    def read(cls, path: Path) -> "Scan":
        raw = path.read_bytes()
        header = Header.parse(raw)
        words = np.frombuffer(raw, dtype="<u2", offset=HEADER.size)
        starts, ends = _sequence_bounds(words, header)
        return cls(path, header, words, starts, ends)

    @property
    def status(self) -> np.ndarray:
        return self.words[self.ends[:, -1]]

    @property
    def overrun_lines(self) -> np.ndarray:
        return np.flatnonzero(self.status & OVERRUN)

    def rows(self, channel: str, start: int, stop: int) -> np.ndarray:
        """Lines [start, stop) of one channel, True where light reached the sensor."""
        index = self.header.channels.index(channel)
        starts = self.starts[start:stop, index]
        ends = self.ends[start:stop, index]
        return _render(self.words, starts, ends, self.header.pixels)


def _sequence_bounds(words: np.ndarray, header: Header) -> tuple[np.ndarray, np.ndarray]:
    """Where each line's run sequences begin and end, walked along the cumulative sum.

    The walk is sequential because every status word shifts the sum for all
    later lines."""
    cumulative = np.cumsum(words, dtype=np.int64)
    width = header.pixels
    starts = np.empty((header.lines, len(header.channels)), dtype=np.int64)
    ends = np.empty_like(starts)
    position = 0
    base = 0
    for line in range(header.lines):
        for channel in range(starts.shape[1]):
            end = int(np.searchsorted(cumulative, base + width))
            if end >= cumulative.size or cumulative[end] != base + width:
                raise FormatError(
                    f"line {line}, channel {channel}: runs do not add up to {width} pixels"
                )
            starts[line, channel] = position
            ends[line, channel] = position = end + 1
            base += width
        if position >= words.size:
            raise FormatError(f"line {line}: status word missing")
        base += int(words[position])
        position += 1
    if position != words.size:
        raise FormatError(f"{words.size - position} words left after the last line")
    return starts, ends


def _render(words: np.ndarray, starts: np.ndarray, ends: np.ndarray, width: int) -> np.ndarray:
    """Rows from their run sequences: a pixel is light after an odd number of changes."""
    counts = ends - starts
    rows = np.repeat(np.arange(counts.size), counts)
    within_row = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    lengths = words[np.repeat(starts, counts) + within_row].astype(np.int64)
    change_at = np.cumsum(lengths) - rows * width
    changes = np.bincount(rows * (width + 1) + change_at, minlength=counts.size * (width + 1))
    parity = np.cumsum(changes.reshape(counts.size, width + 1), axis=1, dtype=np.uint8) & 1
    return parity[:, :width].astype(bool)


def read_annotations(path: Path) -> dict[str, str]:
    """The .ANN sidecar, Stahnke's convention: one `/key: value` per line."""
    lines = path.read_text(encoding="latin-1").splitlines()
    pairs = (line[1:].split(":", 1) for line in lines if line.startswith("/") and ":" in line)
    return {key.strip(): value.strip() for key, value in pairs}


def compose(lit: np.ndarray, unprinted: np.ndarray) -> np.ndarray:
    """Paper grey, white where light came through, black where ink was seen."""
    grey = np.full(lit.shape, PAPER, dtype=np.uint8)
    grey[lit] = 255
    grey[~unprinted] = 0
    return grey


def render(scan: Scan, channel: str, start: int, stop: int) -> np.ndarray:
    if channel == "composite":
        return compose(scan.rows("holes", start, stop), scan.rows("ink", start, stop))
    return scan.rows(channel, start, stop)


def shrink(block: np.ndarray, factor: int) -> np.ndarray:
    """Block means, as 8-bit grey; a factor of one leaves the block as it is."""
    if factor == 1:
        return block
    rows, columns = (side // factor for side in block.shape)
    levels = block[: rows * factor, : columns * factor].astype(np.float32)
    means = levels.reshape(rows, factor, columns, factor).mean(axis=(1, 3))
    return (means * (255 if block.dtype == bool else 1)).astype(np.uint8)


@dataclass(frozen=True)
class Layout:
    """How the requested lines are laid out in the output image."""

    lines: int
    pixels: int
    channel: str
    factor: int

    @property
    def shape(self) -> tuple[int, int]:
        return self.lines // self.factor, self.pixels // self.factor

    @property
    def dtype(self) -> type:
        return bool if self.factor == 1 and self.channel != "composite" else np.uint8

    @property
    def block_lines(self) -> int:
        return BLOCK_LINES // self.factor * self.factor


def fill(image: np.ndarray, scan: Scan, span: range, layout: Layout) -> None:
    whole = len(span) // layout.factor * layout.factor
    for at in range(0, whole, layout.block_lines):
        count = min(layout.block_lines, whole - at)
        block = render(scan, layout.channel, span.start + at, span.start + at + count)
        image[at // layout.factor : (at + count) // layout.factor] = shrink(block, layout.factor)


def write_tiff(path: Path, image: np.ndarray, header: Header, factor: int) -> None:
    import tifffile

    tifffile.imwrite(
        str(path),
        image,
        photometric="minisblack",
        compression="zlib",
        resolution=(header.dpi / factor, header.along_dpi / factor),
        resolutionunit="INCH",
        software="cis2image",
        metadata=None,
        description=header.title,
        extratags=[(274, "H", 1, 1, True)],  # Orientation: first row at the top
    )


def write_png(path: Path, image: np.ndarray) -> None:
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    Image.fromarray(image).save(path)


def describe(scan: Scan) -> str:
    h = scan.header
    kind = h.scanner.name.lower().replace("_", " ")
    flags = [
        name
        for name, on in (
            ("twin array", h.twin_array),
            ("bi-colour", h.bicolour),
            ("speed doubling", h.speed_doubling),
            ("mirrored", h.mirrored),
            ("reversed", h.reversed),
        )
        if on
    ]
    overruns = scan.overrun_lines
    assumed = " (assumed)" if h.spec is Spec.EARLY else ""
    lines = [
        f"file          {scan.path.name}",
        f"header        {h.spec.value} layout",
        f"title         {h.title}",
        f"scanner       {kind}{assumed}" + (", " + ", ".join(flags) if flags else ""),
        f"raster        {h.lines} lines x {h.pixels} pixels; channels {', '.join(h.channels)}",
        f"across        {h.dpi} dpi{assumed}",
        f"along         {h.lpi} lines per inch"
        + (f", encoder division {h.encoder_division}" if h.encoder_division > 1 else "")
        + (", not re-clocked" if h.scanner.clocked else ""),
        f"tempo         {h.tempo}",
        "status        "
        + (f"overrun on {overruns.size} lines, first at {overruns[0]}" if overruns.size else "no overruns"),
    ]
    sidecar = scan.path.with_suffix(".ANN")
    if sidecar.exists():
        lines += [f"[{sidecar.name}] {key} = {value}" for key, value in read_annotations(sidecar).items()]
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


def parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, nargs="?", help=".tif or .png")
    parser.add_argument("--info", action="store_true", help="describe the scan and exit")
    parser.add_argument("--lines", metavar="A:B", help="convert only these scan lines")
    parser.add_argument(
        "--channel",
        choices=CHANNELS,
        default="holes",
        help="holes (white where light came through), twin, ink (black where "
        "printing was seen), or composite (paper grey, holes white, ink black)",
    )
    parser.add_argument(
        "--rotate", action="store_true", help="turn by 180 degrees: the view on the piano"
    )
    parser.add_argument(
        "--shrink", type=int, default=1, metavar="N", help="block-average N x N pixels into one"
    )
    return parser.parse_args(argv)


def convert(args) -> int:
    scan = Scan.read(args.input)
    if args.info or not args.output:
        print(describe(scan))
        return 0

    needed = ("holes", "ink") if args.channel == "composite" else (args.channel,)
    missing = [name for name in needed if name not in scan.header.channels]
    if missing:
        raise ValueError(f"this scan has no {missing[0]} channel")
    if args.shrink < 1:
        raise ValueError("--shrink needs a factor of one or more")

    span = parse_span(args.lines, scan.header.lines)
    layout = Layout(len(span), scan.header.pixels, args.channel, args.shrink)
    image: np.ndarray = np.empty(layout.shape, dtype=layout.dtype)
    fill(image, scan, span, layout)
    if args.rotate:
        image = image[::-1, ::-1]

    suffix = args.output.suffix.lower()
    if suffix in (".tif", ".tiff"):
        write_tiff(args.output, image, scan.header, args.shrink)
    elif suffix == ".png":
        write_png(args.output, image)
    else:
        raise ValueError(f"unsupported output format: {suffix}")

    print(
        f"wrote {args.output} ({args.channel}, {len(span)} lines x {scan.header.pixels} pixels"
        f"{f' shrunk {args.shrink}x' if args.shrink > 1 else ''}"
        f"{', rotated' if args.rotate else ''})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return convert(args)
    except (FormatError, ValueError, OSError) as error:
        print(f"cis2image: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
