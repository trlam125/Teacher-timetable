"""Validation and normalization for user-owned saved timetable quotas.

Stored drafts retain blank rows, unlike validate_limits() which only returns
active thresholds for checking. All changes are explicit per-account saves.
"""
from __future__ import annotations

from math import isfinite
from typing import Any
from .custom_limits import SECTIONS, validate_limits


def clean_limit_draft(source: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(source, dict):
        raise ValueError('Bảng ngưỡng không đúng định dạng.')
    result = {section: [] for section in SECTIONS}
    fields = {
        'class_subject': ('grade', 'subject'),
        'teachers': ('teacher',),
        'assignments': ('teacher', 'class_name', 'subject'),
    }
    for section, names in fields.items():
        rows = source.get(section, [])
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError(f'Bảng {section} có quá nhiều dòng.')
        for source_row in rows:
            if not isinstance(source_row, dict):
                raise ValueError('Dòng ngưỡng không hợp lệ.')
            row = {}
            for name in names:
                value = source_row.get(name, '')
                if not isinstance(value, (str, int)) or isinstance(value, bool):
                    raise ValueError('Tên môn, giáo viên hoặc lớp không hợp lệ.')
                value = str(value).strip()
                if len(value) > 120:
                    raise ValueError('Tên môn, giáo viên hoặc lớp quá dài.')
                row[name] = value
            for name in ('min', 'max'):
                value = source_row.get(name, '')
                if value is None or value == '':
                    row[name] = ''
                    continue
                try:
                    number = float(value)
                except (ValueError, TypeError, OverflowError):
                    raise ValueError('Số tiết phải là một số hợp lệ.') from None
                if isinstance(value, bool) or not isfinite(number) or number < 0 or number > 1000:
                    raise ValueError('Số tiết phải trong khoảng 0–1000.')
                row[name] = number
            if row['min'] != '' and row['max'] != '' and row['min'] > row['max']:
                raise ValueError('Mức tối thiểu không thể cao hơn mức tối đa.')
            result[section].append(row)
    # Verify all configured rows, their class/grade identifiers and duplicates.
    validate_limits(result)
    return result


def clean_import_catalog(source: Any) -> dict[str, list[str]]:
    if not isinstance(source, dict):
        raise ValueError('Danh sách của TKB chưa hợp lệ.')
    clean = {}
    for key in ('classes', 'subjects', 'teachers'):
        values = source.get(key, [])
        if not isinstance(values, list) or len(values) > 1000:
            raise ValueError('Danh sách lớp, môn hoặc giáo viên quá dài.')
        names = []
        seen = set()
        for value in values:
            if not isinstance(value, str) or not 0 < len(value.strip()) <= 120:
                raise ValueError('Một tên lớp, môn hoặc giáo viên không hợp lệ.')
            name = value.strip()
            if name.casefold() not in seen:
                seen.add(name.casefold())
                names.append(name)
        clean[key] = names
    return clean
