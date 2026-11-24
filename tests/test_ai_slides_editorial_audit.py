"""AI-authored samples cannot silently become raw-model or human evidence."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.audit_v4_samples import audit
from tools.package_v4_samples import package

ROOT = Path(__file__).resolve().parents[1]


class EditorialAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='editorial-test-', dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve()
        self.assertTrue(self.folder.is_relative_to(ROOT / 'tmp'))
        self.raw = self.folder / 'v4-benchmark'
        self.edited = self.folder / 'v4-reviewed'
        self.raw.mkdir()
        self.edited.mkdir()
        for n in range(1, 21):
            original = {'profile': {'lesson_title': f'Bài {n}', 'sources': ['Dữ kiện gốc']},
                        'manifest': {'slides': [{'title': 'Bài tổng hợp', 'source_proof': None}]}}
            changed = deepcopy(original)
            changed['editorial_review'] = {'reviewer_kind': 'ai', 'teacher_approved': False,
                                          'office_tested_by_agent': False, 'changes': []}
            self.write(self.raw / f'case-{n:02d}-deck.json', original)
            self.write(self.edited / f'case-{n:02d}-deck.json', changed)
            (self.edited / f'case-{n:02d}-deck.pptx').write_bytes(b'Test hash, not an actual PPTX')
        self.write(self.edited / 'render-report.json', {'complete_decks': 20, 'fully_passed': True, 'inference_calls': 0,
            'decks': [{'case': f'case-{n:02d}-deck',
                       'source_sha256': sha256((self.edited / f'case-{n:02d}-deck.json').read_bytes()).hexdigest(),
                       'pptx_sha256': sha256((self.edited / f'case-{n:02d}-deck.pptx').read_bytes()).hexdigest()} for n in range(1, 21)]})
        self.patch = patch('tools.audit_v4_samples.technical_evidence', return_value={'json_schema_valid': True, 'pptx_zip_xml_valid': True})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def change(self, mutate):
        path = self.edited / 'case-01-deck.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        mutate(data)
        self.write(path, data)

    def test_complete_ai_scores_preserve_separation(self):
        result = audit(self.raw, self.edited)
        self.assertEqual(len(result['records']), 20)
        self.assertFalse(result['teacher_approved'])
        self.assertFalse(result['raw_model_qualified'])
        self.assertFalse(result['deployment_approval_changed'])
        self.assertIsNone(result['passing_threshold'])
        self.assertEqual(result['inference_calls'], 0)

    def test_changed_source_or_human_office_claim_is_rejected(self):
        for mutate in (
            lambda d: d['profile'].update(sources=['Đã đổi nguồn']),
            lambda d: d['editorial_review'].update(teacher_approved=True),
            lambda d: d['editorial_review'].update(office_tested_by_agent=True),
        ):
            with self.subTest(mutate=mutate):
                path = self.edited / 'case-01-deck.json'
                saved = path.read_bytes()
                self.change(mutate)
                with self.assertRaises(ValueError): audit(self.raw, self.edited)
                path.write_bytes(saved)

    def test_inherited_proof_and_changed_raw_baseline_are_rejected(self):
        self.change(lambda d: d['manifest']['slides'][0].update(source_proof={'stale': True}))
        with self.assertRaises(ValueError): audit(self.raw, self.edited)
        self.change(lambda d: d['manifest']['slides'][0].update(source_proof=None))
        baseline = self.folder / 'old-manifest.json'
        self.write(baseline, {'records': [{'variant': 'raw', 'case': n,
            'deck_path': f'raw/{n}', 'assets': {f'raw/{n}': sha256((self.raw / f'case-{n:02d}-deck.json').read_bytes()).hexdigest()}}
            for n in range(1, 21)]})
        self.assertTrue(audit(self.raw, self.edited, baseline)['raw_baseline_compared'])
        with (self.raw / 'case-01-deck.json').open('a', encoding='utf-8') as handle:
            handle.write(' ')
        with self.assertRaises(ValueError): audit(self.raw, self.edited, baseline)

    def test_packaging_rejects_modified_slide_after_audit(self):
        result = audit(self.raw, self.edited)
        self.write(self.folder / 'v4-editorial-audit.json', result)
        (self.edited / 'case-01-deck.pptx').write_bytes(b'Changed')
        with self.assertRaises(ValueError): package(self.folder)
        self.assertFalse((self.folder / 'V4-20-bai-mau-da-ra-soat.zip').exists())

    def test_stale_export_after_text_edit_is_rejected(self):
        self.change(lambda d: d['manifest']['slides'][0].update(title='Nội dung mới chưa xuất'))
        with self.assertRaisesRegex(ValueError, 'render again'):
            audit(self.raw, self.edited)


if __name__ == '__main__':
    unittest.main()
