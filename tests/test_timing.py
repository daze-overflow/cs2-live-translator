import unittest

from backend.timing import AudioClock


class TimingTests(unittest.TestCase):
    def test_capture_gap_reanchors_source_time_without_hiding_network_lag(self):
        clock = AudioClock()
        self.assertFalse(clock.observe(1000, 640, 1020))
        self.assertEqual(clock.started_ms, 980)
        self.assertFalse(clock.observe(1020, 640, 1040))
        self.assertTrue(clock.observe(6020, 640, 6040))
        self.assertEqual(clock.started_ms, 6000)
        self.assertEqual(clock.ingest_age_ms, 20)
        with self.assertRaisesRegex(RuntimeError, "3 秒"):
            clock.observe(6040, 640, 10000)

if __name__ == "__main__":
    unittest.main()
