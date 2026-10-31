"""A supplemental prototype cannot silently introduce HOLD or reorder cuts."""
import unittest
import numpy as np
import spectral_fusion as fusion


class FusionTests(unittest.TestCase):
    def test_primary_remapping_is_monotone_and_preserves_hold_boundary(self):
        values=[fusion.remap_primary(s,.59,.35,.83) for s in np.linspace(0,1,101)]
        self.assertTrue(all(a<=b for a,b in zip(values,values[1:])))
        self.assertAlmostEqual(fusion.remap_primary(.59,.59,.35,.83),.35)
        self.assertEqual(fusion.remap_primary(.83,.59,.35,.83),.83)

    def test_spectral_route_alone_cannot_create_hold(self):
        result=fusion.combine([], [{'trackId':'source','score':1.}],.59,.3,.35,.83)
        self.assertGreaterEqual(result[0]['score'],.35)
        self.assertLess(result[0]['score'],.83)

    def test_invalid_thresholds_fail_explicitly(self):
        with self.assertRaises(ValueError):fusion.combine([],[],.9,.3,.35,.83)


if __name__=='__main__':unittest.main()
