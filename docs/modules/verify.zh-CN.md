# E 模块 · 验证与回归

[English](verify.md)

`codeart.verify.verify(model, plan, rendered, fixtures, profile, *, ctx)` 接收 A 的源模型、C 的布局（含 B 的掩码）、D 的实际输出和 F 的运行上下文，返回 `VerificationReport`。正式入口 `codeart.pipeline.generate()` 默认装配这些组件。独立测试可以注入替身。

## 接入约定

- `model` 提供 `original_source`、`function_name` 和按原始顺序排列的有效 `tokens`。每个 token 有 `index`、`kind`、`spelling`、`width`、`source_line` 和 `source_column`。
- `plan.mask` 直接使用 B 的 `Mask`。`placements` 按 token 顺序提供 `token_index`、`row`、`col`。`protected_blanks` 记录 `(row, col)`。`rendered.position_map` 使用 `token_index -> (row, col)`。网格坐标从 0 起算，面向用户的源码行列从 1 起算。生成源码使用 LF，包含画布的所有行和末尾换行，行末空格可省略。
- A 的 `prepare_profile()` 默认绑定原始词法回调，流水线将 A 返回的 profile 传给 E。自定义回调遵守 `lex_source(text, *, ctx)`，返回带 `kind`、`spelling`、`line`、`column`、`is_comment` 的 token。回调须遵守截止时间和取消信号。缺依赖、分析超时、取消和总超时可通过公共 `StageError(Diagnostic(...))` 传递，E 保留原诊断。
- 普通输入传 `fixtures=None`。内置入口调用 `select_builtin(name)`，把选择对象和其中的 `fixture.source` 交给流水线。行为测试要求选择对象指向固定注册项，并与 A 记录的原始源码及函数名完全匹配。测试包装器只加到临时编译文件，导出的源码仍是 D 的输出。
- `ctx.deadline` 是单调时钟上的绝对时间，`ctx.cancel_event` 是共享取消信号或 `None`。独立测试可以构造 `VerificationContext(monotonic() + 30, event)`。

## 报告和状态

- **词法。** 忽略注释后，比较有效 token 的类别、拼写、数量和顺序。整程序模式先比较图案区的原始 token，再用同一编译器配置预处理原程序和完整输出（含移至顶部的预处理区），比较两份预处理结果的 token。两步都通过才记 `token=PASS`。仅在这一步比较中，`__LINE__`、`__DATE__`、`__TIME__` 和 `__TIMESTAMP__` 被替换为固定值：排版必然改变行号，两次预处理之间时钟也可能变化，因此 `assert` 等信息中的行号对应生成程序自身的行。展开结果中的字符串字面量比较时忽略空白：字符串化（`#x`，如 `assert` 或 `SHOW(x)` 调试宏）会复制参数 token 之间的空格，而排版会改变这些空格。图案区 token 已逐个精确比对，所以只可能是这些空格不同。首个差异记录零基索引及两侧的拼写和行列。预处理差异的行号对应产生该 token 的原程序或生成程序源码行（来自头文件时为 0；靠预处理输出中的行号标记识别来源，Windows 路径里被 Clang 转义的反斜杠会先还原），诊断指向原程序的行且不给列。序列一侧用尽时，该侧位置为 `None`。词法失败后，几何、编译和行为均为 `NOT_RUN (TOKEN_NOT_PASS)`。原始词法因缺依赖或阶段超时跳过时，仍执行独立的几何检查。
- **几何。** 整程序模式只在图案区核对实际字符、边界、孔洞、保护格、占位、注释填充及 D 的位置和计数。宽字符占两格。覆盖率的分母为可填格，分子为可填格中的非空白格。字符串中的空格不计可见覆盖。报告分别记录画布外、掩码外和孔洞泄漏，孔洞格也计入越界合计。
- **编译。** 词法通过后检查完整交付源码，默认使用 `-std=c11 -pedantic-errors`。整程序模式接受 `int main()` 一类空参数列表写法。A 报告 `has_main` 时编译并链接，否则编译为对象文件。即使几何失败也独立报告编译结果。几何通过且符合行为测试条件时，编译阶段还会构建原函数和生成函数的包装器可执行文件。任一构建失败或编译超时，编译项为 `FAIL`，行为项为 `NOT_RUN (COMPILE_NOT_PASS)`，诊断注明失败的构建。
- **行为。** 前三项通过且匹配内置夹具时才运行行为对照。通过前三项的自定义程序，行为项为 `NOT_RUN (NO_FIXTURE)`，对照次数为 0。Web 和 CLI 都不会启动自定义程序，即使已链接成功。前置检查阻止行为对照时，报告记录对应原因。匹配夹具的画布超过 100,000 格时，行为项为 `NOT_RUN (OUTPUT_TOO_LARGE)`。
- **预算。** 每次词法检查和每条编译器命令默认各限 5 秒。预处理使用编译器命令的限时。每个行为可执行程序的八组输入合计限 2 秒。所有操作受总截止时间约束。缺依赖、全局超时和用户取消使相关未完成项保持 `NOT_RUN`。阶段编译或执行超时使该项为 `FAIL`。macOS 和 Linux 上，编译与执行子进程在独立进程组运行，超时和取消会终止该组并回收子进程。Windows 上每个子进程以挂起状态启动并先放入独立的作业对象，超时和取消会结束整个作业，包括编译器包装脚本启动的进程。

