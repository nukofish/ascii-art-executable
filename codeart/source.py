"""codeart/source.py - 成员 A: 代码分析与词法边界实现"""

from __future__ import annotations
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import clang.cindex
from clang.cindex import CursorKind, Index, TokenKind, TranslationUnit


# ==============================================================================
# 契约与数据模型 (对齐 contracts.py)
# ==============================================================================

class ErrorCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"


@dataclass
class Diagnostic:
    code: ErrorCode
    stage: str = "analysis"
    message: str = ""
    line: Optional[int] = None
    column: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)


class PipelineError(Exception):
    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class Token:
    index: int
    kind: str
    spelling: str
    width: int
    source_line: int
    source_column: int


@dataclass
class SourceModel:
    original_source: str
    normalized_source: str
    tokens: List[Token]
    profile: str
    function_name: str
    signature: str
    original_comments: List[Tuple[int, int, str]]  # (line, col, spelling)


@dataclass
class RunContext:
    deadline: float = float("inf")
    cancel_event: Any = None

    def check(self):
        if self.cancel_event and self.cancel_event.is_set():
            raise TimeoutError("Task cancelled")
        if time.monotonic() > self.deadline:
            raise TimeoutError("Analysis timed out")


# 常见需严格禁用的内置编译器宏名
FORBIDDEN_MACRO_NAMES: Set[str] = {
    "__LINE__", "__FILE__", "__DATE__", "__TIME__", "__STDC__",
    "__STDC_VERSION__", "__STDC_HOSTED__", "__COUNTER__",
    "__func__", "__FUNCTION__", "__PRETTY_FUNCTION__"
}


# ==============================================================================
# 字符与源码有效性初筛
# ==============================================================================

def _validate_raw_characters(source: str) -> str:
    """
    检查字符集：仅接受可打印 ASCII (0x20-0x7E)、规定换行 (CR/LF) 与 token 外 tab。
    拒绝非 ASCII、实际控制字符、续行符与三字符组。将 CRLF 规整为 LF。
    """
    lines = source.splitlines(keepends=True)
    curr_line = 1
    for line in lines:
        for col, ch in enumerate(line, start=1):
            code = ord(ch)
            if ch in ("\r", "\n", "\t"):
                continue
            if code < 0x20 or code > 0x7E:
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.UNSUPPORTED_SOURCE,
                        message=f"检测到不支持的非 ASCII 或控制字符 U+{code:04X}",
                        line=curr_line,
                        column=col,
                    )
                )
        curr_line += 1

    # 检查三字符组 (Trigraphs: ??=, ??/, ??', ??(, ??), ??!, ??<, ??>)
    trigraph_match = re.search(r"\?\?[=/'\(\)!<>-]", source)
    if trigraph_match:
        pos = trigraph_match.start()
        # 计算行号列号
        line_no = source[:pos].count("\n") + 1
        col_no = pos - source[:pos].rfind("\n")
        raise PipelineError(
            Diagnostic(
                code=ErrorCode.UNSUPPORTED_SOURCE,
                message="不支持三字符组 (Trigraph sequences)",
                line=line_no,
                column=col_no,
            )
        )

    # 规范化 CRLF -> LF
    return source.replace("\r\n", "\n").replace("\r", "\n")


# ==============================================================================
# 核心入口 1: analyze_source
# ==============================================================================

