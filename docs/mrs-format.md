# The MRS scanner raster format

The MRS format is not documented anywhere I could find. What follows was
derived by inspection of a single scan session, WR0225_02 of 12 April 2023
(Welte Rot, Schumann, *Träumerei* Op. 15, played by Alfred Grünfeld). Figures
quoted are measurements from that session and may not hold for other rolls or
scanner versions. An illustrated version of these notes, with diagrams, is in
`mrs-format.html`.

`mrs2image.py` reads both rasters and measures line width and chunk size from
each file rather than assuming them, so other scanner versions should work,
though only this one session was available to test against.

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
| header version field | `MRS Co Nr` (Color) | `MRS SW Nr` (Schwarz-Weiss) |
| scan number | 0000000000 | 0000007272 |
| camera | Auflicht RGB | Durchlicht black-and-white |
| paper band | 1,371 px | 1,570 px |
| across, measured | ~106 dpi | ~121 dpi |
| across, published | 118 dpi (0.21 mm/px) | 115 dpi (0.22 mm/px) |
| along | 127 dpi (0.2 mm/line) | 127 dpi (0.2 mm/line) |
| trailer | none | 1,802 bytes of INI |

The across-roll figures come from the paper edges measured against
`Roll Width = 328.5` in the trailer. Pixels are not square in either file, and
noticeably less so in the colour one.

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

## The across-roll scale has to be measured

Debrunner publishes 0.22 mm/px for the 2048-px Durchlicht camera and 0.21 mm/px
for the 2098-px Auflicht one, but those figures are given to two significant
figures, are internally inconsistent (25.4/0.21 = 121 dpi, not the 118 printed
beside it), and imply the colour camera resolves finer than the black-and-white
one, which a measurement on the same physical paper contradicts: the paper spans
1,569 px in the `.mrs` against 1,371 px in the `.mrsc`. The paper also says why
no fixed figure should be expected. Scan width runs 20–500 mm "je nach Adapter",
and the calibration section describes computing each camera's
*Abbildungsmassstab* from an adjustment strip and checking it against a
measuring roll of known dimensions. `mrs2roll.py` therefore recovers the across
scale from the roll's own tracker grid on every run.

## Companion files

Two siblings of the input are read when they are present:

- the session's settings CSV, for `MRSC_SpatialCorrOfOneColor`, the three
  brightness-curve coefficients and `MRSC_Length`;
- a sibling `.mrs`, for the `[Rolltype]` block when the input is a `.mrsc`,
  which carries no trailer of its own.

Neither is required. Without `MRSC_Length` the along-roll resolution falls back
to the transport's 0.2 mm line step.

The `.rec` route that suggests itself, `Playtime` × `ConversionSpeed`, is not
used and would be wrong: 50 mm/s is the standard *playback* speed for
conversion, whereas the scan itself runs at 160 mm/s (Debrunner). On WR0225_02
it implies 126.3 dpi against the design 127.

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
forty places along the roll. `mrs2image.py --like-png` performs exactly these
steps.

## Lateral drift

None that I can measure. The paper edges hold to within ±2 px over all 44,000
lines in both files, so there is no evidence that either raster drifts sideways
as it goes, or that one was corrected and the other not. The across-roll
distortion `mrs2roll.py` straightens is a different thing: fixed in the sensor,
the same on every line.

## Open questions

- The last 6 % of PNG pixels, each off by one level. Probably a rounding or
  precision difference in the scanner's own arithmetic; `floor` matches better
  than `round`, but not perfectly.
- Why the measured across-roll resolutions sit where they do relative to the
  published 0.22 and 0.21 mm/px, and in particular why the colour camera's
  field of view comes out much wider than the black-and-white one's when the
  published figures make them nearly equal.
- Whether the chunk size is fixed per camera or simply a write-buffer size that
  could differ on other scans.

## References

- Debrunner, D. *Die Entwicklung des Musikrollenscanners der Berner
  Fachhochschule – aus Musikrollenbildern wird Musik – die elektronische
  Steuerung der Welte-Philharmonie-Orgel.* The scanner that produced these
  files (`ScanOrt=Biel` in the `.dsp`). Gives the scan resolutions, the roll
  type table including Welte-Rot at 328.5 mm and 100 tracks, the calibration
  procedure, and names the two raw formats: "*.mrs (Bilddaten der Durchlicht
  Schwarz-Weiss-Kamera) und *.mrsc (Bilddaten der Auflicht RGB-Kamera)".
  PDF at `~/Zotero/storage/9PH97AGL/`.
