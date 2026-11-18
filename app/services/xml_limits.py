"""Inspect untrusted XML without constructing a tree or resolving entities."""
from __future__ import annotations

from xml.parsers import expat

from app.services.upload_limits import UploadLimitError

MAX_XML_NODES = 100_000
MAX_XML_DEPTH = 64
MAX_XML_ATTRIBUTES = 100_000
MAX_XML_ATTRIBUTES_PER_NODE = 128
MAX_XML_NAME_LENGTH = 2048
MAX_XML_NAME_CHARS = 8_000_000
MAX_XML_TEXT_CHARS = 8_000_000
MAX_XML_ATTRIBUTE_CHARS = 64_000
MAX_XML_NAMESPACE_CHARS = 1024
MAX_XML_NAMESPACE_PREFIX_CHARS = 128
MAX_XML_NAMESPACE_DECLARATIONS = 4096


def ensure_xml_safe(content: bytes) -> None:
    """Bound tree size and namespace expansion before ElementTree sees the XML."""
    nodes = depth = attributes = name_chars = text_chars = namespaces = 0
    parser = expat.ParserCreate(namespace_separator="}")

    def reject(*_args):
        raise UploadLimitError(
            "Cấu trúc XML trong tệp Word vượt giới hạn đọc an toàn hoặc chứa DTD/entity không được phép."
        )

    def start_namespace(prefix, uri):
        nonlocal namespaces, text_chars
        namespaces += 1
        prefix, uri = prefix or "", uri or ""
        text_chars += len(prefix) + len(uri)
        # This callback runs before Expat expands the URI into element names.
        if (len(prefix) > MAX_XML_NAMESPACE_PREFIX_CHARS
                or len(uri) > MAX_XML_NAMESPACE_CHARS
                or namespaces > MAX_XML_NAMESPACE_DECLARATIONS
                or text_chars > MAX_XML_TEXT_CHARS):
            reject()

    def start_element(name, attrs):
        nonlocal nodes, depth, attributes, name_chars, text_chars
        nodes += 1
        depth += 1
        attributes += len(attrs)
        if (nodes > MAX_XML_NODES or depth > MAX_XML_DEPTH
                or attributes > MAX_XML_ATTRIBUTES
                or len(attrs) > MAX_XML_ATTRIBUTES_PER_NODE):
            reject()
        # Include the braces ElementTree adds to expanded namespace names.
        for item in (name, *attrs):
            length = len(item) + (1 if "}" in item else 0)
            name_chars += length
            if length > MAX_XML_NAME_LENGTH or name_chars > MAX_XML_NAME_CHARS:
                reject()
        for value in attrs.values():
            text_chars += len(value)
            if len(value) > MAX_XML_ATTRIBUTE_CHARS or text_chars > MAX_XML_TEXT_CHARS:
                reject()

    def end_element(_name):
        nonlocal depth
        depth -= 1

    def character_data(value):
        nonlocal text_chars
        text_chars += len(value)
        if text_chars > MAX_XML_TEXT_CHARS:
            reject()

    parser.StartNamespaceDeclHandler = start_namespace
    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.CharacterDataHandler = character_data
    parser.StartDoctypeDeclHandler = reject
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        for offset in range(0, len(content), 64 * 1024):
            parser.Parse(content[offset:offset + 64 * 1024], False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise UploadLimitError("Cấu trúc XML trong tệp Word không hợp lệ.") from exc
