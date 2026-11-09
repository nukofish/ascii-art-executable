# E 模块 · 验证与回归

`codeart.verify.verify(model, plan, rendered, fixtures, profile, *, ctx)` 接收 A 的源模型、C 的布局（含 B 的掩码）、D 的实际输出和 F 的运行上下文，返回 `VerificationReport`。正式入口 `codeart.pipeline.generate()` 默认装配这些组件。独立测试可以注入替身。

## 接入约定

- `model` 提供 `original_source`、`function_name` 和按原始顺序排列的有效 `tokens`。每个 token 有 `index`、`kind`、`spelling`、`width`、`source_line` 和 `source_column`。
- `plan.mask` 直接使用 B 的 `Mask`。`placements` 按 token 顺序提供 `token_index`、`row`、`col`。`protected_blanks` 记录 `(row, col)`。`rendered.position_map` 使用 `token_index -> (row, col)`。网格坐标从 0 起算，面向用户的源码行列从 1 起算。生成源码使用 LF，包含画布的所有行和末尾换行，行末空格可省略。
- A 的 `prepare_profile()` 默认绑定原始词法回调，流水线将 A 返回的 profile 传给 E。自定义回调遵守 `lex_source(text, *, ctx)`，返回带 `kind`、`spelling`、`line`、`column`、`is_comment` 的 token。回调须遵守截止时间和取消信号。缺依赖、分析超时、取消和总超时可通过公共 `StageError(Diagnostic(...))` 传递，E 保留原诊断。
- 普通输入传 `fixtures=None`。内置入口调用 `select_builtin(name)`，把选择对象和其中的 `fixture.source` 交给流水线。行为测试要求选择对象指向固定注册项，并与 A 记录的原始源码及函数名完全匹配。测试包装器只加到临时编译文件，导出的源码仍是 D 的输出。
- `ctx.deadline` 是单调时钟上的绝对时间，`ctx.cancel_event` 是共享取消信号或 `None`。独立测试可以构造 `VerificationContext(monotonic() + 30, event)`。

## 报告和状态

- 词法比较完整生成源码的有效 token，忽略注释。首个差异含 0 基索引和两侧原始拼写及行列。序列一侧用尽时，该侧位置为 `None`。
- 几何直接扫描实际字符，核对边界、孔洞、保护格、占位、注释填充规则及 D 的位置和计数。覆盖率的分母是所有可填格，分子只算可填格中的非空白字符。字符串内部空格不计可见覆盖。报告分别记录画布外、掩码外和孔洞泄漏，孔洞格也计入越界合计。
- 词法通过后做 C11 对象编译，默认使用 `-std=c11 -pedantic-errors`。即使几何失败也独立报告编译结果。前三项都通过才运行行为测试。无匹配夹具时，行为项为 `NOT_RUN`，原因 `NO_FIXTURE`。匹配夹具的画布超过 100,000 格时，原因是 `OUTPUT_TOO_LARGE`。
- 编译和词法默认各限 5 秒，每个行为可执行程序的八组输入合计限 2 秒。所有操作受总截止时间约束。缺依赖、全局超时和用户取消使相关未完成项保持 `NOT_RUN`。阶段编译或执行超时使该项为 `FAIL`。macOS 和 Linux 上，编译与执行子进程在独立进程组运行，超时和取消会终止该组并回收子进程。
- `diagnostics` 保存结构化原因，`skip_reasons` 按检查名记录跳过理由，`durations` 以秒记录尝试过的阶段。`compiler` 记录实际编译器路径、版本及选项，`behavior_cases_compared` 记录实际完成的对照数。四项状态供 F 独立展示。

## 固定尺寸验收

从仓库根目录运行。使用新目录保存每次验收，固定尺寸和自动放大的证据分别归档。

```sh
python -m scripts.run_verification --output-dir docs/reports/2026-11-09-pr-review/fixed
```

