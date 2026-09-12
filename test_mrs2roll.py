import unittest

import numpy as np

import mrs2roll
from mrs2roll import Barrel, Calibration, PaperBand, Skew, TrackGrid

MM_PER_LINE = 25.4 / 360


def skewed_trains(slope, across_mm, onsets, mm_per_line=MM_PER_LINE):
    """Onset trains for tracks at `across_mm`, tilted by `slope` mm along per mm across."""
    return {j: onsets + slope * x / mm_per_line for j, x in enumerate(across_mm)}


def scattered_onsets(count=80, span=30000, seed=0):
    """Unevenly spaced onsets, so a cross-correlation has one clear peak."""
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(span // 20, size=count, replace=False)).astype(float) * 20


class FindingOnsets(unittest.TestCase):
    def test_takes_the_rising_edge_and_not_the_falling_one(self):
        # numpy's diff over a boolean array is an xor, so a mask compared
        # against 1 without a cast reports both ends of every punch
        profile = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0])
        self.assertEqual(len(mrs2roll.onset_positions(profile, 0.5)), 2)

    def test_places_the_edge_between_the_lines_that_straddle_it(self):
        profile = np.array([0.0, 0.25, 0.75, 1.0])
        # the crossing sits halfway from line 1 to line 2
        self.assertAlmostEqual(mrs2roll.onset_positions(profile, 0.5)[0], 1.5)

    def test_reads_a_punch_that_is_open_at_the_end(self):
        self.assertEqual(len(mrs2roll.onset_positions(np.array([0.0, 0.0, 1.0]), 0.5)), 1)


class MeasuringSkew(unittest.TestCase):
    def setUp(self):
        self.across = np.linspace(-90.0, 90.0, 12)
        self.onsets = scattered_onsets()

    def recover(self, slope):
        trains = skewed_trains(slope, self.across, self.onsets)
        return mrs2roll.measure_skew(trains, self.across, MM_PER_LINE)

    def test_recovers_a_tilt_it_was_given(self):
        measured = self.recover(-0.0027)
        self.assertAlmostEqual(measured.slope, -0.0027, places=4)

    def test_recovers_the_opposite_tilt_with_the_opposite_sign(self):
        self.assertAlmostEqual(self.recover(+0.0027).slope, +0.0027, places=4)

    def test_reads_a_square_scan_as_unskewed(self):
        self.assertAlmostEqual(self.recover(0.0).slope, 0.0, places=5)

    def test_scales_the_tilt_to_the_width_of_the_paper(self):
        self.assertAlmostEqual(self.recover(-0.0027).across(285.4), -0.7706, places=3)

    def test_leaves_a_small_residual_when_the_tracks_lie_on_a_line(self):
        self.assertLess(self.recover(-0.0027).residual, 0.01)

    def test_declines_to_measure_too_few_tracks(self):
        across = self.across[:4]
        trains = skewed_trains(-0.0027, across, self.onsets)
        self.assertIsNone(mrs2roll.measure_skew(trains, across, MM_PER_LINE))

    def test_declines_to_measure_tracks_with_too_few_punches(self):
        sparse = self.onsets[: mrs2roll.MIN_TRACK_ONSETS - 1]
        trains = skewed_trains(-0.0027, self.across, sparse)
        self.assertIsNone(mrs2roll.measure_skew(trains, self.across, MM_PER_LINE))


class ChoosingTracksToFit(unittest.TestCase):
    """What `fit_skew` keeps.  A track whose correlation locked onto the wrong
    punch shows up as an offset nothing like its neighbours', and the outermost
    tracks are the sparsest, so both are left out of the line."""

    def setUp(self):
        self.across = np.linspace(-90.0, 90.0, 12)
        self.along = -0.0027 * self.across
        self.mass = np.full(12, 500.0)

    def fit(self, across, along):
        return mrs2roll.fit_skew(across, along, self.mass, pairs=66)

    def test_fits_every_track_when_they_all_sit_on_the_line(self):
        measured = self.fit(self.across, self.along)
        self.assertEqual(measured.tracks_used, 12)
        self.assertAlmostEqual(measured.slope, -0.0027, places=6)

    def test_drops_a_track_whose_offset_is_nothing_like_the_rest(self):
        along = self.along.copy()
        along[3] += 5.0  # mm, far past any credible skew
        measured = self.fit(self.across, along)
        self.assertEqual(measured.tracks_used, 11)
        self.assertAlmostEqual(measured.slope, -0.0027, places=6)

    def test_drops_a_track_outside_the_inner_compass(self):
        across = self.across.copy()
        across[0] = -140.0
        self.assertEqual(self.fit(across, self.along).tracks_used, 11)

    def test_declines_when_too_few_tracks_survive(self):
        across = np.linspace(-140.0, -120.0, 12)
        self.assertIsNone(self.fit(across, -0.0027 * across))


