import json
from pathlib import Path
import tempfile
import unittest
from tools.review_ai_slides_v4 import build_packet, validate_report, RUBRIC, HARD_FAILS, DESKTOP


ROOT = Path(__file__).resolve().parents[1]


def review_fixture(directory):
    raw, edited, output = (directory / name for name in ('raw', 'edited', 'desk'))
    for path in (raw, edited):
        path.mkdir()
        deck = {'profile': {'lesson_title': 'Bài <script>không thực thi</script>', 'subject': 'QA', 'grade': 'Lớp 6', 'sources': []},
                'manifest': {'slides': [{'id': 's001', 'kind': 'concept', 'title': 'Ví dụ', 'bullets': ['Nguồn tổng hợp.'], 'speaker_notes': 'Ghi chú.'}]}}
        (path / 'case-01-deck.json').write_text(json.dumps(deck, ensure_ascii=False), encoding='utf-8')
        (path / 'case-01-deck.pptx').write_bytes(b'Only a hash fixture, not a usable PowerPoint')
    packet = build_packet(raw, edited, output)
    report = {'schema_version': 1, 'packet_id': packet['packet_id'], 'reviewer': {'name': '', 'qualified_reviewer': False}, 'records': {}}
    for record in packet['records']:
        report['records'][record['id']] = {'asset_hashes': record['assets'], 'scores': {key: None for key in RUBRIC},
            'hard_fails': {key: 'pending' for key in HARD_FAILS}, 'desktop': {'version': '', 'checks': {key: 'pending' for key in DESKTOP}},
            'content_read': False, 'verdict': 'pending', 'notes': ''}
    return output, report


class HumanReviewTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='review-test-', dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(ROOT / 'tmp'))
        self.output, self.report = review_fixture(self.root)
        self.path = self.output / 'human.json'

    def result(self):
        self.path.write_text(json.dumps(self.report), encoding='utf-8')
        return validate_report(self.output / 'manifest.json', self.path)

    def test_blank_and_edited_reviews_never_qualify_raw_model(self):
        result = self.result()
        self.assertFalse(result['model_content_review_complete'])
        self.assertEqual(result['content_accepted_raw'], 0)
        edited = self.report['records']['edited:01']
        edited.update(scores=RUBRIC.copy(), content_read=True, verdict='accept', hard_fails={key: 'clear' for key in HARD_FAILS})
        result = self.result()
        self.assertEqual(result['content_accepted_edited'], 1)
        self.assertEqual(result['content_accepted_raw'], 0)
        self.assertFalse(result['model_content_review_complete'])

    def test_scores_boolean_overflow_hard_fail_and_incomplete_desktop(self):
        record = self.report['records']['raw:01']
        for value in (True, 31, -1, 1.5):
            record['scores']['knowledge'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.result()
        record.update(scores=RUBRIC.copy(), content_read=True, verdict='accept', hard_fails={key: 'clear' for key in HARD_FAILS})
        record['hard_fails']['invented_reference'] = 'fail'
        result = self.result()
        self.assertFalse(result['results'][0]['content_accepted'])
        self.assertTrue(result['results'][0]['hard_fail_reported'])
        self.assertFalse(result['results'][0]['desktop_pass_reported'])

    def test_modified_file_and_wrong_packet_are_rejected(self):
        self.report['packet_id'] = '0' * 64
        with self.assertRaises(ValueError): self.result()
        packet = json.loads((self.output / 'manifest.json').read_text(encoding='utf-8'))
        self.report['packet_id'] = packet['packet_id']
        (self.output / packet['records'][0]['pptx_path']).write_bytes(b'changed after review')
        with self.assertRaises(ValueError): self.result()

    def test_packet_embeds_source_as_data_and_does_not_invent_desktop_evidence(self):
        html = (self.output / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>không thực thi</script>', html)
        self.assertIn('\\u003cscript\\u003e', html)
        result = self.result()
        self.assertEqual(result['desktop_passes_edited'], 0)
        self.assertEqual(result['evidence_type'], 'human_self_report_not_independently_authenticated')


if __name__ == '__main__': unittest.main()
