import unittest
from pydantic import ValidationError
from app.services.ai_slides.links import normalize_link
from app.services.ai_slides.schemas import ManualResource


class TeachingLinksTests(unittest.TestCase):
    def test_video_canonicalization_and_status(self):
        link = ManualResource(title='Video đã chọn', url='https://youtu.be/abcdefgh_12?t=30')
        self.assertEqual(link.url, 'https://www.youtube.com/watch?v=abcdefgh_12')
        self.assertEqual(link.kind, 'video')
        self.assertEqual(link.verification, 'user_provided')
        self.assertEqual(normalize_link('https://vimeo.com/12345')[1], 'video')
        with self.assertRaises(ValidationError):
            ManualResource(title='Không được tự nhận đã kiểm chứng', url=link.url, verification='verified')

    def test_unsafe_unknown_or_malformed_links_are_rejected_without_fetch(self):
        for url in ['http://youtu.be/abcdefgh_12', 'https://127.0.0.1/x', 'https://localhost/x',
                    'https://phet.colorado.edu.evil.test/x', 'https://evil.test/@phet.colorado.edu',
                    'https://u:p@phet.colorado.edu/x', 'https://phet.colorado.edu:444/x',
                    'https://youtu.be/short', 'https://www.youtube.com/redirect?q=x',
                    'https://phet.colorado.edu\\@evil.test', 'javascript:alert(1)',
                    'https://phet.colorado.edu/\nsecret']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_link(url)
        self.assertEqual(normalize_link('https://vi.wikipedia.org/wiki/Nước?tracking=1#x'),
                         ('https://vi.wikipedia.org/wiki/Nước', 'web'))
