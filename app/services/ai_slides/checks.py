"""Small deterministic checks, deliberately narrower than factual verification."""
import ast
from fractions import Fraction
import re
import unicodedata


NUMBER = r'-?\d+(?:[.,]\d+)?'
EQUALITY = re.compile(r'(?<![\w.,])([\d.,() +−\-*/×÷·²³^%]{3,90})\s*=\s*(' + NUMBER + r')(?!\d|[.,]\d)')
PERCENT = re.compile(r'(' + NUMBER + r')\s*%\s+của\s+(' + NUMBER + r')\s+(?:là|bằng|=)\s*(' + NUMBER + r')', re.I)
COUNTEREXAMPLE = re.compile(r'đúng hay sai|đúng\s*/\s*sai|tìm lỗi|phát hiện lỗi|sai ở đâu|sai lầm|không đúng|là sai|sai:', re.I)
QUANTITY = re.compile(r'^(' + NUMBER + r')(?:\s*/\s*(' + NUMBER + r'))?\s*([a-zA-ZÀ-ỹΩ°²³/%]*)$')


def _number(value):
    # Three-digit separators are ambiguous in Vietnamese prose (1.000/1,000).
    if re.search(r'[.,]\d{3}$', value) or len(value) > 28:
        raise ValueError('Ambiguous or oversized number')
    return Fraction(value.replace(',', '.'))


def _expression(value):
    value = value.strip().replace('×', '*').replace('÷', '/').replace('−', '-').replace(',', '.')
    tree = ast.parse(value, mode='eval')
    if len(list(ast.walk(tree))) > 45:
        raise ValueError('Expression too complex')

    def read(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return _number(ast.get_source_segment(value, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = read(node.operand)
            return -result if isinstance(node.op, ast.USub) else result
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = read(node.left), read(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            return left / right
        raise ValueError('Unsupported expression')
    return read(tree.body)


def _inconsistent(expected, declared, literal):
    # Allow rounding to the displayed decimal precision. Integer equalities
    # with a non-integer result are too ambiguous to judge without context.
    digits = len(re.split('[.,]', literal)[1]) if re.search('[.,]', literal) else 0
    if not digits and expected.denominator != 1:
        return False
    tolerance = Fraction(1, 2 * 10 ** digits) if digits else Fraction(0)
    return abs(expected - declared) > tolerance


def arithmetic_mismatch(text):
    if COUNTEREXAMPLE.search(text):
        return False
    for match in EQUALITY.finditer(text):
        expression, literal = match.groups()
        # Never evaluate a numeric suffix cut from algebra, or the first
        # number of a longer right-hand expression such as 12+8=15+m.
        before, after = text[:match.start()].rstrip(), text[match.end():].lstrip()
        if (expression.lstrip().startswith(('+', '-', '−', '*', '/', '×', '÷', '·', '^', '%'))
                and before and before[-1] not in ':=→([{;'):
            continue
        if after.startswith(('+', '-', '−', '*', '/', '×', '÷', '·', '^', '%', '²', '³')):
            continue
        if not re.search(r'[+−*/×÷]|\d\s*-\s*\d', expression):
            continue
        try:
            expected, declared = _expression(expression), _number(literal)
            if _inconsistent(expected, declared, literal):
                return True
        except ZeroDivisionError:
            return True
        except (ValueError, SyntaxError, TypeError, OverflowError):
            continue
    for match in PERCENT.finditer(text):
        if text[match.end():].lstrip().startswith(('+', '-', '−', '*', '/', '×', '÷', '·', '^', '%')):
            continue
        try:
            percent, base, literal = match.groups()
            if _inconsistent(_number(percent) * _number(base) / 100, _number(literal), literal):
                return True
        except (ValueError, ZeroDivisionError):
            continue
    return False


def _option_key(value):
    value = unicodedata.normalize('NFC', value).strip().rstrip('.;')
    match = QUANTITY.fullmatch(value)
    if match:
        try:
            numerator, denominator, unit = match.groups()
            quantity = _number(numerator) / (_number(denominator) if denominator else 1)
            return ('quantity', quantity, unit)
        except (ValueError, ZeroDivisionError):
            pass
    # Case matters for SI prefixes, variable names and chemical symbols.
    return ('text', re.sub(r'\s+', '', value))


def slide_findings(slide):
    issues = []
    # Distractors and questions can intentionally contain false equalities.
    assertions = [*slide.get('bullets', []), slide.get('speaker_notes', ''), slide.get('explanation', '')]
    if any(arithmetic_mismatch(text) for text in assertions):
        issues.append({'code': 'ARITHMETIC_MISMATCH', 'severity': 'warning',
                       'message': 'Có phép tính số hoặc phần trăm không khớp kết quả. Kiểm tra biểu thức và cách làm tròn trước khi dạy; chưa kiểm tra đại số hay đổi đơn vị.'})
    if slide.get('kind') == 'quiz':
        keys = [_option_key(option) for option in slide.get('options', [])]
        if len(set(keys)) < len(keys):
            issues.append({'code': 'QUIZ_EQUIVALENT_OPTIONS', 'severity': 'warning',
                           'message': 'Có phương án quiz trùng hoặc tương đương về giá trị và đơn vị. Sửa để chỉ một phương án được chấm đúng.'})
    return issues
