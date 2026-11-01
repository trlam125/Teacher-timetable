"""Canonical timetable subject labels used by import, quotas and project setup.

Identifiers distinguish each integrated subject component; generic KHTN/LSĐL
are deliberately *not* treated as a component. Unknown subjects survive.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

STANDARD_SUBJECTS = (
    ('nvan', 'N. Văn'),
    ('toan', 'Toán'),
    ('tanh', 'T.Anh'),
    ('gdcd', 'GDCD'),
    ('lsdls', 'LSĐL (S)'),
    ('lsdld', 'LSĐL (Đ)'),
    ('khtnl', 'KHTN (L)'),
    ('khtnh', 'KHTN (H)'),
    ('khtns', 'KHTN (S)'),
    ('congnghe', 'C.Nghệ'),
    ('tin', 'Tin'),
    ('gdtc', 'GDTC'),
    ('ntnhac', 'NT (Nhạc)'),
    ('ntmythuat', 'NT (MT)'),
    ('hdtnhn', 'HĐTNHN'),
    ('gddp', 'GDĐP'),
)
CANONICAL_BY_CODE = dict(STANDARD_SUBJECTS)
SUBJECT_RANK = {code: pos for pos, (code, _) in enumerate(STANDARD_SUBJECTS)}
_SUBJECT_SYNONYMS = {
    'nvan': ('nvan', 'van', 'nguvan'),
    'toan': ('toan',),
    'tanh': ('tanh', 'anh', 'tienganh', 'ngoaingutanh'),
    'gdcd': ('gdcd', 'giaoduccongdan'),
    'lsdls': ('lsdls', 'lsdlsu', 'lsdllichsu', 'su', 'lichsu', 'lichsuvadialilichsu', 'lichsuvadialylichsu', 'lichsuvadialysu'),
    'lsdld': ('lsdld', 'lsdldia', 'lsdldiali', 'lsdldialy', 'dia', 'diali', 'dialy', 'lichsuvadialidia', 'lichsuvadialidiali', 'lichsuvadialydia', 'lichsuvadialydiali'),
    'khtnl': ('khtnl', 'khtnli', 'khtnly', 'khtnvatli', 'khtnvatly', 'li', 'ly', 'vatli', 'vatly', 'khoahoctunhienvatli', 'khoahoctunhienvatly'),
    'khtnh': ('khtnh', 'khtnhoa', 'khtnhoahoc', 'hoa', 'hoahoc', 'khoahoctunhienhoa', 'khoahoctunhienhoahoc'),
    'khtns': ('khtns', 'khtnsinh', 'khtnsinhhoc', 'sinh', 'sinhhoc', 'khoahoctunhiensinh', 'khoahoctunhiensinhhoc'),
    'congnghe': ('congnghe', 'cnghe', 'cn'),
    'tin': ('tin', 'tinhoc'),
    'gdtc': ('gdtc', 'giaoducthechat', 'theduc'),
    'ntnhac': ('ntnhac', 'amnhac', 'nghethuatamnhac', 'gdnthamnhac'),
    'ntmythuat': ('ntmt', 'ntmythuat', 'ntmithuat', 'mithuat', 'mythuat', 'nghethuatmithuat', 'nghethuatmythuat'),
    'hdtnhn': ('hdtnhn', 'hdtnhuongnghiep', 'hoatdongtrainghiemhuongnghiep'),
    'gddp': ('gddp', 'giaoducdiaphuong'),
    # Whole subjects stay different from their specific components.
    'khtn': ('khtn', 'khoahoctunhien'),
    'lsdl': ('lsdl', 'lichsuvadiali', 'lichsuvadialy'),
}
ALIASES = {alias: code for code, aliases in _SUBJECT_SYNONYMS.items() for alias in aliases}


def subject_key(value: Any) -> str:
    text = unicodedata.normalize('NFC', str(value or '')).strip().casefold()
    folded = unicodedata.normalize('NFKD', text.replace('đ', 'd'))
    ascii_text = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    token = re.sub(r'[^a-z0-9]+', '', ascii_text)
    return ALIASES.get(token, token or text)


def canonical_subject_name(value: Any) -> str:
    label = unicodedata.normalize('NFC', str(value or '')).strip()
    return CANONICAL_BY_CODE.get(subject_key(label), label)


def subject_sort_key(value: Any) -> tuple[int, str]:
    key = subject_key(value)
    return SUBJECT_RANK.get(key, len(STANDARD_SUBJECTS)), canonical_subject_name(value).casefold()


def canonical_subject_short_name(short_name: Any, full_name: Any) -> str:
    """Normalize a short alias only if it identifies the same school subject."""
    short = unicodedata.normalize('NFC', str(short_name or '')).strip()
    return canonical_subject_name(short) if short and subject_key(short) == subject_key(full_name) else short
