import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

import cis2image


def cis_bytes(lines, width=10, status=0x0044, tempo=80):
    """A CIS file in memory: header, then per line one run sequence per channel and a status word."""
    header = cis2image.HEADER.pack(b"test roll".ljust(32), status, 0, 300, width, 0, tempo, 300, len(lines))
    words = [word for sequences, flag in lines for word in sum(sequences, []) + [flag]]
    return header + np.array(words, dtype="<u2").tobytes()


LINES = [
    (([3, 4, 3], [0, 10]), 0),
    (([10], [2, 1, 7]), 0),
    (([0, 2, 8], [0, 10]), 1 << 15),
]


class Decoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _scan(self, lines=LINES, **header):
        path = Path(self.tmp.name) / "roll.CIS"
        path.write_bytes(cis_bytes(lines, **header))
        return cis2image.Scan.read(path)

    def test_reads_the_header_flags(self):
        header = self._scan().header
        self.assertEqual(header.title, "test roll")
        self.assertEqual(header.scanner, cis2image.Scanner.STEPPER)
        self.assertTrue(header.bicolour)
        self.assertFalse(header.twin_array)
        self.assertEqual(header.channels, ("holes", "ink"))
        self.assertEqual((header.pixels, header.tempo, header.lines), (10, 80, 3))

    def test_reserved_scanner_codes_read_as_unknown(self):
        self.assertEqual(self._scan(status=0x0049).header.scanner, cis2image.Scanner.UNKNOWN)

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
