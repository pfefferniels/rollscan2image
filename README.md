# rollscan2image

Readers and converters for the files piano-roll scanners write: they turn a
scan into TIFF or PNG, and prepare it for Craig Sapp's
[roll-image-parser](https://github.com/pianoroll/roll-image-parser).

Two scanner families are covered. The MRS scanner of the Berner Fachhochschule
writes two rasters per session, the monochrome `.mrs` and the colour `.mrsc`.
The contact image sensor scanners of the rollscanners group write run-length
coded `.CIS`.

| tool | reads | writes |
| --- | --- | --- |
| `mrs2image.py` | `.mrs`, `.mrsc` | TIFF or PNG, up to and including the scanner's own PNG pipeline |
| `cis2image.py` | `.CIS` | TIFF or PNG, one channel or a composite |
| `mrs2roll.py` | `.mrs`, `.mrsc` | a 300 dpi RGB TIFF for `tiff2holes` |
| `cis2roll.py` | `.CIS` | a 300 dpi RGB TIFF for `tiff2holes` |

MRS and MRSC are specified in [docs/mrs-format.pdf](docs/mrs-format.pdf),
built from [docs/mrs-format.tex](docs/mrs-format.tex). What could be worked out
about CIS is in [docs/cis-format.md](docs/cis-format.md). It rests on a small
number of scans, so its figures may not hold for other rolls or scanner versions.

## Requirements

Python 3.10 or later, `numpy`, `tifffile` for TIFF output, `Pillow` for PNG.
The tests run with `python3 -m pytest`.

## Converting a scan to an image

### mrs2image.py

```
mrs2image.py [options] INPUT.mrs|INPUT.mrsc [OUTPUT.tif|OUTPUT.png]
```

```sh
# describe a file without converting it
python3 mrs2image.py scan.mrsc --info

# the scanner's own picture, as TIFF
python3 mrs2image.py scan.mrsc roll.tif --like-png

# raw pixels, no processing, a 500-line excerpt
python3 mrs2image.py scan.mrsc probe.png --lines 20000:20500

# the monochrome scan, expanded to RGB
python3 mrs2image.py scan.mrs mono.tif --rgb
```

| Option | Effect |
| --- | --- |
| `--info` | print header, geometry, resolution and trailer metadata, then stop |
| `--lines A:B` | convert only these scan lines |
| `--like-png` | run all three steps of the scanner's own pipeline |
| `--register` | colour registration only |
| `--flat-field` | flat-field correction only |
| `--mirror` | mirror across the roll only |
| `--channel-lag N` | override the sensor's colour-row spacing |
| `--rgb` | expand a monochrome scan to three channels |
| `--horizontal` | roll runs left to right, as in the delivered PNG |
| `--dpi ACROSS,ALONG` | override the resolution written into the TIFF tags |

With no processing options the output is the raw raster, which is dark and
heavily vignetted but untouched. The three steps `--like-png` bundles are
specified in section 6 of [docs/mrs-format.pdf](docs/mrs-format.pdf).

Two siblings of the input are read when they are present, the session's
settings CSV and, for a `.mrsc`, a sibling `.mrs` carrying the roll-type block.
Neither is required, and `--info` reports what was found.

The TIFF written here is single-strip, contiguous, uncompressed, photometric 2,
with inch resolution units, which is what roll-image-parser's `TiffFile` reader
accepts. Its `tiff2holes` wants the roll running down the image with columns
across it, which is the default orientation; `--horizontal` gives the other one.
That reader rejects photometric 1, so a monochrome scan needs `--rgb` before it
will be read.

### cis2image.py

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

Lines are stored in scanning order, so line 0 is the leader and the roll runs
down the image. A file written under the earlier header layout states neither
its scanner type nor its across-roll resolution; both are then inferred, and
`--info` marks them as assumptions. See
[docs/cis-format.md](docs/cis-format.md).

## Preparing a scan for roll-image-parser

`tiff2holes` was written for the Stanford scans and is calibrated for them
throughout, so the way in is to hand it an image in its own units rather than
to retune its thresholds. It wants an uncompressed 24-bit RGB TIFF at about
300 dpi, at least 4096 columns wide, the roll running down the image with bass
at column 0, and holes brighter than the paper.

Both tools resample onto a square-pixel 300 dpi grid and centre the paper in a
4096-column frame. The two axes need different scale factors, since neither
scanner has square pixels. The roll type belongs to `tiff2holes` rather than to
these tools: `-r` for a red Welte T-100, `-g` for a green T-98, `-l` for a
Licensee.

### mrs2roll.py

```sh
python3 mrs2roll.py scan.mrs --dry-run        # show the calibration
python3 mrs2roll.py scan.mrs roll300.tif      # ~1.2 GB for a full roll
tiff2holes -r roll300.tif > analysis.txt
```

| Option | Effect |
| --- | --- |
| `--dry-run` | calibrate and stop |
| `--dpi N`, `--width N` | target grid; 300 dpi and 4096 columns by default |
| `--track-pitch MM` | override the pitch the trailer's roll type implies |
| `--paper-max N`, `--hole-min N` | brightness below which a sample is paper, above which it is a hole |
| `--no-straighten` | leave the camera's across-roll distortion in place |

Neither scale can be looked up. **Across**, the ruler is the roll's own tracker
grid, recovered by a comb fit over the tracks the roll plays and reported with a
standard error. A roll only pins down the grid where it plays, so the pitch is
measured over the whole paper and then remeasured over the longest unbroken run
of played tracks, since perforations outside that compass sit off a straight
grid and drag the comb low. **Along**, the transport's design step of 0.2 mm per
line = 127 dpi, which Debrunner states outright and the colour scan's
`MRSC_Length` confirms to 0.04 %.

The pitch is measured in pixels. Turning it into dpi multiplies by the nominal
track pitch from the roll-type table, which a given roll need not keep to, so
read the printed dpi as good to about a percent rather than to its last digit.

The across axis is also straightened. The camera's tracker columns do not lie on
a straight line: fitting the roll's own column centres against their integer
track indices, a straight grid leaves a systematic residual that an odd cubic
about the middle of the sensor largely removes, displacing the tracks by more
than half a pitch at either paper edge. That is enough to matter, since
roll-image-parser fits one straight grid to the whole width and will read an
expression track as its neighbour. `measure_barrel` fits the cubic from the
roll's own columns on every run rather than assuming a constant for the machine.
A roll is its own and only ruler here, so the fit is skipped, with a line in the
report saying so, unless the roll punches within a quarter of the paper width of
both edges; one that keeps to the middle cannot measure the ends, and a cubic
extrapolated from the middle would do harm.

A cubic is the first term of a radial model and not the whole of it, and
whether the coefficient is the same for every scan from this machine is
untested.

### cis2roll.py

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

Here neither scale has to be measured. The header records the sensor's dots per
inch across the roll and the transport's lines per inch along it, which need
not agree, so each axis is simply rescaled. The tracker pitch those
figures imply is measured back off the holes, by the comb fit `mrs2roll.py`
uses, and printed as a check on both. The scan is written as it was read, so a
roll that comes out with the bass on the right or running up the image needs
`--mirror` or `--rotate`.

Two things need handling beyond the resampling.

**The scanner bed reads as paper.** The sensor is wider than the roll, and what
lies beside the paper is not simply bright: a fixed dark strip, a guide or the
bed itself, sits outside the paper on every line. Taking the first dark column
for the paper edge hands the parser a roll that is too wide, with part of its
margin scored as dust. The paper is therefore taken to be the widest run of
columns dark more often than not, and everything outside it, plus a margin for
the roll's measured wander, is painted as background. That margin has to stop
where the bed begins: a frame reaching into the bed gives `analyzeLeaders` a
margin that never moves on one side and a roll that drifts on the other, and it
stops with "Cannot find leader". `find_paper` reports the dark runs on either
side of the paper along with the band itself, `Paper.keep` clips the margin to
them, and the calibration prints what it kept against what it asked for.

**A one-bit scan speckles.** Isolated lit pixels that an eight-bit scan would
have averaged away survive quantisation, and `tiff2holes` counts them as dust.
Connected components inside the paper separate cleanly into noise and punches,
so a 3×3 opening clears the noise and cannot reach a punch twenty pixels
across.

### Skew

A row of perforations punched at one instant lies square across the paper.
Where the scan line meets that row at a slight angle, every punch in it is
displaced along the roll in proportion to how far across the roll it sits.
Stahnke names this skew, "the tilt of a single row of perforations caused by
angular misalignment of the scan line with respect to the array of punches in
the perforator", and treats it as one of the two systematic errors of a roll
scan.

Both tools measure it and print it, and neither corrects it. Punch onsets are
taken per tracker column, to a fraction of a scan line by interpolating the
threshold crossing, and every pair of columns is cross-correlated to give the
lag between their onset trains; the per-column offsets follow by least squares,
and a straight line through them against position across the roll is the skew.
The line is fitted over the inner ±100 mm of the paper, since the outermost
columns carry the fewest punches and are the likeliest to lock onto a
neighbouring punch. Stahnke separates static skew, the mean over the roll, from
dynamic skew, the variation about it. Only the static mean is reported here.

Leaving it in place is a tested decision rather than a deferral. On the scans
available, shearing the image by the measured slope moved nothing downstream,
and an external check against another copy of the same performance did not see
the predicted tilt either. Two readings survive that, and the data cannot
separate them: the estimator may be reporting something real that the cross-copy
comparison is too noisy to confirm, or part of what it measures may be an
asymmetry shared by the copies, which correcting one copy would introduce rather
than remove. A cutting asymmetry belongs to an edition and a sensor angle
belongs to a machine, so separating them wants other rolls from the same
scanner. The figure is still worth having, as a bound on onset differences read
across the compass of a scan: a caveat to weigh rather than a bias to subtract.

### Changes roll-image-parser needs

All of these are fixed in the copy of the parser used here, not upstream.

- `analyzeTrackerBarSpacing` takes the tallest peak of the centroid histogram's
  spectrum. The histogram is a comb of narrow spikes, so its harmonics are
  about as strong as its fundamental, and a roll that uses only part of its
  tracks can make a harmonic win, halving the measured spacing and throwing
  most of the holes into the bad-hole pile. The spacing is knowable within a
  narrow band before the transform runs, from the measured roll width and the
  roll type's track count, so the fix is to search only that band:

  ```cpp
  double expected = getAverageRollWidth() / (getExpectedTrackerHoleCount() + 2.0);
  ```

  with a ±25 % window around it, wide enough for every roll type the parser
  supports and far too narrow to admit a harmonic.
- The same function indexes the first 4096 columns of the histogram
  unconditionally and aborts with an uncaught `std::out_of_range` on anything
  narrower, which is why both tools pad the frame to 4096 columns.
- The TIFF reader discarded tag 258 and assumed eight bits per sample.
- `setRollTypeGreenWelte` was an unfinished stub that called `exit(1)`, its
  draft carrying two values copied from the red Welte. `setRollTypeLicensee`
  did not exist at all, `-l` being declared and documented as "not yet active";
  it is implemented here from Hagmann and Phillips and the layout Stanford's
  `midi2exp` reads.
- `analyzeLeaders` tested each margin separately for a leader and stopped on
  anything else, so a roll that tracks a few pixels sideways while the transport
  takes up was refused as a partial roll. The test is now on the width between
  the margins, which a lateral shift leaves alone and a leader does not.
- The tear check rejects a hole wider than 1.25 times its length, which assumes
  a scan that responds alike in both directions. A scan whose slicing level
  blooms the holes across the roll does not, so the threshold is now an
  `--aspect` option rather than a constant. It reaches the quality report and
  the marked-up image, not the extracted music.
- `assignMidiKeyNumbersToHoles` checks the tracker grid by finding the track
  whose first perforation comes latest and expecting it to be the rewind. Roll
  types that have no dedicated rewind track, the Welte T-98 among them, cannot
  answer that check, so it is switched off for them and the track numbering
  rests on `m_minTrackerSpacingToPaperEdge` alone.

## References

- roll-image-parser, <https://github.com/pianoroll/roll-image-parser>.
- SUPRA MIDI specification, <https://supra.stanford.edu/midi-spec/>. Documents
  the analysis fields `tiff2holes` emits, and gives Stanford's along-roll
  resolution as 300.25 dpi, measured on *their* scanner in November 2017 to
  ±0.25 dpi. That figure belongs to the Stanford machine; `LENGTH_DPI` in any
  analysis produced here is that literal constant, not a measurement of the
  input.
- Stahnke, W. "Skew, Scatter, and Pitch in Music Roll Scans", in Judith Kemp
  (ed.), *Digitising Piano Rolls*, Deutsches Museum Studies 17 (2026),
  pp. 83–128. Defines skew and scatter as the two systematic errors of a roll
  scan, separates static from dynamic skew, and gives models that find both
  along with the pitch and reconstruct the punch matrix. The measurement here
  follows the definition and takes the estimate no further than the static
  mean; scatter and the punch matrix are not attempted.
- Hagmann, P. *Das Welte-Mignon-Klavier, die Welte-Philharmonie-Orgel und die
  Anfänge der Reproduktion von Musik*, p. 40 f., and Phillips, P. *Piano Rolls
  and Recorded Piano Rolls*, p. 123 and Table 4.3, for the Welte-Mignon
  Licensee: 98 positions at nine to the inch on 11¼ in paper, reading the
  T-100's commands minus its two motor tracks, so the note block and the treble
  valves sit two positions lower.
- The sources for the two scan formats are listed in
  [docs/mrs-format.pdf](docs/mrs-format.pdf) and
  [docs/cis-format.md](docs/cis-format.md).