class ReadingTrackWindows(unittest.TestCase):
    def test_keeps_the_window_inside_the_sensor(self):
        lo, hi = mrs2roll.track_windows(np.array([0.0, 99.0]), 15.5, 100)
        self.assertEqual((lo[0], hi[1]), (0, 100))

    def test_averages_each_track_window_across_its_columns(self):
        block = np.tile(np.arange(10.0), (3, 1))
        means = mrs2roll.window_means(block, np.array([0, 5]), np.array([2, 7]))
        self.assertEqual(means.shape, (3, 2))
        self.assertTrue(np.allclose(means[0], [0.5, 5.5]))


class InvertingTheBarrel(unittest.TestCase):
    def setUp(self):
        self.barrel = Barrel(centre=980.6, k3=-2.1732e-08, pitch=15.488, rms=0.45,
                             linear_rms=1.17)

    def test_source_of_undoes_image_of(self):
        columns = np.linspace(200.0, 1800.0, 17)
        back = self.barrel.source_of(self.barrel.image_of(columns))
        self.assertTrue(np.allclose(back, columns, atol=1e-6))


def calibration(barrel):
    return Calibration(
        band=PaperBand(223, 1792, 3),
        grid=TrackGrid(pitch=15.466, phase=0.0, coherence=0.879, tracks_seen=33,
                       pitch_error=0.009, residual=0.49),
        straighten=barrel is not None,
        barrel=barrel,
        skew=None,
        along_px_per_mm=5.0,
        track_pitch_mm=3.18687,
    )


class ReportingTheAcrossScale(unittest.TestCase):
    """The pitch quoted and the pitch resampled from have to be the same one."""

    def setUp(self):
        self.barrel = Barrel(centre=980.6, k3=-2.1732e-08, pitch=15.488, rms=0.45,
                             linear_rms=1.17)

    def test_resamples_from_the_cubic_pitch_when_straightening(self):
        self.assertEqual(calibration(self.barrel).source_pitch, 15.488)

    def test_resamples_from_the_comb_pitch_when_not_straightening(self):
        self.assertEqual(calibration(None).source_pitch, 15.466)

    def test_does_not_put_the_combs_error_bar_on_the_cubics_dpi(self):
        said = mrs2roll.across_uncertainty(calibration(self.barrel))
        self.assertNotIn("+/- 0.1", said)  # the comb's 0.009 px scaled to dpi
        self.assertIn("no error bar of its own", said)

    def test_states_how_far_the_two_estimators_stand_apart(self):
        self.assertIn("+0.14%", mrs2roll.across_uncertainty(calibration(self.barrel)))

    def test_keeps_the_combs_error_bar_when_the_comb_is_what_was_used(self):
        said = mrs2roll.across_uncertainty(calibration(None))
        self.assertIn("from the pitch alone", said)
        self.assertNotIn("no error bar", said)


class ReportingSkew(unittest.TestCase):
    def test_says_so_when_it_could_not_be_measured(self):
        self.assertIn("not measured", mrs2roll.skew_line(None, 285.4, 14.17))

    def test_gives_the_shift_in_mm_and_in_scan_lines(self):
        said = mrs2roll.skew_line(Skew(-0.002686, 0.03, 32, 442), 285.4, 360 / 25.4)
        self.assertIn("-0.77 mm", said)
        self.assertIn("-10.9 scan lines", said)

    def test_says_the_image_is_left_alone(self):
        self.assertIn("not deskewed", mrs2roll.skew_line(Skew(-0.0027, 0.03, 32, 442),
                                                         285.4, 14.17))


if __name__ == "__main__":
    unittest.main()
