"""Meaningful invariance and independent-sample acceptance checks."""
import unittest
import numpy as np
import dual_tonal_retrieval as dual
from validate_fresh_ai import upper95


class NextStageTests(unittest.TestCase):
    def test_descriptor_ignores_global_key_but_keeps_relative_motion(self):
        rng=np.random.default_rng(20261023)
        rows=np.repeat(np.eye(12,dtype=np.float32)[rng.integers(0,12,48)],2,axis=0)
        a=dual.descriptors(rows)
        np.testing.assert_allclose(a,dual.descriptors(np.roll(rows,5,axis=1)),atol=1e-6)
        self.assertGreater(np.linalg.norm(a-dual.descriptors(rows[::-1])),1.)

    def test_silence_does_not_create_nan_or_positive_signature(self):
        rows=dual.descriptors(np.zeros((3,12),np.float32))
        self.assertTrue(np.isfinite(rows).all());self.assertEqual(float(np.linalg.norm(rows)),0.)

    def test_claimed_zero_event_sample_requirements(self):
        self.assertGreater(upper95(0,28),.10)
        self.assertLessEqual(upper95(0,29),.10)
        self.assertGreater(upper95(0,148),.02)
        self.assertLessEqual(upper95(0,149),.02)
        self.assertGreater(upper95(1,149),.02)
        self.assertIsNone(upper95(0,0))


if __name__=='__main__':unittest.main()
