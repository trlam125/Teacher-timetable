from __future__ import annotations

import re
import textwrap
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


def _natural_key(value: str):
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", str(value or ""))
    ]


def _safe_excel_text(value: object) -> str:
    text = str(value or "")
    # Prevent user-provided names from accidentally becoming Excel formulas.
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _day_label(day_index: int) -> str:
    return "CN" if day_index == 6 else str(day_index + 2)


def _wrapped_lines(value: str, width: int) -> int:
    return sum(max(1, len(textwrap.wrap(line, width=width))) for line in value.split("\n"))


def _session_label(session_index: int, session_count: int) -> str:
    if session_count == 1:
        return "S"
    if session_count == 2:
        return "S" if session_index == 0 else "C"
    return f"B{session_index + 1}"


def _finish_table(sheet, header_row: int, last_row: int, last_col: int, border: Border):
    # Set borders after merging, including blank cells. Only merged-label
    # perimeters are drawn; no lines cross through the day/session labels.
    for row in sheet.iter_rows(min_row=header_row, max_row=last_row, max_col=last_col):
        for cell in row:
            cell.border = Border() if isinstance(cell, MergedCell) else border
    for merged_range in sheet.merged_cells.ranges:
        if merged_range.min_row >= header_row:
            merged_range.format()
    sheet.freeze_panes = None
    sheet.sheet_view.showGridLines = False
    sheet.print_title_rows = f"1:{header_row}"
    sheet.print_area = f"A1:{get_column_letter(last_col)}{last_row}"
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.sheet_properties.pageSetUpPr.autoPageBreaks = False
    sheet.page_margins.left = 0.2
    sheet.page_margins.right = 0.2
    sheet.page_margins.top = 0.35
    sheet.page_margins.bottom = 0.35
    sheet.page_margins.header = 0.1
    sheet.page_margins.footer = 0.1


