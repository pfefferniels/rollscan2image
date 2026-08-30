# mrs2image

A reader and converter for the raster files an MRS piano-roll scanner writes:
the monochrome `.mrs` and the colour `.mrsc`. It turns either into uncompressed
TIFF or PNG, and can reproduce the PNG the scanner itself delivers.

The format is not documented anywhere I could find. What follows was derived by
inspection of a single scan session, WR0225_02 of 12 April 2023 (Welte Rot,
Schumann, *Träumerei* Op. 15, played by Alfred Grünfeld). Figures quoted are
measurements from that session and may not hold for other rolls or scanner
versions. A fuller write-up with diagrams is in `docs/mrs-format.html`.

## Requirements

Python 3.10 or later, `numpy`, `tifffile` for TIFF output, `Pillow` for PNG.

## Usage

```
mrs2image.py [options] INPUT.mrs|INPUT.mrsc [OUTPUT.tif|OUTPUT.png]
```

```sh
# describe a file without converting it
python3 mrs2image.py WR0225_02_….mrsc --info

# the scanner's own picture, as TIFF
python3 mrs2image.py WR0225_02_….mrsc roll.tif --like-png

# raw pixels, no processing, a 500-line excerpt
python3 mrs2image.py WR0225_02_….mrsc probe.png --lines 20000:20500

# the monochrome scan, expanded to RGB
python3 mrs2image.py WR0225_02_….mrs mono.tif --rgb
```

| Option | Effect |
| --- | --- |
| `--info` | print header, geometry, resolution and trailer metadata, then stop |
| `--lines A:B` | convert only these scan lines |
| `--like-png` | run all three steps of the scanner's own pipeline (below) |
| `--register` | colour registration only |
| `--flat-field` | flat-field correction only |
| `--mirror` | mirror across the roll only |
| `--channel-lag N` | override the sensor's colour-row spacing |
| `--rgb` | expand a monochrome scan to three channels |
| `--horizontal` | roll runs left to right, as in the delivered PNG |
| `--dpi ACROSS,ALONG` | override the resolution written into the TIFF tags |

With no processing options the output is the raw raster, which is dark and
heavily vignetted but untouched.

Line width and chunk size are measured from each file rather than assumed, so
other scanner versions should work, though only this one session was available
to test against.

### Companion files

The converter reads two siblings of the input when they are present, and says so
in `--info` output when it does:

- the session's settings CSV, for `MRSC_SpatialCorrOfOneColor`, the three
  brightness-curve coefficients and `MRSC_Length`;
- the `.rec` of the same soundtrack, for playtime and conversion speed, from
  which the along-roll resolution of a `.mrs` is derived.

Neither is required. Without them the resolution falls back to a nominal
127 dpi, and `--info` labels it as assumed.

### Interoperability with roll-image-parser

