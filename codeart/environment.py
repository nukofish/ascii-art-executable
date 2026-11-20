"""Collect reproducible environment information without exposing credentials."""

from importlib.metadata import PackageNotFoundError, version
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys

from .presentation import FONT_ID


def revision_info(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    # An installed package has no checkout of its own; asking git there would
    # report whatever repository the environment happens to sit in.
    if not (root / ".git").exists():
        return {"commit": None, "dirty": None}
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                         text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
        changes = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"],
                                          text=True, stderr=subprocess.DEVNULL, timeout=2)
        return {"commit": commit, "dirty": bool(changes.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def environment_info():
    packages = {}
    for name in ("code-art-studio", "libclang", "pytest"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    compiler = shutil.which("clang")
    compiler_version = None
    if compiler:
        try:
            result = subprocess.run([compiler, "--version"], capture_output=True,
                                    text=True, timeout=5, check=True)
            compiler_version = result.stdout.splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            compiler_version = "unavailable"
    return {
        "python": sys.version.split()[0], "platform": platform.platform(),
        "packages": packages, "compiler": compiler, "compiler_version": compiler_version,
        "font": FONT_ID, "cell_aspect": 0.5,
        "revision": revision_info(),
    }


if __name__ == "__main__":
    print(json.dumps(environment_info(), indent=2))
