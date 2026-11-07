"""Compatibility fixes for the final XLSX bytes sent to spreadsheet readers."""
from __future__ import annotations

from io import BytesIO
from xml.dom import Node, minidom
from zipfile import ZipFile


_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_BORDER_EDGES = frozenset({
    "left", "right", "top", "bottom", "diagonal", "vertical", "horizontal",
    "start", "end",
})


def _elements(parent, name: str | None = None):
    return [
        child for child in parent.childNodes
        if child.nodeType == Node.ELEMENT_NODE
        and child.namespaceURI == _SPREADSHEET_NS
        and (name is None or child.localName == name)
    ]


def _apply_border_flags(styles_xml: bytes) -> bytes:
    # Preserve namespace prefixes and all existing XML nodes/attributes. In
    # particular, never recreate styles or renumber border/cell style IDs.
    with minidom.parseString(styles_xml) as document:
        root = document.documentElement
        if root.namespaceURI != _SPREADSHEET_NS or root.localName != "styleSheet":
            raise ValueError("Unrecognized Excel stylesheet namespace or root")
        cell_xfs = _elements(root, "cellXfs")
        border_tables = _elements(root, "borders")
        if len(cell_xfs) != 1 or len(border_tables) != 1:
            raise ValueError("Excel stylesheet must contain cellXfs and borders")
        borders = _elements(border_tables[0], "border")
        cell_styles = _elements(cell_xfs[0], "xf")
        if not borders or not cell_styles:
            raise ValueError("Excel stylesheet must contain border and cell style records")
        styled_borders = {
            index for index, border in enumerate(borders)
            if any(
                edge.localName in _BORDER_EDGES
                and edge.getAttribute("style") not in ("", "none")
                for edge in _elements(border)
            )
        }
        changed = False
        for xf in cell_styles:
            border_id = int(xf.getAttribute("borderId") or "0")
            if not 0 <= border_id < len(borders):
                raise ValueError("Excel cell style references a missing border")
            if border_id > 0 and border_id in styled_borders:
                if xf.getAttribute("applyBorder") != "1":
                    xf.setAttribute("applyBorder", "1")
                    changed = True
        return document.toxml(encoding="utf-8") if changed else styles_xml


def ensure_excel_borders_applied(xlsx_bytes: bytes) -> bytes:
    """Explicitly enable existing borders without changing workbook contents.

    openpyxl 3.1.5 omits applyBorder when serializing cellXfs. Some Excel
    installations need that flag to display the referenced borders. Patch the
    final archive instead of modifying openpyxl internals or rebuilding cells.
    Invalid archives/styles raise before the download response is created.
    """
    with ZipFile(BytesIO(xlsx_bytes)) as source:
        if source.namelist().count("xl/styles.xml") != 1:
            raise ValueError("Excel workbook must contain one xl/styles.xml")
        original_styles = source.read("xl/styles.xml")
        compatible_styles = _apply_border_flags(original_styles)
        if compatible_styles == original_styles:
            return xlsx_bytes
        output = BytesIO()
        with ZipFile(output, "w") as target:
            target.comment = source.comment
            for entry in source.infolist():
                payload = (compatible_styles if entry.filename == "xl/styles.xml"
                           else source.read(entry))
                target.writestr(entry, payload)
        return output.getvalue()
