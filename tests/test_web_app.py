"""Run browser-event regressions with Node when it is available."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_web_application_event_regressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the web application event regressions")
    result = subprocess.run(
        [node, str(Path(__file__).with_name("web_app_regressions.cjs"))],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
