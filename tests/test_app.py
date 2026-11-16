"""HTTP integration, fixture eligibility, cancellation and result downloads."""

from dataclasses import replace
import json
from threading import Event, Thread
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from codeart.app import create_server, make_request
from codeart._integration_demo import demo_deps
from codeart.contracts import Diagnostic, ErrorCode, GenerationResult
from codeart.pipeline import generate
from codeart.verification_fixtures import BUILTIN_FIXTURES
from fixtures.verification_reports import make_verifier_stub


@pytest.fixture
def web_server():
    entered = Event()

    def runner(request, *, cancel_event):
        if request.source_text == "slow":
            entered.set()
            cancel_event.wait(3)
            return GenerationResult(diagnostics=[
                Diagnostic(ErrorCode.CANCELLED, "pipeline", "Generation cancelled")
            ])
        from codeart._integration_demo import DEMO_SOURCE
        request = replace(request, source_text=DEMO_SOURCE)
        return generate(request, deps=demo_deps(), cancel_event=cancel_event)

    server = create_server(0, runner=runner)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    yield base, entered
    server.shutdown()
    server.jobs.shutdown()
    server.server_close()
    thread.join()


def call(base, path, payload=None, origin=None):
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(base + path, data=data, headers=headers)
    with urlopen(request, timeout=5) as response:
        return response.read(), response.headers


def wait_result(base, identifier):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        data, _ = call(base, "/api/jobs/" + identifier)
        job = json.loads(data)
        if job["state"] == "finished":
            return job
        sleep(0.01)
    pytest.fail("Job did not finish")


def test_builtin_selection_requires_matching_source():
    sample = BUILTIN_FIXTURES["max2"]
    assert make_request({"source": sample.source, "sample": "max2"}).fixtures is not None
    assert make_request({"source": sample.source + "\n", "sample": "max2"}).fixtures is None
    assert make_request({"source": sample.source}).fixtures is None


@pytest.mark.parametrize("payload", [
    {}, {"source": "x", "scale": 0}, {"source": "x", "scale": float("nan")},
    {"source": "x", "scale": True}, {"source": "x", "shape": "ring"},
    {"source": "x", "sample": "unknown"},
])
def test_invalid_requests(payload):
    with pytest.raises(ValueError):
        make_request(payload)


def test_page_assets_and_report_download(web_server):
    base, _ = web_server
    page, _ = call(base, "/")
    assert b"Code Art Studio" in page
    font, _ = call(base, "/fonts/RobotoMono-Regular.ttf")
    assert len(font) > 10000
    samples, _ = call(base, "/api/samples")
    assert len(json.loads(samples)) == 6
    data, _ = call(base, "/api/generate", {"source": "fixture"})
    identifier = json.loads(data)["id"]
    job = wait_result(base, identifier)
    assert job["result"]["checks"]["behavior"]["status"] == "NOT_RUN"
    source, headers = call(base, f"/api/jobs/{identifier}/source.c")
    assert source == job["result"]["source_text"].encode("utf-8")
    assert source.endswith(b"\n")
    assert "\r" not in source.decode()
    assert "attachment" in headers["Content-Disposition"]
    report, _ = call(base, f"/api/jobs/{identifier}/report.json")
    assert json.loads(report)["result"] == job["result"]


@pytest.mark.parametrize(("case", "status", "verified"), [
    ("pass", "OK", True),
    ("token_mismatch", "FAILED", False),
    ("hole_leakage", "FAILED", False),
    ("compiler_unavailable", "FAILED", False),
    ("wrapper_compile_failure", "FAILED", False),
])
def test_web_report_uses_e_verifier_stub(case, status, verified):
    report = make_verifier_stub(case)(None, None, None, None, None, ctx=None)
    result = GenerationResult(verification=report)

    def runner(request, *, cancel_event):
        return result

    server = create_server(0, runner=runner)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        data, _ = call(base, "/api/generate", {"source": "int f(void){return 0;}"})
        identifier = json.loads(data)["id"]
        job = wait_result(base, identifier)
        assert job["result"]["status"] == status
        assert job["result"]["verified"] is verified
        assert job["result"]["checks"] == {
            name: {"status": getattr(report, f"{name}_status").value, "reason": report.skip_reasons.get(name)}
            for name in ("token", "geometry", "compile", "behavior")
        }
        downloaded, _ = call(base, f"/api/jobs/{identifier}/report.json")
        assert json.loads(downloaded)["result"] == job["result"]
    finally:
        server.shutdown()
        server.jobs.shutdown()
        server.server_close()
        worker.join()


def test_cancel_and_reject_overlapping_job(web_server):
    base, entered = web_server
    data, _ = call(base, "/api/generate", {"source": "slow"})
    identifier = json.loads(data)["id"]
    assert entered.wait(1)
    with pytest.raises(HTTPError) as exc:
        call(base, "/api/generate", {"source": "another"})
    assert exc.value.code == 400
    call(base, f"/api/jobs/{identifier}/cancel", {})
    job = wait_result(base, identifier)
    assert job["result"]["diagnostics"][0]["code"] == "CANCELLED"
    assert all(item["status"] == "NOT_RUN" for item in job["result"]["checks"].values())


def test_reject_foreign_origin_and_missing_result(web_server):
    base, _ = web_server
    with pytest.raises(HTTPError) as exc:
        call(base, "/api/generate", {"source": "x"}, origin="https://example.com")
    assert exc.value.code == 403
    with pytest.raises(HTTPError) as exc:
        call(base, "/api/jobs/unknown")
    assert exc.value.code == 404
