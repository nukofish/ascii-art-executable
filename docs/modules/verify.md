# E 模块 · 验证与回归

`codeart.verify.verify(model, plan, rendered, fixtures, profile, *, ctx)` 接收 A 的源模型、C 的布局、D 的实际输出和 F 的运行上下文，返回 `VerificationReport`。当前可用独立测试适配器运行。待共享契约合入后，由 F 装配正式类型和词法适配器。

## 接入约定

- `model` 提供 `original_source`、`function_name` 和按原始顺序排列的有效 `tokens`。每个 token 有 `index`、`kind`、`spelling`、`width`、`source_line` 和 `source_column`。
- `plan.mask` 直接使用 B 的 `Mask`。`placements` 按 token 顺序提供 `token_index`、`row`、`col`。`protected_blanks` 记录 `(row, col)`。`rendered.position_map` 暂定为 `token_index -> (row, col)`。网格坐标从 0 起算，面向用户的源码行列从 1 起算。生成源码使用 LF，包含画布的所有行和末尾换行，行末空格可省略。
- `VerificationProfile(lex_source=..., compiler=..., flags=...)` 适配 A 的同一套原始词法和编译选项。将 A 的回调绑定成 `lex_source(text, *, ctx)`，返回带 `kind`、`spelling`、`line`、`column`、`is_comment` 的 token。回调须遵守收到的绝对截止时间和取消信号，终止自己启动的词法子进程。词法库不可用时可报 `DependencyUnavailable` 或 `FileNotFoundError`，词法超时用 `TimeoutError`，无法解析的源码可用带位置的 `LexingError`。
- 普通输入传 `fixtures=None`。内置入口调用 `select_builtin(name)`，把选择对象和其中的 `fixture.source` 交给流水线。行为测试要求选择对象指向固定注册项，并与 A 记录的原始源码及函数名完全匹配。测试包装器只加到临时编译文件，导出的源码仍是 D 的输出。
- `ctx.deadline` 是单调时钟上的绝对时间，`ctx.cancel_event` 是共享取消信号或 `None`。独立测试可以构造 `VerificationContext(monotonic() + 30, event)`。

## 报告和状态

- 词法比较完整生成源码的有效 token，忽略注释。首个差异含 0 基索引和两侧原始拼写及行列。序列一侧用尽时，该侧位置为 `None`。
- 几何直接扫描实际字符，核对边界、孔洞、保护格、占位、注释填充规则及 D 的位置和计数。覆盖率的分母是所有可填格，分子只算可填格中的非空白字符。字符串内部空格不计可见覆盖。报告分别记录画布外、掩码外和孔洞泄漏，孔洞格也计入越界合计。
- 词法通过后做 C11 对象编译，默认使用 `-std=c11 -pedantic-errors`。即使几何失败也独立报告编译结果。前三项都通过才运行行为测试。无匹配夹具时，行为项为 `NOT_RUN`，原因 `NO_FIXTURE`。匹配夹具的画布超过 100,000 格时，原因是 `OUTPUT_TOO_LARGE`。
- 编译和词法默认各限 5 秒，每个行为可执行程序的八组输入合计限 2 秒。所有操作受总截止时间约束。缺依赖、全局超时和用户取消使相关未完成项保持 `NOT_RUN`。阶段编译或执行超时使该项为 `FAIL`。macOS 和 Linux 上，编译与执行子进程在独立进程组运行，超时和取消会终止该组并回收子进程。
- `diagnostics` 保存结构化原因，`skip_reasons` 按检查名记录跳过理由，`durations` 以秒记录尝试过的阶段。`compiler` 记录实际编译器路径、版本及选项，`behavior_cases_compared` 记录实际完成的对照数。四项状态供 F 独立展示。

## 独立测试和正式回归

从仓库根目录使用可运行 pytest 的 Python 执行：

```sh
python3 -m pytest -q tests/test_shapes.py tests/test_verify.py
```

测试提供 F 可注入的四种报告夹具，见 `tests/fixtures/verification_reports.py`。矩阵测试用 B 的真实网格、测试专用布局和 Clang 原始词法适配器生成 18 份源码，实际编译并比较 144 组返回值。正式接入时，矩阵改由 A、C、D、F 的真实流水线产出。

`codeart.verification_regression.run_regression(generate_case)` 传给适配器 `(selection, shape_spec, *, ctx)`。适配器负责调用真实流水线，原样转交选择对象和共享截止时间及取消信号，并返回 `VerificationReport`。流水线未产出报告时可返回 `None`。回归总预算为 180 秒，每例最多 30 秒，适配器需支持把剩余预算传入流水线。串行回归会话缓存原函数的可执行构建和对象编译结果，结束时清理所有临时产物。

`matrix_passed` 要求 18 例的四项状态都通过，实际对照 144 次，且原函数和生成函数的可执行构建次数分别为 6 和 18。默认总覆盖率至少 0.85，每只猫耳至少 0.70。猫头放大参考通过 `cat_references` 传入，键为 1、2、4 倍，参考含眼鼻基础面积、各尺度中心和边界格容差，以及耳峰凹陷深度。缺少参考的尺度记 `NOT_RUN`，只有矩阵和三个尺度都通过时 `passed` 才为真。B 现有的 32 行基准用于基础形状测试，独立的放大验收数据待 B 提供。
