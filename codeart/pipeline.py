"""Assemble and run the independent analysis, layout, render and verify stages."""

from importlib import import_module
from threading import Event
from time import monotonic

from .contracts import (
    Diagnostic,
    ErrorCode,
    GenerationRequest,
    GenerationResult,
    PipelineDeps,
    RunContext,
    StageError,
)
from .shapes import ShapeError, build_mask


def production_deps() -> PipelineDeps:
    """Load the real modules when they are available in this checkout."""
    modules = {}
    for name in ("source", "layout", "fill", "verify"):
        module_name = f"{__package__}.{name}"
        try:
            modules[name] = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            raise StageError(Diagnostic(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "setup", f"Missing module: {module_name}"
            )) from exc
    return PipelineDeps(
        analyzer=modules["source"].analyze_source,
        mask_builder=build_mask,
        join_checker=modules["source"].can_join,
        layout_engine=modules["layout"].fit_layout,
        renderer=modules["fill"].render_source,
        verifier=modules["verify"].verify,
    )


def generate(
    request: GenerationRequest,
    *,
    deps: PipelineDeps | None = None,
    cancel_event: Event | None = None,
) -> GenerationResult:
    """Run the stages under one deadline and preserve results already returned."""
    ctx = RunContext(monotonic() + request.timeout_s, cancel_event)
    result = GenerationResult()
    stage = "setup"
    try:
        ctx.check()
        if deps is None:
            deps = production_deps()

        stage = "analysis"
        ctx.check()
        model = deps.analyzer(request.source_text, request.profile, ctx=ctx)

        stage = "layout"
        ctx.check()
        result.plan = deps.layout_engine(
            model, request.shape_spec, request.layout_options,
            mask_builder=deps.mask_builder, join_checker=deps.join_checker, ctx=ctx,
        )

        stage = "render"
        ctx.check()
        result.rendered = deps.renderer(model, result.plan, request.fill_options, ctx=ctx)

        stage = "verification"
        ctx.check()
        result.verification = deps.verifier(
            model, result.plan, result.rendered, request.fixtures, request.profile, ctx=ctx,
        )
        result.diagnostics.extend(result.verification.diagnostics)
        stop_codes = (ErrorCode.CANCELLED, ErrorCode.PIPELINE_TIMEOUT)
        if not any(item.code in stop_codes for item in result.diagnostics):
            ctx.check()
    except StageError as exc:
        result.diagnostics.append(exc.diagnostic)
    except ShapeError as exc:
        code = ErrorCode.INVALID_SHAPE if exc.code == "INVALID_SHAPE" else ErrorCode.LAYOUT_LIMIT
        result.diagnostics.append(Diagnostic(code, "layout", exc.message))
    except (ImportError, FileNotFoundError) as exc:
        result.diagnostics.append(Diagnostic(ErrorCode.DEPENDENCY_UNAVAILABLE, stage, str(exc)))
    except Exception as exc:
        result.diagnostics.append(Diagnostic(
            ErrorCode.INTERNAL_ERROR, stage, f"{type(exc).__name__}: {exc}"
        ))
    return result
