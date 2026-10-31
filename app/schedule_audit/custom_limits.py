"""User-entered weekly period limits for standalone timetable imports.

No school-specific or bundled teaching allocation is used here. A row is
checked only when the user explicitly provides a lower/upper bound.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
import re
from typing import Any

from .workload import COMPOSITES, _key, subject_code

CLASS_PATTERN = re.compile(r'^\s*(1[0-2]|[1-9])\s*([a-zA-Z])\s*0*(\d{1,2})\s*$', re.I)
SECTIONS = ('class_subject', 'teachers', 'assignments')


def _class_name(value: Any) -> str:
    match = CLASS_PATTERN.fullmatch(str(value or ''))
    if not match:
        return ''
    return f'{int(match.group(1))}{match.group(2).upper()}{int(match.group(3))}'


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 120:
        raise ValueError(f'{label} phải có từ 1 đến 120 ký tự.')
    return value.strip()


def _subject_key(value: Any) -> str:
    return subject_code(value) or _key(value)


def _range_number(value: Any, name: str) -> float | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError(f'{name} phải là số không âm.')
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f'{name} phải là số không âm.') from None
    if not isfinite(result) or result < 0 or result > 1000:
        raise ValueError(f'{name} phải nằm trong khoảng từ 0 đến 1000.')
    return result


def validate_limits(limits: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(limits, dict):
        raise ValueError('Định mức phải là một đối tượng JSON hợp lệ.')
    clean = {section: [] for section in SECTIONS}
    for section in SECTIONS:
        rows = limits.get(section, [])
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError(f'Bảng {section} phải có tối đa 500 dòng.')
        used = set()
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError('Một dòng định mức không hợp lệ.')
            lower = _range_number(item.get('min'), 'Tiết tối thiểu')
            upper = _range_number(item.get('max'), 'Tiết tối đa')
            if lower is None and upper is None:
                continue  # Empty rows are intentionally NOT quotas.
            if lower is not None and upper is not None and lower > upper:
                raise ValueError('Tiết tối thiểu không được lớn hơn tiết tối đa.')
            row: dict[str, Any] = {'min': lower, 'max': upper}
            if section == 'class_subject':
                grade = str(item.get('grade', '')).strip()
                if not grade.isdigit() or not 1 <= int(grade) <= 12:
                    raise ValueError('Khối học phải từ 1 đến 12.')
                row.update(grade=str(int(grade)), subject=_text(item.get('subject'), 'Tên môn'))
                key = (row['grade'], _subject_key(row['subject']))
            elif section == 'teachers':
                row['teacher'] = _text(item.get('teacher'), 'Tên giáo viên')
                key = (_key(row['teacher']),)
            else:
                row.update(teacher=_text(item.get('teacher'), 'Tên giáo viên'),
                           subject=_text(item.get('subject'), 'Tên môn'))
                row['class_name'] = _class_name(item.get('class_name'))
                if not row['class_name']:
                    raise ValueError('Lớp phải có dạng 6A1, 7A2, 9C1...')
                key = (_key(row['teacher']), row['class_name'], _subject_key(row['subject']))
            if key in used:
                raise ValueError('Có dòng định mức trùng nhau. Hãy gộp thành một dòng.')
            used.add(key)
            clean[section].append(row)
    return clean


def _state(actual: int, lower: float | None, upper: float | None) -> tuple[str, float]:
    if lower is not None and actual < lower:
        return 'missing', round(actual - lower, 3)
    if upper is not None and actual > upper:
        return 'extra', round(actual - upper, 3)
    return 'ok', 0


def _counts_for_subject(counts: Counter, subject: str) -> int:
    # Composite limit counts all components plus cells written as the umbrella.
    included = set(COMPOSITES.get(subject, ())) | {subject}
    return sum(value for sub, value in counts.items() if sub in included)


def _ambiguous_missing(counts: Counter, subject: str, status: str) -> bool:
    if status != 'missing':
        return False
    # A generic KHTN/LS&ĐL cell cannot be assigned reliably to a component.
    return any(subject in components and counts.get(generic, 0)
               for generic, components in COMPOSITES.items())


def check_custom_weekly_workload(viewer: dict[str, Any], limits: Any) -> dict[str, Any]:
    limits = validate_limits(limits)
    imported_classes = {_class_name(row.get('name')) for row in viewer.get('classes', [])}
    imported_classes.discard('')
    class_subjects: dict[str, Counter] = defaultdict(Counter)
    teacher_subjects: dict[tuple[str, str], Counter] = defaultdict(Counter)
    teacher_counts: Counter = Counter()
    teacher_names = {}
    unknown_subjects = Counter()
    for cell in viewer.get('cells', []):
        cls = _class_name(cell.get('class_name'))
        if not cls or cls not in imported_classes:
            continue
        subject_name = str(cell.get('subject_name') or '').strip()
        subject = _subject_key(subject_name)
        teacher_name = str(cell.get('teacher_name') or '').strip()
        teacher = _key(teacher_name)
        class_subjects[cls][subject] += 1
        if teacher:
            teacher_subjects[(teacher, cls)][subject] += 1
            teacher_counts[teacher] += 1
            teacher_names.setdefault(teacher, teacher_name)
        if not subject or _key(subject_name).startswith('mon chua xac dinh'):
            unknown_subjects[f'{cls} · {subject_name or "Chưa rõ môn"}'] += 1

    class_rows = []
    for row in limits['class_subject']:
        subject = _subject_key(row['subject'])
        for cls in sorted(imported_classes):
            grade_match = CLASS_PATTERN.fullmatch(cls)
            if not grade_match or grade_match.group(1) != row['grade']:
                continue
            counts = class_subjects[cls]
            actual = _counts_for_subject(counts, subject)
            status, difference = _state(actual, row['min'], row['max'])
            if _ambiguous_missing(counts, subject, status):
                status, difference = 'unverified', None
            class_rows.append({'class_name': cls, 'subject': row['subject'], 'min': row['min'],
                               'max': row['max'], 'actual': actual, 'difference': difference, 'status': status})

    teacher_details: dict[str, list] = defaultdict(list)
    for row in limits['assignments']:
        cls = row['class_name']
        teacher = _key(row['teacher'])
        subject = _subject_key(row['subject'])
        if cls not in imported_classes:
            actual, status, difference = None, 'unverified', None
        else:
            counts = teacher_subjects[(teacher, cls)]
            actual = _counts_for_subject(counts, subject)
            status, difference = _state(actual, row['min'], row['max'])
            if _ambiguous_missing(class_subjects[cls], subject, status):
                status, difference = 'unverified', None
        teacher_details[teacher].append({'class_name': cls, 'subject': row['subject'],
                                         'min': row['min'], 'max': row['max'], 'actual': actual,
                                         'difference': difference, 'status': status})
        teacher_names.setdefault(teacher, row['teacher'])

    totals = {_key(row['teacher']): row for row in limits['teachers']}
    for key, row in totals.items():
        teacher_names.setdefault(key, row['teacher'])
    teacher_rows = []
    for key in sorted(teacher_names, key=lambda k: teacher_names[k].casefold()):
        target = totals.get(key)
        actual = teacher_counts[key]
        if target:
            status, difference = _state(actual, target['min'], target['max'])
        else:
            status, difference = 'not_set', None
        details = teacher_details.get(key, [])
        teacher_rows.append({'name': teacher_names[key], 'min': target['min'] if target else None,
                             'max': target['max'] if target else None, 'actual': actual,
                             'difference': difference, 'status': status, 'detail': details})

    class_mismatches = sum(row['status'] in {'missing', 'extra'} for row in class_rows)
    teacher_mismatches = sum(row['status'] in {'missing', 'extra'} for row in teacher_rows)
    assignment_mismatches = sum(row['status'] in {'missing', 'extra'}
                                for rows in teacher_details.values() for row in rows)
    return {
        'source': 'Định mức do người dùng nhập khi kiểm tra; không dùng bảng Word mẫu.',
        'classes': class_rows,
        'teachers': teacher_rows,
        'unclassified_subjects': [{'name': name, 'lessons': n} for name, n in sorted(unknown_subjects.items())],
        'summary': {
            'classes_checked': len(imported_classes),
            'class_subject_mismatches': class_mismatches,
            'teacher_mismatches': teacher_mismatches,
            'assignment_mismatches': assignment_mismatches,
            'class_rules': len(limits['class_subject']),
            'teacher_rules': len(limits['teachers']),
            'assignment_rules': len(limits['assignments']),
        },
        'notes': [
            'Dòng không nhập tối thiểu/tối đa không được kiểm tra.',
            'Phạm vi là các lớp và các tiết có trong file TKB đã import. Nếu file không đủ lớp hoặc đủ tuần, kết quả có thể thiếu.',
            'Môn học gộp KHTN, Lịch sử và Địa lí chưa tách phần sẽ được đánh dấu chưa xác minh khi cần.',
        ],
    }
