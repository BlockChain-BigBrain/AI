"""Alignment must preserve time offsets and reject silence/unrelated energy."""
import unittest
import numpy as np
import spectral_sequence as spectral


class SpectralTests(unittest.TestCase):
    def test_transposition_and_offset_are_recovered(self):
        rng=np.random.default_rng(42)
        reference=rng.normal(size=(150,84)).astype(np.float32)
        query=np.zeros((60,84),np.float32)
        query[:,:-2]=reference[40:100,2:]
        evidence=spectral.compare(query,reference)
        self.assertGreater(evidence['spectralScore'],.95)
        self.assertEqual(evidence['pitchShift'],2)
        self.assertAlmostEqual(evidence['refStartSec'],40*spectral.STEP)
        self.assertAlmostEqual(evidence['refEndSec'],100*spectral.STEP)

    def test_silence_and_unrelated_sequences_do_not_match(self):
        rng=np.random.default_rng(17)
        query=rng.normal(size=(60,84)).astype(np.float32)
        reference=rng.normal(size=(150,84)).astype(np.float32)
        self.assertLess(spectral.compare(query,reference)['spectralScore'],.1)
        self.assertEqual(spectral.compare(np.zeros_like(query),reference)['spectralScore'],0.)


if __name__=='__main__':unittest.main()
