"""Assemble and run the independent analysis, layout, render and verify stages."""

from dataclasses import replace
from importlib import import_module
from threading import Event
from time import monotonic

from .contracts import (
    CheckStatus,
    Diagnostic,
    ErrorCode,
    GenerationRequest,
    GenerationResult,
    GenerationStatus,
    PipelineDeps,
    PipelineError,
    RunContext,
)
from .shapes import build_mask


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
            raise PipelineError(Diagnostic(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "setup", f"Missing module: {module_name}"
            )) from exc
    return PipelineDeps(
        analyzer=modules["source"].analyze_source,
        mask_builder=build_mask,
        join_checker=modules["source"].can_join,
        layout_engine=modules["layout"].fit_layout,
        renderer=modules["fill"].render_source,
        verifier=modules["verify"].verify,
        program_analyzer=modules["source"].analyze_program,
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
        analyzer = deps.analyzer
        if request.program_mode:
            analyzer = deps.program_analyzer
            if analyzer is None:
                analyzer = import_module(f"{__package__}.source").analyze_program
        model = analyzer(request.source_text, request.profile, ctx=ctx)

        stage = "layout"
        ctx.check()
        result.plan = deps.layout_engine(
            model, request.shape_spec, request.layout_options,
            mask_builder=deps.mask_builder, join_checker=deps.join_checker, ctx=ctx,
        )

        stage = "render"
        ctx.check()
        result.rendered = deps.renderer(model, result.plan, request.fill_options, ctx=ctx)
        if model.program_mode:
            artwork = result.rendered.source_text
            prefix = model.preamble_text
            if prefix:
                prefix += "\n\n" if prefix.endswith("\n") else "\n\n\n"
            result.rendered = replace(
                result.rendered,
                source_text=prefix + artwork,
                artwork_source_text=artwork,
                program_mode=True,
                preamble_text=prefix,
            )

        stage = "verification"
        ctx.check()
        result.verification = deps.verifier(
            model, result.plan, result.rendered, request.fixtures, model.profile, ctx=ctx,
        )
        result.diagnostics.extend(result.verification.diagnostics)
        stop_codes = (ErrorCode.CANCELLED, ErrorCode.PIPELINE_TIMEOUT)
        if not any(item.code in stop_codes for item in result.diagnostics):
            ctx.check()
    except PipelineError as exc:
        # Keep the code and the stage the failing stage reported: B's shape
        # failures stay INVALID_SHAPE/INVALID_SIZE at stage "shape" and are
        # never rewritten into LAYOUT_LIMIT here.
        result.diagnostics.append(exc.diagnostic)
    except (ImportError, FileNotFoundError) as exc:
        result.diagnostics.append(Diagnostic(ErrorCode.DEPENDENCY_UNAVAILABLE, stage, str(exc)))
    except Exception as exc:
        result.diagnostics.append(Diagnostic(
            ErrorCode.INTERNAL_ERROR, stage, f"{type(exc).__name__}: {exc}"
        ))
    result.status = _final_status(result)
    return result


def _final_status(result: GenerationResult) -> GenerationStatus:
    """Map diagnostics and verification FAILs onto the top-level status."""
    if any(item.code == ErrorCode.CANCELLED for item in result.diagnostics):
        return GenerationStatus.CANCELLED
    if result.diagnostics:
        return GenerationStatus.FAILED
    if result.verification is not None:
        required = (
            result.verification.token_status,
            result.verification.geometry_status,
            result.verification.compile_status,
        )
        if any(status != CheckStatus.PASS for status in required):
            return GenerationStatus.FAILED
        if result.verification.behavior_status == CheckStatus.FAIL:
            return GenerationStatus.FAILED
    return GenerationStatus.OK