def build_timetable_workbook(
    project, data: dict, *, integrity: dict | None = None
) -> Workbook:
    """Match the supplied .xls layout: each class spans subject/teacher columns.

    Generate a fresh .xlsx so recovered sheets, sample lessons and irregular
    blank rows from the reference never become part of an exported project.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Thời khóa biểu"
    sheet.sheet_view.showGridLines = False

    classes = sorted(
        data.get("classes", []), key=lambda item: _natural_key(item.get("name", ""))
    )
    teachers = {item["id"]: item for item in data.get("teachers", [])}
    assignments = {item["id"]: item for item in data.get("assignments", [])}
    lessons = data.get("lessons", [])

    class_column = {item["id"]: 4 + 2 * index for index, item in enumerate(classes)}
    last_col = max(3, 3 + 2 * len(classes))

    thin = Side(style="thin", color="FF000000")
    table_border = Border(left=thin, right=thin, top=thin, bottom=thin)
    white_fill = PatternFill(fill_type="solid", fgColor="FFFFFF")

    # Title area follows the structure of the provided sample: school name, then timetable title.
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    sheet.cell(1, 1, _safe_excel_text(project.school_name or "TRƯỜNG HỌC"))
    sheet.cell(1, 1).font = Font(name="Times New Roman", size=9, bold=True)
    sheet.cell(1, 1).alignment = Alignment(horizontal="left", vertical="center")
    sheet.row_dimensions[1].height = 22.5

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    sheet.cell(2, 1, _safe_excel_text(project.name or "THỜI KHÓA BIỂU"))
    sheet.cell(2, 1).font = Font(name="Times New Roman", size=14, bold=True)
    sheet.cell(2, 1).alignment = Alignment(
        horizontal="center", vertical="center", wrap_text=True
    )
    sheet.row_dimensions[2].height = 30

    header_row = 4
    sheet.row_dimensions[3].height = 7
    if integrity is not None and (not integrity["valid"] or integrity.get("partial")):
        sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=last_col)
        warning = sheet.cell(
            3,
            1,
            _safe_excel_text(
                "CẢNH BÁO — Lịch chưa hoàn chỉnh hoặc còn xung đột. "
                + integrity["message"]
            ),
        )
        warning.font = Font(name="Times New Roman", size=9, bold=True, color="92400E")
        warning.fill = PatternFill(fill_type="solid", fgColor="FFFBEB")
        warning.alignment = Alignment(
            horizontal="left", vertical="center", wrap_text=True
        )
        # Keep the warning visible both on screen and on every printed page.
        sheet.row_dimensions[3].height = max(
            60, 15 * (len(str(warning.value)) // 60 + 1)
        )
    for col, value in enumerate(["Thứ", "Buổi", "Tiết"], start=1):
        cell = sheet.cell(header_row, col, value)
        cell.font = Font(name="Times New Roman", size=8, bold=True)
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = table_border
        cell.fill = white_fill
    for class_item in classes:
        col = class_column[class_item["id"]]
        sheet.merge_cells(start_row=header_row, start_column=col, end_row=header_row, end_column=col + 1)
        cell = sheet.cell(header_row, col, _safe_excel_text(class_item["name"]))
        cell.font = Font(name="Times New Roman", size=9, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.fill = white_fill
    sheet.row_dimensions[header_row].height = 23.25

    # Build a quick lookup from (slot, class) to the assignment taught in that slot.
    by_slot_class = defaultdict(list)
    busy_teachers = defaultdict(set)
    for lesson in lessons:
        assignment = assignments.get(lesson.get("assignment_id"))
        if not assignment:
            continue
        slot = int(lesson["slot"])
        class_id = assignment.get("class_id")
        teacher_id = assignment.get("teacher_id")
        if class_id is not None:
            by_slot_class[(slot, class_id)].append(assignment)
        if teacher_id is not None:
            busy_teachers[slot].add(teacher_id)

    active_teacher_ids = {
        item.get("teacher_id")
        for item in assignments.values()
        if item.get("teacher_id") in teachers
    }

    # Keep the existing free-teacher information on its own sheet so the main
    # timetable has exactly the class pairs shown in the reference.
    free_sheet = workbook.create_sheet("GV nghỉ")
    for col, label in enumerate(["Thứ", "Buổi", "Tiết", "GV không có tiết dạy"], start=1):
        cell = free_sheet.cell(1, col, label)
        cell.font = Font(name="Times New Roman", size=9, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    free_sheet.row_dimensions[1].height = 24
    free_row = 2

    periods_per_day = project.sessions * project.periods_per_session
    current_row = header_row + 1
    for day in range(project.days):
        day_start = current_row
        for session in range(project.sessions):
            session_start = current_row
            for period in range(project.periods_per_session):
                slot = (
                    day * periods_per_day
                    + session * project.periods_per_session
                    + period
                )
                sheet.cell(current_row, 3, period + 1)
                max_lines = 1

                for class_item in classes:
                    cell_assignments = by_slot_class.get((slot, class_item["id"]), [])
                    subject_lines = []
                    teacher_lines = []
                    for assignment in cell_assignments:
                        subject = str(
                            assignment.get("subject_short")
                            or assignment.get("subject_name")
                            or ""
                        ).strip()
                        teacher = str(
                            assignment.get("teacher_short")
                            or assignment.get("teacher_name")
                            or ""
                        ).strip()
                        subject_lines.append(subject)
                        teacher_lines.append(teacher)
                    # Invalid timetables may have several lessons in one cell.
                    # Preserve them all instead of silently overwriting a lesson.
                    col = class_column[class_item["id"]]
                    subject_text = "\n".join(subject_lines)
                    teacher_text = "\n".join(teacher_lines)
                    sheet.cell(current_row, col, _safe_excel_text(subject_text))
                    sheet.cell(current_row, col + 1, _safe_excel_text(teacher_text))
                    max_lines = max(max_lines, _wrapped_lines(subject_text, 9), _wrapped_lines(teacher_text, 8))

                free_teacher_names = []
                for teacher_id in sorted(
                    active_teacher_ids - busy_teachers.get(slot, set()),
                    key=lambda tid: _natural_key(
                        teachers[tid].get("short_name") or teachers[tid].get("name", "")
                    ),
                ):
                    teacher = teachers[teacher_id]
                    free_teacher_names.append(
                        str(
                            teacher.get("short_name") or teacher.get("name") or ""
                        ).strip()
                    )
                free_values = [_day_label(day), _session_label(session, project.sessions), period + 1,
                               _safe_excel_text(", ".join(name for name in free_teacher_names if name))]
                for col, value in enumerate(free_values, start=1):
                    cell = free_sheet.cell(free_row, col, value)
                    cell.font = Font(name="Times New Roman", size=9)
                    cell.alignment = Alignment(horizontal="left" if col == 4 else "center",
                                               vertical="center", wrap_text=True)
                free_sheet.row_dimensions[free_row].height = 24 * max(1, (len(str(free_values[3])) + 79) // 80)
                free_row += 1

                for col in range(1, last_col + 1):
                    cell = sheet.cell(current_row, col)
                    cell.font = Font(name="Times New Roman", size=9)
                    cell.alignment = Alignment(
                        horizontal="center" if col <= 3 else "left", vertical="center", wrap_text=True
                    )
                    cell.border = table_border
                    cell.fill = white_fill
                sheet.row_dimensions[current_row].height = max(24, 12 * max_lines + 4)
                current_row += 1

            session_end = current_row - 1
            if session_end >= session_start:
                sheet.merge_cells(
                    start_row=session_start,
                    start_column=2,
                    end_row=session_end,
                    end_column=2,
                )
                session_cell = sheet.cell(
                    session_start, 2, _session_label(session, project.sessions)
                )
                session_cell.font = Font(name="Times New Roman", size=9, bold=True)
                session_cell.alignment = Alignment(
                    horizontal="center", vertical="center", wrap_text=True
                )
                session_cell.border = table_border

        day_end = current_row - 1
        if day_end >= day_start:
            sheet.merge_cells(
                start_row=day_start, start_column=1, end_row=day_end, end_column=1
            )
            day_cell = sheet.cell(day_start, 1, _day_label(day))
            day_cell.font = Font(name="Times New Roman", size=9, bold=True)
            day_cell.alignment = Alignment(horizontal="center", vertical="center")
            day_cell.border = table_border

    last_row = current_row - 1

    # Reference widths: narrow day/session/period, then a pair for every class.
    sheet.column_dimensions["A"].width = 3.4
    sheet.column_dimensions["B"].width = 3.9
    sheet.column_dimensions["C"].width = 3.6
    for col in class_column.values():
        sheet.column_dimensions[get_column_letter(col)].width = 8.3
        sheet.column_dimensions[get_column_letter(col + 1)].width = 7.5

    _finish_table(sheet, header_row, last_row, last_col, table_border)
    sheet.page_setup.paperSize = (
        sheet.PAPERSIZE_A3 if len(classes) > 10 else sheet.PAPERSIZE_A4
    )
    for col, width in (("A", 5), ("B", 7), ("C", 5), ("D", 80)):
        free_sheet.column_dimensions[col].width = width
    _finish_table(free_sheet, 1, free_row - 1, 4, table_border)
    free_sheet.page_setup.paperSize = free_sheet.PAPERSIZE_A4

    return workbook