def analyze_source(
    text: str,
    profile: str = "-std=c11 -pedantic-errors",
    *,
    ctx: Optional[RunContext] = None,
) -> SourceModel:
    """
    解析并验证 C11 源码。要求恰好包含一个独立自包含函数定义，
    提取规范 token 流与原始注释，严格检查未声明外部引用与预定义宏。
    """
    ctx = ctx or RunContext()
    ctx.check()

    # 1. 字符初筛与 LF 规范化
    normalized = _validate_raw_characters(text)

    # 2. 预处理语法检查 (#)
    for idx, line in enumerate(normalized.split("\n"), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            raise PipelineError(
                Diagnostic(
                    code=ErrorCode.UNSUPPORTED_SOURCE,
                    message="不支持预处理指令或宏依赖",
                    line=idx,
                    column=line.find("#") + 1,
                )
            )

    # 3. 创建临时 TranslationUnit 进行 AST 与 Token 解析
    index = Index.create()
    args = profile.split() + ["-c"]

    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False, encoding="utf-8") as f:
        f.write(normalized)
        temp_name = f.name

    try:
        ctx.check()
        tu = index.parse(
            temp_name,
            args=args,
            options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )

        # 检查编译器诊断（语法错误、未定义等）
        for diag in tu.diagnostics:
            if diag.severity >= clang.cindex.Diagnostic.Error:
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.INVALID_SOURCE,
                        message=diag.spelling,
                        line=diag.location.line,
                        column=diag.location.column,
                    )
                )

        ctx.check()

        # 4. AST 遍历：确认仅有一个顶层函数定义，且无未声明外部引用
        function_cursor = None
        func_count = 0

        for child in tu.cursor.get_children():
            # 忽略系统内置头引入的内容（若有）
            if child.location.file and child.location.file.name != temp_name:
                continue

            if child.kind == CursorKind.FUNCTION_DECL:
                # 仅计包含函数体的实际定义
                if child.is_definition():
                    func_count += 1
                    function_cursor = child
            elif child.kind in (
                CursorKind.VAR_DECL,
                CursorKind.STRUCT_DECL,
                CursorKind.TYPEDEF_DECL,
                CursorKind.UNION_DECL,
                CursorKind.ENUM_DECL,
            ):
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.UNSUPPORTED_SOURCE,
                        message="不支持函数体外的全局变量、外部声明或顶层类型定义",
                        line=child.location.line,
                        column=child.location.column,
                    )
                )

        if func_count == 0 or function_cursor is None:
            raise PipelineError(
                Diagnostic(
                    code=ErrorCode.INVALID_SOURCE,
                    message="源码必须恰好包含一个完整的函数定义",
                )
            )
        if func_count > 1:
            raise PipelineError(
                Diagnostic(
                    code=ErrorCode.UNSUPPORTED_SOURCE,
                    message=f"源码包含 {func_count} 个函数定义，第一版仅支持单函数",
                    line=function_cursor.location.line,
                    column=function_cursor.location.column,
                )
            )

        # 检查 AST 节点引用 (DeclRefExpr)：确保解析到形参、局部声明或函数自身递归
        _check_scope_and_references(function_cursor)

        # 5. 提取 Tokens 与注释
        tokens: List[Token] = []
        comments: List[Tuple[int, int, str]] = []
        token_index = 0

        for t in tu.get_tokens(extent=tu.cursor.extent):
            spelling = t.spelling
            kind_name = t.kind.name

            # 区分注释与有效 Token
            if t.kind == TokenKind.COMMENT:
                comments.append((t.location.line, t.location.column, spelling))
                continue

            # 检查预定义宏引用 (如 __LINE__, __FILE__)
            if spelling in FORBIDDEN_MACRO_NAMES:
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.UNSUPPORTED_SOURCE,
                        message=f"不支持引用预定义宏: {spelling}",
                        line=t.location.line,
                        column=t.location.column,
                    )
                )

            # 检查 token 内部是否包含真实非法 tab (除普通空格外)
            if "\t" in spelling and t.kind != TokenKind.LITERAL:
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.UNSUPPORTED_SOURCE,
                        message="Token 内部不得包含真实制表符",
                        line=t.location.line,
                        column=t.location.column,
                    )
                )

            tokens.append(
                Token(
                    index=token_index,
                    kind=kind_name,
                    spelling=spelling,
                    width=len(spelling),
                    source_line=t.location.line,
                    source_column=t.location.column,
                )
            )
            token_index += 1

        func_name = function_cursor.spelling
        signature = f"{function_cursor.result_type.spelling} {function_cursor.displayname}"

        return SourceModel(
            original_source=text,
            normalized_source=normalized,
            tokens=tokens,
            profile=profile,
            function_name=func_name,
            signature=signature,
            original_comments=comments,
        )

    except TimeoutError:
        raise PipelineError(
            Diagnostic(
                code=ErrorCode.ANALYSIS_TIMEOUT,
                message="代码分析超出规定时间预算",
            )
        )
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def _check_scope_and_references(func_cursor: clang.cindex.Cursor):
    """
    递归遍历函数 AST，检查 DeclRefExpr 节点是否均在内部声明或指向自身函数，
    拦截外部函数引用（如 return g(x)）与外部未声明变量（如 return ext）。
    """
    for node in func_cursor.walk_preorder():
        if node.kind == CursorKind.DECL_REF_EXPR:
            ref_decl = node.referenced
            # 若引用的标识符解析为空，或其声明处于当前函数之外（且不是自身递归）
            if ref_decl is None:
                raise PipelineError(
                    Diagnostic(
                        code=ErrorCode.UNSUPPORTED_SOURCE,
                        message=f"未声明的引用或外部依赖: {node.spelling}",
                        line=node.location.line,
                        column=node.location.column,
                    )
                )

            # 如果引用的声明不是函数自身，且父级不在本函数内
            if ref_decl != func_cursor:
                # 检查声明位置所在的作用域是否在函数体内
                parent = ref_decl.semantic_parent
                is_local = False
                while parent and parent != parent.semantic_parent:
                    if parent == func_cursor:
                        is_local = True
                        break
                    parent = parent.semantic_parent

                # 若既非形参也非函数局部变量
                if not is_local and ref_decl.kind != CursorKind.PARM_DECL:
                    raise PipelineError(
                        Diagnostic(
                            code=ErrorCode.UNSUPPORTED_SOURCE,
                            message=f"引用了外部函数或未绑定的全局符号: '{node.spelling}'",
                            line=node.location.line,
                            column=node.location.column,
                        )
                    )


