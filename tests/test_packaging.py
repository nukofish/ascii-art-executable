"""The pip package ships every runtime file and reports its own revision only."""

from fnmatch import fnmatch
import shutil
import subprocess
from pathlib import Path

import pytest

from codeart import __version__
from codeart.environment import revision_info

ROOT = Path(__file__).resolve().parents[1]


def _pyproject():
    tomllib = pytest.importorskip("tomllib")
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_data_covers_every_web_asset():
    patterns = _pyproject()["tool"]["setuptools"]["package-data"]["codeart"]
    package = ROOT / "codeart"
    missing = [
        path.relative_to(package).as_posix()
        for path in (package / "web").rglob("*")
        if path.is_file() and not any(
            fnmatch(path.relative_to(package).as_posix(), pattern) for pattern in patterns
        )
    ]
    assert missing == []


def test_console_scripts_point_at_existing_entry_points():
    import importlib

    for target in _pyproject()["project"]["scripts"].values():
        module, function = target.split(":")
        assert callable(getattr(importlib.import_module(module), function)), target


def test_version_is_a_release_number():
    assert all(part.isdigit() for part in __version__.split("."))


@pytest.mark.skipif(shutil.which("git") is None, reason="Requires git")
def test_installed_package_does_not_report_the_surrounding_repository(tmp_path):
    # A virtual environment inside some other project: site-packages has no
    # .git of its own, so the enclosing repository must not be reported.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    site_packages = tmp_path / ".venv" / "lib" / "site-packages"
    site_packages.mkdir(parents=True)
    assert revision_info(site_packages) == {"commit": None, "dirty": None}


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(),
                    reason="Requires a Git checkout")
def test_checkout_reports_its_commit():
    assert len(revision_info()["commit"]) == 40
