import copy
import csv
import io
import unittest
import zipfile
import json
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape

from openpyxl import Workbook

from app.schedule_audit import (
    ScheduleAuditParseError, analyze_standalone_schedule_file, apply_standalone_viewer_edits,
)
from app.schedule_audit.custom_limits import check_custom_weekly_workload
from app.excel_export import build_timetable_workbook, serialize_timetable_workbook
from app.services.audit import read_schedule_audit_report_json
from fastapi import HTTPException


HEADERS = ['Thứ', 'Buổi', 'Tiết', 'Lớp', 'Môn', 'Giáo viên', 'Phòng']


def csv_file(rows, delimiter=','):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=delimiter)
    writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


def xlsx_file(sheets, merges=()):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets:
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    for sheet_name, cell_range in merges:
        workbook[sheet_name].merge_cells(cell_range)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def merged_word_file():
    # Same supported two-column class layout as the application's Excel export.
    rows = [
        [('Thứ', 1), ('Buổi', 1), ('Tiết', 1), ('6A1', 2), ('6A2', 2)],
        [('Thứ 2', 1), ('Sáng', 1), ('1', 1), ('Toán', 1),
         ('Nguyễn Văn An', 1), ('Ngữ văn', 1), ('Trần Thị Mai', 1)],
    ]
    table = []
    for row in rows:
        cells = []
        for value, span in row:
            props = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ''
            cells.append(f'<w:tc>{props}<w:p><w:r><w:t>{escape(value)}</w:t></w:r></w:p></w:tc>')
        table.append('<w:tr>' + ''.join(cells) + '</w:tr>')
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:tbl>' + ''.join(table) + '</w:tbl></w:body></w:document>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', xml)
    return output.getvalue()


