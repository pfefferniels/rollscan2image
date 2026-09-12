# rollscan2image

Readers and converters for the files piano-roll scanners write, turning them
into TIFF or PNG.

`mrs2image.py` reads the raster files of an MRS scanner, the monochrome `.mrs`
and the colour `.mrsc`, and can reproduce the PNG the scanner itself delivers.
`mrs2roll.py` prepares such a scan for Craig Sapp's
[roll-image-parser](https://github.com/pianoroll/roll-image-parser); see
[Feeding roll-image-parser](#feeding-roll-image-parser) below. `cis2image.py`
reads a different scanner's files, the run-length coded `.CIS` of the
rollscanners group, and `cis2roll.py` prepares one of those for the parser in
the same way; see [CIS files](#cis-files). Most of what follows concerns the
MRS format.

The MRS format is not documented anywhere I could find. What follows was derived by
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
- a sibling `.mrs`, for the `[Rolltype]` block when the input is a `.mrsc`,
  which carries no trailer of its own.

Neither is required. Without `MRSC_Length` the along-roll resolution falls back
to the transport's 0.2 mm line step, and `--info` says so.

The `.rec` route that suggests itself, `Playtime` × `ConversionSpeed`, is not
used and would be wrong: 50 mm/s is the standard *playback* speed for
conversion, whereas the scan itself runs at 160 mm/s (Debrunner). On WR0225_02
it implies 126.3 dpi against the design 127.

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
| header version field | `MRS Co Nr` (Color) | `MRS SW Nr` (Schwarz-Weiss) |
| scan number | 0000000000 | 0000007272 |
| camera | Auflicht RGB | Durchlicht black-and-white |
| paper band | 1,371 px | 1,570 px |
| across, measured | ~106 dpi | ~121 dpi |
| across, published | 118 dpi (0.21 mm/px) | 115 dpi (0.22 mm/px) |
| along | 127 dpi (0.2 mm/line) | 127 dpi (0.2 mm/line) |
| trailer | none | 1,802 bytes of INI |

The across-roll figures come from the paper edges measured against
`Roll Width = 328.5` in the trailer. A second estimate from the track pitch
(100 tracks between 6.5 mm and 322 mm) gives 123.3 dpi for the `.mrs`, 1.6 %
higher. That gap is this roll's own departure from the nominal track scale, an
open question below. Pixels are not square in either file, and noticeably less
so in the colour one.

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

## Feeding roll-image-parser

`tiff2holes` was written for the Stanford scans and is calibrated for them
throughout, so the way in is to hand it an image in its own units rather than
to retune its thresholds. It wants an uncompressed 24-bit RGB TIFF at about
300 dpi, at least 4096 columns wide (`analyzeTrackerBarSpacing` indexes the
first 4096 columns of the centroid histogram unconditionally), the roll running
down the image with bass at column 0, and holes brighter than the paper.

```sh
python3 mrs2roll.py WR0225_02_….mrs --dry-run          # show the calibration
python3 mrs2roll.py WR0225_02_….mrs roll300.tif        # ~1.2 GB for this roll
python3 mrs2roll.py WR0225_02_….mrs roll300.tif --no-straighten   # leave the
                                                      # across-roll bend in
tiff2holes -r roll300.tif > analysis.txt
```

`mrs2roll.py` resamples onto a square-pixel 300 dpi grid and centres the paper
in a 4096-column frame. The two axes need different scale factors because MRS
pixels are not square:

- **Across**, the ruler is the roll's own tracker grid, recovered by a comb fit
  over the tracks the roll plays. On WR0225_02 that gives 15.466 ± 0.009 px between
  tracks; against the 3.18687 mm pitch implied by the trailer's `First Track`,
  `Last Track` and `Number Of Tracks`, that is 4.853 px/mm ≈ 123.3 dpi.
- **Along**, the transport's design step of 0.2 mm per line = 127 dpi, which
  Debrunner states outright. The colour scan's `MRSC_Length` confirms it to
  0.04 %, and the two rasters share the step to 0.05 %.

A roll only pins down the grid where it plays. This one uses 33 tracks
spanning columns 577-1303 of a 1,569 px paper, and the perforations outside that
compass — two groups near each paper edge, present the whole length of the roll —
land 0.39 to 0.50 of a pitch off a *straight* grid fitted to the played tracks.
Left in, they drag the comb 0.3 % low. So the pitch is measured, then remeasured
over the longest unbroken run of played tracks:

| estimator | pitch | |
| --- | --- | --- |
| comb over the whole paper | 15.420 px | coherence 0.807 |
| comb over the played compass (used) | 15.466 px | coherence 0.879 |
| integer grid fit to the played track centres | 15.466 px | rms 0.49 px |
| least squares over all track centres | 15.392 px | |
| zeroing the linear drift of the grid phase | 15.396 px | |

**That table is method spread, not uncertainty.** All of these rest on the same
33 track centres, so the agreement between the middle two measures consistency
of method, not precision of measurement. Propagating the scatter about the
fitted line through the regression gives the actual figure:

```
pitch  15.466 ± 0.009 px   (0.06 %, 33 tracks over an index span of 46)
```

which the tool prints. Three of the residuals are low-mass tracks sitting beside
much heavier ones, each pulled *toward* the heavy neighbour — centroid
contamination rather than misplaced tracks — so the error bar is if anything
conservative. Dropping them moves the pitch by 0.009 %.

The estimators that include the edge groups sit 0.3-0.5 % low, and the apparent
1.9 % "arch" in local pitch across the sensor is the same artefact seen another
way: the windows carrying it hold four to seven tracks each, and a handful of
tracks separated by large empty gaps can be fitted at many periods. Restricted
to windows with at least eight occupied tracks the spread is 0.46 %, and their
mass-weighted mean is 15.469.

None of this matters downstream — remeasuring from 15.392 to 15.466 moved
`MUSICAL_HOLES` by two, `MUSICAL_NOTES` by one, and `BAD_HOLE_COUNT` from 8 to 7
— and the ± 0.06 % is a third of the smallest change that moved anything at all.
Whether the grid stays uniform out to the paper edges is a separate question, and
the answer is no; see [Straightening the across axis](#straightening-the-across-axis).

One caveat on reading 123.3 dpi as an absolute figure. The ± 0.06 % is the
repeatability of the *pixel* measurement. Turning it into dpi multiplies by the
nominal 3.18687 mm track pitch from the roll-type table, and the pitch-to-paper
ratio measured here is 1.6 % off that nominal. Straightening the across axis
accounts for something over half of the gap, since the played tracks sit where
the magnification is highest and the paper edges where it is lowest; what is left
is the roll's own departure from nominal, the paper edges, or both. So the
across-roll dpi is good to about a percent, not to 0.07 dpi, and the digits past
123 carry the nominal assumption rather than the measurement.

The across scale has to be measured rather than looked up. Debrunner publishes
0.22 mm/px for the 2048-px Durchlicht camera and 0.21 mm/px for the 2098-px
Auflicht one, but those figures are given to two significant figures, are
internally inconsistent (25.4/0.21 = 121 dpi, not the 118 printed beside it),
and imply the colour camera resolves finer than the black-and-white one — which
a measurement on the same physical paper contradicts, the paper spanning
1,569 px in the `.mrs` against 1,371 px in the `.mrsc`. The paper also says why
no fixed figure should be expected: scan width runs 20–500 mm "je nach Adapter",
and the calibration section describes computing each camera's
*Abbildungsmassstab* from an adjustment strip and checking it against a
measuring roll of known dimensions.

Two independent measurements say the across scale is right. The scanner's own
MIDI puts one semitone about 15.44 px apart; and after
resampling, hole widths come out at 23.7 px = 2.01 mm against the trailer's
nominal 2 mm track width.

### Straightening the across axis

The camera's tracker columns do not lie on a straight line. Fitting the roll's
own column centres against their integer track indices, a straight grid leaves an
rms of 1.18 px on a 15.49 px pitch, with a residual that is systematic rather than
scattered; adding a cubic term drops it to 0.46 px:

```
straight grid   pitch 15.3906 px   rms 1.18 px
cubic           pitch 15.4872 px   rms 0.46 px   k3 -2.166e-08 /px^2 about column 979
```

The cubic is odd about the middle of the sensor, which is what radial distortion
looks like, and it displaces the tracks by +0.60 of a pitch at the bass paper edge
and −0.75 at the treble edge. It holds steady over the length of the roll, so it
is a property of the camera and not of the paper:

| | k3 | pitch | edge shift |
| --- | --- | --- | --- |
| first third | −2.157e−08 | 15.487 px | +0.60, −0.76 |
| middle third | −2.267e−08 | 15.486 px | +0.69, −0.73 |
| last third | −2.136e−08 | 15.498 px | +0.55, −0.79 |
| whole roll (used) | −2.166e−08 | 15.487 px | +0.60, −0.75 |

Half a pitch is enough to matter. roll-image-parser fits one straight grid to the
whole width, phase-locked to the busiest column, so it lands on the notes and
misses the expression tracks at both edges. On WR0225_02 it read the treble
expression one tracker hole low: 103 crescendo-ons and no crescendo-off at all,
which no Welte roll can contain, and 61 forzando-offs the roll does not have. A
Stanford scan of another copy of the same roll (DRUID `mf320jq4997`), whose grid
is straight, reads a balanced crescendo pair there. Straightened, this scan reads
the same seven treble controls that copy does:

| treble control | before | straightened | Stanford copy |
| --- | --- | --- | --- |
| 104 Rewind | 7 | 7 | 26 |
| 106 Sustain-On | 95 | 85 | 90 |
| 107 Sustain-Off | 74 | 84 | 88 |
| 108 Forzando-On | 3 | 3 | 6 |
| 109 Forzando-Off | 61 | 1 | 4 |
| 110 Crescendo-On | 103 | 81 | 99 |
| 111 Crescendo-Off | — | 82 | 103 |

The bass expression was smeared the same way, its three inner columns of 37, 31
and 3 holes read as 21, 41 and 9; straightened they come out 37, 31 and 3. The
note tracks were never affected, and their MIDI key numbers are unchanged.

`measure_barrel` fits this from the roll's own columns on every run. A roll is its
own and only ruler here, so the fit is skipped, with a line in the report saying
so, unless the roll punches within a quarter of the paper width of both edges;
one that keeps to the middle cannot measure the ends, and a cubic extrapolated
from the middle would do harm. `--no-straighten` turns it off.

Two caveats. This is one roll from one session, so whether `k3` is the same
constant for every scan from this machine is untested, and the tool remeasures it
per roll rather than assuming so. And a cubic is the first term of a radial model,
not the whole of it; it takes the track centres from 1.18 px off a straight grid
to 0.46 px, which is the same order as the Stanford scans manage, but the residual
that remains has not been chased further.

### Skew along the roll

A row of perforations punched at one instant lies square across the paper. Where
the scan line meets that row at a slight angle, every punch in it is displaced
along the roll in proportion to how far across the roll it sits. Stahnke names
this skew, "the tilt of a single row of perforations caused by angular
misalignment of the scan line with respect to the array of punches in the
perforator", and treats it as one of the two systematic errors of a roll scan,
the other being scatter.

Both tools measure skew and print it. Neither corrects it, and the resampled
image is byte-for-byte what it was before the measurement was added. That is a
tested decision rather than a deferral; see [What correcting it
buys](#what-correcting-it-buys).

The roll is its own reference here. Punch onsets are taken per tracker column, to
a fraction of a scan line by interpolating the threshold crossing, and every pair
of columns is cross-correlated to give the lag between their onset trains. The
per-column offsets follow from those pairwise lags by least squares, and a
straight line through them against position across the roll is the skew.
Correlating whole trains rather than pairing onsets that happen to fall close
together matters, since restricting pairs to a small window biases the slope
towards zero.

Three scans of one performance, Grünfeld's *Träumerei* from roll 225:

| scan | skew across the paper | scan lines |
| --- | --- | --- |
| MRS `.mrs`, Welte Rot | −0.18 mm over 323 mm | −0.9 |
| Chase CIS, Welte Licensee | +0.11 mm over 286 mm | +0.8 |
| Dyer CIS, Welte T-98 | −0.77 mm over 285 mm | −10.9 |

The Dyer figure is about 9 px once resampled to 300 dpi, and something like 20 ms
of playing time at the roll's printed tempo. The other two are under a scan line.

The estimator cannot separate a tilted scan line from a performance whose bass
consistently preceded its treble, because both displace one side of the roll
against the other. The defence is differential rather than internal. These are
three scans of the same playing and they disagree, so at least two of the three
figures belong to the scanners. The Dyer figure also holds page by page down its
roll, reading −0.91, −0.41, −0.70 and −0.88 mm over four successive fifths of it,
which is what a fixed angle looks like rather than a drifting performance.

Outside evidence points the same way for the Chase scan. The MIDI distributed
with it, `W225E.mid`, was written in 2004 by Warren Trachtman's conversion
software, and carries text meta-events in the keyword scheme Stahnke published
and Trachtman adopted:

```
/skew_correction:   0.0112 degrees | Auto
/punch_length:  0.075 inches | manually set
/Punch_Matrix_Restoration: DISABLED
```

That is the software's own record of what it did to its own output rather than a
measurement made here. Read at face value it says skew was found and removed
automatically, and Chase's is the scan that measures nearest zero, so the one
pipeline known to have had a skew correction step is the one that leaves least
behind. (His 0.0112 degrees is about 0.056 mm over his 285.5 mm of paper, the
same order as the +0.11 mm still measurable, though the two figures are not
directly comparable and no part of the argument rests on their agreeing.) The
same block is a reminder of how much of Stahnke's parameter set was already
implemented in period software: punch length is set there, and punch-matrix
restoration is a switch, turned off for this file.

Three limits are worth stating plainly. The line is fitted over the inner ±100 mm
of the paper, since the outermost columns carry the fewest punches and are the
ones whose correlation is likeliest to lock onto a neighbouring punch. A column
that does lock wrongly is dropped from the fit, though its bad lags still pull the
remaining offsets a little through the least squares. And the page-by-page spread
above is a third of the figure itself, so the whole-roll number carries a sign and
an order of magnitude rather than three digits. Stahnke separates static skew, the
mean over the roll, from dynamic skew, the variation about it. Only the static
mean is reported here, and the page-to-page spread cannot be read as dynamic
skew: over 300 mm stretches the MRS scan, whose whole-roll slope is the smallest
of the three, scatters more widely than the Dyer scan does. At that window length
the estimate is dominated by its own noise.

### What correcting it buys

Nothing measurable, on the evidence available. Shearing the Dyer scan by its
measured slope drops the residual skew from −2.73e-3 to −0.41e-3, so the
correction works as arithmetic, and then almost nothing downstream moves.
`tiff2holes` returns the same 15,680 musical holes and 1,103 notes, the same
18.84 px hole width, a roll width changed by 0.06 px and a tracker separation
changed in the fourth decimal. Only `BAD_HOLE_COUNT` moves, from 1 to 11, and
that is the second interpolation softening one-bit edges rather than anything
about the roll.

The external test is the sharper one and also comes out flat. Aligning the Dyer
scan against the MRS scan note by note, the residual should tilt with position
across the roll by the difference of their skews. Over the note compass that
predicts +0.39 mm and the observed tilt is +0.17 ± 0.22 mm; over the longer lever
of the sustain marks it predicts −0.52 mm and the observed offset is
−0.02 ± 0.12 mm. Fitting one multiplier on the predicted displacement across both
gives 0.12 ± 0.25, which excludes 1 at about 3.5 sigma. Deskewing before aligning
changes the residual from 0.991 to 0.994 mm, which is to say not at all.

So the shear is in the image and does not appear to be in the paper positions.
Two readings survive that, and this data cannot separate them: the estimator may
be reporting something real about the scanner that the cross-copy comparison is
too noisy to confirm, or part of what it measures may be a bass-to-treble
asymmetry shared by the copies, which correcting one copy would then introduce
rather than remove. A cutting asymmetry belongs to an edition and a sensor angle
belongs to a machine, so the way to separate them is to measure other rolls from
the same scanner rather than other copies of this one.

The measurement is reported because it bounds a within-scan reading: onset
differences taken across the compass of the Dyer scan carry up to about 17 ms of
instrumental origin. It is a caveat to weigh, not a bias to subtract.

### Scatter and the punch matrix

Skew is the first of Stahnke's two systematic errors. The second is scatter, a
per-column displacement along the roll from tolerances and wear in the punch and
die set, and beyond both lies his real object: reconstruct the punch matrix by
snapping every perforation to its nearest row, which removes random error as well
as systematic. His pipeline applies these in order, so testing skew alone is not
a test of the method.

Applied here, correcting each copy against its own measurements over 200 mm
windows:

```
stage                   grid residual sd (mm)        cross-copy RMS (mm)
                        Dyer   Chase   MRS      Dyer→MRS  Chase→MRS  Dyer→Chase
as scanned             0.3322  0.2432  0.4385     0.9900    1.7034     1.1870
after skew removal     0.3220  0.2432  0.4384     0.9911    1.7010     1.1702
after scatter removal  0.3213  0.2425  0.4351     0.9947    1.6773     1.1672
after dynamic skew     0.3218  0.2457  0.4306     0.9965    1.6865     1.1679
after snapping to rows   -       -       -        1.5479    2.0046     1.4478
```

The best any stage manages is 3.3 % off a grid residual. Cross-copy agreement
moves by under 2 % in either direction, and snapping makes it 17 to 56 % worse.
A second pass degrades every column.

One measurement explains the whole table. **The row grid belongs to the
continuation punches of held notes, not to the onsets.** Those punches are 93 % of
all holes and carry the entire periodic signal; measured against the local grid
they establish, the onsets are near-uniform across the row, at 13.7 % within a
tenth of a row where uniform would give 13.8 %.

```
              held punches            note onsets
Dyer          R 0.683  sd 0.30 mm     R 0.111  sd 0.71 mm
Chase         R 0.897  sd 0.18 mm     R 0.112  sd 0.81 mm
MRS           R 0.700  sd 0.40 mm     R 0.158  sd 0.91 mm
```

Within one note's chain the advance is very regular, to 0.047 mm on the Dyer
scan. Across chains the phases scatter over most of a row. So there is no single
punch matrix to snap to, and snapping moves onsets by up to half a row for no
reason, which is what the last line of the table shows.

A ceiling argument closes the question. Fitting a free offset per column is the
most general correction of Stahnke's form, since skew is its linear part and
scatter the remainder, so it bounds whatever skew and scatter could achieve here
however well they were estimated. That bound is 3.1 % of the residual variance
for the Dyer scan, 2.2 % for Chase and 1.2 % for MRS, and the straight-line part
alone is under 0.4 %. No better estimator reopens it.

His model is not describing nothing. Dyer's per-column offsets replicate across
the two halves of its roll at r = +0.85, so that scatter is a real signature of a
machine rather than noise; MRS's replicate at r = -0.14, so MRS's apparent
scatter is noise. MRS's dynamic skew wanders smoothly by about ±0.6 mm, which is
what he describes for a takeup-spool transport. These are real and they are about
2 % of the problem.

Why the onsets are continuous where the chains are quantised is inference, not
measurement: a recording perforator would start each note's chain where the
performance put it and then advance the paper at its own rate. Two things argue
for caution. Chase's copy is a counter-case, its onsets sitting on a grid of
0.6084 mm, a quarter of its chain step, though that is below the 0.75 mm Stahnke
sets as his own floor for reconstruction. And these are production copies, so any
claim about a recording machine is one remove from the evidence. There is also a
plainer possibility not ruled out: the onset scatter concentrates in large,
low-circularity holes, 17.7 % of the largest quarter by area falling beyond
four tenths of a row against 0.9 % of the smallest, which points at the parser's
edge detection on merged holes rather than at the paper.

Stahnke's method goes further in two directions this does not follow. He also
finds and removes scatter, the column-to-column deviation left once skew is taken
out, and he reconstructs the punch matrix rather than only measuring its defects.

### The one change roll-image-parser needs

`analyzeTrackerBarSpacing` takes the tallest peak of the centroid histogram's
spectrum. The histogram is a comb of narrow spikes, so its harmonics are about
as strong as its fundamental, and a roll that uses only part of its tracks —
47 of 100 by the parser's own census, which counts the edge groups and tracks
carrying a handful of holes — can easily make a harmonic win. On this roll it
returned 18.91 px, exactly half the true 37.64 px, which put 4702 of 10453 holes
in the bad-hole pile.

The spacing is knowable within a narrow band before the transform runs, from
the measured roll width and the roll type's track count, so the fix is to
search only that band:

```cpp
double expected = getAverageRollWidth() / (getExpectedTrackerHoleCount() + 2.0);
```

with a ±25 % window around it. That is wide enough for every roll type the
parser supports and far too narrow to admit a harmonic. With it the measured
spacing is 37.66 px and the bad-hole count drops to 7, one below the 8 of the
reference analysis that ships with the repo.

### What the run produced

| | this roll | repo's reference roll |
| --- | --- | --- |
| image | 4096 × 103937 | 4096 × 164167 |
| roll width | 3877.10 px | 3895.98 px |
| hole separation | 37.6612 px | 37.7939 px |
| avg hole width | 23.77 px | 20.19 px |
| musical holes | 10456 | 11527 |
| bad holes | 8 | 8 |
| tears / dust | 0 / 0 ppm | 4 / 279 ppm |

Those are the figures after straightening. Unstraightened the same run gives a
roll width of 3828.65 px, 10453 musical holes and 7 bad holes; the paper measures
wider once the camera's inward bend at the edges is undone.

Four independent checks that the transcription is sound:

1. Counting punch runs straight off the image gives 10353 against the parser's
   10453 musical holes.
2. Gaps between punches within a track are bimodal with an empty valley from
   25 to 100 px (29 gaps out of 10306 fall in it). The parser's bridging
   threshold, 32.5 px, sits in that valley, so its note grouping is not a
   judgement call.
3. The extracted MIDI is in **F major** (Krumhansl-Kessler fit r = 0.911),
   the right key for *Träumerei*, so the track-to-pitch mapping is anchored
   correctly.
4. Its pitch-class profile matches the scanner's own MIDI at r = 0.955.

That last comparison also shows two things about the scanner's MIDI: it is
transposed (its numbers are track indices, not pitches — it reads as C# major),
and it re-attacks 1067 of 1492 consecutive same-pitch pairs within 80 ms,
splitting the punch chains of held notes into spurious repeats. Its 1529 note
events against the parser's 463 is that artefact, not lost detail.

Two things to keep in mind. `analyzeMidiKeyMapping` anchors the track numbering
by assuming the first track sits half a hole-separation in from the paper edge;
on this roll it is nearer two, and the assignment is rescued afterwards by the
rewind-hole alignment. It lands correctly here, but a roll type without a
rewind hole would have nothing to fall back on. And `analyzeLeaders` cannot see
this roll's leader, whose paper is the same width as the rest, so
`LEADER_ROW` is reported as 0; the scan only carries about 79 mm of blank paper
before the first perforation anyway.

## Lateral drift

None that I can measure. The paper edges hold to within ±2 px over all 44,000
lines in both files, so there is no evidence that either raster drifts sideways
as it goes, or that one was corrected and the other not. The across-roll
distortion described under [Feeding roll-image-parser](#feeding-roll-image-parser)
is a different thing: fixed in the sensor, the same on every line.

## CIS files

The rollscanners group, formed in 2001 around Richard Stibbons' contact image
sensor scanner design, stores its scans as `.CIS` files: 1-bit, run-length
coded, with a 52-byte header. Stibbons published the layout in 2003 and Pete
Knobloch had described an earlier version in 2002; PlaySK's reader follows the
same layout. Sample scans from this scanner family are in the PlaySK
repository, and Stanford's pianoroll.sapp.org has a short page on the format.

The format is Stibbons' own, written for his scanner rather than designed
separately, and the dated points along the way are these. In December 1999 he
and Spencer Chase had two machines nearly built. The earliest artefact of the
format is the description string in his own sample scan, `R Stibbons © 2000
02-07`. The trailing month and day is a scan date: it matches the file's own
timestamp in all seven surviving scans of that era. So the scan was made on
7 February, and the year in the string is a copyright rather than the date.
On 12 February 2001 he offered the design on the Mechanical Music
Digest as "a package of notes, diagrams and software", QuickBASIC source
included, by e-mail rather than from a site; the rollscanners group formed out
of that post, and by May 2001 had Gene Gerety's ROLLSCAN-1 board and a home at
Warren Trachtman's iammp.org. Knobloch documented the format on 5 May 2002 by
reading that source, without having spoken to any of them. Stibbons' own header
page followed on 22 February 2003, describing the revised layout, and the
scanner code that writes it carries the note "Based on CFG file version of
3 Feb 2003, R Stibbons".

```
cis2image.py [options] INPUT.CIS [OUTPUT.tif|OUTPUT.png]
```

```sh
# describe a file, with its .ANN sidecar when one sits beside it
python3 cis2image.py roll.CIS --info

# the holes, as a 1-bit deflate TIFF
python3 cis2image.py roll.CIS holes.tif

# the printing of a bi-colour scan, the first 12000 lines, readable
python3 cis2image.py roll.CIS text.png --channel ink --lines 0:12000 --rotate

# a 1:8 overview of paper, holes and printing together
python3 cis2image.py roll.CIS overview.png --channel composite --shrink 8
```

| Option | Effect |
| --- | --- |
| `--info` | print the header, then stop |
| `--lines A:B` | convert only these scan lines |
| `--channel NAME` | `holes` (default), `twin`, `ink`, or `composite` |
| `--rotate` | turn by 180 degrees, the view of the roll on the piano |
| `--shrink N` | block-average N × N pixels into one grey level |

A single channel comes out as a bilevel image, white where light reached the
sensor: in `holes` that is a hole or the space beside the paper, in `ink` it
is everything but printing. `composite` needs a bi-colour scan and paints the
paper grey, holes white and printing black. The TIFF carries the header's
across and along resolutions, deflate compression and the title as its
description.

### Layout

| Offset | Bytes | Content |
| --- | --- | --- |
| 0 | 32 | title, space padded |
| 32 | 2 | reserved |
| 34 | 2 | status word, below |
| 36 | 2 | vertical separation of a twin array, in thousandths of an inch |
| 38 | 2 | dots per inch across the roll |
| 40 | 2 | pixels per line |
| 42 | 2 | changeover pixel between the two arrays of a twin scanner |
| 44 | 2 | tempo printed on the roll |
| 46 | 2 | steps or encoder ticks per inch along the roll, before division |
| 48 | 4 | number of lines |
| 52 | | run-length data |

All integers are little-endian. In the status word, bits 0–3 give the scanner
type (1 free run, 2 position encoder, 3 shaft encoder, 4 stepper, 5 Kevin
Keymer's delta mode 4), bit 4 speed-doubling hardware, bit 5 a twin array,
bit 6 bi-colour, bits 8–11 the encoder division as a power of two, bit 12 a
mirrored scan and bit 13 a reversed one. The scanner code names bits 12 and 13
`HorzReverse` and `VertReverse`.

The lines-per-inch field and the division go together for a reason. Stibbons'
build notes describe the position encoder as a repurposed hand scanner whose
wheel "produces a tick every 1/400th of an inch", with a divider on the
interface card reducing "the 400 ticks per inch generated by the hand scanner
down to a more useful 200 or 100". So the field holds the encoder's own rate and
the division says what was taken from it, which is what `along_dpi` computes.

A scan is more often multi-channel than not. Of 7,358 CIS files surveyed in the
public archives, 4,934 are bi-colour and 122 twin-array, so two thirds carry a
second sequence per line and the `ink` and `composite` channels matter more than
the format's own documentation suggests.

Each line then holds one run sequence per channel, in the order holes, twin
array, ink: 16-bit run lengths alternating between dark and light, starting
dark, that add up to the pixels per line. A line that begins light starts
with a zero-length dark run. After the last channel comes one status word,
whose bit 5 carries the hardware clock, bit 7 the encoder state and bit 15 a
data overrun. The reader locates every sequence by walking the cumulative
sum of the whole file, which has to be sequential because each status word
shifts the sum for every line after it, and then renders rows by toggling at
each run boundary.

Those two rules interact badly if the status word is ignored. On a stepper scan
every status word is zero, and a zero is also how a line that begins light
opens, so a reader not expecting the word absorbs it as a leading run and parses
the file as twice as many single-channel lines, self-consistently and with no
error. How many sequences a line holds has to come from the status word's bits 5
and 6, never from the data. This reader requires the word and refuses a file
with anything left over after the last line.

### The earlier layout

Stibbons' page describes the second version of the header. Files written before
it carry the one Knobloch documented in 2002, and the two agree from byte 40 on:

| Offset | Bytes | 2002 | 2003 |
| --- | --- | --- | --- |
| 0 | 32 | description, 40 bytes | title |
| 32 | 2 | " | reserved |
| 34 | 2 | " | status word |
| 36 | 2 | " | twin-array separation |
| 38 | 2 | " | dots per inch across |
| 40 | 12 | pixels, reserved, tempo, lines per inch, line count | the same five fields |

The later fields were carved out of the tail of the description rather than
appended, which is why Knobloch's 40-byte title and Stibbons' 32-byte one
describe one format and not two. Knobloch gives the defaults of the day as
2,432 pixels, 182 lines per inch and a tempo of 90 where the field is zero, and
his sample scan is titled "R Stibbons © 2000 02-07", so the format is at least
that old.

His 182 looks wrong, and he half-suspected the field himself, asking whether it
was lines per inch at all. All seven of Stibbons' surviving scans of 2000–01
declare **180**, and 180 is what Spencer Chase's files carry three years later.
The width and the tempo default stand; that one figure does not.

The scanner's own `FIXCIS.BAS` tells the two apart by reading the reserved word
at bytes 32–33, which the writing code sets to zero and which falls inside the
earlier description: non-zero means the earlier layout. `cis2image.py` uses that
test, and adds the one on bytes 34–39 being text, since Knobloch notes a
description could be cut short with a NUL, which would defeat the first. No
later file can look early under either test, the second meaning a resolution of
8,224 dpi or more.

Take the layout test from `FIXCIS.BAS` and nothing else. It is the oldest file in
that package and the only one without a version comment, and its reading of the
status word is out of date: it takes bits 6–7 as a reverse field, where the
writing code and Stibbons' own specification give bit 6 to bi-colour and put
reversal on bits 12–13. Worse, it writes that reading back, so running it over a
bi-colour scan silently reclassifies it and drops the mirror and reverse flags.

An early file states neither its scanner type nor its across-roll resolution. It
is read as a stepper, and at the resolution its width implies, following
`CISREPORT`: "it is assumed to be a Stepper Scanner and the Horizontal
Resolution is inferred from the Scan Width".
`--info` says which layout was found and marks both assumptions. Since
`cis2roll.py` scales the across axis by that figure, its report says so too.

Early files survive and the reader is tested against them. Knobloch prints the
first 400 bytes of `40057AO.CIS`, the sample scan in Stibbons' `SCANNER.ZIP`,
and the tests parse those bytes: description `R Stibbons (c) 2000 02-07`, 2,432
pixels, tempo 55, 182 lines per inch, 31,022 lines, with the two run sequences
that follow adding to the line width. Whole files survive too: seven Duo-Art
scans of November 2000 to July 2001, from Stibbons' section of the
pianorollmusic.org archive, `SSSS.CIS` on Julie Porter's roll transport page,
and Spencer Chase's scan of Welte roll 225, which is
[described below](#a-licensee-copy-of-the-same-performance). All nine read end
to end here, every line summing to the width.

Those nine may be most of what is left. A survey of the public archives,
reading the header of every CIS file reachable in them, came to 7,352 files of
which eight are early, Chase's not being among them. The 2003 revision was close
to total, so the path this section describes is rarely exercised and worth
keeping anyway.

Those nine also settle the resolution, which an early file does not state.
`CISREPORT` says it is "inferred from the Scan Width", and two sensors are
attested. The seven Duo-Art scans are 2,432 pixels wide and measure
203.7 ± 0.3 dpi against that roll type's 0.11111 in track pitch, the estimates
spanning 0.7 dpi: that is the 8 dots/mm of a fax sensor, and not the round 200
PlaySK assumes for a scan it cannot identify. Chase's scan is the same width and
measures 203.6 dpi against the Licensee's 1/9 in pitch, on a second machine of
that generation; his own conversion software stamped `scanner_horiz_DPI: 204`
into every file it wrote, so the declaration and the measurement agree to within
half a dot. Porter's is 3,648 pixels, the
DynaImage A3 that the later files declare as 300 dpi, and read at 300 its
tracker pitch comes out 0.1228 in against the 0.1227 her own `Rollfile.ini`
gives for a Wurlitzer 165.

The scanner type of an early file is still assumption.

The reader has been run against every status-word variant found in that survey —
twin, bi-colour, speed-doubled, encoder-divided and plain, early layout and late
— and parses each to zero leftover words.

Six programs that read or write this format were consulted while the reader here
was written: Stibbons' QuickBASIC capture program, his two readers and his
header editor, Gerety's Windows `RollSCAN`, Robinson's converters, Sasaki's
PlaySK and Julie Porter's Macintosh *Maddalena*. None of them reads more of the
header than this one, and most read less. The QuickBASIC readers never look at
the mirror and reverse bits, and *Maddalena* reads five fields and nothing else,
skipping the status word entirely. That is the ground for thinking this reader
complete, which is a weaker thing than knowing it.

The per-line status word changed as well. Knobloch describes an encoder value
cycling 0x0C, 0x08, 0x04, 0x00, that is bits 2 and 3, beside a real-time clock
he never saw move, and he advises ignoring the word; Stibbons puts the clock on
bit 5, the encoder on bit 7 and an overrun flag on bit 15. The reader follows
the later reading, and uses only the overrun bit.

### Orientation

Lines are stored in scanning order, so line 0 is the leader and the roll runs
down the image, which is also how the Stanford scans are oriented. On the one
file examined, a bi-colour stepper scan of an Auto Pneumatic Action Company
test roll at 300 dpi and 300 lines per inch, the printing reads upside down
and not mirrored, so the bass side is at the left and `--rotate` gives the
view on the piano. Encoder-clocked scans are written line for line; their
lines are not evenly spaced along the roll, and re-clocking them, as PlaySK
does, is not attempted here. The two arrays of a twin scanner are written as
separate channels rather than stitched.

### Feeding roll-image-parser from a CIS scan

`cis2roll.py` does for a CIS scan what `mrs2roll.py` does for an MRS one: it
writes the square-pixel 300 dpi RGB TIFF described under
[Feeding roll-image-parser](#feeding-roll-image-parser), with the paper centred
in a 4096-column frame.

```sh
python3 cis2roll.py roll.CIS --dry-run     # show the calibration
python3 cis2roll.py roll.CIS roll300.tif
tiff2holes -g roll300.tif > analysis.txt
```

| Option | Effect |
| --- | --- |
| `--dry-run` | calibrate and stop |
| `--dpi N`, `--width N` | target grid; 300 dpi and 4096 columns by default |
| `--rotate` | turn by 180 degrees |
| `--mirror` | mirror across the roll, for a scan with the bass on the right |
| `--no-despeckle` | keep the scan's isolated lit pixels |

The roll type belongs to `tiff2holes` rather than here: `-g` for a green Welte
T-98, `-l` for a Welte Licensee, `-r` for a red T-100.

Neither scale has to be measured as it does for MRS. The header records the
sensor's dots per inch across the roll and the transport's lines per inch along
it, and on the scan tested those differ — 300 against 360 — so each axis is
simply rescaled. The tracker pitch those figures imply is measured back off the
holes, by the comb fit `mrs2roll.py` uses, and printed as a check on both.

Two things need handling beyond the resampling.

**The scanner bed reads as paper.** The sensor is wider than the roll, and what
lies beside the paper is not simply bright: on the scan below, columns 1–14 are
lit, 15–127 are dark on every line, 128–176 are lit again, and the roll runs from
177 to 3548. Taking the first dark column for the paper edge puts it 162 columns
too far out and hands the parser a roll 0.54 in too wide, with a quarter of its
bass margin scored as dust. The dark strip is fixed in the sensor — its position
does not correlate with the roll's drift (r = +0.03) where the edge at 177 does
(r = +0.85), and the width from 177 to the treble edge holds to 1 px — so it is
the bed, or a guide, and not the roll. The paper is therefore taken to be the
*widest* run of columns dark more often than not, and everything outside it, plus
a margin for the measured wander, is painted as background.

The margin kept for that wander has to stop where the bed begins, which the
Licensee scan below made plain. Its lit gap on the bass side is only 18 columns
wide against the Dyer scan's 49, so the fixed margin of wander plus 16 columns
reached past it into the bed. Those columns are dark, the parser reads them as
paper, and the bass margin comes out pinned at the frame edge on every line:
`analyzeLeaders` then finds a margin that never moves on one side and a roll
that drifts on the other, and stops with "Cannot find leader". `find_paper`
therefore reports the dark runs on either side of the paper along with the band
itself, and `Paper.keep` clips the margin to them; the calibration prints what
it kept against what it asked for. On a scan with room to spare, Dyer's among
them, nothing changes.

**A one-bit scan speckles.** Isolated lit pixels that an eight-bit scan would
have averaged away survive quantisation, and `tiff2holes` counts them as dust:
`ANTIDUST_COUNT` came out at 6823 against 0 for the MRS scan above. Connected
components inside the paper separate cleanly — 9445 blobs under 60 px, only 59
between 60 and 199, then 14016 at 200–499 px, which are the punches — so a 3×3
opening clears the noise and cannot reach a punch twenty pixels across. On this
roll it took `ANTIDUST_COUNT` from 6823 to 2, moved `MUSICAL_HOLES` by one and
`AVG_HOLE_WIDTH` by 0.27 px, and left the extracted MIDI identical key for key.

**The scan line can sit at an angle to the punch rows.** `cis2roll.py` measures
that skew and prints it, by the method described under
[Skew along the roll](#skew-along-the-roll), and leaves the image alone. The two
CIS scans of roll 225 differ here more than anywhere else in their geometry: the
Dyer scan comes out at −0.77 mm along the roll across its 285 mm of paper, about
10.9 scan lines or 9 px once resampled, where Chase's reads +0.11 mm, under a
scan line. The MRS scan of the same performance reads −0.18 mm, so the Dyer
figure is the outlier of the three and holds steady page by page down its own
roll, and the MIDI written from Chase's scan declares that his conversion
software corrected skew automatically, which fits his being the one that measures
near zero. What the estimator cannot do is tell a tilted sensor from an asymmetry
in the playing, which is why three scans of one performance are needed to say
anything at all.

### What the run produced

Julian Dyer's T-98 scan of Welte roll 225 (Grünfeld, *Träumerei*), 3648 × 115246
at 300 × 360 dpi, converted to 4096 × 96038 and parsed with `tiff2holes -g`:

| | value |
| --- | --- |
| paper | 3372.67 px = 11.24 in |
| hard margins | 358 px bass, 358 px treble |
| hole separation | 33.2957 px = 0.1110 in (9.01 tracks/in) |
| tracker grid residual | 0.043 |
| tracker holes | 98 |
| musical holes / notes | 15681 / 1103 |
| antidust / bad holes | 2 / 0 |
| tears / dust | 0 / 0 ppm |

The tracker grid residual of 0.043 says the hole columns sit on a straight grid,
so no straightening is called for; the CIS sensor shows nothing like the MRS
camera's across-roll bend. The extracted MIDI runs C1–G7 with expression on 16–20
and 109–113, which is the Welte 80-note compass inside the T-98's 98 tracks.

Read `MUSICAL_NOTES` with the trailer in mind. The 1103 counts everything the
paper carries, the rewind slot and the test section included. What the piano
plays is the 742 chains beginning before row 82462, where the rewind slot starts:
**464 notes, 185 bass valve chains and 93 treble**. The cut is exclusive of that
row, and has to be — the rewind chain's own attack sits exactly on it.

The red Welte copy of the same performance gives the external check, and on notes
the two agree to within one: 463 of the green's 464 note onsets match a red onset,
leaving a single green note with no counterpart, over an alignment whose residual
stays inside ±0.64 mm along the whole roll. Measured in the roll-desk edition, not
here. Comparing the two `MUSICAL_NOTES` totals instead would mislead, since each
includes its own post-performance marks and only the green has a test section.

On playback speed the roll speaks for itself: it wants `setTPQ(420)`. Welte's
printed "tempo" is roughly feet per minute times ten, the CIS header records
tempo 70, Welte's own Skala-Rolle 98 booklet is calibrated at 70, and Phillips
gives the green Welte 7 ft/min against nearly ten for the red. `cis2roll.py`
prints the header's tempo and the ticks it implies, since the right value belongs
to the roll rather than to the format.

Comparing the two copies is a weaker check than it looks. Aligning them note by
note gives a scale of 1.2907 between the two papers — Theil–Sen over 463 matched
pairs at 0.99 mm rms, measured in the roll-desk edition rather than here. Read as
pure speed that would put the red copy near tempo 90, comfortably below the
parser's generic 98.5, which is the point worth keeping: 98.5 is a format default
and not roll 225's own tempo. But the scale between two papers also carries
whatever one has shrunk and the other stretched, and a single pair of copies
cannot separate stretch from speed. A ratio taken from two landmark holes instead
of the whole alignment is weaker again, and easy to get wrong: measure the green
to its last performance hole and the red into its post-performance marks and the
answer comes out near 1.35, because the run-out between last note and rewind is
3.3 in on the red against 10.8 in on the green.

Three things about the parser are worth knowing before repeating this.
`setRollTypeGreenWelte` was an unfinished stub that called `exit(1)`, and its
draft carried two values copied from the red Welte;
`analyzeTrackerBarSpacing` indexed 4096 columns unconditionally and aborted with
an uncaught `std::out_of_range` on anything narrower, which is why the frame here
is padded to 4096 rather than left at the sensor's 3648; and the TIFF reader
discarded tag 258 and assumed eight bits per sample. All three are fixed in the
copy of roll-image-parser used here.

A fourth is not a bug but a mismatch of assumption. `assignMidiKeyNumbersToHoles`
checks the tracker grid by finding the track whose first perforation comes latest
and expecting it to be the rewind. A T-98 has no such track. Welte's own
*Gebrauchsanweisung* for the Skala-Rolle 98 (§10) and the *Technische
Beschreibung* (pp. 17–18) put the rewind on bass hole 1, worked by the same valve
as Bass Forzando-piano and told apart from it by length alone: short perforations
play the expression, and one very long one, against a bellows given enough dead
travel that a short one cannot trip it, rewinds the roll. This scan shows exactly
that — 20 punches of at most 0.19 in on hole 1 during the music, then a chain of
177 punches with 0.019 in bridges running 15.2 in, beginning 16.8 in after the
last note. So the check is switched off for this roll type rather than pointed at
a hole, and the track numbering rests on `m_minTrackerSpacingToPaperEdge` alone —
how far in from the bass paper edge the first tracker position sits, in hole
separations. For the T-98 that is 2.125 by construction: 98 tracks at 9 to the
inch span 97/9 in, leaving (11.25 − 97/9)/2 in at each edge. Measurement agrees
across four scans — 2.08 and 2.09 on the two sides of this roll, and 2.07 to 2.33
per side on three Stanford scans of two Condon rolls. Most of that spread is how
the soft margin is split rather than a difference between rolls, one test roll
scanned twice giving 2.07 and 2.28; the rest is paper measuring 11.24 to 11.28 in
wide. `analyzeMidiKeyMapping` snaps to the nearest tracker position, so it needs
the figure only to half a spacing and every measurement is inside a quarter of
one.

The slot is a chain, not a single opening, which matters if you go looking for
it: measuring unbroken openings finds nothing longer than 0.19 in on hole 1 and
misses the rewind entirely. Two original green Welte rolls in the Condon
collection at Stanford, measured the same way, cut it identically:

| | rewind slot | punches | die | bridge | pitch |
| --- | --- | --- | --- | --- | --- |
| Welte 3414, Reger/Kwast-Hodapp (original) | 10.07 in | 109 | 19 px | 6 px | 25 px |
| Welte 98er test roll (original) | 5.48 in | 60 | 19 px | 7 px | 26 px |
| this roll, Dyer's 225 | 15.20 in | 177 | 19.2 px | 5.8 px | 25.0 px |

All three at 300 dpi. The slot's length varies — it need only be long enough to
collapse the bellows — but the punching does not, and roll 225's note
perforations quantise the same way the originals' do, clustering at 19–20 px and
then at 29, 34, 39 and 45 px, which is a 19–20 px die on a 5 px step.

Past the rewind slot, where the paper never reaches the tracker bar because the
roll is already rewinding, roll 225 carries a **test section**: the graduated
pattern commonly appended to a roll — sometimes prepended instead — for checking
that the reproducing mechanism responds on every channel. It runs 9.2 in, holds
547 perforations spread over 90 of the 98 positions, and gives each of them about
six notes whose lengths step through the die-and-step series, 19, 24, 29, 34, 39,
44 and 49 px. The 90 positions are holes 1–5, 9–88 and 94–98: the perforator's
whole working set, skipping the eight note positions outside the 80-note compass,
which is what a pattern meant to exercise every pneumatic should cover. A 2.3 in
chain on the track at MIDI 108 sits in the same tail, 5 in ahead of it.

None of that is music, and the parser counts it: the tail accounts for 361 of the
1103 `MUSICAL_NOTES`, four on each note track, and `LAST_HOLE` runs to the end of
the section. Whether
to keep it is a judgement for whoever reads the analysis — it is a genuine part of
the roll, just not part of the performance. Neither of the two original rolls
above carries one, and on 3414 hole 93 is empty throughout, so a test section is
evidently not something every green Welte roll was issued with.

### A Licensee copy of the same performance

Spencer Chase's scan of roll 225 is a second copy of the same Grünfeld
*Träumerei*, and a different edition of it: a Welte-Mignon (Deluxe) Licensee,
the American re-cut, against Dyer's German green T-98. It also carries the
2002 header, which makes it the ninth early file this reader has seen and the
second, after Porter's, from a machine other than Stibbons' own.

```
header        Knobloch 2002 layout
title         Traumerei 07-14
scanner       stepper (assumed)
raster        54286 lines x 2432 pixels; channels holes
across        203 dpi (assumed)
along         180 lines per inch
tempo         80
```

The title follows the convention of the format's own sample scan, a scan date
with no year: 14 July. The file states neither scanner nor across-roll
resolution, so both are the inferences described under
[The earlier layout](#the-earlier-layout), and this scan is the first chance to
check the resolution one against a roll of known geometry. Read at 203 dpi the
paper comes out 11.256 in and the tracker pitch 0.1114 in, so the pitch implies
203.6 dpi against a nominal 1/9 in. That sits between the 203.7 ± 0.3 measured
on Stibbons' Duo-Art scans and the 204 Chase's own conversion software stamped
into the files it wrote, and it is a measurement on his machine rather than a
declaration of it.

It parses end to end, every line summing to the width, with no overruns.

Beside the CIS sit Chase's `.bar` and `.ann`, which were all this project had of
his copy until now. The annotation names the roll correctly — `/roll_class:
Licensee`, `/roll_number: 225` — and the scan bears that out track for track.
Its `/roll_tempo: 83` and the header's tempo 80 do not agree with each other, and
neither agrees with the green's 70; the tempo field is what the operator typed,
and on this format it is worth no more than that.

Converted to 4096 × 90477 and parsed with `tiff2holes -l`:

| | Chase, Licensee | Dyer, green T-98 |
| --- | --- | --- |
| source | 2432 × 54286 at 203 × 180 dpi | 3648 × 115246 at 300 × 360 dpi |
| paper | 3377.73 px = 11.26 in | 3372.67 px = 11.24 in |
| hole separation | 33.4130 px = 0.1114 in | 33.2957 px = 0.1110 in |
| tracker grid residual | 0.092 | 0.043 |
| tracker holes | 98 | 98 |
| musical holes / notes | 10080 / 955 | 15681 / 1103 |
| notes in the compass, before the rewind | **463** | **464** |
| antidust / tears | 2 / 0 | 2 / 0 |

**The layout is the Licensee's, valve for valve.** Anchoring the tracker grid on
the rewind puts track 1 at 2.24 spacings from the bass paper edge and track 98 at
2.45 from the treble, which is the 2.125 the geometry requires to within a
quarter of a spacing, and every lock-and-cancel pair then comes out matched:
bass Crescendo off/on at 86 and 86 punches, bass Forzando at 18 and 19, bass Soft
pedal at 2 and 3, treble Sustain at 52 and 51, treble Forzando at 3 and 3, treble
Crescendo at 83 and 83. Mezzoforte is punched once, on the bass cancel track
before the music begins, and not at all on its treble pair, so the hook is
cancelled at the head of the roll and never set.
The rewind is a single 1.5 in perforation on track 89, 13 in past the last note,
which is the T-100's dedicated rewind track moved two places in — quite unlike
the green, where the rewind shares bass hole 1 with Forzando piano and is told
from it by length. That makes `assignMidiKeyNumbersToHoles`'s rewind check usable
here, where on the green it had to be switched off.

**Neither the rewind slot nor a test section.** Past the rewind punch the paper
runs 21 in blank to the end of the scan. The green copy's 15.2 in chain of 177
punches and its 9.2 in graduated test section have no counterpart, which is why
the two `MUSICAL_NOTES` totals are not comparable and the note counts in the
table are taken before each copy's rewind instead.

**On notes the two copies agree to within one**, 463 against 464, and every one
of the 37 pitches the Licensee carries also appears in the green. The 43 pitches
the green has and this one has not are its test section sweeping 90 of the 98
tracks. That is the same agreement the red copy gave, and it is now three
editions of one performance agreeing on the notes.

**The scan reads holes wider than they are long.** Measured on isolated single
punches, the Licensee scan gives 0.0788 in across and 0.0611 in along, an aspect
of 1.29, where the Dyer scan gives 0.0667 and 0.0639, an aspect of 1.04. The
along figures are close enough to each other to corroborate the header's 180
lines per inch: a scale wrong by the 14 % that would square the punches up
would put the die at 0.069 or 0.054 in against the green's 0.0639. So the
across dimension is the one that is off, by about 0.012 in or two and a half
sensor pixels, and it is the scanner's own slicing level rather than the roll or
the resampling. A third of a pixel of it is the 3×3 opening, which takes the
across width from 0.0837 to 0.0788 in and leaves the length alone.

That bloom trips `tiff2holes`'s aspect check, which rejects a hole wider than
1.25 times its length as a tear and threw out 6705 of 10079 holes on this scan.
The check assumes a scan that responds alike in both directions, which this one
does not, so the threshold is now a `--aspect` option rather than a constant.
The figure used here is 1.55: the default clears an isotropic scan's 1.04 by a
factor of 1.20, and the same margin over this scan's 1.29 gives 1.55.
`BAD_HOLE_COUNT` falls from 6705 to 95, `EDGE_TEAR_COUNT` stays 0, and the
extracted MIDI is identical either way — the check reaches the quality report
and the marked-up image, not the music. Whether the bloom should instead be
taken out of the image is an open question below.

**Chase's own reading of the roll agrees with the analysis.** The `.bar` beside
the CIS is his software's hole list for the same copy, at its own calibration of
400 rows to the inch, and it is an external check on everything above. Imported
into the `linked-rolls` edition alongside the analysis, the two give the same 51
tracker positions with the same counts on each, and 953 of the `.bar`'s 955 holes
find a counterpart within 1.5 mm. Aligned note by note the residual is 0.026 mm
over 463 notes, and the onsets differ by a median of 0.000 mm with the fifth and
ninety-fifth percentiles at ±0.063 mm. The scale between them comes out
1.000833, which is exactly `LENGTH_DPI`: the reader divides by that literal
300.25 where this image is 300 dpi, so the two calibrations agree outright once
the constant is taken off. That also settles the along-roll figure from a second
direction, since 400 rows to the inch and 180 lines to the inch describe the
same paper.

Three holes differ, and none of them is a note. The `.bar` reads a Mezzoforte-On
at the head of the roll where the scan has a slot 0.19 in wide and 2.3 in long,
spanning two tracker positions and far too wide to be a punch; it lies in the
leader, and the analysis leaves it out. The `.bar` splits one C4 into a short
punch and the chain behind it where the analysis reads the two as one note, a
borderline call at a 0.063 in bridge. And the analysis carries the rewind, which
the `.bar` stops short of, so the edition can find the roll's end from the
analysis and not from the `.bar`.

Two things the `.bar` cannot be asked for and the analysis gives: the
measurements — paper width, hole separation, margins, scan resolution, punch
diameter, and the software and date behind them — and a track calibration, since
the `.bar` is already on tracker positions and states nothing about the image it
came from. What the `.bar` has and the analysis has not is the paper speed, which
its `.ann` states as tempo 83.

One thing to pass by hand. `readFromStanfordAton` infers the track shift by
putting the rewind on the bar's rewind track, and finds it as the holes past the
last musical attack — which works on the green, whose rewind is a chain of 177
punches whose continuations carry no attack. Here the rewind is a single punch,
so it is the head of its own chain, carries an attack, and leaves nothing behind
it; the fallback, the columns spanning the full track count, does not fire either
because the occupied ones span 96 of 98. The shift falls back to zero and the
import comes out unusable, 678 notes and no expression at all. Passing
`trackShift: track(-12)` gives the reading above, and the `.bar` confirms it
independently by putting the same counts on the same positions.

**Playback speed is the roll's own.** `setMidiFileTempo` has no figure for this
format and should not borrow one: Phillips (p. 181) says Licensee rolls play at
a range of paper speeds. The parser writes the neutral `setTPQ(480)`, which is
6 × 80 and happens to match this header's tempo 80, and `cis2roll.py` prints the
header's tempo and the ticks it implies so the choice stays visible.

Four things about the parser were needed for this scan, on top of the four the
green copy needed. `setRollTypeLicensee` did not exist — `-l` was declared and
documented as "not yet active" — and is now implemented from the scale in
Hagmann (p. 40 f.) and Phillips (p. 123), the layout Stanford's `midi2exp`
reads, and the same tracker geometry as the green, 98 tracks at nine to the inch
on 11¼ in paper. `analyzeLeaders` tested each margin separately for a leader and
stopped on anything else, so a roll that tracks 6 px sideways over its first
seven inches, as this one does while the transport takes up, was refused as a
partial roll; the test is now on the width between the margins, which a lateral
shift leaves alone and a leader does not. The aspect threshold became an option,
as above. And `setMidiFileTempo` gained the branch described above.

## Open questions

- The last 6 % of PNG pixels, each off by one level. Probably a rounding or
  precision difference in the scanner's own arithmetic; `floor` matches better
  than `round`, but not perfectly.
- Why this roll's tracks sit 1.6 % further apart relative to its paper than the
  nominal Welte-Rot scale (99 pitches span 1,531 px inside a 1,569 px paper,
  leaving 3.9 mm to the first track where the trailer says 6.5). Undoing the
  camera's across-roll distortion takes something over half of this out, since
  the pitch is measured where the magnification is highest and the paper edges
  sit where it is lowest. What remains may be the roll: the trailer has
  `Is Replica=1`, so a recut with slightly different geometry would explain it,
  though that is an inference from a flag and this roll cannot test it. A second
  Welte-Rot scan with `Is Replica=0`, straightened the same way, would.
- Why the measured across-roll resolutions sit where they do relative to the
  published 0.22 and 0.21 mm/px, and in particular why the colour camera's
  field of view comes out much wider than the black-and-white one's when the
  published figures make them nearly equal.
- Whether the chunk size is fixed per camera or simply a write-buffer size that
  could differ on other scans.
- Whether the Licensee scan's across-roll bloom should be taken out of the image
  rather than worked around in the parser. It measures a fairly constant
  0.012 in, which an erosion of one source pixel across would very nearly
  undo, and that would put the punches on the green copy's die. But the figure
  is calibrated against the other copy, and eroding the image to make a
  threshold pass is the retuning this project has otherwise refused. Whether the
  bloom is constant, or grows with the punch, would want more than one scan from
  that machine to say.
- What the tempo of roll 225 is on Licensee paper. The header says 80, the `.ann`
  83, and the green copy 70, while the music in the two copies occupies nearly
  the same length of paper, which those tempi do not predict. Separating paper
  speed from the shrinkage and stretch of two different papers needs more copies
  than this, exactly as it does for the green and red pair above.

## References

- Debrunner, D. *Die Entwicklung des Musikrollenscanners der Berner
  Fachhochschule – aus Musikrollenbildern wird Musik – die elektronische
  Steuerung der Welte-Philharmonie-Orgel.* The scanner that produced these
  files (`ScanOrt=Biel` in the `.dsp`). Gives the scan resolutions, the roll
  type table including Welte-Rot at 328.5 mm and 100 tracks, the calibration
  procedure, and names the two raw formats: "*.mrs (Bilddaten der Durchlicht
  Schwarz-Weiss-Kamera) und *.mrsc (Bilddaten der Auflicht RGB-Kamera)".
  PDF at `~/Zotero/storage/9PH97AGL/`.
- SUPRA MIDI specification, <https://supra.stanford.edu/midi-spec/>. Documents
  the analysis fields `tiff2holes` emits, and gives Stanford's along-roll
  resolution as 300.25 dpi, measured on *their* scanner in November 2017 to
  ±0.25 dpi. That figure belongs to the Stanford machine and should not be
  applied to MRS scans; `LENGTH_DPI` in any analysis produced here is that
  literal constant, not a measurement of the input.
- roll-image-parser, <https://github.com/pianoroll/roll-image-parser>.
- Hagmann, P. *Das Welte-Mignon-Klavier, die Welte-Philharmonie-Orgel und die
  Anfänge der Reproduktion von Musik*, p. 40 f., and Phillips, P. *Piano Rolls
  and Recorded Piano Rolls*, p. 123 and Table 4.3, for the Welte-Mignon
  Licensee: 98 positions at nine to the inch on 11¼ in paper, reading the
  T-100's commands minus its two motor tracks, so the note block and the treble
  valves sit two positions lower. Phillips p. 181 for Licensee rolls playing at
  a range of paper speeds. The hole-by-hole layout `setRollTypeLicensee` uses is
  the one Stanford's `midi2exp` reads; it was checked valve by valve against
  roll 225 in the `linked-rolls` edition before being carried here.
- Stibbons, R. *Contact Image Sensor Roll Scanner File Formats*, 22 February
  2003, <http://semitone440.co.uk/rolls/utils/cisheader/cis-format.htm>. The
  header and status-word layout followed by `cis2image.py`.
- Knobloch, P. *CIS File Format (Preliminary)*, Rev A1, 5 May 2002, read from
  Stibbons' QuickBASIC scanner software. Describes the earlier layout with a
  40-byte description; archived copy at
  <https://web.archive.org/web/20130310192155id_/http://www.trachtman.org/rollscans/CIS_File_Format.doc>.
- `CIS33.BAS`, `FIXCIS.BAS` and the rest of the Mk3a scanner source, QuickBASIC,
  in `MK3a_software.ZIP` on Trachtman's iammp.org, archived at
  <https://web.archive.org/web/20070721162941id_/http://www.iammp.org/design/files/MK3a_software.ZIP>.
  Take that copy rather than the one now served from pianorollmusic.org, which
  is a 2026 repack with six of its compiled binaries truncated to zero bytes.
  The `source.zip` inside is byte-identical in both, so the code is unaffected.
  The code that writes the format, and the primary source for it: `CIS33.BAS`
  builds the status word and the header field by field, and `FIXCIS.BAS` reads
  both layouts. Credited to R. Stibbons, with later work by KMK and JRD.
- Stibbons, R. "Roll Scanner Design Package", *Mechanical Music Digest*,
  12 February 2001, <https://www.mmdigest.com/archives/Digests/200102/2001.02.12.06.html>,
  and "Rollscanners Group Progress", 26 May 2001,
  <https://www.mmdigest.com/archives/Digests/200105/2001.05.26.01.html>. His
  own account of releasing the design and of the group forming around it; his
  MMD archive is <https://www.mmdigest.com/Archives/Authors/Aut1197.html>.
- *CIS Utilities* readme, April 2005, in `CISUtilities.ZIP` on iammp.org.
  Anthony Robinson on re-clocking encoder scans, and on having "dragged Richard
  out of retirement" to settle ambiguities in the specification.
- Stahnke, W. "Skew, Scatter, and Pitch in Music Roll Scans", in Judith Kemp
  (ed.), *Digitising Piano Rolls*, Deutsches Museum Studies 17 (2026),
  pp. 83–128. Defines skew and scatter as the two systematic errors of a roll
  scan, separates static from dynamic skew, and gives models that find both
  along with the pitch and reconstruct the punch matrix. The skew measurement
  here follows the definition and takes the estimate no further than the static
  mean; scatter and the punch matrix are not attempted.
- `W225E.mid`, the MIDI distributed with Chase's scan of roll 225, converted
  6 March 2004 by Trachtman's software and copyright 2006 Spencerserolls.com.
  Its text meta-events follow the keyword scheme below and record the conversion's
  own settings: `/scanner_horiz_DPI: 204`, `/scanner_LPI: 180`,
  `/skew_correction:   0.0112 degrees | Auto`, `/punch_length:  0.075 inches |
  manually set` and `/Punch_Matrix_Restoration: DISABLED`. These are the
  software's claims about its own output, not measurements made here, and they
  are used above only as evidence that a skew-correction step was in that
  pipeline and not in Dyer's.
- Stahnke, W. *Annotation Keywords*, <http://semitone440.co.uk/rolls/utils/stahnke/keywords.htm>.
  The specification for the `.ANN` sidecar `cis2image.py` reads, and the reason
  the file is his rather than the scanner group's. It states the syntax — "All
  keywords begin with a slash ('/') and end with a colon (':'), and do not
  contain embedded white space. The slash must be at the start of a line" —
  then 35 keywords in five groups with their units, and a table of the
  `/roll_type:` and `/roll_class:` pairs, among them Welte-Mignon Red/T-100,
  Green/T-98 and Licensee. Trachtman adopted the scheme for his MIDI text
  events and says so. Alongside it at
  <http://semitone440.co.uk/rolls/utils/stahnke/> sit `rollfile.htm`, the byte
  specification of his RAW, WEB and BAR containers, and `imagefile.htm`. His
  *View and Edit Music Roll Image*, V10.48, 1991–1997, with sample `.ann`,
  `.bar` and `.web` files, is in `mmdigest.com/Tech/57504a.zip`.
- Stibbons, R. *How to build a Piano Roll Scanner*, signed 4 February 2001,
  archived at
  <https://web.archive.org/web/20070627001331id_/http://www.iammp.org/design/files/How_to_build_a_Roll_Scanner.doc>
  and still served from <http://www.pianorollmusic.org/designfiles.php>, where
  it is credited to another contributor; the document itself carries Stibbons'
  byline and signature. The hardware behind the header: the position encoder is
  a repurposed hand scanner ticking every 1/400 inch, divided down to 200 or 100
  lines. Written eight days before he offered the design on the Digest, so it is
  the surviving half of that package. The QuickBASIC half lived at
  `groups.yahoo.com/group/Rollscanners/files/scanner.zip`, which the Wayback
  index still lists, but no capture holds its bytes: the only one, of 8 June
  2021, returns a Yahoo redirect, the files area having been deleted in
  December 2019. Knobloch's hex dump is what survives of it.
- PlaySK Piano Roll Reader, <https://github.com/nai-kon/PlaySK-Piano-Roll-Reader>.
  Its `src/cis_image.py` reads the same layout, re-clocks encoder scans and
  stitches twin arrays; its `sample_scans` folder holds CIS files of several
  reproducing-piano formats.
- Sapp, C. S. *CIS file format*, <http://pianoroll.sapp.org/file-types/cis/>.
