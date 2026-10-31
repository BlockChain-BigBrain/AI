"""Reject contaminated or falsely independent fresh-validation inputs."""
import csv,json,unittest,uuid
from pathlib import Path
from validate_fresh_ai import ROOT,REQUIRED,intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'.runtime-tests/intake-unit'/uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.assertTrue(self.folder.resolve().is_relative_to(ROOT/'.runtime-tests'))

    def write_manifest(self,rows):
        path=self.folder/'manifest.csv'
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=REQUIRED);writer.writeheader();writer.writerows(rows)
        return path

    def row(self,audio,work='work-a'):
        record={'generator':'unit-test-service','model':'unit-test-model','generation_id':'unit-test-id','human_performance':False}
        path=self.folder/'record.json';path.write_text(json.dumps(record),encoding='utf-8')
        return {'audio_path':str(audio),'role':'normal','work_id':work,'generator':record['generator'],'model':record['model'],
            'generation_id':record['generation_id'],'generation_record_path':str(path),'expected_track_id':''}

    def test_empty_template_cannot_claim_validation(self):
        with self.assertRaisesRegex(ValueError,'empty'):intake(self.write_manifest([]))

    def test_previously_evaluated_original_is_rejected(self):
        source=next((ROOT/'original_music').glob('*.mp3'))
        with self.assertRaisesRegex(ValueError,'Previously evaluated'):intake(self.write_manifest([self.row(source)]))

    def test_different_files_of_same_generation_are_not_independent_normals(self):
        a,b=self.folder/'a.wav',self.folder/'b.wav'
        a.write_bytes(uuid.uuid4().bytes);b.write_bytes(uuid.uuid4().bytes)
        with self.assertRaisesRegex(ValueError,'Repeated generation'):
            intake(self.write_manifest([self.row(a,'a'),self.row(b,'b')]))


if __name__=='__main__':unittest.main()
