import io
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.chatbot import ChatbotError, parse_uploaded_table


class ChatbotUploadTests(unittest.TestCase):
    @staticmethod
    def _text_pdf_bytes(text: str) -> bytes:
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        })
        font_ref = writer._add_object(font)
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font_ref})
        })
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(f'BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET'.encode('latin-1'))
        page[NameObject('/Contents')] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()

    def test_pdf_text_is_extracted(self):
        parsed = parse_uploaded_table('yeu-cau.pdf', self._text_pdf_bytes('Hello timetable PDF'))
        self.assertEqual(parsed['type'], 'pdf')
        self.assertIn('Hello timetable PDF', parsed['pages'][0]['text'])

    def test_scanned_or_blank_pdf_has_clear_error(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(ChatbotError, 'không có văn bản'):
            parse_uploaded_table('blank.pdf', output.getvalue())

    def test_print_buttons_removed(self):
        root = Path(__file__).resolve().parents[1] / 'app' / 'templates'
        for name in ('workspace.html', 'teacher_portal.html', 'share.html'):
            source = (root / name).read_text(encoding='utf-8')
            self.assertNotIn('window.print()', source)


if __name__ == '__main__':
    unittest.main()
