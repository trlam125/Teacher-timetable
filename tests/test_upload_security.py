"""Small, bounded fixtures exercising pre-load rejection and normal file compatibility."""
import io
import unittest
import threading
import zipfile
from unittest.mock import patch

from test_auth_security import request  # Set dummy app configuration before imports.
from app.services import upload_limits as limits


def archive(name, xml):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(name, xml)
    return output.getvalue()


class UploadSecurityTests(unittest.TestCase):
    def test_parser_admission_is_bounded_and_released_after_failure(self):
        @limits.bounded_document_parser(limits.UploadLimitError)
        def inner():
            return 'ok'
        @limits.bounded_document_parser(limits.UploadLimitError)
        def nested():
            return inner()
        with patch.object(limits, '_parser_slots', threading.BoundedSemaphore(1)):
            with self.assertRaises(limits.UploadLimitError):
                nested()
            self.assertEqual(inner(), 'ok')

    def test_normal_workbook_round_trip(self):
        from openpyxl import Workbook
        from app.schedule_audit.parsing import _read_excel_tables
        workbook = Workbook()
        workbook.active.append(['Thứ', 'Tiết', '10A1'])
        workbook.active.append([2, 1, 'Toán - An'])
        stream = io.BytesIO()
        workbook.save(stream)
        limits.ensure_workbook_safe(stream.getvalue())
        tables = _read_excel_tables(stream.getvalue(), '.xlsx')
        self.assertEqual(tables[0][1][1], ['2', '1', 'Toán - An'])

    def test_huge_sparse_geometry_rejected_even_with_nonstandard_part_name(self):
        xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:XFD1048576"/></worksheet>'
        for name in ['xl/worksheets/sheet1.xml', 'xl/alternate.xml', 'xl/payload.bin']:
            with self.subTest(name=name), self.assertRaises(limits.UploadLimitError):
                limits.ensure_workbook_safe(archive(name, xml))

    def test_actual_coordinates_cannot_hide_behind_small_dimension(self):
        xml = '<worksheet><dimension ref="A1"/><sheetData><row r="1"><c r="A5001"><v>1</v></c></row></sheetData></worksheet>'
        with self.assertRaises(limits.UploadLimitError):
            limits.ensure_workbook_safe(archive('xl/sheet.xml', xml))

    def test_shared_string_count_and_rich_text_are_checked_for_renamed_parts(self):
        with patch.object(limits, 'MAX_SHARED_STRINGS', 2):
            with self.assertRaises(limits.UploadLimitError):
                limits.ensure_workbook_safe(archive('xl/renamed.bin', '<sst><si><t>a</t></si><si><t>b</t></si><si><t>c</t></si></sst>'))
        xml = '<sst><si><r><t>' + 'a' * 3000 + '</t></r><r><t>' + 'b' * 3000 + '</t></r></si></sst>'
        with self.assertRaises(limits.UploadLimitError):
            limits.ensure_workbook_safe(archive('xl/strings.bin', xml))

    def test_xml_entity_declarations_and_excessive_depth_are_rejected(self):
        values = ['<!DOCTYPE x [<!ENTITY a "small">]><worksheet/>', '<x>' * 65 + '</x>' * 65]
        for xml in values:
            with self.subTest(xml=xml[:25]), self.assertRaises(limits.UploadLimitError):
                limits.ensure_workbook_safe(archive('xl/custom.bin', xml))

    def test_expanded_namespace_names_are_bounded(self):
        xml = '<worksheet xmlns="urn:' + 'n' * 20_000 + '"><row/></worksheet>'
        with self.assertRaises(limits.UploadLimitError):
            limits.ensure_workbook_safe(archive('xl/custom.bin', xml))

    def test_archive_expansion_checked_before_workbook_loader(self):
        content = archive('xl/large.xml', ' ' * 256)
        with self.assertRaises(limits.UploadLimitError):
            limits.ensure_workbook_safe(content, max_bytes=128)
        from app import chatbot
        bad = archive('xl/alternate.bin', '<worksheet><dimension ref="A1:A5001"/></worksheet>')
        with patch.object(chatbot, 'load_workbook') as loader:
            with self.assertRaises(chatbot.ChatbotError):
                chatbot.parse_uploaded_table('test.xlsx', bad)
            loader.assert_not_called()

    def test_resolved_output_budget_shared_across_sheets(self):
        budget = {'cells': 20, 'chars': 8}
        self.assertEqual(limits.bounded_rows([['aaaa']], budget=budget), [['aaaa']])
        with self.assertRaises(limits.UploadLimitError):
            limits.bounded_rows([['aaaaa']], budget=budget)

    def test_updated_pdf_reader_handles_a_normal_blank_document(self):
        from pypdf import PdfWriter
        from app.chatbot import ChatbotError, parse_uploaded_table
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        stream = io.BytesIO()
        writer.write(stream)
        with self.assertRaisesRegex(ChatbotError, 'PDF không có văn bản'):
            parse_uploaded_table('blank.pdf', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
