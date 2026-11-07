from __future__ import annotations

from copy import copy
from io import BytesIO
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, ZipInfo

from openpyxl import load_workbook

from app.excel_export import build_timetable_workbook, serialize_timetable_workbook
from app.services.excel_compat import ensure_excel_borders_applied


NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
M = {"m": NS}
EDGES = ("left", "right", "top", "bottom", "diagonal", "vertical",
         "horizontal", "start", "end")


def fixture(class_count=3, *, days=6, sessions=2, periods=5, partial=False):
    project = SimpleNamespace(
        id=1, name="TKB Tuần 1–4, 9–12", school_name="THCS HÀ LONG",
        days=days, sessions=sessions, periods_per_session=periods,
    )
    data = {
        "classes": [{"id": i, "name": f"6A{i}"}
                    for i in range(class_count, 0, -1)],
        "teachers": [{"id": 1, "name": "Nguyễn Văn A", "short_name": "A"},
                     {"id": 2, "name": "Trần Thị B", "short_name": "B"}],
        "assignments": [{"id": i, "class_id": i, "teacher_id": 1 + i % 2,
                         "subject_short": "N. Văn", "teacher_short": "A" if i % 2 == 0 else "B"}
                        for i in range(1, class_count + 1)],
        # Consecutive lessons and blank slots occur in the same fixture.
        "lessons": [{"assignment_id": i, "slot": slot}
                    for i in range(1, class_count + 1)
                    for slot in range(min(2, periods))],
    }
    integrity = {"valid": True, "partial": partial, "message": "Còn tiết chưa xếp."}
    return project, data, integrity


def raw_bytes(workbook):
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def stylesheet(xlsx):
    with ZipFile(BytesIO(xlsx)) as archive:
        return ET.fromstring(archive.read("xl/styles.xml"))


def needs_border_flag(xf, borders):
    index = int(xf.get("borderId", "0"))
    return index > 0 and any(
        edge.tag == f"{{{NS}}}{name}" and edge.get("style") not in (None, "", "none")
        for edge in borders[index] for name in EDGES
    )


def xml_archive(styles):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.comment = b"archive comment"
        entry = ZipInfo("xl/styles.xml", date_time=(2020, 1, 2, 3, 4, 6))
        entry.comment = b"style comment"
        archive.writestr(entry, styles)
        archive.writestr("unchanged.bin", b"keep these exact bytes\x00\xff")
    return output.getvalue()