The TIFF written here is single-strip, contiguous, uncompressed, photometric 2,
with inch resolution units, which is what Craig Sapp's
[roll-image-parser](https://github.com/pianoroll/roll-image-parser) `TiffFile`
reader accepts. Its `tiff2holes` wants the roll running down the image with
columns across it, which is the default orientation here; `--horizontal` gives
the other one. That reader rejects photometric 1, so a monochrome scan needs
`--rgb` before it will be read.

## The container

Both file types share one container.

| Offset | Bytes | Content |
| --- | --- | --- |
| 0 | 30 | `Headsize in Bytes = %010d`, observed `0000000064` |
| 30 | 64 | ` Date = DD.MM.YYYY, MRS XX Nr = V.n.n, Scan Number = %010d;` |
| 94 | 30 | `Datasize in Bytes = %010d` |
| 124 | 10 | opening chunk marker, `$000000000` |
| 134 | … | chunks, each preceded by its own `$%09d` counter |
| end | 10 | closing sentinel, `$999999999` |
| after | … | INI trailer, `.mrs` only |

The field named `Headsize` is 64 and describes the middle field alone, not the
124-byte header as a whole.

`Datasize` counts the markers as well as the pixels, which is why it does not
divide evenly by the line length. For the colour file, 44,507 × 6,294 pixel
bytes plus 44,508 × 10 marker bytes gives exactly the 280,572,138 the header
declares.

The chunk is one scan line in `.mrsc` and a thousand scan lines in `.mrs`. Since
markers sit between chunks and not between lines, reading a `.mrs` at a flat
2,048-byte stride makes the image shear by ten bytes every thousand lines, which
looks convincingly like lateral drift and is not.

## The two rasters

| | `.mrsc` | `.mrs` |
| --- | --- | --- |
| raster | 44,507 × 2,098 × 3 | 44,000 × 2,048 × 1 |
| chunk | 1 line, 6,294 B | 1,000 lines, 2,048,000 B |
| header version field | `MRS Co Nr = V.1.0` | `MRS SW Nr = V.1.3` |
| scan number | 0000000000 | 0000007272 |
| optics | reflective colour | backlit monochrome |
| paper band | 1,371 px | 1,570 px |
| across | ~106 dpi | ~121 dpi |
| along | ~127 dpi | ~126 dpi |
| trailer | none | 1,802 bytes of INI |

The across-roll figures come from the paper edges measured against
`Roll Width = 328.5` in the trailer. A second estimate from the track pitch
(100 tracks between 6.5 mm and 322 mm) agrees within about one percent. Pixels
are not square in either file, and noticeably less so in the colour one.

The two are separate rasters of the same roll in the same session, neither
derived from the other. Matching note patterns across them gives

```
mrsc_line ≈ 1.0005 × mrs_line − 570
```

so the same along-roll step to within 0.05 %, with the colour scan starting some
570 lines (about 11 cm) further into the roll and running about 1,000 lines past
the end of the monochrome one. They share the across-roll orientation; only the
delivered PNG is mirrored.

The `.mrs` trailer is plain INI, prefixed by its own `Def.size in Bytes = %010d`
field: a `[Soundtrack 1]` block with title, composer and performer, a
`[Rolltype]` block describing the roll (Welte Rot, 100 tracks, `Roll Width`,
`First Track`, `Last Track`), and a `[Definition]` block with catalogue number
and paper type.

## From .mrsc to the delivered PNG

The PNG the scanner delivers is 44,489 × 2,098, eighteen columns short of the
colour raster's 44,507 lines. Three steps account for the difference, all of
them parameterised by the settings CSV written beside the scan.

Nothing is resampled. The PNG carries the `.mrsc` at its native resolution, one
scan line per column and all 2,098 samples per column, so the two have the same
resolution in both directions. The monochrome raster is a different matter: its
own sensor, about 15 % finer across the roll, unrelated to the PNG's grid.

1. **Register the colour rows.** The sensor is trilinear, its rows
   `MRSC_SpatialCorrOfOneColor = 9` lines apart. Green is taken 9 lines later
   than blue, red 18. Those 18 lines are the ones lost.
2. **Divide out the flat field.** A parabola across the sensor, its three
   coefficients in the CSV, normalised to its vertex and divided out. Up to
   2.4× at the sensor ends, 1.0× at the centre, below 1.35× over the paper.
3. **Mirror across the roll.** Sample `s` becomes row `2097 − s`.

```
png[x, 2097 − s, c] = floor( mrsc[x + lag[c], s, c] × Cmax / curve(s) )

  lag      = (R 18, G 9, B 0)        from MRSC_SpatialCorrOfOneColor = 9
  curve(s) = A·s² + B·s + C          A = −7.469772303e−05
  Cmax     = curve at its vertex     B =  0.15701233763037
           ≈ 141.59 at s ≈ 1051      C =  59.0841072672962
```

Reconstructed this way, 93–94 % of pixels come out bit-identical to the
scanner's own PNG and no pixel differs by more than one level in 255, checked at
forty places along the roll. `--like-png` performs exactly these steps.

## Lateral drift

None that I can measure. The paper edges hold to within ±2 px over all 44,000
lines in both files, so there is no evidence that either raster needs
straightening, or that one was corrected and the other not.

## Open questions

- Whether `MRS Co Nr` and `MRS SW Nr` really name the colour and monochrome
  modules. The reading fits which file carries which, but nothing in the data
  confirms it.
- The last 6 % of PNG pixels, each off by one level. Probably a rounding or
  precision difference in the scanner's own arithmetic; `floor` matches better
  than `round`, but not perfectly.
- Why the two sensors differ in across-roll resolution at all, and why neither
  has square pixels.
- The unit of `Spurdistanz = 1.18686868686869` in the `.dsp` file. It is exactly
  117.5 / 99, which does not match the 3.187 mm track pitch the trailer implies.
- Whether the chunk size is fixed per module or simply a write-buffer size that
  could differ on other scans.
