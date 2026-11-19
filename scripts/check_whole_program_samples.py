"""Regenerate the whole-program samples and compare their output with the originals.

For each program in docs/reports/whole_program/input and each shape, generate the
artwork, build the generated program with the same Clang the tool uses, feed it
the recorded stdin and require byte-identical output and a zero exit status.
Works on macOS, Linux and Windows.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from codeart.contracts import GenerationRequest, ShapeSpec
from codeart.pipeline import generate


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "reports" / "whole_program"
SHAPES = ("cat", "circle", "code")
EXE = ".exe" if os.name == "nt" else ""


def _build(clang, source, binary):
    subprocess.run([clang, "-std=c11", "-pedantic-errors", str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path,
                        help="keep generated sources here (default: a temporary folder)")
    args = parser.parse_args(argv)

    clang = shutil.which("clang")
    if clang is None:
        print("clang not found on PATH", file=sys.stderr)
        return 2
    work = args.output_dir or Path(tempfile.mkdtemp(prefix="codeart-samples-"))
    work.mkdir(parents=True, exist_ok=True)

    failures = 0
    for source in sorted((SAMPLES / "input").glob("*.c")):
        name = source.stem
        stdin = (SAMPLES / "stdin" / f"{name}.txt").read_bytes()
        expected = (SAMPLES / "stdin" / f"{name}.expected.txt").read_bytes()
        for shape in SHAPES:
            label = f"{name} {shape}"
            result = generate(GenerationRequest(
                source.read_text(encoding="utf-8"),
                ShapeSpec(shape, "CODE" if shape == "code" else None),
                program_mode=True,
            ))
            if result.status.value != "OK":
                failures += 1
                details = "; ".join(f"{item.code.value}: {item.message}" for item in result.diagnostics)
                print(f"FAIL {label}: {result.status.value} {details}")
                continue
            generated = work / f"{name}_{shape}.c"
            generated.write_text(result.rendered.source_text, encoding="utf-8", newline="")
            binary = work / f"{name}_{shape}{EXE}"
            try:
                _build(clang, generated, binary)
            except subprocess.CalledProcessError as exc:
                failures += 1
                print(f"FAIL {label}: build failed\n{exc.stderr}")
                continue
            run = subprocess.run([str(binary)], input=stdin, capture_output=True, timeout=10)
            # Text mode on Windows writes CRLF; compare line content only.
            actual = run.stdout.replace(b"\r\n", b"\n")
            if run.returncode != 0 or actual != expected.replace(b"\r\n", b"\n"):
                failures += 1
                print(f"FAIL {label}: exit {run.returncode}, output differs")
                continue
            print(f"PASS {label}")

    total = len(list((SAMPLES / "input").glob("*.c"))) * len(SHAPES)
    print(f"{total - failures}/{total} whole-program samples match the original output")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