class ExcelBorderCompatibilityTests(unittest.TestCase):
    def assert_flags(self, payload):
        root = stylesheet(payload)
        borders = root.find("m:borders", M)
        xfs = root.find("m:cellXfs", M)
        selected = [xf for xf in xfs if needs_border_flag(xf, borders)]
        self.assertTrue(selected)
        for xf in selected:
            self.assertEqual(xf.get("applyBorder"), "1")

    def test_only_required_cell_xf_flags_change(self):
        for count, days, sessions, periods, partial in (
            (0, 1, 1, 1, False), (1, 1, 1, 2, False),
            (3, 6, 2, 5, True), (17, 7, 3, 2, False),
        ):
            with self.subTest(classes=count, days=days, sessions=sessions):
                project, data, integrity = fixture(
                    count, days=days, sessions=sessions, periods=periods, partial=partial,
                )
                book = build_timetable_workbook(project, data, integrity=integrity)
                before = raw_bytes(book)
                after = ensure_excel_borders_applied(before)
                self.assert_flags(after)
                with ZipFile(BytesIO(before)) as original, ZipFile(BytesIO(after)) as fixed:
                    self.assertIsNone(fixed.testzip())
                    self.assertEqual(original.namelist(), fixed.namelist())
                    for name in original.namelist():
                        if name != "xl/styles.xml":
                            self.assertEqual(original.read(name), fixed.read(name), name)
                        old, new = original.getinfo(name), fixed.getinfo(name)
                        for attr in ("date_time", "compress_type", "comment", "extra", "external_attr"):
                            self.assertEqual(getattr(old, attr), getattr(new, attr))
                old_root, new_root = stylesheet(before), stylesheet(after)
                old_xfs = old_root.find("m:cellXfs", M)
                new_xfs = new_root.find("m:cellXfs", M)
                self.assertEqual(len(old_xfs), len(new_xfs))
                borders = old_root.find("m:borders", M)
                for old, new in zip(old_xfs, new_xfs):
                    if needs_border_flag(old, borders):
                        if "applyBorder" in old.attrib:
                            new.set("applyBorder", old.get("applyBorder"))
                        else:
                            del new.attrib["applyBorder"]
                    self.assertEqual(ET.tostring(old), ET.tostring(new))
                self.assertEqual(ET.tostring(old_root), ET.tostring(new_root))

    def test_workbook_values_merges_styles_and_print_settings_survive(self):
        project, data, integrity = fixture(partial=True)
        book = build_timetable_workbook(project, data, integrity=integrity)
        # An unrelated formula/number format must survive serialization too.
        book["GV nghỉ"]["E1"] = "=1+2"
        book["GV nghỉ"]["E1"].number_format = "0.00"
        before = load_workbook(BytesIO(raw_bytes(book)))
        after = load_workbook(BytesIO(serialize_timetable_workbook(book)))
        self.assertEqual(before.sheetnames, after.sheetnames)
        for old, new in zip(before, after):
            self.assertEqual(str(old.merged_cells), str(new.merged_cells))
            self.assertEqual((old.max_row, old.max_column), (new.max_row, new.max_column))
            for old_row, new_row in zip(old, new):
                for a, b in zip(old_row, new_row):
                    self.assertEqual((a.value, a.data_type), (b.value, b.data_type))
                    for attr in ("font", "fill", "border", "alignment", "protection"):
                        self.assertEqual(copy(getattr(a, attr)), copy(getattr(b, attr)))
                    self.assertEqual(a.number_format, b.number_format)
            for holder in ("column_dimensions", "row_dimensions"):
                self.assertEqual(
                    {key: (dict(dim), dim.style) for key, dim in getattr(old, holder).items()},
                    {key: (dict(dim), dim.style) for key, dim in getattr(new, holder).items()},
                )
            for attr in ("page_setup", "page_margins", "print_options", "print_area",
                         "print_title_rows", "sheet_properties", "sheet_view", "freeze_panes"):
                self.assertEqual(getattr(old, attr), getattr(new, attr), attr)
        self.assertEqual(after.worksheets[0]["D5"].border.right.style, "dotted")
        self.assertEqual(after.worksheets[0]["E5"].border.right.style, "thin")

    def test_download_serialization_applies_flags_to_both_sheets(self):
        project, data, integrity = fixture(17)
        output = serialize_timetable_workbook(build_timetable_workbook(project, data, integrity=integrity))
        self.assert_flags(output)
        root = stylesheet(output)
        xfs = root.find("m:cellXfs", M)
        with ZipFile(BytesIO(output)) as archive:
            for path in ("xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"):
                sheet = ET.fromstring(archive.read(path))
                cells = sheet.findall("m:sheetData/m:row/m:c", M)
                styled = [xfs[int(c.get("s", "0"))] for c in cells]
                self.assertTrue(any(xf.get("applyBorder") == "1" for xf in styled))

    def test_empty_and_color_only_borders_and_named_styles_are_unchanged(self):
        styles = f'''<s:styleSheet xmlns:s="{NS}" xmlns:ext="urn:example">
          <s:borders count="4"><s:border/><s:border/>
            <s:border><s:left><s:color rgb="FF000000"/></s:left></s:border>
            <s:border><s:right style="dotted"/></s:border></s:borders>
          <s:cellStyleXfs count="1"><s:xf borderId="3"/></s:cellStyleXfs>
          <s:cellXfs count="5"><s:xf borderId="0"/><s:xf borderId="1"/>
            <s:xf borderId="2"/><s:xf borderId="3" applyBorder="0" applyFont="1"/>
            <s:xf borderId="3" applyBorder="true"/></s:cellXfs>
          <s:extLst><ext:extra keep="yes"/></s:extLst>
        </s:styleSheet>'''
        output = ensure_excel_borders_applied(xml_archive(styles))
        root = stylesheet(output)
        xfs = root.find("m:cellXfs", M)
        self.assertEqual([xf.get("applyBorder") for xf in xfs], [None, None, None, "1", "1"])
        self.assertEqual(xfs[3].get("applyFont"), "1")
        self.assertIsNone(root.find("m:cellStyleXfs/m:xf", M).get("applyBorder"))
        with ZipFile(BytesIO(output)) as archive:
            xml = archive.read("xl/styles.xml")
            self.assertIn(b"<s:styleSheet", xml)
            self.assertIn(b'<ext:extra keep="yes"', xml)
            self.assertEqual(archive.comment, b"archive comment")
            self.assertEqual(archive.read("unchanged.bin"), b"keep these exact bytes\x00\xff")

    def test_all_supported_border_edges_are_detected(self):
        borders = "<border/>" + "".join(f'<border><{edge} style="thin"/></border>' for edge in EDGES)
        xfs = "".join(f'<xf borderId="{i}"/>' for i in range(1, 1 + len(EDGES)))
        styles = f'<styleSheet xmlns="{NS}"><borders>{borders}</borders><cellXfs>{xfs}</cellXfs></styleSheet>'
        self.assert_flags(ensure_excel_borders_applied(xml_archive(styles)))

    def test_reapplying_fix_is_byte_identical(self):
        project, data, integrity = fixture()
        fixed = serialize_timetable_workbook(build_timetable_workbook(project, data, integrity=integrity))
        self.assertEqual(fixed, ensure_excel_borders_applied(fixed))

    def test_valid_styles_without_borders_need_no_changes(self):
        styles = f'<styleSheet xmlns="{NS}"><borders><border/><border/></borders><cellXfs><xf borderId="1"/></cellXfs></styleSheet>'
        original = xml_archive(styles)
        self.assertEqual(original, ensure_excel_borders_applied(original))

    def test_malformed_archives_or_styles_fail_instead_of_becoming_a_download(self):
        from xml.parsers.expat import ExpatError

        for styles in (
            b"not XML", b"<styleSheet/>",
            f'<styleSheet xmlns="{NS}"/>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders/><cellXfs/></styleSheet>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders><border/></borders><cellXfs/></styleSheet>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders><border/></borders><cellXfs><xf borderId="9"/></cellXfs></styleSheet>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders><border/></borders><cellXfs><xf borderId="-1"/></cellXfs></styleSheet>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders><border/></borders><cellXfs><xf borderId="bad"/></cellXfs></styleSheet>'.encode(),
            f'<styleSheet xmlns="{NS}"><borders/><cellXfs/><cellXfs/></styleSheet>'.encode(),
        ):
            with self.subTest(styles=styles):
                with self.assertRaises((ValueError, ExpatError)):
                    ensure_excel_borders_applied(xml_archive(styles))
        with self.assertRaises(BadZipFile):
            ensure_excel_borders_applied(b"not a zip")
        out = BytesIO()
        with ZipFile(out, "w") as archive:
            archive.writestr("other.xml", b"<root/>")
        with self.assertRaises(ValueError):
            ensure_excel_borders_applied(out.getvalue())


class ExcelDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import the router without needing real credentials or connecting to
        # Neon. The standalone FastAPI test app has no startup/migration hooks.
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql+psycopg://test:test@127.0.0.1:1/test",
            "SECRET_KEY": "excel-export-tests-only",
        }):
            from app.routers import share_export
        cls.router_module = share_export

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        module = self.router_module
        app = FastAPI()
        app.include_router(module.router)
        app.dependency_overrides[module.current_user] = lambda: SimpleNamespace(id=1)
        app.dependency_overrides[module.db_session] = lambda: Mock(name="unused_db")
        project, data, integrity = fixture(partial=True)
        self.project = project
        for name, value in (("get_project", project), ("project_data", data),
                            ("schedule_integrity_report", integrity)):
            self.enterContext(patch.object(module, name, return_value=value))
        # Any accidental database connection is a test failure.
        self.enterContext(patch("sqlalchemy.engine.Engine.connect", side_effect=AssertionError("Unexpected DB access")))
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))

    def test_download_and_legacy_entry_keep_filename_and_fixed_xlsx(self):
        legacy = self.client.get("/projects/1/export.csv", follow_redirects=False)
        self.assertEqual(legacy.status_code, 303)
        self.assertEqual(legacy.headers["location"], "/projects/1/export.xlsx")
        for _ in range(2):
            response = self.client.get(legacy.headers["location"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn(quote(self.project.name + ".xlsx", safe=""), response.headers["content-disposition"])
            ExcelBorderCompatibilityTests.assert_flags(self, response.content)
            self.assertEqual(load_workbook(BytesIO(response.content)).sheetnames, ["Thời khóa biểu", "GV nghỉ"])

    def test_serialization_error_does_not_send_an_xlsx_file(self):
        with patch("app.excel_export.serialize_timetable_workbook", side_effect=ValueError("bad stylesheet")):
            response = self.client.get("/projects/1/export.xlsx")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("content-disposition", response.headers)
        self.assertFalse(response.content.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
