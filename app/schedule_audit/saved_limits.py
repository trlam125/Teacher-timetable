"""Validate and store per-account exact weekly quotas, without redundant teacher totals."""
from __future__ import annotations

from math import isfinite
from typing import Any
from .custom_limits import SECTIONS, validate_limits


FIELDS = {
    'class_subject': ('grade', 'subject'),
    'assignments': ('teacher', 'class_name', 'subject'),
}


def clean_limit_draft(source: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(source, dict):
        raise ValueError('Bảng số tiết không đúng định dạng.')
    result = {section: [] for section in SECTIONS}
    for section, names in FIELDS.items():
        rows = source.get(section, [])
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError(f'Bảng {section} có quá nhiều dòng.')
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError('Dòng số tiết không hợp lệ.')
            if 'min' in item or 'max' in item:
                raise ValueError('Chỉ nhập một mức Tiết/tuần, không dùng tối thiểu/tối đa.')
            row = {}
            for name in names:
                value = item.get(name, '')
                if not isinstance(value, (str, int)) or isinstance(value, bool):
                    raise ValueError('Tên môn, giáo viên hoặc lớp không hợp lệ.')
                value = str(value).strip()
                if len(value) > 120:
                    raise ValueError('Tên môn, giáo viên hoặc lớp quá dài.')
                row[name] = value
            raw = item.get('periods', '')
            if raw is None or raw == '':
                row['periods'] = ''
            else:
                try:
                    number = float(raw)
                except (ValueError, TypeError, OverflowError):
                    raise ValueError('Số tiết phải là một số hợp lệ.') from None
                if isinstance(raw, bool) or not isfinite(number) or number < 0 or number > 1000:
                    raise ValueError('Số tiết phải trong khoảng 0–1000.')
                row['periods'] = number
            result[section].append(row)
    validate_limits(result)
    return result


def migrate_saved_draft(source: Any) -> dict[str, list[dict[str, Any]]]:
    """One-time compatibility for previously saved min/max rows; no range checking.

    An exact old pair survives. Unequal bounds cannot represent a single required
    value and are left blank. The former independent 'teachers' section is dropped.
    """
    if not isinstance(source, dict):
        return clean_limit_draft({})
    converted = {section: [] for section in SECTIONS}
    for section in SECTIONS:
        for original in source.get(section, []):
            if not isinstance(original, dict):
                continue
            row = {name: original.get(name, '') for name in FIELDS[section]}
            if 'periods' in original:
                row['periods'] = original['periods']
            else:
                lower, upper = original.get('min'), original.get('max')
                row['periods'] = lower if lower is not None and lower != '' and str(lower) == str(upper) else ''
            converted[section].append(row)
    return clean_limit_draft(converted)


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
