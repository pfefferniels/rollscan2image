import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

import cis2image


def body(lines):
    """Per line one run sequence per channel, each followed by a status word."""
    words = [word for sequences, flag in lines for word in sum(sequences, []) + [flag]]
    return np.array(words, dtype="<u2").tobytes()


def cis_bytes(lines, width=10, status=0x0044, tempo=80):
    """A CIS file in memory, in the 2003 layout."""
    header = cis2image.HEADER.pack(b"test roll".ljust(32), status, 0, 300, width, 0, tempo, 300, len(lines))
    return header + body(lines)


def early_cis_bytes(lines, width=10, tempo=80, lpi=182):
    """A CIS file in the 2002 layout: a 40-byte description and one channel."""
    header = cis2image.EARLY_HEADER.pack(b"early roll".ljust(40), width, 0, tempo, lpi, len(lines))
    return header + body(lines)


LINES = [
    (([3, 4, 3], [0, 10]), 0),
    (([10], [2, 1, 7]), 0),
    (([0, 2, 8], [0, 10]), 1 << 15),
]

EARLY_LINES = [(([3, 4, 3],), 0), (([10],), 0)]

# The one attested early header: Knobloch's hex dump of 40057AO.CIS, the sample
# scan in Stibbons' SCANNER.ZIP, with the two run sequences that follow it.
KNOBLOCH_40057AO = bytes.fromhex(
    "52 20 53 74 69 62 62 6F 6E 73 20 28 63 29 20 32"
    "30 30 30 20 30 32 2D 30 37 20 20 20 20 20 20 20"
    "20 20 20 20 20 20 20 20 80 09 00 00 37 00 B6 00"
    "2E 79 00 00 01 00 28 09 57 00 0C 00 03 00 06 00"
    "03 00 01 00 73 09 08 00"
)


class Decoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _read(self, data):
        path = Path(self.tmp.name) / "roll.CIS"
        path.write_bytes(data)
        return cis2image.Scan.read(path)

    def _scan(self, lines=LINES, **header):
        return self._read(cis_bytes(lines, **header))

    def test_reads_the_header_flags(self):
        header = self._scan().header
        self.assertIs(header.spec, cis2image.Spec.CURRENT)
        self.assertEqual(header.title, "test roll")
        self.assertEqual(header.scanner, cis2image.Scanner.STEPPER)
        self.assertTrue(header.bicolour)
        self.assertFalse(header.twin_array)
        self.assertEqual(header.channels, ("holes", "ink"))
        self.assertEqual((header.pixels, header.tempo, header.lines), (10, 80, 3))

    def test_reserved_scanner_codes_read_as_unknown(self):
        self.assertEqual(self._scan(status=0x0049).header.scanner, cis2image.Scanner.UNKNOWN)

    def test_reads_the_2002_layout(self):
        header = self._read(early_cis_bytes(EARLY_LINES)).header
        self.assertIs(header.spec, cis2image.Spec.EARLY)
        self.assertEqual(header.title, "early roll")
        self.assertEqual(header.scanner, cis2image.Scanner.STEPPER)
        self.assertEqual(header.channels, ("holes",))
        self.assertEqual((header.pixels, header.lpi, header.lines), (10, 182, 2))

    def test_early_resolution_comes_from_the_scan_width(self):
        self.assertEqual(cis2image.early_dpi(2432), 203)  # fax sensor, 8 dots/mm
        self.assertEqual(cis2image.early_dpi(3648), 300)  # the DynaImage A3
        self.assertEqual(cis2image.early_dpi(1216), 100)  # an unattested width

    def test_renders_an_early_scan(self):
        holes = self._read(early_cis_bytes(EARLY_LINES)).rows("holes", 0, 2)
        np.testing.assert_array_equal(holes[0], [0, 0, 0, 1, 1, 1, 1, 0, 0, 0])
        np.testing.assert_array_equal(holes[1], np.zeros(10))

    def test_a_text_free_header_is_never_read_as_early(self):
        printable = cis2image.HEADER.pack(b"t".ljust(32), 0x2424, 0x2020, 300, 10, 0, 80, 300, 1)
        self.assertFalse(cis2image.is_early_layout(printable))
        self.assertTrue(cis2image.is_early_layout(early_cis_bytes(EARLY_LINES)))

    def test_reads_knoblochs_sample_header(self):
        header = cis2image.Header.parse(KNOBLOCH_40057AO)
        self.assertIs(header.spec, cis2image.Spec.EARLY)
        self.assertEqual(header.title, "R Stibbons (c) 2000 02-07")
        self.assertEqual((header.pixels, header.tempo, header.lpi), (2432, 55, 182))
        self.assertEqual(header.lines, 31022)

    def test_knoblochs_sample_runs_fill_their_lines(self):
        words = np.frombuffer(KNOBLOCH_40057AO, dtype="<u2", offset=cis2image.HEADER.size)
        self.assertEqual(int(words[:3].sum()), 2432)
        self.assertEqual(int(words[4:9].sum()), 2432)

    def test_a_description_cut_short_still_reads_as_early(self):
        header = bytearray(early_cis_bytes(EARLY_LINES))
        header[9:34] = b"\0" * 25
        self.assertTrue(cis2image.is_early_layout(bytes(header)))

    def test_renders_runs_dark_first(self):
        scan = self._scan()
        holes = scan.rows("holes", 0, 3)
        np.testing.assert_array_equal(holes[0], [0, 0, 0, 1, 1, 1, 1, 0, 0, 0])
        np.testing.assert_array_equal(holes[1], np.zeros(10))
        np.testing.assert_array_equal(holes[2], [1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
        ink = scan.rows("ink", 0, 3)
        np.testing.assert_array_equal(ink[1], [0, 0, 1, 0, 0, 0, 0, 0, 0, 0])
        self.assertTrue(ink[[0, 2]].all())

    def test_status_words_follow_each_line(self):
        scan = self._scan()
        np.testing.assert_array_equal(scan.status, [0, 0, 1 << 15])
        np.testing.assert_array_equal(scan.overrun_lines, [2])

    def test_rejects_runs_that_do_not_fill_the_line(self):
        with self.assertRaises(cis2image.FormatError):
            self._scan([(([3, 4], [0, 10]), 0)])

    def test_composite_marks_holes_white_and_ink_black(self):
        scan = self._scan()
        grey = cis2image.render(scan, "composite", 0, 3)
        np.testing.assert_array_equal(grey[0, 3:7], 255)
        np.testing.assert_array_equal(grey[0, :3], cis2image.PAPER)
        np.testing.assert_array_equal(grey[1, 2], cis2image.PAPER)
        np.testing.assert_array_equal(grey[1, 3:], 0)

    def test_shrink_averages_blocks(self):
        block = np.zeros((4, 4), dtype=bool)
        block[:2, :2] = True
        np.testing.assert_array_equal(cis2image.shrink(block, 2), [[255, 0], [0, 0]])
        self.assertIs(cis2image.shrink(block, 1), block)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cis = self.tmp / "roll.CIS"
        self.cis.write_bytes(cis_bytes(LINES))

    def _run(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cis2image.main([str(self.cis), *arguments])

    def test_writes_a_rotated_excerpt_as_png(self):
        from PIL import Image

        out = self.tmp / "roll.png"
        self.assertEqual(self._run(str(out), "--lines", "0:2", "--rotate"), 0)
        with Image.open(out) as image:
            pixels = np.asarray(image)
        np.testing.assert_array_equal(pixels[1], [0, 0, 0, 1, 1, 1, 1, 0, 0, 0][::-1])
        np.testing.assert_array_equal(pixels[0], np.zeros(10))

    def test_refuses_a_channel_the_scan_lacks(self):
        self.cis.write_bytes(cis_bytes([(([3, 4, 3],), 0)], status=0x0004))
        self.assertEqual(self._run(str(self.tmp / "x.tif"), "--channel", "ink"), 1)


if __name__ == "__main__":
    unittest.main()
