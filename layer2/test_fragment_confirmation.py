"""Recover reordered evidence without counting one short match three times."""
import unittest
import numpy as np
import fragment_confirmation as fragments
import tonal_alignment as tonal


class FragmentTests(unittest.TestCase):
    def test_reordered_sections_are_confirmed(self):
        rng=np.random.default_rng(51023)
        ref=np.repeat(np.eye(12,dtype=np.float32)[rng.integers(0,12,60)],2,axis=0)
        chunks=[ref[i*30:(i+1)*30] for i in range(4)]
        query=np.concatenate([chunks[i] for i in [2,0,3,1,0,2,1,3]])
        result=fragments.compare(query,ref,.5,.5,center_time=False)
        self.assertEqual(len(result['fragments']),3)
        self.assertGreater(result['fragmentScore'],.45)
        self.assertGreater(result['fragmentScore'],tonal.compare(query,ref)['tonalScore'])

    def test_one_reference_excerpt_is_not_three_independent_matches(self):
        rng=np.random.default_rng(51024)
        ref=np.eye(12,dtype=np.float32)[rng.integers(0,12,20)]
        query=np.tile(ref,(8,1))
        self.assertEqual(fragments.compare(query,ref,.5,.5,center_time=False)['fragmentScore'],0.)

    def test_silence_has_no_fragment_evidence(self):
        silence=np.zeros((200,12),np.float32)
        self.assertEqual(fragments.compare(silence,silence,.5,.5,center_time=False)['fragmentScore'],0.)


if __name__=='__main__':unittest.main()
