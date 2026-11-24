"""Source interpretation is a suggestion. Exact quotations are checked server-side."""
from .analysis import source_signature
from .provider import StudioError


def inspection_evidence(profile):
    """Bounded, literal word-boundary windows, independent of prior decisions."""
    evidence = []
    for source in profile.get('sources', []):
        rest = source['text'].strip()
        while rest:
            end = min(480, len(rest))
            if end < len(rest):
                boundary = rest.rfind(' ', 0, end)
                if boundary > 0:
                    end = boundary
            quote = rest[:end].strip()
            rest = rest[end:].strip()
            if len(quote) >= 8:
                evidence.append({'source_id': source['id'], 'quote': quote})
    return evidence


def checked_intelligence(result, profile):
    sources = {source['id']: source for source in profile.get('sources', [])}
    quotes = [*result.metadata, *(quote for conflict in result.conflicts for quote in conflict.evidence)]
    if any(quote.source_id not in sources or quote.quote not in sources[quote.source_id]['text'] for quote in quotes):
        raise StudioError('AI_SOURCE_ERROR', 'AI trích dẫn không khớp đoạn đã chọn; không lưu phân tích này.', 422)
    limits = {'subject': 80, 'grade': 40, 'lesson_title': 240, 'objectives': 300}
    for suggestion in result.metadata:
        invalid = len(suggestion.value) > limits.get(suggestion.field, 300)
        if suggestion.field == 'duration_minutes':
            invalid = not suggestion.value.isascii() or not suggestion.value.isdigit() or not 10 <= int(suggestion.value) <= 240
        if invalid:
            raise StudioError('AI_CONSTRAINT_ERROR', 'Gợi ý metadata vượt giới hạn hoặc thời lượng không hợp lệ. Thông tin đã nhập được giữ.', 422)
    for conflict in result.conflicts:
        if len({(item.source_id, item.quote) for item in conflict.evidence}) != len(conflict.evidence):
            raise StudioError('AI_SOURCE_ERROR', 'Phân tích lặp cùng chứng cứ; hãy thu hẹp nguồn hoặc rà soát thủ công.', 422)
    return {**result.model_dump(), 'signature': source_signature(profile)}
