# rollscan2image

Readers and converters for the files piano-roll scanners write, turning them
into TIFF or PNG.

`mrs2image.py` reads the raster files of an MRS scanner, the monochrome `.mrs`
and the colour `.mrsc`, and can reproduce the PNG the scanner itself delivers.
`mrs2roll.py` prepares such a scan for Craig Sapp's
[roll-image-parser](https://github.com/pianoroll/roll-image-parser); see
[Feeding roll-image-parser](#feeding-roll-image-parser) below. `cis2image.py`
reads a different scanner's files, the run-length coded `.CIS` of the
rollscanners group; see [CIS files](#cis-files). Most of what follows concerns
the MRS format.

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
mirrored scan and bit 13 a reversed one.

Each line then holds one run sequence per channel, in the order holes, twin
array, ink: 16-bit run lengths alternating between dark and light, starting
dark, that add up to the pixels per line. A line that begins light starts
with a zero-length dark run. After the last channel comes one status word,
whose bit 5 carries the hardware clock, bit 7 the encoder state and bit 15 a
data overrun. The reader locates every sequence by walking the cumulative
sum of the whole file, which has to be sequential because each status word
shifts the sum for every line after it, and then renders rows by toggling at
each run boundary.

Lines are stored in scanning order, so line 0 is the leader and the roll runs
down the image, which is also how the Stanford scans are oriented. On the one
file examined, a bi-colour stepper scan of an Auto Pneumatic Action Company
test roll at 300 dpi and 300 lines per inch, the printing reads upside down
and not mirrored, so the bass side is at the left and `--rotate` gives the
view on the piano. Encoder-clocked scans are written line for line; their
lines are not evenly spaced along the roll, and re-clocking them, as PlaySK
does, is not attempted here. The two arrays of a twin scanner are written as
separate channels rather than stitched.

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
- Stibbons, R. *Contact Image Sensor Roll Scanner File Formats*, 22 February
  2003, <http://semitone440.co.uk/rolls/utils/cisheader/cis-format.htm>. The
  header and status-word layout followed by `cis2image.py`.
- Knobloch, P. *CIS File Format (Preliminary)*, 5 May 2002, read from
  Stibbons' Q-Basic scanner software. Describes the single-channel version
  with a 40-byte title; archived copy at
  <https://web.archive.org/web/2012/http://www.trachtman.org/rollscans/CIS_File_Format.doc>.
- PlaySK Piano Roll Reader, <https://github.com/nai-kon/PlaySK-Piano-Roll-Reader>.
  Its `src/cis_image.py` reads the same layout, re-clocks encoder scans and
  stitches twin arrays; its `sample_scans` folder holds CIS files of several
  reproducing-piano formats.
- Sapp, C. S. *CIS file format*, <http://pianoroll.sapp.org/file-types/cis/>.