# ==============================================================================
# 核心入口 2: can_join (最小词法分隔仲裁)
# ==============================================================================

@lru_cache(maxsize=4096)
def _can_join_cached(
    run_spellings: Tuple[str, ...],
    next_spelling: str,
    profile: str,
) -> bool:
    """
    缓存加速：将连续 token 串与候选 token 无缝拼接，重新执行词法分词。
    只有分词出的 token 序列与预期拼写完全一致，才允许零空格紧贴。
    """
    expected = list(run_spellings) + [next_spelling]
    joined_text = "".join(expected)

    # 排除注释触发符组合的前置防御 (如 '/' 接 '*' 或 '/' 接 '/')
    if joined_text.endswith("/*") or joined_text.endswith("//"):
        return False

    index = Index.create()
    args = profile.split() + ["-c"]

    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False, encoding="utf-8") as f:
        f.write(joined_text)
        temp_name = f.name

    try:
        tu = index.parse(temp_name, args=args)
        actual_tokens = [
            t.spelling
            for t in tu.get_tokens(extent=tu.cursor.extent)
            if t.kind != TokenKind.COMMENT
        ]
        return actual_tokens == expected
    except Exception:
        return False
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def can_join(
    run_tokens: Sequence[Token],
    next_token: Token,
    profile: str = "-std=c11 -pedantic-errors",
) -> bool:
    """
    仲裁是否可以允许 0 个空格直接紧贴放置。
    满足边界覆盖：f(x)、a[0]、i++ 允许紧排；+与+、/与*、三个独立点等必须被拦截。
    """
    if not run_tokens:
        return True

    # 提取最近无空白连续 token 序列（避免长序列性能浪费，只取末尾最多 4 个 token）
    recent_spellings = tuple(t.spelling for t in run_tokens[-4:])
    return _can_join_cached(recent_spellings, next_token.spelling, profile)