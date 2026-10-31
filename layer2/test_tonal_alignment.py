"""Behavioral tests: transposition, tempo variation, unrelated content and silence."""
import unittest
import numpy as np
import tonal_alignment as tonal


class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(20261022)
        notes = rng.integers(0, 12, 40)
        cls.sequence = np.repeat(np.eye(12, dtype=np.float32)[notes], 2, axis=0)
        cls.other = np.repeat(np.eye(12, dtype=np.float32)[rng.integers(0, 12, 40)], 2, axis=0)

    def test_pitch_shift_and_reference_offset_are_recovered(self):
        shifted = np.roll(self.sequence, 3, axis=1)
        reference = np.concatenate([self.other[:20], shifted, self.other[:20]])
        result = tonal.compare(self.sequence, reference)
        self.assertGreater(result['tonalScore'], .95)
        self.assertEqual(result['pitchShift'], 3)
        self.assertAlmostEqual(result['refStartSec'], 10)

    def test_tempo_variation_still_matches_better_than_unrelated(self):
        slowed = np.repeat(self.sequence, 2, axis=0)
        score = tonal.compare(self.sequence, slowed)['tonalScore']
        unrelated = tonal.compare(self.sequence, self.other)['tonalScore']
        self.assertGreater(score, unrelated + .3)

    def test_silence_has_no_evidence(self):
        zero = np.zeros((60, 12), np.float32)
        self.assertEqual(tonal.compare(zero, self.sequence)['tonalScore'], 0)


if __name__ == '__main__':
    unittest.main()
