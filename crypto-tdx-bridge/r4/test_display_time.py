from datetime import datetime
import struct
import unittest
from display_time import shift_minute_labels


class DisplayTimeTests(unittest.TestCase):
    def test_midnight_leap_day_year_boundary_and_tail_preserved(self):
        for date in (datetime(2024, 2, 28, 23, 55), datetime(2026, 12, 31, 23, 55)):
            original = struct.pack('<HHfffffII', (date.year - 2004) * 2048 + date.month * 100 + date.day,
                                   date.hour * 60 + date.minute, 1, 2, .5, 1.5, 123.5, 7, 19660816)
            shifted = shift_minute_labels(original, 420)
            self.assertEqual(shifted[4:], original[4:])
            self.assertEqual(shift_minute_labels(shifted, -420), original)
            self.assertEqual(struct.unpack_from('<H', shifted, 2)[0], 415)

    def test_invalid_alignment_and_minute_rejected(self):
        with self.assertRaises(ValueError):
            shift_minute_labels(b'x', 420)
        with self.assertRaises(ValueError):
            shift_minute_labels(struct.pack('<HH', 46001, 1440) + bytes(28), 420)
