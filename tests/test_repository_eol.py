"""Files compared byte for byte must check out with LF on every OS."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPARED = (
    "tests/fixtures/shapes/metrics_h32.json",
    "docs/reports/whole_program/input/task_manager.c",
    "docs/reports/whole_program/stdin/task_manager.expected.txt",
    "docs/reports/whole_program/stdin/grade_stats.txt",
)


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                    reason="Requires a Git checkout")
def test_compared_text_files_check_out_as_lf():
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *COMPARED],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    attributes = {}
    for line in result.stdout.splitlines():
        path, name, value = (part.strip() for part in line.split(":"))
        attributes[path, name] = value
    for path in COMPARED:
        assert (ROOT / path).is_file(), path
        assert attributes[path, "text"] == "auto", path
        assert attributes[path, "eol"] == "lf", path


def test_compared_text_files_are_lf_on_disk():
    # The attributes only apply to files Git writes after they took effect. A
    # clone made earlier with core.autocrlf=true keeps CRLF copies; refresh it
    # as docs/windows.md describes.
    for path in COMPARED:
        assert b"\r\n" not in (ROOT / path).read_bytes(), (
            f"{path} has CRLF line endings; see 'Common problems' in docs/windows.md"
        )
