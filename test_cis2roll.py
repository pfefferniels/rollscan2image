import tempfile
import unittest
from pathlib import Path

import numpy as np

import cis2roll
from cis2image import Scan
from mrs2roll import PaperBand
from test_cis2image import early_cis_bytes


def scan_of(profile, lines=cis2roll.SAMPLE_BLOCKS * cis2roll.SAMPLE_LINES):
    """A one-channel scan whose every line reads `profile`."""
    runs = np.flatnonzero(np.diff(np.r_[False, profile, False]))
    sequence = np.diff(np.r_[0, runs, len(profile)]).tolist()
    if profile[0]:
        sequence = [0] + sequence
    path = Path(tempfile.mkdtemp()) / "probe.CIS"
    path.write_bytes(early_cis_bytes([((sequence,), 0)] * lines, width=len(profile)))
    return Scan.read(path)


def source_of(profile):
    return cis2roll.Source(scan=scan_of(profile), despeckle=False,
                           flip_lines=False, flip_columns=False)


# The sensor is wider than the roll: a dark strip of bed, a lit gap, the paper,
# a wider lit gap, and bed again.  This is the shape of Spencer Chase's scan of
# Welte roll 225, at a twentieth of its width.
BED = np.r_[np.zeros(6), np.ones(2), np.zeros(114), np.ones(6), np.zeros(2)].astype(bool)


class FindingThePaper(unittest.TestCase):
    def test_takes_the_widest_dark_run_and_not_the_first(self):
        paper = cis2roll.find_paper(source_of(BED))
        self.assertEqual((paper.band.left, paper.band.right), (8, 121))

    def test_clears_only_as_far_as_the_bed(self):
        paper = cis2roll.find_paper(source_of(BED))
        self.assertEqual((paper.clear_left, paper.clear_right), (6, 127))

    def test_a_sensor_no_wider_than_the_roll_clears_to_its_ends(self):
        paper = cis2roll.find_paper(source_of(np.zeros(40, dtype=bool)))
        self.assertEqual((paper.clear_left, paper.clear_right), (0, 39))


class KeepingAMargin(unittest.TestCase):
    def setUp(self):
        self.paper = cis2roll.Paper(band=PaperBand(8, 121, 0), clear_left=6, clear_right=127)

    def test_keeps_the_whole_margin_where_the_bed_leaves_room(self):
        self.assertEqual(self.paper.keep(2), (6, 124))

    def test_stops_at_the_bed_rather_than_reaching_into_it(self):
        # asked for 25 columns, which would take in the bed on both sides
        self.assertEqual(self.paper.keep(25), (6, 128))

    def test_never_gives_back_less_than_the_paper(self):
        self.assertEqual(self.paper.keep(0), (8, 122))


if __name__ == "__main__":
    unittest.main()
