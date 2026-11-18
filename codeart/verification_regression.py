"""Fixed v1.4 regression matrix for an injected pipeline adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from math import sqrt
from pathlib import Path
from time import monotonic

from .procutil import BuildSession, WorkStopped, check_context
from .shapes import FontMetrics, ShapeSpec, SizeRequest, build_mask, geometry_metrics
from .verification_fixtures import BUILTIN_FIXTURES, FixtureSelection
from .verify import CheckStatus, VerificationContext, VerificationReport


_CAT_BASE_HEIGHT = 32
_CAT_SCALES = (1, 2, 4)
_CAT_HOLE_MIN_CELLS = (("eye_left", 4), ("eye_right", 4), ("nose", 2))


@dataclass(frozen=True)
class HoleReference:
    base_area: float
    center: tuple[float, float]
    boundary_cells: float


@dataclass(frozen=True)
class CatScaleReference:
    holes: Mapping[str, HoleReference]
    ear_gap_rows: int


def _read_shape_metrics(directory: Path, height: int):
    path = directory / f"metrics_h{height}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (document["schema_version"] != 1
            or document["height_rows"] != height
            or document["cell_aspect"] != FontMetrics().cell_aspect):
        raise ValueError(f"Incompatible shape metrics: {path}")
    return document


def load_cat_references(directory: Path) -> dict[int, CatScaleReference]:
    """Adapt B's h32/h64/h128 snapshots to E's scale and coordinate conventions."""
    base = _read_shape_metrics(directory, _CAT_BASE_HEIGHT)
    if base is None:
        return {}
    base_features = base["shapes"]["cat"]["features"]
    tolerance = base["tolerance"]
    references = {}
    for scale in _CAT_SCALES:
        document = base if scale == 1 else _read_shape_metrics(directory, _CAT_BASE_HEIGHT * scale)
        if document is None:
            continue
        cat = document["shapes"]["cat"]
        holes = {}
        for name, _ in _CAT_HOLE_MIN_CELLS:
            base_area = base_features[name]["cells"]
            area_at_scale = base_area * scale ** 2
            row, col = cat["features"][name]["centroid"]
            holes[name] = HoleReference(
                base_area=base_area,
                center=(row - 0.5, col - 0.5),
                boundary_cells=max(
                    tolerance["area_rel"] * area_at_scale,
                    tolerance["area_perimeter_factor"] * sqrt(area_at_scale),
                    tolerance["area_min_cells"],
                ),
            )
        references[scale] = CatScaleReference(holes, cat["ear_gap_rows"])
    return references


@dataclass(frozen=True)
class RegressionCase:
    fixture: str
    shape: str
    verification: VerificationReport | None
    issues: tuple[str, ...]


@dataclass(frozen=True)
class CatScaleResult:
    status: CheckStatus
    issues: tuple[str, ...]


@dataclass(frozen=True)
class RegressionReport:
    cases: tuple[RegressionCase, ...]
    build_counts: dict[str, int]
    cat_scales: dict[int, CatScaleResult]
    elapsed_s: float
    interrupted: str | None

    @property
    def comparisons(self) -> int:
        return sum(case.verification.behavior_cases_compared for case in self.cases
                   if case.verification is not None)

    @property
    def matrix_passed(self) -> bool:
        return (
            self.interrupted is None and len(self.cases) == 18
            and all(not case.issues for case in self.cases)
            and self.comparisons == 144
            and self.build_counts["original"] == 6 and self.build_counts["rendered"] == 18
        )

    @property
    def passed(self) -> bool:
        return self.matrix_passed and all(
            result.status == CheckStatus.PASS for result in self.cat_scales.values()
        )


def _case_issues(report, shape, min_coverage, min_ear_coverage):
    if report is None:
        return ("VERIFICATION_MISSING",)
    issues = [
        f"{name.upper()}_{CheckStatus(getattr(report, f'{name}_status')).value}"
        for name in ("token", "geometry", "compile", "behavior")
        if getattr(report, f"{name}_status") != CheckStatus.PASS
    ]
    metrics = report.geometry_metrics
    if metrics.get("kind") != shape:
        issues.append("WRONG_SHAPE")
    if report.behavior_cases_compared != 8:
        issues.append("BEHAVIOR_CASES_INCOMPLETE")
    if metrics.get("coverage", 0.0) < min_coverage:
        issues.append("COVERAGE_BELOW_TARGET")
    if shape == "cat":
        ears = metrics.get("ear_coverage", {})
        if min(ears.get("ear_left", 0.0), ears.get("ear_right", 0.0)) < min_ear_coverage:
            issues.append("EAR_COVERAGE_BELOW_TARGET")
    return tuple(issues)


def _check_cat_scale(scale, reference, ctx):
    mask = build_mask(ShapeSpec("cat"), SizeRequest(_CAT_BASE_HEIGHT * scale), FontMetrics(), ctx=ctx)
    metrics = geometry_metrics(mask)
    issues = []
    if len(metrics["holes"]) != 3:
        issues.append("HOLE_COUNT")
    if abs(metrics["ear_gap_rows"] - reference.ear_gap_rows) > 1:
        issues.append("EAR_GAP")
    for name, minimum in _CAT_HOLE_MIN_CELLS:
        check_context(ctx)
        cells = mask.features[name]
        expected = reference.holes.get(name)
        if expected is None:
            issues.append(f"MISSING_REFERENCE_{name}")
            continue
        if not cells or any(mask.allowed[row][col] for row, col in cells):
            issues.append(f"HOLE_NOT_BLANK_{name}")
            continue
        if (len(cells) < minimum
                or abs(len(cells) - expected.base_area * scale ** 2) > expected.boundary_cells):
            issues.append(f"HOLE_AREA_{name}")
        center = tuple(sum(cell[axis] for cell in cells) / len(cells) for axis in (0, 1))
        if any(abs(actual - target) > 1 for actual, target in zip(center, expected.center)):
            issues.append(f"HOLE_CENTER_{name}")
    return CatScaleResult(CheckStatus.FAIL if issues else CheckStatus.PASS, tuple(issues))


def run_regression(
    generate_case: Callable[..., VerificationReport | None], *,
    ctx=None,
    cat_references: Mapping[int, CatScaleReference] | None = None,
    min_coverage: float = 0.85,
    min_ear_coverage: float = 0.70,
) -> RegressionReport:
    """Call generate_case(selection, shape_spec, *, ctx) once per matrix case.

    The adapter must forward the fixture selection and observe the supplied
    context. The runner owns the serial session and its temporary build cache.
    """
    start = monotonic()
    if ctx is None:
        total = VerificationContext(start + 180)
    else:
        total = VerificationContext.within(ctx, 180)
    cases = []
    interrupted = None
    cat_scales = {
        scale: CatScaleResult(CheckStatus.NOT_RUN, ("MISSING_REFERENCE",))
        for scale in _CAT_SCALES
    }
    references = cat_references or {}
    with BuildSession() as builds:
        try:
            for fixture in BUILTIN_FIXTURES.values():
                selection = FixtureSelection(fixture, builds)
                for kind in ("circle", "cat", "code"):
                    check_context(total)
                    case_ctx = VerificationContext.within(total, 30)
                    shape = ShapeSpec(kind, text="CODE" if kind == "code" else None)
                    report = generate_case(selection, shape, ctx=case_ctx)
                    issues = _case_issues(report, kind, min_coverage, min_ear_coverage)
                    if case_ctx.remaining_s() <= 0:
                        issues += ("CASE_DEADLINE",)
                    cases.append(RegressionCase(fixture.name, kind, report, issues))
            for scale in cat_scales:
                check_context(total)
                if scale in references:
                    cat_scales[scale] = _check_cat_scale(scale, references[scale], total)
            check_context(total)
        except WorkStopped as exc:
            interrupted = exc.reason
            for scale in cat_scales:
                if scale in references and cat_scales[scale].status == CheckStatus.NOT_RUN:
                    cat_scales[scale] = CatScaleResult(CheckStatus.NOT_RUN, (exc.reason,))
        counts = dict(builds.counts)
    return RegressionReport(tuple(cases), counts, cat_scales, monotonic() - start, interrupted)