将 `2026-11-09-pr-review` 换成此次验收的目录名。命令调用真实流水线，显式传入六个内置样例，把布局限制在 32 行、一次尝试。成功时输出 18 份 `case_<function>_<shape>_h32.c` 和 `report.json`。报告记录 commit SHA、工作区是否有改动、每例尺寸、证据文件、四项状态、诊断、跳过原因、阶段耗时和构建计数。正式证据应来自 `checkout_dirty=false` 的提交。目录已存在时命令退出，避免覆盖历史证据。

退出码 0 表示固定尺寸矩阵通过。个案失败时，报告保留已生成的源码和失败诊断。若流水线在验证前停止，四项状态都为 `NOT_RUN`，具体原因见 `generation_diagnostics`。行为项的 `NO_FIXTURE` 和 `OUTPUT_TOO_LARGE` 都是跳过原因，计入 144 次的是实际完成的比较。

猫头放大验收单列。B 的 PR #14 提供 32、64、96 行回归基准，面积容差使用周长近似。v1.4 的独立验收仍约定 32、64、128 行，以及与真实孔洞轮廓相交的格数作为面积容差。待 B、E 对齐尺度、参考来源和容差后，再接入正式验收。固定尺寸命令报告放大项为 `NOT_RUN (MISSING_REFERENCE)`，其退出码只反映固定尺寸矩阵。

## 独立测试与回归接口

从仓库根目录使用可运行 pytest 的 Python 执行：

```sh
python3 -m pytest -q tests/test_shapes.py tests/test_verify.py
```

测试提供 F 可注入的四种报告夹具，见 `tests/fixtures/verification_reports.py`。E 的隔离矩阵使用真实 B 掩码、测试布局和 Clang 原始词法适配器。真实流水线也有 18 个独立测试，见 `tests/test_source.py`。上面的正式命令在同一个构建会话中运行整套矩阵，保留归档证据。

`codeart.verification_regression.run_regression(generate_case)` 传给适配器 `(selection, shape_spec, *, ctx)`。适配器负责调用真实流水线，原样转交选择对象和共享截止时间及取消信号，并返回 `VerificationReport`。流水线未产出报告时可返回 `None`。回归总预算为 180 秒，每例最多 30 秒，适配器需支持把剩余预算传入流水线。串行回归会话缓存原函数的可执行构建和对象编译结果，结束时清理所有临时产物。

`matrix_passed` 要求 18 例的四项状态都通过，实际对照 144 次，且原函数和生成函数的可执行构建次数分别为 6 和 18。默认总覆盖率至少 0.85，每只猫耳至少 0.70。猫头放大参考通过 `cat_references` 传入，键为 1、2、4 倍，参考含眼鼻基础面积、各尺度中心和边界格容差，以及耳峰凹陷深度。缺少参考的尺度记 `NOT_RUN`，只有矩阵和三个尺度都通过时 `passed` 才为真。

## 跨模块修改说明

- **A 和 E 共用进程工具。** 进程启动、终止和临时构建会话移到 `codeart.procutil`。`source.py` 从该模块引用 `run_command`、`BuildSession` 及相关异常。`_source_lexer.py` 改用公开的 `stop_process`，并继续由调用方等待、回收进程。改动仅涉及进程工具的归属和调用路径。调整这些接口时，同时跑 A 的源码与词法测试、E 的超时与取消测试。
- **B、C、D 通过共享数据结构交付。** 修改 mask 特征命名、坐标约定、占位或注释计数时，同步核对 `contracts.py`、E 的几何检查和固定尺寸回归。独立的图案参考由 B 提供，E 用它核对实际结果。
- **F 消费公开的报告和样例选择。** 普通输入走 `generate()`。内置入口通过 `select_builtin(name)` 取得匹配源码和选择对象，原样交给流水线，界面读取 `VerificationReport` 的四项状态及跳过原因。跨组件调用走这些入口。带下划线的模块和样例的内部构建缓存由 E 自己维护。
