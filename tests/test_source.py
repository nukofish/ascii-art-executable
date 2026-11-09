"""tests/test_source.py - 成员 A 的单元测试与第一天交付 fixtures"""

import pytest
from codeart.source import (
    ErrorCode,
    PipelineError,
    Token,
    analyze_source,
    can_join,
)


# ==============================================================================
# 第一天冻结的交接 Mock 数据 (供 C/D/E 脱机使用)
# ==============================================================================

MOCK_MAX2_SOURCE = """int max2(int a, int b) {
    if (a > b) return a;
    return b;
}"""

MOCK_TOKENS = [
    Token(0, "KEYWORD", "int", 3, 1, 1),
    Token(1, "IDENTIFIER", "max2", 4, 1, 5),
    Token(2, "PUNCTUATION", "(", 1, 1, 9),
    Token(3, "KEYWORD", "int", 3, 1, 10),
    Token(4, "IDENTIFIER", "a", 1, 1, 14),
    Token(5, "PUNCTUATION", ",", 1, 1, 15),
    Token(6, "KEYWORD", "int", 3, 1, 17),
    Token(7, "IDENTIFIER", "b", 1, 1, 21),
    Token(8, "PUNCTUATION", ")", 1, 1, 22),
    Token(9, "PUNCTUATION", "{", 1, 1, 24),
    Token(10, "KEYWORD", "if", 2, 2, 5),
    Token(11, "PUNCTUATION", "(", 1, 2, 8),
    Token(12, "IDENTIFIER", "a", 1, 2, 9),
    Token(13, "PUNCTUATION", ">", 1, 2, 11),
    Token(14, "IDENTIFIER", "b", 1, 2, 13),
    Token(15, "PUNCTUATION", ")", 1, 2, 14),
    Token(16, "KEYWORD", "return", 6, 2, 16),
    Token(17, "IDENTIFIER", "a", 1, 2, 23),
    Token(18, "PUNCTUATION", ";", 1, 2, 24),
    Token(19, "KEYWORD", "return", 6, 3, 5),
    Token(20, "IDENTIFIER", "b", 1, 3, 12),
    Token(21, "PUNCTUATION", ";", 1, 3, 13),
    Token(22, "PUNCTUATION", "}", 1, 4, 1),
]


# ==============================================================================
# analyze_source 单元测试
# ==============================================================================

def test_analyze_valid_function():
    """测试合法的单函数能够完整解析并保留原始 token"""
    model = analyze_source(MOCK_MAX2_SOURCE)
    assert model.function_name == "max2"
    assert len(model.tokens) == len(MOCK_TOKENS)
    assert model.tokens[0].spelling == "int"
    assert model.tokens[1].spelling == "max2"


def test_reject_external_function():
    """拒绝引用未声明的外部函数: return g(x)"""
    code = "int f(int x) { return g(x); }"
    with pytest.raises(PipelineError) as exc_info:
        analyze_source(code)
    assert exc_info.value.diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert "外部函数" in exc_info.value.diagnostic.message or "未声明" in exc_info.value.diagnostic.message


def test_reject_external_variable():
    """拒绝引用外部全局对象: return ext"""
    code = "int f(void) { return ext; }"
    with pytest.raises(PipelineError) as exc_info:
        analyze_source(code)
    assert exc_info.value.diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE


def test_reject_macro_usage():
    """拒绝使用预定义宏 (即使没有 # 号)"""
    code = "int f(void) { return __LINE__; }"
    with pytest.raises(PipelineError) as exc_info:
        analyze_source(code)
    assert exc_info.value.diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert "__LINE__" in exc_info.value.diagnostic.message


def test_reject_non_ascii():
    """拒绝非 ASCII 字符并准确定位行列"""
    code = "int f(void) { int a = 1; /* 中文注释不影响，但代码字符影响 */ return a; }"
    model = analyze_source(code)
    assert len(model.original_comments) == 1

    # 变量名为非 ASCII 时拒绝
    invalid_code = "int f(void) { int 变量 = 1; return 变量; }"
    with pytest.raises(PipelineError) as exc_info:
        analyze_source(invalid_code)
    assert exc_info.value.diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE


def test_allow_self_recursion():
    """允许单函数内部的自身递归调用"""
    code = "int gcd(int a, int b) { return b == 0 ? a : gcd(b, a % b); }"
    model = analyze_source(code)
    assert model.function_name == "gcd"


# ==============================================================================
# can_join 单元测试 (涵盖正例与全部边界反例)
# ==============================================================================

def test_can_join_allowed_cases():
    """测试常规允许紧贴的场景: f(x), a[0], i++"""
    tok_f = Token(0, "IDENTIFIER", "f", 1, 1, 1)
    tok_lparen = Token(1, "PUNCTUATION", "(", 1, 1, 2)
    tok_x = Token(2, "IDENTIFIER", "x", 1, 1, 3)
    tok_rparen = Token(3, "PUNCTUATION", ")", 1, 1, 4)

    assert can_join([tok_f], tok_lparen) is True
    assert can_join([tok_f, tok_lparen], tok_x) is True
    assert can_join([tok_f, tok_lparen, tok_x], tok_rparen) is True

    # 自增符号
    tok_i = Token(0, "IDENTIFIER", "i", 1, 1, 1)
    tok_plusplus = Token(1, "PUNCTUATION", "++", 2, 1, 2)
    assert can_join([tok_i], tok_plusplus) is True


def test_can_join_rejected_cases():
    """测试必须拦截的分隔场景"""
    # 1. 独立加号合并为 ++: '+' 与 '+'
    tok_plus1 = Token(0, "PUNCTUATION", "+", 1, 1, 1)
    tok_plus2 = Token(1, "PUNCTUATION", "+", 1, 1, 2)
    assert can_join([tok_plus1], tok_plus2) is False

    # 2. 注释起始符: '/' 与 '*'
    tok_slash = Token(0, "PUNCTUATION", "/", 1, 1, 1)
    tok_star = Token(1, "PUNCTUATION", "*", 1, 1, 2)
    assert can_join([tok_slash], tok_star) is False

    # 3. 三个连续点合并为省略号 '...'
    tok_dot1 = Token(0, "PUNCTUATION", ".", 1, 1, 1)
    tok_dot2 = Token(1, "PUNCTUATION", ".", 1, 1, 2)
    tok_dot3 = Token(2, "PUNCTUATION", ".", 1, 1, 3)
    # 虽然两个点在 C 中可能非终结符，但三个连续点会变成 VARARGS '...'
    assert can_join([tok_dot1, tok_dot2], tok_dot3) is False

    # 4. 标识符紧接标识符 (int a -> inta)
    tok_int = Token(0, "KEYWORD", "int", 3, 1, 1)
    tok_a = Token(1, "IDENTIFIER", "a", 1, 1, 4)
    assert can_join([tok_int], tok_a) is False