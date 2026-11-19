# Running Code Art Studio on Windows

[中文版](windows.zh-CN.md)

Every command below was run in Windows PowerShell 5.1 on Windows 11 Pro
(build 26300) on 2026-11-19. Tested versions:

| Tool | Version | Installed with |
| --- | --- | --- |
| Python | 3.11.9 (any 3.10 or later works; CI uses 3.12) | already present, `py -3.11` |
| Git for Windows | 2.56.0.windows.4 | `winget install --id Git.Git -e` |
| LLVM (Clang) | 23.1.6, target `x86_64-pc-windows-msvc` | `winget install --id LLVM.LLVM -e` |
| Node.js | 26.13.1 LTS (only for `node --check`) | `winget install --id OpenJS.NodeJS.LTS -e` |
| MSVC headers, libraries and linker | Visual Studio 2026 Community with the C++ desktop workload, Windows SDK 10.0.26100 | already present |
| libclang (Python) | 18.1.1, from `requirements.txt` | pip |

The `windows-latest` CI job uses Python 3.12 and the runner's Clang 20.1.8.

## 1. Install the tools

Clang on Windows compiles against the MSVC headers and links with the MSVC
linker. It finds them by itself, so a normal PowerShell window is enough, but
Visual Studio 2022 or later (or Build Tools for Visual Studio) with the
**Desktop development with C++** workload and a Windows SDK must be installed.
`vswhere` shows whether that is the case:

```powershell
& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
```

Install Git, LLVM and Node. Git and Node ask for administrator approval:

```powershell
winget install --id Git.Git -e --source winget
winget install --id LLVM.LLVM -e --source winget
winget install --id OpenJS.NodeJS.LTS -e --source winget
```

The LLVM installer does not put Clang on PATH. Add it to your user PATH once,
then open a new PowerShell window:

```powershell
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', $userPath.TrimEnd(';') + ';C:\Program Files\LLVM\bin', 'User')
```

Check that Clang can compile and link a C11 program:

```powershell
clang --version
Set-Content hello.c '#include <stdio.h>', 'int main(void) { puts("hello from clang"); return 0; }'
clang -std=c11 -pedantic-errors hello.c -o hello.exe
.\hello.exe
```

## 2. Clone and create the virtual environment

```powershell
git clone https://github.com/nukofish/ascii-art-executable
cd ascii-art-executable
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m codeart.environment
```

`Set-ExecutionPolicy -Scope Process Bypass` only affects the current window. It
is needed because Windows does not run `.ps1` scripts such as `Activate.ps1` by
default. Without activating, every command also works with
`.\.venv\Scripts\python.exe` in place of `python`.

## 3. Run the checks

```powershell
python -m pytest -q
python -m scripts.run_verification --output-dir "$env:TEMP\codeart-fixed"
python -m scripts.check_whole_program_samples --output-dir "$env:TEMP\codeart-samples"
node --check codeart/web/app.js
```

Expected results on this machine: pytest passes with 5 skipped tests (4 need
symlink rights, see below, and 1 needs POSIX process groups), the fixed matrix
reports `PASS fixed matrix (144/144 comparisons)` and
`Scaled cat: 1x PASS, 2x PASS, 4x PASS`, and the samples report
`9/9 whole-program samples match the original output`.

## 4. Web interface and command line

```powershell
python -m codeart.app --port 8768
```

Open <http://127.0.0.1:8768/>. Without `--port` the app uses 8765.

```powershell
python -m codeart.cli --program docs\reports\whole_program\input\task_manager.c --shape cat --output task_manager_cat.c --report task_manager_cat.json
```

Paths with Chinese characters or spaces work.

## 5. Compile and run a generated program

With Clang:

```powershell
clang -std=c11 -pedantic-errors -Wno-strict-prototypes task_manager_cat.c -o task_manager_cat.exe
cmd /c "task_manager_cat.exe < docs\reports\whole_program\stdin\task_manager.txt"
```

With MSVC, load the developer environment first. `/utf-8` is required because
the generated source is UTF-8 without a byte order mark:

```powershell
$vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
cmd /c "`"$vs\Common7\Tools\VsDevCmd.bat`" -arch=x64 -no_logo && cl /nologo /std:c11 /utf-8 task_manager_cat.c /Fe:task_manager_cat_cl.exe"
```

MSVC prints C4996 warnings for `strncpy` and `sscanf`. They come from the input
program and do not affect the result. Both executables produced exactly the
expected output for the sample input.

The programs print UTF-8, so Chinese text needs a console in code page 65001.
Check with `chcp` and switch with `chcp 65001`; the console on the test machine
was already in 65001.

## Common problems

**`clang` is not recognized.** LLVM is installed but not on PATH; see step 1.

**`fatal error: 'stdio.h' file not found`, or a linker error.** Clang cannot
find the MSVC headers or linker. Install the C++ desktop workload and a Windows
SDK, and check with the `vswhere` command in step 1.

**`Activate.ps1 cannot be loaded because running scripts is disabled`.** Run
`Set-ExecutionPolicy -Scope Process Bypass` in that window first, or call
`.\.venv\Scripts\python.exe` directly.

**Fixture or expected-output tests fail with `\r\n` differences.** Git for
Windows sets `core.autocrlf=true`. The repository's `.gitattributes` checks text
files out with LF, but a clone made before that file existed, or a branch switch
that did not rewrite unchanged files, can keep CRLF copies. Refresh the working
tree; this discards uncommitted changes:

```powershell
git rm -q -r --cached .
git reset -q --hard
git ls-files --eol tests/fixtures/shapes/metrics_h32.json
```

The last command must show `w/lf`.

**Four `test_cli.py` cases are skipped.** Windows only lets accounts with
Developer Mode or administrator rights create symlinks, so the symlink alias
cases skip themselves elsewhere.

**PowerShell shows `NativeCommandError` around normal output.** Windows
PowerShell 5.1 reports anything a program writes to stderr this way when the
output is redirected. Git progress and the command-line tool's summary go to
stderr; check the exit code instead.

**Console encoding.** The command-line tool printed the Chinese sample without
encoding errors in a 65001 console, and with its output redirected to a file
under code pages 936 and 1252. If another setup raises
`UnicodeEncodeError`, set `$env:PYTHONUTF8 = 1` and report it with the output
of `python -m codeart.environment`.

**Clang version.** The Python package pins libclang 18.1.1 with its own native
library; the `clang` executable can be newer. This setup used Clang 23.1.6 and
CI uses Clang 20.1.8. Include both versions from `python -m codeart.environment`
in bug reports.