class ScheduleAuditTests(unittest.TestCase):
    def analyze(self, rows):
        return analyze_standalone_schedule_file(filename='schedule.csv', content=csv_file([HEADERS, *rows]))

    def test_teacher_collision_is_detected(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'Nguyễn Văn An', 'P1'],
            ['Thứ 2', 'Sáng', 1, '6A2', 'Toán', 'Nguyễn Văn An', 'P2'],
        ])
        self.assertIn('teacher_collision', {row['code'] for row in report['issues']})
        self.assertEqual(report['summary']['recognized_lessons'], 2)

    def test_room_collision_is_detected(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'An', 'P1'],
            ['Thứ 2', 'Sáng', 1, '6A2', 'Toán', 'Mai', 'P1'],
        ])
        self.assertIn('room_collision', {row['code'] for row in report['issues']})

    def test_same_lesson_in_class_and_teacher_sheets_is_counted_once(self):
        content = xlsx_file([
            ('6A1', [['Tiết', 'Thứ 2', 'Thứ 3'], [1, 'Toán - Nguyễn Văn An', '']]),
            ('Nguyễn Văn An', [['Tiết', 'Thứ 2', 'Thứ 3'], [1, '6A1 - Toán', '']]),
        ])
        report = analyze_standalone_schedule_file(filename='schedule.xlsx', content=content)
        self.assertEqual(report['summary']['recognized_lessons'], 1)
        self.assertEqual(report['summary']['collisions'], 0)

    def test_export_style_merged_excel_headers_keep_subject_teacher_columns(self):
        content = xlsx_file([('Thời khóa biểu', [
            ['Thứ', 'Buổi', 'Tiết', '6A1', '', '6A2', ''],
            ['Thứ 2', 'Sáng', 1, 'Toán', 'Nguyễn Văn An', 'Ngữ văn', 'Trần Thị Mai'],
        ])], [('Thời khóa biểu', 'D1:E1'), ('Thời khóa biểu', 'F1:G1')])
        report = analyze_standalone_schedule_file(filename='schedule.xlsx', content=content)
        actual = {(row['class_name'], row['subject_name'], row['teacher_name']) for row in report['viewer']['cells']}
        self.assertEqual(actual, {('6A1', 'Toán', 'Nguyễn Văn An'), ('6A2', 'N. Văn', 'Trần Thị Mai')})

    def test_merged_word_headers_keep_subject_teacher_columns(self):
        report = analyze_standalone_schedule_file(filename='schedule.docx', content=merged_word_file())
        actual = {(row['class_name'], row['subject_name'], row['teacher_name']) for row in report['viewer']['cells']}
        self.assertEqual(actual, {('6A1', 'Toán', 'Nguyễn Văn An'), ('6A2', 'N. Văn', 'Trần Thị Mai')})

    def test_tsv_preserves_morning_and_afternoon(self):
        content = csv_file([HEADERS,
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'An', ''],
            ['Thứ 2', 'Chiều', 1, '6A1', 'Toán', 'An', ''],
        ], delimiter='\t')
        report = analyze_standalone_schedule_file(filename='schedule.tsv', content=content)
        self.assertEqual(len({row['slot'] for row in report['viewer']['cells']}), 2)
        self.assertEqual(report['summary']['collisions'], 0)

    def test_weekly_load_keeps_teachers_with_different_accents_separate(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'Nguyễn Văn An', ''],
            ['Thứ 2', 'Sáng', 2, '6A1', 'Toán', 'Nguyễn Văn Ân', ''],
            ['Thứ 2', 'Sáng', 3, '6A1', 'Toán', 'Nguyễn Văn Ân', ''],
        ])
        limits = {'assignments': [
            {'teacher':'Nguyễn Văn An', 'class_name':'6A1', 'subject':'Toán', 'periods':1},
            {'teacher':'Nguyễn Văn Ân', 'class_name':'6A1', 'subject':'Toán', 'periods':2},
        ]}
        workload = check_custom_weekly_workload(report['viewer'], limits)
        self.assertEqual({row['name']: (row['actual'], row['status']) for row in workload['teachers']},
                         {'Nguyễn Văn An':(1,'ok'), 'Nguyễn Văn Ân':(2,'ok')})

    def test_weekly_load_does_not_merge_known_and_placeholder_teachers(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', '', ''],
            ['Thứ 2', 'Sáng', 1, '6A2', 'Toán', '', ''],
        ])
        self.assertNotIn('teacher_collision', {row['code'] for row in report['issues']})

    def test_edited_teacher_recomputes_conflicts_from_original_cells(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'An', ''],
            ['Thứ 2', 'Sáng', 1, '6A2', 'Toán', 'Mai', ''],
        ])
        edited = copy.deepcopy(report)
        edited['viewer']['cells'][1]['teacher_name'] = 'An'
        edited['issues'] = []
        result = apply_standalone_viewer_edits(report, edited)
        self.assertIn('teacher_collision', {row['code'] for row in result['issues']})

    def test_class_and_teacher_column_layouts_read_both_classes(self):
        for headers, values in (
            (['Thứ', 'Buổi', 'Tiết', '6A1', '6A2'], ['Thứ 2', 'Sáng', 1, 'Toán - An', 'Tin - Mai']),
            (['Thứ', 'Buổi', 'Tiết', 'An', 'Mai'], ['Thứ 2', 'Sáng', 1, '6A1 - Toán', '6A2 - Tin']),
        ):
            with self.subTest(headers=headers):
                report = analyze_standalone_schedule_file(filename='schedule.csv', content=csv_file([headers, values]))
                self.assertEqual({row['class_name'] for row in report['viewer']['cells']}, {'6A1', '6A2'})
                self.assertEqual(report['summary']['collisions'], 0)

    def exported_report(self, conflicting=False):
        project = SimpleNamespace(id=1, name='Test', school_name='Test', days=5, sessions=2, periods_per_session=5)
        data = {
            'classes': [{'id':1, 'name':'6A1'}, {'id':2, 'name':'6A2'}],
            'teachers': [{'id':1, 'name':'An', 'short_name':'An'}, {'id':2, 'name':'Mai', 'short_name':'Mai'}],
            'assignments': [
                {'id':1, 'class_id':1, 'subject_id':1, 'teacher_id':1, 'subject_name':'Toán', 'teacher_name':'An'},
                {'id':2, 'class_id':1 if conflicting else 2, 'subject_id':2, 'teacher_id':2, 'subject_name':'Tin', 'teacher_name':'Mai'},
            ],
            'lessons': [{'assignment_id':1, 'slot':0}, {'assignment_id':2, 'slot':0}],
        }
        workbook = build_timetable_workbook(project, data)
        try:
            content = serialize_timetable_workbook(workbook)
        finally:
            workbook.close()
        return analyze_standalone_schedule_file(filename='export.xlsx', content=content)

    def test_app_export_round_trip_ignores_free_teacher_sheet(self):
        report = self.exported_report()
        self.assertEqual(report['summary']['recognized_lessons'], 2)
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual(report['summary']['warnings'], 0)

    def test_app_export_with_multiple_lessons_in_one_cell_preserves_collision(self):
        report = self.exported_report(conflicting=True)
        self.assertEqual(report['summary']['recognized_lessons'], 2)
        self.assertIn('class_collision', {row['code'] for row in report['issues']})

    def test_wrapped_subject_component_is_not_split_into_two_lessons(self):
        content = xlsx_file([('Thời khóa biểu', [
            ['Thứ', 'Buổi', 'Tiết', '6A1', ''],
            ['Thứ 2', 'Sáng', 1, 'KHTN\n(L)', 'Nguyễn Văn\nAn'],
        ])], [('Thời khóa biểu', 'D1:E1')])
        report = analyze_standalone_schedule_file(filename='schedule.xlsx', content=content)
        self.assertEqual(report['summary']['recognized_lessons'], 1)
        self.assertEqual(report['summary']['collisions'], 0)
        self.assertEqual(report['viewer']['cells'][0]['subject_name'], 'KHTN (L)')

    def test_periods_numbered_across_day_with_session_labels_are_not_lost(self):
        report = self.analyze([
            ['Thứ 2', 'Sáng' if period <= 5 else 'Chiều', period, '6A1', 'Toán', 'An', '']
            for period in range(1, 11)
        ])
        self.assertEqual(report['viewer']['sessions'], 2)
        self.assertEqual(report['viewer']['periods'], 5)
        self.assertEqual(report['summary']['recognized_lessons'], 10)
        self.assertEqual(report['summary']['errors'], 0)
        self.assertEqual({cell['slot'] for cell in report['viewer']['cells']}, set(range(10)))

    def test_invalid_coordinates_are_reported_instead_of_silently_reinterpreted(self):
        for day, session, period in (
            ('23/11/2026', 'Sáng', 1),
            ('Thứ 2', 'Buổi 9', 1),
            ('Thứ 2', 'Buổi không rõ', 1),
            ('Thứ 2', 'Sáng', '1.5'),
            ('Thứ 2', 'Sáng', '-1'),
            ('Thứ 2', 'Sáng', '1-2'),
        ):
            with self.subTest(day=day, session=session, period=period):
                report = self.analyze([[day, session, period, '6A1', 'Toán', 'An', '']])
                self.assertIn('invalid_slot', {row['code'] for row in report['issues']})
                self.assertEqual(report['summary']['recognized_lessons'], 0)

    def test_invalid_edited_numbers_return_bad_request(self):
        original = self.analyze([['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'An', '']])
        for field, value in (('days', float('inf')), ('days', True), ('periods', 1.5)):
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(original)
                report['viewer'][field] = value
                with self.assertRaises(HTTPException) as error:
                    read_schedule_audit_report_json(json.dumps(report))
                self.assertEqual(error.exception.status_code, 400)
        for field, value in (('slot', float('inf')), ('slot', 0.5), ('class_id', True), ('draft_id', 0)):
            with self.subTest(field=field, value=value):
                report = copy.deepcopy(original)
                report['viewer']['cells'][0][field] = value
                with self.assertRaises(HTTPException) as error:
                    read_schedule_audit_report_json(json.dumps(report))
                self.assertEqual(error.exception.status_code, 400)

    def test_session_local_numbering_still_restarts_at_one(self):
        report = self.analyze([
            ['Thứ 2', session, period, '6A1', 'Toán', 'An', '']
            for session in ('Sáng', 'Chiều') for period in range(1, 6)
        ])
        self.assertEqual(report['viewer']['periods'], 5)
        self.assertEqual(report['summary']['recognized_lessons'], 10)
        self.assertEqual({cell['slot'] for cell in report['viewer']['cells']}, set(range(10)))
        self.assertEqual(report['summary']['errors'], 0)

    def test_malformed_period_in_wide_and_grid_layout_is_not_dropped(self):
        for rows in (
            [['Thứ', 'Buổi', 'Tiết', '6A1'],
             ['Thứ 2', 'Sáng', '1.5', 'Toán - An'], ['Thứ 2', 'Sáng', 2, 'Tin - Mai']],
            [['Lớp 6A1'], ['Tiết', 'Thứ 2', 'Thứ 3'],
             ['1.5', 'Toán - An', ''], [2, 'Tin - Mai', '']],
        ):
            with self.subTest(rows=rows):
                report = analyze_standalone_schedule_file(filename='schedule.csv', content=csv_file(rows))
                self.assertEqual(report['summary']['recognized_lessons'], 1)
                self.assertIn('invalid_slot', {row['code'] for row in report['issues']})

    def test_repeated_table_headers_are_not_lessons(self):
        report = analyze_standalone_schedule_file(filename='schedule.csv', content=csv_file([
            HEADERS, ['Thứ 2', 'Sáng', 1, '6A1', 'Toán', 'An', ''],
            HEADERS, ['Thứ 2', 'Sáng', 2, '6A1', 'Tin', 'Mai', ''],
        ]))
        self.assertEqual(report['summary']['recognized_lessons'], 2)
        self.assertEqual(report['summary']['errors'], 0)

    def test_xls_merged_header_coordinates_keep_teacher_columns(self):
        rows = [
            ['Thứ', 'Buổi', 'Tiết', '6A1', '', '6A2', ''],
            ['Thứ 2', 'Sáng', 1, 'Toán', 'An', 'Tin', 'Mai'],
        ]
        sheet = SimpleNamespace(name='TKB', nrows=2, ncols=7, merged_cells=[(0,1,3,5),(0,1,5,7)],
                                cell_value=lambda row,col: rows[row][col])
        book = SimpleNamespace(sheets=lambda:[sheet], release_resources=lambda:None)
        # Exercise BIFF merged-cell metadata without requiring a writer package.
        with patch('xlrd.open_workbook', return_value=book):
            report = analyze_standalone_schedule_file(filename='schedule.xls', content=b'fixture')
        self.assertEqual({(cell['class_name'], cell['teacher_name']) for cell in report['viewer']['cells']},
                         {('6A1','An'),('6A2','Mai')})
        self.assertEqual(report['summary']['warnings'], 0)

    def test_csv_with_oversized_cell_returns_parse_error(self):
        content = csv_file([HEADERS, ['Thứ 2','Sáng',1,'6A1','Toán','An','x'*150000]])
        with self.assertRaises(ScheduleAuditParseError):
            analyze_standalone_schedule_file(filename='schedule.csv', content=content)


if __name__ == '__main__':
    unittest.main()
