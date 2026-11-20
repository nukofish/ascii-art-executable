# Code Art Studio

[English](README.md) · 简体中文

粘贴或打开一份完整的 C11 程序，把它排成圆形、猫头或镂空 CODE，再复制或下载
生成的 `.c` 文件。排版先用源程序里的 token 选择紧凑画布，再把短注释分散到
剩余空位。也可以输入单函数、从文件提取函数或运行内置样例。

libclang 检查 token 是否保持，Clang 编译生成结果。词法、几何、编译和行为
四项检查分别展示。

## 安装

需要 Python 3.10 或更新版本，以及支持 C11 的 Clang 编译器。

macOS 缺少编译器时，先运行 `xcode-select --install`。
Ubuntu 24.04 可以运行以下命令：

```sh
sudo apt-get update
sudo apt-get install -y clang-18
export PATH="/usr/lib/llvm-18/bin:$PATH"
```

在仓库根目录创建环境并安装固定版本依赖：

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m codeart.environment
python -m pytest -q
```

Windows 上的 Clang 使用 MSVC 的头文件和链接器，所以还需要安装含 C++ 桌面
开发工作负载的 Visual Studio 或其生成工具。在 PowerShell 中的对应步骤、实测
版本和常见问题见 [在 Windows 上运行](docs/windows.zh-CN.md)。

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass -Force
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m codeart.environment
python -m pytest -q
```

`requirements.txt` 用于运行，固定 `libclang==18.1.1`，包含 Python
绑定及原生库。开发依赖另外固定 pytest 9.2.0。请用
`python -m pip`，确保安装与运行使用同一个解释器。

## 当前状态

