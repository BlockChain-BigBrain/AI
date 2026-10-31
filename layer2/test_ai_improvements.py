"""Calibration must preserve source retrieval and never fit held-out scores."""
import unittest
import compare_ai_improvements as experiment
import selective_retrieval as selective


class CalibrationTests(unittest.TestCase):
    def rows(self):
        rows=[{'file':f'n{i}', 'dataset':'safe_music','split':'tune','score':i/100} for i in range(1,19)]
        rows += [{'file':f'p{i}','dataset':'positive','split':'tune','score':.8+i/1000,
                  'expected_score':.8+i/1000,'source_rank_after_tonal':1} for i in range(40)]
        return rows

    def test_margin_preserves_recall_and_reduces_false_warnings(self):
        rows=self.rows();policy=experiment.calibrate(rows);metrics=experiment.metrics(rows,policy)
        self.assertGreater(policy['warn_threshold'],.18)
        self.assertLess(policy['warn_threshold'],.8)
        self.assertGreater(policy['hold_threshold'],policy['warn_threshold'])
        self.assertEqual(metrics['normal_warn_count'],0)
        self.assertEqual(metrics['correct_source_warn_top3_count'],40)

    def test_test_and_premusic_scores_cannot_change_thresholds(self):
        rows=self.rows();before=experiment.calibrate(rows)
        for split in ('test','external_diagnostic'):
            rows += [{'file':'unexpected','dataset':'safe_music','split':split,'score':1.0}]
        self.assertEqual(before,experiment.calibrate(rows))

    def test_wrong_source_or_hidden_source_is_not_recall(self):
        row={'file':'p','dataset':'positive','score':.99,'expected_score':None,'source_rank_after_tonal':None}
        policy={'warn_threshold':.5,'hold_threshold':.8}
        self.assertEqual(experiment.metrics([row],policy)['correct_source_warn_top3_count'],0)
        row.update(expected_score=.9,source_rank_after_tonal=4)
        self.assertEqual(experiment.metrics([row],policy)['correct_source_warn_top3_count'],0)

    def test_expansion_preserves_original_evidence_and_rejects_weak_extra_match(self):
        self.assertEqual(selective.apply({'tonalScore':.368},5)['tonalScore'],.368)
        self.assertLess(selective.apply({'tonalScore':.368},6)['tonalScore'],.347)
        self.assertGreater(selective.apply({'tonalScore':.687},6)['tonalScore'],.347)


if __name__=='__main__':unittest.main()
