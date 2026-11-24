import unittest
from app.services.ai_slides.checks import arithmetic_mismatch, slide_findings


class LessonChecksTests(unittest.TestCase):
    def test_clear_numeric_errors_and_percentages(self):
        for text in ['I = 6/3 = 3 A.', '25% của 80 là 30.', '12 ÷ 5 = 3,4.', '2 × (3 + 4) = 12.', '1/0=0']:
            with self.subTest(text=text):
                self.assertTrue(arithmetic_mismatch(text))
        for text in ['I = 6/3 = 2 A.', '25% của 80 là 20.', '12 ÷ 5 = 2,4.', '2 × (3 + 4) = 14.', '10/3=3,33']:
            with self.subTest(text=text):
                self.assertFalse(arithmetic_mismatch(text))

    def test_counterexamples_rounding_and_unsupported_algebra_are_not_certified(self):
        for text in ['Sai lầm: 6/3=3. Tìm lỗi.', '2+2=5 là sai.', '10/3=3', '1.000+2.000=3.000',
                     'x²−5x+6=0', 'x² − 5x + 6 = 0.', '2²-5·2+6=0', '12 + 8 = 15 + m(khí)',
                     '25% của 80 = 80 × 25% = 20', '30% của 200 = 200 × 30/100 = 60.',
                     '__import__("os").system("echo unsafe")=0', 'ρ=m/V']:
            with self.subTest(text=text):
                self.assertFalse(arithmetic_mismatch(text))
        slide = {'kind': 'quiz', 'question': '2+2=5 đúng hay sai?', 'options': ['2+2=5', '2+2=4'],
                 'explanation': '2+2=4.', 'bullets': [], 'speaker_notes': ''}
        self.assertFalse(slide_findings(slide))

    def test_equivalent_quiz_quantities_keep_units_and_do_not_convert(self):
        for options in [['2 A', '2A'], ['0,5', '1/2'], ['25%', '25 %'], ['Tế bào', 'Tế  bào.']]:
            with self.subTest(options=options):
                self.assertIn('QUIZ_EQUIVALENT_OPTIONS', [item['code'] for item in slide_findings({'kind': 'quiz', 'options': options})])
        for options in [['2 A', '2 V'], ['2 mV', '2 MV'], ['mV', 'MV'], ['A', 'a'], ['1,000 mV', '1,000 MV'], ['100 cm', '1 m'], ['1/3', '0,33'], ['1,000', '1000']]:
            with self.subTest(options=options):
                self.assertFalse(slide_findings({'kind': 'quiz', 'options': options}))

    def test_manual_warnings_and_scoped_ai_edit_preserve_unchanged_teacher_content(self):
        from app.services.ai_slides.state import validate_generated_checks
        from app.services.ai_slides.provider import StudioError
        from app.services.ai_slides.review import content_review
        original = {'id': 's001', 'kind': 'concept', 'title': 'Tính toán', 'bullets': ['6/3=3.'], 'speaker_notes': ''}
        warnings = content_review({'slides': [original]}, {'sources': [], 'grounding': 'balanced'})
        self.assertIn('ARITHMETIC_MISMATCH', [item['code'] for item in warnings])
        validate_generated_checks({**original, 'title': 'Đổi tên'}, original)
        with self.assertRaises(StudioError) as error:
            validate_generated_checks(original)
        self.assertEqual(error.exception.code, 'AI_ARITHMETIC_ERROR')
        with self.assertRaises(StudioError) as error:
            validate_generated_checks({'kind': 'quiz', 'options': ['0.5 A', '1/2 A']})
        self.assertEqual(error.exception.code, 'AI_QUIZ_ERROR')


if __name__ == '__main__':
    unittest.main()
