"""Bound Office archive expansion and worksheet geometry before loading workbooks."""
from __future__ import annotations

import io
from functools import wraps
import re
import threading
import zipfile
from xml.etree import ElementTree as ET

MAX_ARCHIVE_ENTRIES = 2048
MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 80 * 1024 * 1024
MAX_SHEETS = 20
MAX_ROWS = 5000
MAX_COLUMNS = 512
MAX_CELLS = 500_000
MAX_CELL_CHARS = 4000
MAX_TEXT_CHARS = 8_000_000
MAX_XML_NODES = 500_000
MAX_SHARED_STRINGS = 100_000
MAX_STYLE_RECORDS = 10_000
MAX_XML_NAME_CHARS = 32_000_000
_xml_tag = re.compile(rb'''<(?:[^"'>]|"[^"]*"|'[^']*')*>''')
_coordinate = re.compile(r"([A-Z]{1,3})([1-9][0-9]{0,6})")
_parser_slots = threading.BoundedSemaphore(2)


class UploadLimitError(ValueError):
    pass


def bounded_document_parser(error_type):
    """Small compressed uploads must not occupy every worker with heavy parsing."""
    def decorate(function):
        @wraps(function)
        def limited(*args, **kwargs):
            if not _parser_slots.acquire(blocking=False):
                raise error_type("Hệ thống đang đọc tệp khác. Vui lòng đợi một lúc rồi tải lại.")
            try:
                return function(*args, **kwargs)
            finally:
                _parser_slots.release()
        return limited
    return decorate


def _fail():
    raise UploadLimitError("Tệp vượt giới hạn đọc an toàn. Hãy giảm số sheet, hàng/cột hoặc nội dung rồi tải lại.")


