"""Shared data and runtime contracts for the C11 code-art pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from threading import Event
from time import monotonic
from typing import Protocol
from unicodedata import category, east_asian_width


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class GenerationStatus(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ErrorCode(str, Enum):
    INVALID_SOURCE = "INVALID_SOURCE"
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"
    INVALID_SHAPE = "INVALID_SHAPE"
    INVALID_SIZE = "INVALID_SIZE"
    LAYOUT_LIMIT = "LAYOUT_LIMIT"
    LAYOUT_TIMEOUT = "LAYOUT_TIMEOUT"
    TOKEN_MISMATCH = "TOKEN_MISMATCH"
    GEOMETRY_MISMATCH = "GEOMETRY_MISMATCH"
    COMPILE_FAILED = "COMPILE_FAILED"
    COMPILE_TIMEOUT = "COMPILE_TIMEOUT"
    BEHAVIOR_MISMATCH = "BEHAVIOR_MISMATCH"
    EXECUTION_TIMEOUT = "EXECUTION_TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    CANCELLED = "CANCELLED"
    PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class Diagnostic:
    """One diagnosed failure.

    ``line`` and ``column`` point into a source text. ``location`` names the
    non-source target instead (a request field, e.g.
    ``"SizeRequest.height_rows"``, or a produced artifact, e.g.
    ``"Mask.allowed"``); it is ``None`` when the failure has no such target.
    The field is last so the positional ``Diagnostic(code, stage, message,
    line, column, details)`` calls of the other stages keep their meaning.
    """

    code: ErrorCode
    stage: str
    message: str
    line: int | None = None
    column: int | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    location: str | None = None


class PipelineError(Exception):
    """A diagnosed failure that stops the current stage.

    This is the canonical name for the shared stage failure. ``StageError`` is
    kept as a synonym, so existing ``except StageError`` clauses, imports and
    ``raise StageError(...)`` call sites keep working unchanged.
    """

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic

    @property
    def code(self) -> str:
        """Compatibility accessor: the diagnostic code as a plain string.

        The old ``ShapeError.code`` was a string (``"INVALID_SHAPE"``), so a
        string keeps ``exc.code == "INVALID_SHAPE"`` and formatted output
        unchanged; new code should read ``exc.diagnostic.code``.
        """
        return self.diagnostic.code.value


#: Synonym for :class:`PipelineError`, kept for the existing stage call sites.
StageError = PipelineError

# B already owns these public types. Re-export the same classes so callers
# and build_mask agree on type identity.  This import stays below the error
# contract because ``codeart.shapes`` imports these error types back to raise
# them; defining the errors first keeps a single direction of initialisation.
from .shapes import FontMetrics, Mask, ShapeSpec, SizeRequest  # noqa: E402


@dataclass(frozen=True)
class RunContext:
    """One shared budget measured by the caller's clock and real monotonic time."""

    deadline: float
    cancel_event: Event | None = None
    clock: Callable[[], float] = field(default=monotonic, repr=False, compare=False)
    _real_deadline: float | None = field(default=None, kw_only=True, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._real_deadline is None:
            real_deadline = self.deadline
            if self.clock is not monotonic:
                real_deadline = monotonic() + (self.deadline - self.clock())
            object.__setattr__(self, "_real_deadline", real_deadline)

    @classmethod
    def within(cls, parent: RunContext, timeout: float):
        """Derive a stage budget limited by both of the parent's deadlines."""
        return cls(
            min(parent.deadline, parent.clock() + timeout),
            parent.cancel_event,
            clock=parent.clock,
            _real_deadline=min(parent._real_deadline, monotonic() + timeout),
        )

    @property
    def real_deadline(self) -> float | None:
        """Deadline on the real monotonic clock, used when the injected clock is untrusted.

        ``deadline`` is measured by the injected ``clock``, which deterministic
        tests may freeze or rescale; such a clock cannot prove that real time
        is passing.  This read-only value is derived once, at construction
        time, from :func:`time.monotonic` (or supplied by an enclosing stage),
        so a stage can fall back to real time without changing the meaning of
        ``deadline`` or ``remaining_s``.  ``__post_init__`` always fills the
        stored value for a normally constructed context.
        """
        return self._real_deadline

    def remaining_s(self) -> float:
        now = self.clock()
        real_now = now if self.clock is monotonic else monotonic()
        return max(0.0, min(self.deadline - now, self._real_deadline - real_now))

    def check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise StageError(Diagnostic(ErrorCode.CANCELLED, "pipeline", "Generation cancelled"))
        if self.remaining_s() == 0:
            raise StageError(Diagnostic(ErrorCode.PIPELINE_TIMEOUT, "pipeline", "Generation timed out"))


@dataclass(frozen=True)
class TokenLocation:
    kind: str
    spelling: str
    line: int
    column: int


@dataclass(frozen=True)
class LexedToken(TokenLocation):
    """Raw lexer token before filtering comments, with one-based coordinates."""

    is_comment: bool = False


class LexSource(Protocol):
    def __call__(self, text: str, *, ctx: RunContext) -> Iterable[LexedToken]: ...


@dataclass(frozen=True)
class VerificationProfile:
    """The compiler and raw lexer settings shared by A and E."""

    lex_source: LexSource | None = None
    compiler: str = "clang"
    flags: tuple[str, ...] = ("-std=c11", "-pedantic-errors")
    lex_timeout: float = 5.0
    compile_timeout: float = 5.0
    execution_timeout: float = 2.0
    max_behavior_cells: int = 100_000


@dataclass(frozen=True)
class Token:
    index: int
    kind: str
    spelling: str
    width: int
    source_line: int
    source_column: int


@dataclass(frozen=True)
class SourceModel:
    original_source: str
    normalized_source: str
    tokens: Sequence[Token]
    profile: VerificationProfile
    function_name: str
    signature: str
    original_comments: Sequence[Token] = ()
    program_mode: bool = False
    preamble_text: str = ""
    has_main: bool = False


@dataclass(frozen=True)
class Placement:
    token_index: int
    row: int
    col: int


@dataclass(frozen=True)
class AttemptRecord:
    scale: float
    width: int
    height: int
    failure_token_index: int | None
    reason: str | None
    elapsed_s: float


@dataclass(frozen=True)
class LayoutOptions:
    base_height_rows: int = 32
    initial_scale: float = 1.0
    growth_factor: float = 1.25
    max_attempts: int = 12
    max_columns: int = 800
    max_rows: int = 600
    layout_timeout_s: float = 5.0
    font_metrics: FontMetrics = field(default_factory=FontMetrics)


@dataclass(frozen=True)
class LayoutPlan:
    """Placements and retry history for the final mask selected by C."""

    mask: Mask
    placements: Sequence[Placement]
    protected_blanks: frozenset[tuple[int, int]]
    actual_scale: float
    attempt_count: int
    attempt_history: Sequence[AttemptRecord]


PROGRAM_FILL_PATTERN = ".:o+-x=()&"


def is_grid_character(char: str) -> bool:
    return " " <= char <= "~" or (char.isprintable() and not category(char).startswith("M"))


def character_cells(char: str) -> int:
    return 2 if east_asian_width(char) in ("W", "F") else 1


def grid_text(text: str) -> str:
    """Return one character per cell for measuring and checking grid slices."""
    if text.isascii():
        return text
    return "".join(char * character_cells(char) for char in text)


@dataclass(frozen=True)
class FillOptions:
    allow_line_comments: bool = True


@dataclass(frozen=True)
class RenderedCode:
    """Generated source with zero-based token positions and coverage fractions."""

    source_text: str
    position_map: Mapping[int, tuple[int, int]]
    coverage: float
    token_coverage: float
    comment_coverage: float
    comment_cells: Mapping[str, int]
    artwork_source_text: str | None = None
    program_mode: bool = False
    preamble_text: str = ""


@dataclass(frozen=True)
class TokenDiff:
    index: int
    expected: TokenLocation | None
    actual: TokenLocation | None
    reason: str


@dataclass(frozen=True)
class CompilerInfo:
    path: str
    version: str
    flags: tuple[str, ...]
    _fingerprint: tuple[int, ...] = field(repr=False)


@dataclass
class VerificationReport:
    """Independent check results, including completed checks on cancellation."""

    token_status: CheckStatus = CheckStatus.NOT_RUN
    geometry_status: CheckStatus = CheckStatus.NOT_RUN
    compile_status: CheckStatus = CheckStatus.NOT_RUN
    behavior_status: CheckStatus = CheckStatus.NOT_RUN
    geometry_metrics: Mapping[str, object] = field(default_factory=dict)
    first_diff: TokenDiff | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    skip_reasons: dict[str, str] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    compiler: CompilerInfo | None = None
    behavior_cases_compared: int = 0


@dataclass(frozen=True)
class GenerationRequest:
    source_text: str
    shape_spec: ShapeSpec
    profile: VerificationProfile = field(default_factory=VerificationProfile)
    layout_options: LayoutOptions = field(default_factory=LayoutOptions)
    fill_options: FillOptions = field(default_factory=FillOptions)
    fixtures: object = None
    timeout_s: float = 30.0
    program_mode: bool = False

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")


@dataclass
class GenerationResult:
    """Artifacts retained from all stages that returned before the pipeline stopped."""

    plan: LayoutPlan | None = None
    rendered: RenderedCode | None = None
    verification: VerificationReport | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    status: GenerationStatus = GenerationStatus.OK

    def __post_init__(self) -> None:
        if self.status != GenerationStatus.OK:
            return
        if self.diagnostics:
            if any(item.code == ErrorCode.CANCELLED for item in self.diagnostics):
                self.status = GenerationStatus.CANCELLED
            else:
                self.status = GenerationStatus.FAILED
            return
        if self.verification is not None:
            required = (
                self.verification.token_status,
                self.verification.geometry_status,
                self.verification.compile_status,
            )
            if any(status != CheckStatus.PASS for status in required):
                self.status = GenerationStatus.FAILED
            elif self.verification.behavior_status == CheckStatus.FAIL:
                self.status = GenerationStatus.FAILED


class Analyzer(Protocol):
    def __call__(
        self, text: str, profile: VerificationProfile, /, *, ctx: RunContext,
    ) -> SourceModel: ...


class MaskBuilder(Protocol):
    def __call__(
        self, shape_spec: ShapeSpec, size_request: SizeRequest, font_metrics: FontMetrics,
        /, *, ctx: RunContext,
    ) -> Mask: ...


JoinChecker = Callable[[Sequence[Token], Token, VerificationProfile], bool]


class LayoutEngine(Protocol):
    def __call__(
        self, model: SourceModel, shape_spec: ShapeSpec, options: LayoutOptions, /, *,
        mask_builder: MaskBuilder, join_checker: JoinChecker, ctx: RunContext,
    ) -> LayoutPlan: ...


class Renderer(Protocol):
    def __call__(
        self, model: SourceModel, plan: LayoutPlan, fill_options: FillOptions,
        /, *, ctx: RunContext,
    ) -> RenderedCode: ...


class Verifier(Protocol):
    def __call__(
        self, model: SourceModel, plan: LayoutPlan, rendered: RenderedCode,
        fixtures: object, profile: VerificationProfile, /, *, ctx: RunContext,
    ) -> VerificationReport: ...


@dataclass(frozen=True)
class PipelineDeps:
    """Explicit stage implementations used by production and integration tests."""

    analyzer: Analyzer
    mask_builder: MaskBuilder
    join_checker: JoinChecker
    layout_engine: LayoutEngine
    renderer: Renderer
    verifier: Verifier
    program_analyzer: Analyzer | None = None
