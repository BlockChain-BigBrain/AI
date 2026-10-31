"""Supplemental evidence respects its cutoff and cannot create HOLD."""
import unittest
from unittest.mock import patch
import numpy as np
import secondary_precision as secondary


class SecondaryTests(unittest.TestCase):
    def calculate(self,whole,clap,fragments=None):
        segment={'tonalScore':whole,'queryStartSec':0.,'queryEndSec':10.,'refStartSec':0.,'refEndSec':10.}
        with patch('secondary_precision.tonal.compare',return_value=segment),patch('secondary_precision.fragments.compare',return_value={'fragments':fragments or []}):
            return secondary.compare(np.zeros((1,12)),np.zeros((1,12)),.5,.5,clap,.3474893216,.4579778546)

    def test_cutoff_maps_to_primary_warn_boundary(self):
        r=self.calculate(np.sqrt(.4579778546),1.)
        self.assertAlmostEqual(r['score'],.3474893216)

    def test_secondary_route_cannot_create_hold(self):
        r=self.calculate(1.,1.)
        self.assertLess(r['score'],.8337449399)
        self.assertLessEqual(r['rawScore'],.8)

    def test_no_semantic_agreement_has_no_rescue_score(self):
        self.assertEqual(self.calculate(1.,-.5)['score'],0.)

    def test_one_matching_excerpt_is_not_a_three_fragment_route(self):
        one={'tonalScore':1.,'queryStartSec':0.,'queryEndSec':10.,'refStartSec':0.,'refEndSec':10.}
        self.assertEqual(self.calculate(0.,1.,[one])['fragmentMean'],0.)


if __name__=='__main__':unittest.main()
