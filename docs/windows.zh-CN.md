# 在 Windows 上运行 Code Art Studio

[English](windows.md)

下面的命令都于 2026 年 11 月 19 日在 Windows 11 Pro（build 26300）的
Windows PowerShell 5.1 中实际运行过。实测版本：

| 工具 | 版本 | 安装方式 |
| --- | --- | --- |
| Python | 3.11.9（3.10 及以上均可，CI 用 3.12） | 本机已有，`py -3.11` |
| Git for Windows | 2.56.0.windows.4 | `winget install --id Git.Git -e` |
| LLVM（Clang） | 23.1.6，目标 `x86_64-pc-windows-msvc` | `winget install --id LLVM.LLVM -e` |
| Node.js | 26.13.1 LTS（只用于 `node --check`） | `winget install --id OpenJS.NodeJS.LTS -e` |
| MSVC 头文件、库和链接器 | Visual Studio 2026 Community，含 C++ 桌面开发工作负载，Windows SDK 10.0.26100 | 本机已有 |
| libclang（Python 包） | 18.1.1，见 `requirements.txt` | pip |

CI 的 `windows-latest` 任务使用 Python 3.12 和运行器自带的 Clang 20.1.8。

## 1. 安装工具

Windows 上的 Clang 使用 MSVC 的头文件和链接器，它会自己找到它们，所以普通
PowerShell 窗口就够了；但必须装有 Visual Studio 2022 或更新版本（或 Visual
Studio 生成工具），并包含 **使用 C++ 的桌面开发** 工作负载和 Windows SDK。
可以用 `vswhere` 检查：

```powershell
& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
```

安装 Git、LLVM 和 Node。Git 和 Node 会请求管理员确认：

```powershell
winget install --id Git.Git -e --source winget
winget install --id LLVM.LLVM -e --source winget
winget install --id OpenJS.NodeJS.LTS -e --source winget
```

LLVM 安装程序不会把 Clang 加入 PATH。执行一次下面的命令加入用户 PATH，然后
打开一个新的 PowerShell 窗口：

```powershell
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', $userPath.TrimEnd(';') + ';C:\Program Files\LLVM\bin', 'User')
```

确认 Clang 能编译并链接 C11 程序：

```powershell
clang --version
Set-Content hello.c '#include <stdio.h>', 'int main(void) { puts("hello from clang"); return 0; }'
clang -std=c11 -pedantic-errors hello.c -o hello.exe
.\hello.exe
```

## 2. 克隆并创建虚拟环境

```powershell
git clone https://github.com/nukofish/ascii-art-executable
cd ascii-art-executable
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m codeart.environment
```

`Set-ExecutionPolicy -Scope Process Bypass` 只对当前窗口生效。Windows 默认
不运行 `Activate.ps1` 这类 `.ps1` 脚本，所以需要这一步。不激活也可以，把下文
命令里的 `python` 换成 `.\.venv\Scripts\python.exe` 即可。

## 3. 运行检查

```powershell
python -m pytest -q
python -m scripts.run_verification --output-dir "$env:TEMP\codeart-fixed"
python -m scripts.check_whole_program_samples --output-dir "$env:TEMP\codeart-samples"
node --check codeart/web/app.js
```

`scripts.run_verification` 不接受已经存在的 `--output-dir`（报
`[WinError 183]`），再次运行前请删除该目录或换一个新目录。

本机的结果：pytest 全部通过，跳过 5 项（4 项需要创建符号链接的权限，见下文；
1 项需要 POSIX 进程组）；固定验收输出 `PASS fixed matrix (144/144 comparisons)`
和 `Scaled cat: 1x PASS, 2x PASS, 4x PASS`；整程序样例输出
`9/9 whole-program samples match the original output`。

## 4. 网页界面和命令行

```powershell
python -m codeart.app --port 8768
```

在浏览器打开 <http://127.0.0.1:8768/>。不加 `--port` 时使用 8765 端口。

```powershell
python -m codeart.cli --program docs\reports\whole_program\input\task_manager.c --shape cat --output task_manager_cat.c --report task_manager_cat.json
```

路径里有中文或空格也没有问题。

## 5. 编译并运行生成的程序

用 Clang：

```powershell
clang -std=c11 -pedantic-errors -Wno-strict-prototypes task_manager_cat.c -o task_manager_cat.exe
cmd /c "task_manager_cat.exe < docs\reports\whole_program\stdin\task_manager.txt"
```

用 MSVC 时要先加载开发者环境。生成的源码是不带 BOM 的 UTF-8，所以必须加
`/utf-8`：

```powershell
$vs = & "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
cmd /c "`"$vs\Common7\Tools\VsDevCmd.bat`" -arch=x64 -no_logo && cl /nologo /std:c11 /utf-8 task_manager_cat.c /Fe:task_manager_cat_cl.exe"
```

两个编译器都会提示 `strncpy` 和 `sscanf` 已弃用（Clang 的
`-Wdeprecated-declarations`，MSVC 的 C4996）。这是 Microsoft C 运行库的标记，
调用来自输入程序本身，不影响结果。两个可执行文件对样例输入的输出都与期望完全一致。

程序输出 UTF-8，所以中文要在代码页 65001 的控制台里才能正常显示。用 `chcp`
查看，用 `chcp 65001` 切换；测试机器的控制台本来就是 65001。

## 常见问题

**提示无法识别 `clang`。** LLVM 已安装但不在 PATH 里，见第 1 步。

**`fatal error: 'stdio.h' file not found`，或链接报错。** Clang 找不到 MSVC 的
头文件或链接器。安装 C++ 桌面开发工作负载和 Windows SDK，再用第 1 步的
`vswhere` 命令检查。

**`Activate.ps1` 因为禁止运行脚本而无法加载。** 先在该窗口执行
`Set-ExecutionPolicy -Scope Process Bypass`，或者直接调用
`.\.venv\Scripts\python.exe`。

**fixture 或期望输出相关的测试因 `\r\n` 不同而失败。** Git for Windows 默认设置
`core.autocrlf=true`。仓库的 `.gitattributes` 会让文本文件以 LF 检出，但在
该文件加入之前克隆的仓库，或者切换分支时没有重写的文件，仍可能是 CRLF。
用下面的命令刷新工作区（会丢弃未提交的修改）：

```powershell
git rm -q -r --cached .
git reset -q --hard
git ls-files --eol tests/fixtures/shapes/metrics_h32.json
```

最后一条命令应显示 `w/lf`。

**`test_cli.py` 有 4 项被跳过。** Windows 只允许开启了开发者模式或有管理员权限
的账户创建符号链接，没有这个权限时，符号链接相关的用例会自动跳过。

**PowerShell 在正常输出周围显示 `NativeCommandError`。** 输出被重定向时，
Windows PowerShell 5.1 会这样标记程序写到 stderr 的内容。Git 的进度信息和
命令行工具的摘要都写到 stderr，请以退出码为准。

**控制台编码。** 命令行工具在 65001 控制台中输出中文样例没有编码错误；在
936 和 1252 代码页下把输出重定向到文件也没有出错。如果其他环境出现
`UnicodeEncodeError`，先设置 `$env:PYTHONUTF8 = 1`，并附上
`python -m codeart.environment` 的输出反馈问题。

**Clang 版本。** Python 包固定 libclang 18.1.1，自带原生库；`clang` 可执行文件
可以更新。本次实测用 Clang 23.1.6，CI 用 Clang 20.1.8。反馈问题时请附上
`python -m codeart.environment` 中的两个版本。
