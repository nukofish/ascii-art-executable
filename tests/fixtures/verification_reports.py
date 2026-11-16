"""Dependency-free fake verifiers for F's pipeline and display tests."""

from codeart.verify import (
    CheckStatus, Diagnostic, ErrorCode, TokenDiff, TokenLocation, VerificationReport,
)


def _pass():
    return VerificationReport(
        token_status=CheckStatus.PASS, geometry_status=CheckStatus.PASS,
        compile_status=CheckStatus.PASS, behavior_status=CheckStatus.PASS,
        geometry_metrics={"out_of_bounds_cells": 0, "hole_leakage_cells": 0},
        behavior_cases_compared=8,
    )


def _token_mismatch():
    report = VerificationReport(token_status=CheckStatus.FAIL)
    report.first_diff = TokenDiff(
        7, TokenLocation("numeric_constant", "0", 2, 12),
        TokenLocation("numeric_constant", "1", 8, 16), "KIND_OR_SPELLING",
    )
    report.diagnostics.append(Diagnostic(
        ErrorCode.TOKEN_MISMATCH, "token", "Effective token sequence changed", 8, 16,
    ))
    report.skip_reasons.update(
        geometry="TOKEN_NOT_PASS", compile="TOKEN_NOT_PASS", behavior="TOKEN_NOT_PASS",
    )
    return report


def _hole_leakage():
    report = _pass()
    report.geometry_status = CheckStatus.FAIL
    report.behavior_status = CheckStatus.NOT_RUN
    report.behavior_cases_compared = 0
    report.geometry_metrics.update(out_of_bounds_cells=4, hole_leakage_cells=4)
    report.diagnostics.append(Diagnostic(
        ErrorCode.GEOMETRY_MISMATCH, "geometry", "Rendered characters occupy a hole", 14, 21,
    ))
    report.skip_reasons["behavior"] = "GEOMETRY_NOT_PASS"
    return report


def _compiler_unavailable():
    report = _pass()
    report.compile_status = report.behavior_status = CheckStatus.NOT_RUN
    report.behavior_cases_compared = 0
    report.diagnostics.append(Diagnostic(
        ErrorCode.DEPENDENCY_UNAVAILABLE, "compile", "Compiler not found",
    ))
    report.skip_reasons.update(compile="DEPENDENCY_UNAVAILABLE", behavior="COMPILE_NOT_PASS")
    return report


def _wrapper_compile_failure():
    return VerificationReport(
        token_status=CheckStatus.PASS, geometry_status=CheckStatus.PASS,
        compile_status=CheckStatus.FAIL,
        geometry_metrics={"out_of_bounds_cells": 0, "hole_leakage_cells": 0},
        diagnostics=[Diagnostic(
            ErrorCode.COMPILE_FAILED, "compile", "Compiler returned a nonzero exit status",
            details={"build": "rendered", "exit_code": 1, "stderr": "wrapper build failed"},
        )],
        skip_reasons={"behavior": "COMPILE_NOT_PASS"},
    )


def make_verifier_stub(case):
    factory = {
        "pass": _pass, "token_mismatch": _token_mismatch,
        "hole_leakage": _hole_leakage, "compiler_unavailable": _compiler_unavailable,
        "wrapper_compile_failure": _wrapper_compile_failure,
    }[case]

    def verify(model, plan, rendered, fixtures, profile, *, ctx):
        return factory()

    return verify