`0c80b7b` 基线已通过 328 项测试、18 份固定尺寸输出、144 次行为对照，
以及猫头 1×、2×、4× 检查。[main@0c80b7b 的 Ubuntu 全量 CI](https://github.com/nukofish/ascii-art-executable/actions/runs/42843452033)
也已通过全量套件；这次 CI 未运行正式验收矩阵。

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 固定 h32 矩阵 | 基线 PASS | 18 份输出的四项检查通过 |
| 内置样例行为 | 基线 PASS | 实际完成 144 次比较 |
| 猫头 h32/h64/h128 | 基线 PASS | E 已加载 B 的参考数据 |
| 普通或修改后的输入 | 行为 NOT_RUN | 原因为 NO_FIXTURE |
| 超过行为尺寸限制 | 行为 NOT_RUN | 原因为 OUTPUT_TOO_LARGE |
| 当前 CI | 查看实际运行 | [GitHub Actions](https://github.com/nukofish/ascii-art-executable/actions/workflows/tests.yml) |
| 各成员完成检查表 | 分别记录版本 | [报告目录](docs/reports/README.md) |

历史报告保留原提交的结果，包括当时的 NOT_RUN。判断新版本时，重新运行
验收并读取新报告，不能仅根据旧报告或退出码认定全部通过。

## 本地网页

```sh
python -m codeart.app
```

打开 **http://127.0.0.1:8765**。端口被占用时使用 `--port 8766`。

1. 选择六个内置样例之一，或打开、粘贴 C 源码。
2. 选择圆形、猫头或镂空 CODE，以及 1 到 4 的初始倍率。
3. 网页默认勾选 **Arrange a complete C program**。预处理指令和完整条件编译块
   保留在顶部，与下方图案隔两行。
4. 生成后查看原文、图案、实际尺寸、倍率、尝试次数、覆盖率和四项检查。
5. 用 **Copy code** 复制或下载完整源码。也可以查看诊断、布局历史和 JSON 报告。
6. 生成过程中可以取消，已完成的结果会保留。

网页只监听本机回环地址，同时运行一个生成任务，在内存中保留最近五次结果。
重启服务或结果被淘汰前，请保存下载。按 Ctrl+C 请求取消并关闭服务。
网页不会执行用户程序。自定义程序的行为检查为 `NOT_RUN`，需要手动运行下载文件确认交互行为。

图案预览随可用空间缩放，保持各行和孔洞对齐。汉字和全角标点占两格。
预览使用仓库附带的 Roboto Mono Regular，缺少的字形由系统字体补齐。
详见 [F 的应用说明](docs/modules/app.md)。

## 命令行

运行真实内置样例并进行行为对照：

```sh
python -m codeart.cli --sample max2 --shape cat --scale 1.5 \
  --output max2_cat.c --report max2_cat.json
```

验证普通输入：

```sh
python -m codeart.cli --source example.c --shape circle --output generated.c
```

排版并输出一份完整 C 程序：

```sh
python -m codeart.cli --program task_manager.c --shape cat \
  --output task_manager_art.c --report task_manager_art.json
```

完整程序模式把 `#include`、宏指令及整块条件编译区域移到输出顶部，剩余源码 token
按原顺序一起排版。验证会比较预处理后的 token，并对最终完整源码进行编译；
含 `main` 时还会链接。普通输入不会自动执行，因此行为检查显示
`NOT_RUN (NO_FIXTURE)`。如果移动指令会改变宏展开，生成会以 token 检查失败，
不会把不同含义的输出标成通过。当前整文件输入不解析相对路径引用的本地头文件。
指令必须能安全移到顶部。含代码的条件编译块（`#if`/`#ifdef`）只能出现在第一个声明之前；
函数体内或已有代码之后的此类块会在其 `#if` 所在行被拒绝，代码之后的 `#undef` 同样拒绝。
程序可以使用 `assert`、`__LINE__` 及日期时间宏，它们报告的行号对应生成后的程序；字符串化（`#x`，如 `assert` 消息）产生的文本按生成程序的空格排版。

样例包括 max2、min2、clamp、absdiff、gcd、sum_to_n，每个有八组固定输入。
普通输入和修改后的样例没有匹配夹具，行为检查显示
`NOT_RUN (NO_FIXTURE)`，同名函数不会自动取得行为执行资格。
源码文件、生成文件和 JSON 报告应使用不同路径。

检查失败或流水线有诊断时返回非零退出码。普通输入在词法、几何、编译通过、
行为因没有夹具而跳过时，可以正常返回成功。`--demo` 保留早期模拟流程，
其中的验证明确标为未运行。

## 输入范围

整文件模式支持 UTF-8 C 源码。字符串、标识符和预处理区中的汉字会保留，
图案里的汉字按两格排版。`int main()` 和其他使用空参数列表的无参函数可直接输入。

单函数模式接收一个使用可打印 ASCII 的自包含 C11 函数。支持参数、局部变量（含
`static` 和 `static const`）、`__func__` 和自身递归。拒绝外部声明、预处理依赖、
反斜杠续行、三字符组、token 内的真实 tab、预定义宏名（`__LINE__`、`__FILE__`、`__COUNTER__` 等，
不需要 `#` 也拒绝）以及 GNU 扩展关键字（`__asm__` 等）。
详见 [A 的源码说明](docs/modules/source.md)。

结果提供词法保持、编译通过及给定样例行为一致的证据。没有执行的检查显示
NOT_RUN 和原因；几何失败时不会显示整体验证通过。

## 正式验收

```sh
python -m scripts.run_verification --output-dir docs/reports/local-check/fixed
```

每次使用一个尚不存在的新目录。报告记录 commit、工作区状态、18 份 h32
输出和实际行为比较次数，同时核对猫头的 h32/h64/h128 参考数据。
请检查 `report.json` 的 `passed`，它合并固定矩阵和放大检查结果。
验收命令的退出码目前仅反映固定矩阵。

[验证说明](docs/modules/verify.zh-CN.md)、
[报告目录及自动放大演示](docs/reports/README.md)、
[F 的后续交付记录](docs/reports/F_delivery.md)。

## CI

当前 CI 采用 #27 已合并的配置：Ubuntu 使用 ubuntu-latest、Python 3.12、
固定 clang-18 和 pip 提供的 libclang 18.1.1。Ubuntu 全量任务限时 30 分钟；
clang-18 不装推荐包，下载的软件包按运行器镜像缓存，因为运行器的 Ubuntu 镜像源
有时很慢。全量任务检查依赖导入、记录环境、检查前端脚本语法和测试数量，再运行
完整测试套件。
Windows 全量任务在 windows-latest 上用 Python 3.12 和运行器自带的 Clang，
以 PowerShell 运行完整测试、固定验收、整程序样例，以及用中文程序运行命令行
工具。每一步在前面失败时也照常执行，一次运行就能看到全部 Windows 问题。
正式验收需另行运行上面的 `scripts.run_verification` 命令；当前 CI 不自动
生成或上传正式验收报告。已有验收证据请按报告中的 commit 核对。

| 事件 | Ubuntu 快速检查 | Ubuntu 全量 | Windows 全量 | macOS 附加全量 |
| --- | --- | --- | --- | --- |
| PR 创建、更新、重开（无标签） | 运行 | 运行 | 运行 | 跳过 |
| PR 仅有 macos-ci 标签 | 运行 | 运行 | 运行 | 运行 |
| 推送 main 或 v* 标签 | 运行 | 运行 | 运行 | 跳过 |
| Actions 手动运行 | 运行 | 运行 | 运行 | 运行 |

每个 PR 都运行两个 Ubuntu 任务和 Windows 任务。需要 Apple Clang 验证时，添加 `macos-ci`
标签；也可以在 Actions 中手动运行 Python tests，一次运行两个平台。macOS
运行器容量不足可能延迟附加检查。
同一 PR 的新事件会取消旧运行。PR 应写明实际命令、测试结果和环境版本。

## 参考资料

创意背景（IOCCC、donut.c）、GCC/Clang 词法参考、Roboto Mono 字体与 OFL、
运行/测试依赖见 [docs/references.md](docs/references.md)。donut.c 只作为
“源码排版成图形”的创意来源，未复用其代码、数学或渲染方式。

## Clang 与 libclang 排错

**找不到 clang 命令**

Clang 编译器与 Python libclang 包需要分别安装。macOS 使用 Apple 开发者
命令行工具，Ubuntu 按上面的 Clang 18 命令安装。安装后先检查
`clang --version` 和 `python -m codeart.environment`。

**No module named clang 或原生库加载失败**

```sh
python -m pip install -r requirements-dev.txt
python -m pip show libclang
python -c "import clang.cindex; clang.cindex.Index.create(); print('libclang loaded')"
```

Apple Clang 命令可用，并不代表当前 Python 已安装绑定。项目固定的
`libclang==18.1.1` 自带原生库；不要在同一个环境额外安装同名命名空间的
`clang` 包。如果已有环境混装，创建一个新虚拟环境再安装仓库依赖。

**换终端后测试结果不同**

比较 `python -m codeart.environment`、`python -m pip --version`
与 `clang --version`，检查虚拟环境和 PATH。反馈时附上版本、命令、输入和诊断。

**检查显示 NOT_RUN**

`NO_FIXTURE` 表示没有行为夹具，`OUTPUT_TOO_LARGE` 表示因尺寸跳过行为。
`DEPENDENCY_UNAVAILABLE` 则需要修复安装，不能记为通过。

## 整份 C 文件提取 / Complete-file extraction

`--source` 仍是 v1.4 的单函数入口。`--file` 是 F 层可选的便利功能：在完整
C 文件中定位候选函数，逐个交给 A 的真实分析器，只把选中的函数交给
`generate()`。`generate()` 和 A 仍然只接受一个自包含函数。2026-11-10
组内确认把它作为 v1.5 扩展接纳；v1.4 冻结验收仍使用单函数入口，正式验收
请继续使用 `--sample`/`--source`。

重复的可选函数名会报 `AMBIGUOUS_FUNCTION`；只有名字唯一时才应使用 `--function`。

```sh
python -m codeart.cli --file example.c --function helper --shape circle --output helper_art.c --report helper_report.json
```

定位器会先屏蔽注释、字面量和预处理指令行，再匹配花括号；注释或宏体里的
`#if`/`#endif` 不会误改条件区域。输入统一 CRLF/单独 CR，并剥离开头的
UTF-8 BOM。`main` 和条件编译区域里的函数不合格。省略 `--function` 时选择
第一个通过的候选。函数指针、括号包住函数名等声明符由 A 返回的
`function_name` 命名，不依赖定位器的正则。外部 typedef、宏、全局对象和
其它函数不会复制；抽出函数内部的注释和字面量保留，是否可用由 A 判定。

定位器是词法定位，不是完整 C 解析器或预处理器：K&R 风格定义和部分宏生成
的声明可能列不出来；条件区域按保守策略排除。JSON 的 `prepass` 记录候选、
选择、忽略行区间，以及同一行前后缀的精确 `ignored_segments`；它不声称
整个程序通过验证。自定义抽取没有内置行为夹具，行为检查为
`NOT_RUN (NO_FIXTURE)`。

网页中勾选 **Extract from a complete C file**，点击 **Find functions**，
再选择 PASS 候选。失败候选显示 A 映射回原文件的行列。生成时会重新检查
选中的函数。只验证抽出的函数，不代表原程序已验证。

`code_fill_ratio` 是有效非空白 token 墨迹除以可填格数（即渲染器的 token
覆盖率），不计填充注释。普通输入模式下，低于 10% 时显示
`Token density is low; filler comments occupy most allowed cells.`，只作信息提示，
不影响验证或布局，也不给出尺寸建议。整程序模式先按原代码选择紧凑画布，
在确实有余量时，用短块注释把填充分散到 token 之间。
