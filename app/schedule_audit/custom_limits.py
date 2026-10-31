"""Compare imported lessons with user-entered exact quotas, not sample Word tables."""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
import re
import unicodedata
from typing import Any

CLASS_PATTERN = re.compile(r'^\s*(1[0-2]|[1-9])\s*([a-zA-Z])\s*0*(\d{1,2})\s*$', re.I)
SECTIONS = ('class_subject', 'assignments')


def _key(text: Any) -> str:
    value = unicodedata.normalize('NFKD', str(text or '').casefold().replace('đ', 'd'))
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', value).strip()


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
    """Preserve subject components: KHTN and KHTN(S) are independent."""
    label = unicodedata.normalize('NFC', str(value or '')).strip().casefold()
    label = re.sub(r'\s+', ' ', label)
    label = re.sub(r'\s*\(\s*', '(', label)
    return re.sub(r'\s*\)\s*', ')', label)


def _periods(value: Any) -> float | None:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('Số tiết/tuần phải là số không âm.')
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('Số tiết/tuần phải là số không âm.') from None
    if not isfinite(number) or number < 0 or number > 1000:
        raise ValueError('Số tiết/tuần phải nằm trong khoảng từ 0 đến 1000.')
    return number


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
            if 'min' in item or 'max' in item:
                raise ValueError('Chỉ nhập một mức Tiết/tuần, không dùng ngưỡng tối thiểu/tối đa.')
            periods = _periods(item.get('periods'))
            if periods is None:
                continue  # Blank values are deliberately not checked.
            row: dict[str, Any] = {'periods': periods}
            if section == 'class_subject':
                grade = str(item.get('grade', '')).strip()
                if not grade.isdigit() or not 1 <= int(grade) <= 12:
                    raise ValueError('Khối học phải từ 1 đến 12.')
                row.update(grade=str(int(grade)), subject=_text(item.get('subject'), 'Tên môn'))
                key = (row['grade'], _subject_key(row['subject']))
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


def _state(actual: int, periods: float) -> tuple[str, float]:
    difference = round(actual - periods, 3)
    if difference < 0:
        return 'missing', difference
    if difference > 0:
        return 'extra', difference
    return 'ok', 0


def check_custom_weekly_workload(viewer: dict[str, Any], raw_limits: Any) -> dict[str, Any]:
    limits = validate_limits(raw_limits)
    imported_classes = {_class_name(row.get('name')) for row in viewer.get('classes', [])}
    imported_classes.discard('')
    class_subjects: dict[str, Counter] = defaultdict(Counter)
    teacher_subjects: dict[tuple[str, str], Counter] = defaultdict(Counter)
    teacher_counts: Counter = Counter()
    teacher_names: dict[str, str] = {}
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
            match = CLASS_PATTERN.fullmatch(cls)
            if not match or match.group(1) != row['grade']:
                continue
            actual = class_subjects[cls][subject]
            status, difference = _state(actual, row['periods'])
            class_rows.append({'class_name': cls, 'subject': row['subject'],
                               'periods': row['periods'], 'actual': actual,
                               'difference': difference, 'status': status})

    teacher_details: dict[str, list] = defaultdict(list)
    teacher_targets: Counter = Counter()
    configured: set[tuple[str, str, str]] = set()
    unverified_teachers: set[str] = set()
    for row in limits['assignments']:
        cls = row['class_name']
        teacher = _key(row['teacher'])
        subject = _subject_key(row['subject'])
        configured.add((teacher, cls, subject))
        teacher_targets[teacher] += row['periods']
        if cls not in imported_classes:
            actual, status, difference = None, 'unverified', None
            unverified_teachers.add(teacher)
        else:
            actual = teacher_subjects[(teacher, cls)][subject]
            status, difference = _state(actual, row['periods'])
        teacher_details[teacher].append({'class_name': cls, 'subject': row['subject'],
                                         'periods': row['periods'], 'actual': actual,
                                         'difference': difference, 'status': status})
        teacher_names.setdefault(teacher, row['teacher'])

    # A blank assignment is intentionally not a quota, but makes the teacher's
    # aggregate inconclusive. Otherwise the partial sum could flag false surplus.
    if isinstance(raw_limits, dict):
        for row in raw_limits.get('assignments', []):
            if not isinstance(row, dict) or row.get('periods') not in ('', None):
                continue
            teacher = _key(row.get('teacher'))
            if teacher:
                unverified_teachers.add(teacher)
                teacher_names.setdefault(teacher, str(row.get('teacher')))

    unconfigured_counts: Counter = Counter()
    for (teacher, cls), subjects in teacher_subjects.items():
        for subject, amount in subjects.items():
            if (teacher, cls, subject) not in configured:
                unconfigured_counts[teacher] += amount

    teacher_rows = []
    for key in sorted(teacher_names, key=lambda item: teacher_names[item].casefold()):
        target = round(teacher_targets[key], 3) if key in teacher_targets else None
        actual = teacher_counts[key]
        missing_rules = unconfigured_counts[key]
        if target is None:
            status, difference = 'not_set', None
        elif missing_rules or key in unverified_teachers:
            status, difference = 'unverified', None
        else:
            status, difference = _state(actual, target)
        teacher_rows.append({'name': teacher_names[key], 'periods': target,
                             'actual': actual, 'difference': difference, 'status': status,
                             'unconfigured_lessons': missing_rules,
                             'detail': teacher_details.get(key, [])})

    class_mismatches = sum(row['status'] in {'missing', 'extra'} for row in class_rows)
    teacher_mismatches = sum(row['status'] in {'missing', 'extra'} for row in teacher_rows)
    assignment_mismatches = sum(row['status'] in {'missing', 'extra'}
                                for details in teacher_details.values() for row in details)
    return {
        'source': 'Định mức số tiết do người dùng nhập; không dùng bảng Word mẫu.',
        'classes': class_rows,
        'teachers': teacher_rows,
        'unclassified_subjects': [{'name': name, 'lessons': n} for name, n in sorted(unknown_subjects.items())],
        'summary': {
            'classes_checked': len(imported_classes),
            'class_subject_mismatches': class_mismatches,
            'teacher_mismatches': teacher_mismatches,
            'assignment_mismatches': assignment_mismatches,
            'class_rules': len(limits['class_subject']),
            'assignment_rules': len(limits['assignments']),
        },
        'notes': [
            'Mỗi ô định mức chỉ có một số tiết bắt buộc; để trống là chưa khai báo.',
            'Tổng số tiết mỗi giáo viên được tự cộng từ các phân công lớp/môn; không nhập tổng riêng.',
            'Nếu còn phân công chưa nhập hoặc có tiết chưa được gán định mức, tổng giáo viên là Chưa xác minh.',
            'Chỉ kiểm tra những lớp có trong file TKB đã import.',
            'KHTN và KHTN(S) (tương tự LSĐL và LSĐL(Đ)) là các nhãn môn độc lập.',
        ],
    }