def _check_archive(archive, max_bytes):
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES or len({entry.filename for entry in entries}) != len(entries):
        _fail()
    if sum(entry.file_size for entry in entries) > max_bytes:
        _fail()
    for entry in entries:
        if (entry.file_size < 0 or entry.file_size > MAX_ENTRY_BYTES
                or entry.flag_bits & 1 or len(entry.filename) > 256
                or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
            _fail()
    return entries


def ensure_archive_safe(content: bytes, *, max_bytes=MAX_ARCHIVE_BYTES):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            _check_archive(archive, max_bytes)
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise UploadLimitError("Tệp nén không hợp lệ hoặc đã bị hỏng.") from exc


def _cell_position(value):
    match = _coordinate.fullmatch(value)
    if not match:
        _fail()
    column = 0
    for letter in match[1]:
        column = column * 26 + ord(letter) - ord('A') + 1
    row = int(match[2])
    if row > MAX_ROWS or column > MAX_COLUMNS:
        _fail()
    return row, column


def ensure_workbook_safe(content: bytes, *, max_bytes=MAX_ARCHIVE_BYTES):
    """Inspect all XML, including shared strings/styles and actual sparse coordinates."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = _check_archive(archive, max_bytes)
            nodes = text_chars = actual_cells = shared_strings = grid_cells = worksheet_count = styles = name_chars = 0
            for entry in entries:
                raw = archive.read(entry)
                # OPC relationships can point to XML with any name/extension.
                # Sniff every bounded part, then classify by its XML root.
                declarations = raw.replace(b'\x00', b'').upper()
                if not declarations.lstrip(b'\xef\xbb\xbf\xff\xfe \t\r\n').startswith(b'<'):
                    continue
                if b'<!DOCTYPE' in declarations or b'<!ENTITY' in declarations:
                    _fail()
                # Bound namespace/attribute markup before a parser can expand
                # long namespace URIs into every element name.
                if any(len(tag[0]) > 16_384 for tag in _xml_tag.finditer(declarations)):
                    _fail()
                worksheet = strings = workbook = False
                depth = rows = row_cells = max_row = max_column = sheet_count = string_chars = 0
                for event, element in ET.iterparse(io.BytesIO(raw), events=('start', 'end')):
                    local = element.tag.rsplit('}', 1)[-1]
                    if event == 'start':
                        nodes += 1
                        depth += 1
                        if nodes > MAX_XML_NODES or depth > 64:
                            _fail()
                        name_chars += len(element.tag)
                        if len(element.tag) > 2048 or name_chars > MAX_XML_NAME_CHARS:
                            _fail()
                        for key, value in element.attrib.items():
                            name_chars += len(key)
                            if len(key) > 2048 or name_chars > MAX_XML_NAME_CHARS:
                                _fail()
                            if len(value) > MAX_CELL_CHARS:
                                _fail()
                            text_chars += len(value)
                        if text_chars > MAX_TEXT_CHARS:
                            _fail()
                        if local in {'xf', 'font', 'fill', 'border', 'numFmt'}:
                            styles += 1
                            if styles > MAX_STYLE_RECORDS:
                                _fail()
                        if depth == 1:
                            worksheet, strings, workbook = local == 'worksheet', local == 'sst', local == 'workbook'
                            if worksheet:
                                worksheet_count += 1
                                if worksheet_count > MAX_SHEETS:
                                    _fail()
                        if workbook and local == 'sheet':
                            sheet_count += 1
                            if sheet_count > MAX_SHEETS:
                                _fail()
                        if local == 'si':
                            strings = True
                            shared_strings += 1
                            string_chars = 0
                            if shared_strings > MAX_SHARED_STRINGS:
                                _fail()
                        # The loader dispatches SpreadsheetML row tags even if
                        # a malformed part uses a different root element.
                        if (not worksheet and local in {'dimension', 'row', 'c'}
                                and element.tag.startswith('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}')):
                            worksheet = True
                            worksheet_count += 1
                            if worksheet_count > MAX_SHEETS:
                                _fail()
                        if worksheet and local == 'dimension':
                            for point in element.get('ref', '').split(':'):
                                row, col = _cell_position(point)
                                max_row, max_column = max(max_row, row), max(max_column, col)
                        if worksheet and local == 'row':
                            rows += 1
                            row_cells = 0
                            row = int(element.get('r', rows))
                            if rows > MAX_ROWS or not 1 <= row <= MAX_ROWS:
                                _fail()
                            max_row = max(max_row, row)
                        if worksheet and local == 'c':
                            actual_cells += 1
                            row_cells += 1
                            if actual_cells > MAX_CELLS or row_cells > MAX_COLUMNS:
                                _fail()
                            if element.get('r'):
                                row, col = _cell_position(element.get('r'))
                                max_row, max_column = max(max_row, row), max(max_column, col)
                            else:
                                max_column = max(max_column, row_cells)
                    else:
                        if element.text:
                            length = len(element.text)
                            text_chars += length
                            if text_chars > MAX_TEXT_CHARS:
                                _fail()
                            if local in {'t', 'v'}:
                                if length > MAX_CELL_CHARS:
                                    _fail()
                                if strings:
                                    string_chars += length
                                    if string_chars > MAX_CELL_CHARS:
                                        _fail()
                        element.clear()
                        depth -= 1
                if worksheet:
                    grid_cells += max_row * max_column
                    if grid_cells > MAX_CELLS:
                        _fail()
    except UploadLimitError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, OSError, EOFError, ValueError, NotImplementedError) as exc:
        raise UploadLimitError("Cấu trúc tệp Excel không hợp lệ hoặc không thể đọc an toàn.") from exc


def bounded_rows(source, *, remaining_cells=MAX_CELLS, budget=None):
    if budget is None:
        budget = {"cells": remaining_cells, "chars": MAX_TEXT_CHARS}
    rows = []
    for index, row in enumerate(source, 1):
        if index > MAX_ROWS or len(row) > MAX_COLUMNS or len(row) > budget["cells"]:
            _fail()
        budget["cells"] -= len(row)
        clean = []
        for value in row:
            text = '' if value is None else str(int(value)) if isinstance(value, float) and value.is_integer() else str(value).strip()
            if len(text) > MAX_CELL_CHARS:
                _fail()
            budget["chars"] -= len(text)
            if budget["chars"] < 0:
                _fail()
            clean.append(text)
        rows.append(clean)
    return rows