F 分别展示四项状态。`PASS` 表示已检查且符合条件，`FAIL` 表示检查发现失败，`NOT_RUN` 表示跳过或未完成，报告保留原因。自定义程序的前三项通过时，网页可显示 `Verified`，Web 与 CLI 报告的行为项仍为 `NOT_RUN (NO_FIXTURE)`。

`diagnostics` 保存结构化原因，`skip_reasons` 按检查名记录跳过理由，`durations` 以秒记录尝试过的阶段。`compiler` 记录实际编译器路径、版本及选项，`behavior_cases_compared` 记录实际完成的对照数。

[v1.5 验收结论](../reports/E_verify.md#v15-budget-and-coverage-decision)记录了保留固定样例覆盖率阈值的实测依据。F 已签收整体覆盖率 **85%**、每只猫耳 **70%** 的阈值，并确认 Web 函数提取模式的预分析和生成共用 **30 秒**预算及同一取消信号。[F 浏览器验收与签收 #53](https://github.com/nukofish/ascii-art-executable/pull/53)

## 固定尺寸验收

从仓库根目录运行。使用新目录保存每次验收，固定尺寸和自动放大的证据分别归档。

```sh
python -m scripts.run_verification --output-dir docs/reports/2026-11-09-pr-review/fixed
```

将 `2026-11-09-pr-review` 换成此次验收的目录名。命令调用真实流水线，显式传入六个内置样例，把布局限制在 32 行、一次尝试。成功时输出 18 份 `case_<function>_<shape>_h32_s1.c` 和 `report.json`。报告记录 commit SHA、工作区是否有改动、每例尺寸、证据文件、四项状态、诊断、跳过原因、阶段耗时和构建计数。正式证据应来自 `checkout_dirty=false` 的提交。目录已存在时命令退出，避免覆盖历史证据。

退出码 0 表示固定尺寸矩阵通过。个案失败时，报告保留已生成的源码和失败诊断。若流水线在验证前停止，四项状态都为 `NOT_RUN`，具体原因见 `generation_diagnostics`。行为项的 `NO_FIXTURE` 和 `OUTPUT_TOO_LARGE` 都是跳过原因，计入 144 次的是实际完成的比较。

同一命令读取 B 提供的 `metrics_h{32,64,128}.json`，把猫头放大验收按 1×、2×、4× 单列在 `cat_scales` 中。h96 保留作 B 的 3× 回归。JSON 中 `passed` 要求固定矩阵和三档猫头检查全部通过，命令退出码仍对应 `fixed_matrix_passed`。缺少对应夹具或旧夹具缺少精确边界格数时，该档报告 `NOT_RUN (MISSING_REFERENCE)`。

眼鼻的预期面积统一用 h32 格数乘以倍率平方。每个孔洞的面积容差采用 B 在相应高度夹具中记录的精确 `boundary_cells` 格数。质心和耳间距也采用各档的参考值。B 以格中心为坐标，E 以零基格下标为坐标，适配器将质心的行、列各减 0.5。

## 独立测试与回归接口

从仓库根目录使用可运行 pytest 的 Python 执行：

```sh
python3 -m pytest -q tests/test_shapes.py tests/test_verify.py
```

测试提供 F 可注入的报告夹具，见 `tests/fixtures/verification_reports.py`。E 的隔离矩阵使用真实 B 掩码、测试布局和 Clang 原始词法适配器。真实流水线也有 18 个独立测试，见 `tests/test_source.py`。上面的正式命令在同一个构建会话中运行整套矩阵，保留归档证据。

`codeart.verification_regression.run_regression(generate_case)` 传给适配器 `(selection, shape_spec, *, ctx)`。适配器负责调用真实流水线，原样转交选择对象和共享截止时间及取消信号，并返回 `VerificationReport`。流水线未产出报告时可返回 `None`。回归总预算为 180 秒，每例最多 30 秒，适配器需支持把剩余预算传入流水线。串行回归会话缓存原函数的可执行构建和对象编译结果，结束时清理所有临时产物。

`matrix_passed` 要求 18 例的四项状态都通过，实际对照 144 次，且原函数和生成函数的可执行构建次数分别为 6 和 18。默认总覆盖率至少 0.85，每只猫耳至少 0.70。调用者可以用 `load_cat_references(directory)` 读取 B 的夹具，再通过 `cat_references` 传入。键为 1、2、4 倍，参考含眼鼻基础面积、各尺度中心和面积容差，以及耳峰凹陷深度。缺少参考的尺度记 `NOT_RUN`，只有矩阵和三个尺度都通过时 `passed` 才为真。

## 跨模块修改说明

- **A 和 E 共用进程工具。** 进程启动、终止和临时构建会话移到 `codeart.procutil`。`source.py` 从该模块引用 `run_command`、`BuildSession` 及相关异常。`_source_lexer.py` 改用公开的 `stop_process`，并继续由调用方等待、回收进程。改动仅涉及进程工具的归属和调用路径。调整这些接口时，同时跑 A 的源码与词法测试、E 的超时与取消测试。
- **B、C、D 通过共享数据结构交付。** 修改 mask 特征命名、坐标约定、占位或注释计数时，同步核对 `contracts.py`、E 的几何检查和固定尺寸回归。独立的图案参考由 B 提供，E 用它核对实际结果。
- **F 消费公开的报告和样例选择。** 普通输入走 `generate()`。内置入口通过 `select_builtin(name)` 取得匹配源码和选择对象，原样交给流水线，界面读取 `VerificationReport` 的四项状态及跳过原因。跨组件调用走这些入口。带下划线的模块和样例的内部构建缓存由 E 自己维护。
