# B 模块（v2）—— 图案生成 `codeart/shapes.py`

[English](shapes.md)

B 不再做图片降采样，而是**生成图案**：给定图案请求，返回一个 `Mask`——排版引擎（C）可填的
格子集合，以及校验器（F）要度量的几何特征。B 不产出任何源码。

## 接口

```python
from codeart import FontMetrics, ShapeSpec, SizeRequest, build_mask, geometry_metrics

mask = build_mask(
    ShapeSpec(kind="cat"),          # "circle" | "cat" | "code"
    SizeRequest(height_rows=32),    # 行数由 C 决定
    FontMetrics(cell_aspect=0.5),   # 项目固定常数
)
```

`build_mask(shape_spec, size_request, font_metrics, *, ctx=None) -> Mask`

| 类型 | 字段 |
|---|---|
| `FontMetrics` | `font_id: str \| None = None`、`cell_width_px: float \| None = None`、`cell_height_px: float \| None = None`；`cell_aspect` 是**推导出来的 property**（见下） |
| `SizeRequest` | `height_rows: int` |
| `ShapeSpec` | `kind: str`、`text: str \| None`、`inner_radius: float \| None` |
| `Mask` | `kind`、`width`、`height`、`allowed[row][col]`、`spans[row]`、`font_metrics`、`features`、`inner_radius`；`scale` 是**推导出来的 property** |

`ctx` 是可选的取消上下文：若提供且带 `raise_if_cancelled()` 或 `check()`，每生成一行调用一次
（鸭子类型，不硬依赖 F 的 `contracts.py`）。

### 字符度量与 `cell_aspect`

`FontMetrics` 存的是字体身份与可选的字符像素尺寸，C 用的宽高比由它们**推导**，不构成第二个权威：

| 构造方式 | `cell_aspect` |
|---|---|
| `FontMetrics()` | `0.5`（项目默认值） |
| `FontMetrics(0.5)` / `FontMetrics(cell_aspect=0.5)` | `0.5`——与 `FontMetrics()` 完全等价 |
| `FontMetrics(font_id="mono", cell_width_px=8, cell_height_px=16)` | `8 / 16 = 0.5` |

`cell_aspect` 仍是第一个参数，所以 `FontMetrics(0.5)` 继续可用；`font_id` 与字符像素尺寸是
关键字参数。项目把该比值固定为 `CELL_ASPECT_DEFAULT = 0.5`：显式 `cell_aspect` 或像素宽高对
只有落在 `CELL_ASPECT_TOLERANCE = 1e-9` 之内才被接受，否则在构造时就抛 `INVALID_SHAPE`。

### 尺寸

行数由 C 决定，B 按物理宽高比 `r` 反推列数：

```
columns = ceil(height_rows × r / cell_aspect)
```

`cell_aspect = 0.5` 时，`r = 1.0` 的图案在 32 行下是 64 列（物理宽 `64 × 0.5 = 32`，与高相等）。

`Mask.scale` 不是字段：它是只读 property，等于 `height / 2`，即"每个图案单位占多少行"
（图案归一化到 `v ∈ [-1, 1]`）。它是 **derived, not authoritative**——`Mask` 上唯一的尺寸权威
是 `width` 与 `height`，因此两者不可能互相矛盾。

| 图案 | r | 32 行 | 64 行 |
|---|---|---|---|
| `circle` | 1.0 | 64×32 | 128×64 |
| `cat` | 1.0 | 64×32 | 128×64 |
| `code` | 25/9 ≈ 2.778 | 178×32 | 356×64 |

## 三种图案

### `circle`

实心圆：格中心满足 `u² + v² ≤ 1` 即可填；`(u, v)` 为归一化坐标，`v ∈ [-1, 1]`，`u` 按
`cell_aspect` 缩放。外接矩形正好是请求的矩形，物理宽高比恒为 1.0。

### `cat`

猫头：椭圆头（`rx = 0.95`、`ry = 0.80`，中心略偏下）+ 两个三角形耳朵（耳尖顶到上边界）+
两个椭圆眼洞 + 一个鼻洞。孔洞是从实心轮廓中挖出来的，因此头部仍是一个连通的可填区域、内部有 3 个孔。

### `code`

实心矩形中挖空 **CODE** 四个字母，使用内置 5×7 点阵字形（字距 1 单位、四周留 1 单位边距，
保证笔画不贴边）。`text` 默认 `"CODE"`，传其它值抛 `INVALID_SHAPE`。字形表在
`codeart/shapes.py` 的 `_GLYPHS`，就是普通 ASCII 画，方便修改。

## `spans` 约定

`spans[row]` 是该行所有可填区间，用半开区间 `(start, end)`：

- 按 `start` 有序、互不重叠、`0 ≤ start < end ≤ width`；
- 孔洞会把一行切成多段（`cat` 与 `code` 都有多区间行，例如穿过猫眼的那几行）；
- 整行可填是 `((0, width),)`；整行不可填是 `()`。

用 spans 重建出来的行必须与 `allowed[row]` 完全一致；测试在 32/64 行下对三种图案都做了断言。

`tests/fixtures/shapes/{circle,cat,code}_32.json` 是 32 行下 `allowed` + `spans` 的固定快照
（合计约 12 KB），回归测试会逐行比对。

## `features`

命名几何，每项是 0 基 `(row, col)` 的集合：

| 键 | 含义 |
|---|---|
| `eye_left`、`eye_right` | 两个眼洞（这些格 `allowed == False`） |
| `nose` | 鼻洞 |
| `ear_left`、`ear_right` | 两只耳朵的轮廓（可填格） |
| `eyes`、`ears` | 左右两侧的并集 |
| `code_strokes` | `code` 矩形里被挖空的笔画格 |

圆没有 features（`{}`）。眼、鼻描述的是孔洞，所以它们的格子一定不可填。

## `geometry_metrics(mask)`

给校验器（E）用的度量，返回：

```
kind, cols, rows, cell_aspect,
bbox: {cols, rows, ratio},                 # ratio = cols*cell_aspect/rows
allowed_cells, spans_total, rows_with_multiple_spans,
eye_cells: {left, right}, nose_cells,
ear_gap_rows,                             # 两个耳尖之间的凹陷行数
boundary_cells: {eye_left, eye_right, nose},  # v1.5：与轮廓相交的格数
holes: [{cells, centroid: {row, col}}],   # 只统计内部孔洞
code_stroke_cells
```

### 耳峰凹陷（`ear_gap_rows`，v1.5 计划）

`ear_gap_rows` 是两个耳峰之间的凹陷。v1.5《统一验收清单——耳峰凹陷定义》把 v1.4 的
「全局最高行 + 两个耳尖质心之间的单列」改成：

1. **左右耳分别求峰**：左峰是 `features["ear_left"]` 的最高可填行，右峰同理取
   `ear_right`——一侧耳尖被削掉时，不会因此看不见另一侧的峰；
2. **固定中央区域**：凹陷底取中央列窗口 `[start, end)` 内**上边界最低**的格，其中
   `end - start = max(NOTCH_MIN_WINDOW_CELLS, round(width * NOTCH_WINDOW_FRACTION))`，
   窗口以 `width * NOTCH_CENTER_FRACTION` 为中心；
3. **以较低耳峰为基准**：深度 = `凹陷底行 - max(左峰, 右峰)`，所以被削高的耳朵只会让
   凹陷变浅，不会被另一侧"补"回来。

公开常量（`codeart` 与 `codeart.shapes` 均可导入）：

| 常量 | 默认 | 含义 |
|---|---|---|
| `NOTCH_CENTER_FRACTION` | `0.5` | 窗口中心，占 mask 宽度的比例 |
| `NOTCH_WINDOW_FRACTION` | `0.02` | 窗口宽度，占 mask 宽度的比例 |
| `NOTCH_MIN_WINDOW_CELLS` | `3` | 窗口至少三列宽 |

窗口刻意取窄：凹陷底部只在中央一小段是平的（128 行时，凹陷所在行的格覆盖
`|u| <= 0.026`，约为宽度的 2.6%），窗口再宽就会量到头顶的斜坡，把分辨率带来的行差
当成凹陷。`ear_notch_rows(mask, *, center_fraction=..., window_fraction=...)` 把同一
计算公开出来，需要时可以直接调不同窗口。

v1.5 复现用例：把 h32 左耳顶端去掉 3 格后，左、右峰分别是第 1、0 行，中央上边界在第 5
行，深度 = `5 - 1 = 4`。v1.4 在那里返回 0，因为左耳在全局最高行没有顶点；该不对称用例由
`test_ear_notch_survives_a_trimmed_ear_tip` 固定。对称模板的数值与 v1.4 一致
（h32/h64/h96/h128 分别为 5 / 10 / 15 / 20），因为窗口仍落在凹陷底部的平段上。

### 孔洞边界格（`boundary_cells`，v1.5 计划）

`hole_boundary_cells(mask, hole)` 返回给定孔洞（`eye_left`、`eye_right`、`nose`）的
**解析轮廓**与网格相交的格数——它是格中心采样孔洞面积的精确量化上界，不是面积近似公式。

算法：

- 孔洞就是 `HOLE_ELLIPSES` 里的椭圆（`(cx, cy, rx, ry)`，与 mask 光栅化用的归一化
  `(u, v)` 同一坐标系）；
- 网格来自 mask 本身：格边在 `u = (col - width/2) * 2*aspect/rows`、
  `v = row * 2/rows - 1`；
- 只要轮廓从格的**某一条边**穿进该格就计数：四条边各是一段线段，用二次方程
  `A t² + B t + C = 0` 求 `t ∈ [0, 1]` 的交点，不做角点采样、不设容差；
- 四角全在轮廓内（或全在外）的格不计数，即使轮廓与它相切——因为轮廓没有穿过任何一条边。

实测值（同时按孔洞写进 `metrics_h*.json`）：

| 孔洞 | h32 | h64 | h96 | h128 |
|---|---|---|---|---|
| 眼（每只） | 31 | 63 | 95 | 125 |
| 鼻 | 14 | 30 | 46 | 62 |

E 之前用 `max(0.02*A, 4*sqrt(A), 2)` 近似这个上界。精确格数正是那条公式想表达的量：
格中心采样的面积误差就等于轮廓穿过的格数，所以可以直接当作每个孔洞的面积容差；只有面积
信息时，公式仍可作为兜底。

## 供验收使用的放大参考数据

`tests/fixtures/shapes/metrics_h{32,64,96,128}.json` 是给 E 用的生成快照：每个文件覆盖
`circle`、`cat` 与 `code`（`text="CODE"`）三种图案在同一高度下的几何数据。重新生成：

```bash
python scripts/gen_shape_metrics.py
```

`h128` 是 E 验收高度集（h32/h64/h128）所用的高度；`h96` 为了保持连续性而保留。

脚本对每个「图案 × 高度」调用 `build_mask` + `geometry_metrics`，没有手填数字；输出确定
（两次运行字节一致），`tests/test_shape_metrics.py` 会校验 fixture 与当前实现一致。

顶层字段：

| 字段 | 含义 |
|---|---|
| `schema_version` | `1` |
| `cell_aspect` | `0.5`，项目固定的字符宽 / 字符高 |
| `height_rows` | 本文件所有图案共用的行数 |
| `generated_by` | 生成脚本路径 `scripts/gen_shape_metrics.py` |
| `tolerance` | E 使用的容差（见下） |
| `shapes` | `circle`、`cat`、`code` → 各图案的记录 |
| `scaling_expectation` | 文字说明 + 缩放公式的参考高度（`32`） |

单个图案的记录：

| 字段 | 含义 |
|---|---|
| `cols`、`rows` | mask 尺寸（列数由图案物理宽高比决定） |
| `bbox_ratio` | 占据的外接矩形比：`bbox_cols * cell_aspect / bbox_rows` |
| `allowed_cells` | 可填格数 |
| `spans_total` | 所有行上极大可填区间的总数 |
| `rows_with_multiple_spans` | 被至少一个孔洞切成多段的行数 |
| `features` | 只含命名的眼/鼻洞；`circle` 与 `code` 为 `{}` |
| `hole_count` | 命名孔洞特征数：`cat` 为 `3`，其余为 `0` |
| `ear_gap_rows` | 仅 `cat`：较低耳峰到固定窗口凹陷底的行数；其余为 `null` |

每个 feature：

| 字段 | 含义 |
|---|---|
| `cells` | 该特征的格数（即下文的 `A_ref`） |
| `bbox` | 闭区间 `[min_row, min_col, max_row, max_col]` |
| `centroid` | `[row, col]`，采用**格中心**坐标（下标 + 0.5） |
| `boundary_cells` | v1.5：该孔洞解析轮廓穿过的格数（面积量化误差的精确上界） |

### 容差口径

对 32 行下测得面积为 `A_ref` 的 feature：

```
A_expected(h) = A_ref * (h / 32) ** 2
area_limit(h) = max(area_rel * A_expected(h),
                    area_perimeter_factor * sqrt(A_expected(h)),
                    area_min_cells)
area_ok      = abs(cells(h) - A_expected(h)) <= area_limit(h)
centroid_ok  = abs(centroid(h)[axis] - centroid(32)[axis] * h / 32) <= centroid_abs_cells
```

面积项刻意做成**周长级**：参考格数是在格中心采样的，孔洞实测格数与理想连续面积之差，
来自轮廓切过的那些格，误差与孔洞**周长**成正比；而面积为 `A` 的孔洞，周长约按 `sqrt(A)`
增长，不是常数。所以任何固定的绝对格数都会两头不对：`20` 格让 32 行只有 10 格的鼻子
允许了 300% 误差，而 96 行眼睛本身 16 格的量化漂移就已经吃掉这份预算的 80%，几乎没给
真正的回归留下余量。

以 32 行为参考实测（`area_perimeter_factor = 4.0`、`area_rel = 0.02`、
`area_min_cells = 2`）：

| feature | h | `A_ref` | `A_expected` | 实测 | `area_limit` | 结论 |
|---|---|---|---|---|---|---|
| 眼 | 32 | 43 | 43 | 43 | 26.2 | 通过（参考本身） |
| 眼 | 64 | 43 | 172 | 163 | 52.5 | 通过（漂 9 格） |
| 眼 | 96 | 43 | 387 | 371 | 78.7 | 通过（漂 16 格） |
| 鼻 | 32 | 10 | 10 | 10 | 12.6 | 通过（参考本身） |
| 鼻 | 64 | 10 | 40 | 34 | 25.3 | 通过（漂 6 格） |
| 鼻 | 96 | 10 | 90 | 74 | 37.9 | 通过（漂 16 格） |

系数 4.0 对应格中心采样下圆盘边界环的规模：边界格数大致是 `4 * sqrt(A)`。这样既能容纳
实测漂移、留一点余量，又不会放过参考值错 50% 的实现。面积更大的特征由 2% 相对项主导；
`area_min_cells = 2` 避免退化成 1 格的孔洞拿到零预算。`bbox_ratio` 无量纲，四档之间差异
不得超过 `bbox_ratio_abs = 0.05`。

`centroid` 刻意存成格中心坐标：原始下标带 `-0.5` 偏置，不随 `h` 缩放；`(row + 0.5)` 才会。
`hole_count` 只数命名的眼/鼻孔洞，不等同于 `len(geometry_metrics()["holes"])`——后者在某些
分辨率下会多出 1 格的量化空洞。

### E 的断言示例

```python
doc = json.loads((FIXTURES / "metrics_h32.json").read_text())
ref, tol = doc["shapes"]["cat"]["features"]["eye_left"], doc["tolerance"]
expected = ref["cells"] * (96 / 32) ** 2
limit = max(tol["area_rel"] * expected,
            tol["area_perimeter_factor"] * expected ** 0.5,
            tol["area_min_cells"])
got = len(build_mask(ShapeSpec("cat"), SizeRequest(96), FontMetrics()).features["eye_left"])
assert abs(got - expected) <= limit  # 371 vs 387，limit 78.7
```

`tests/test_shape_metrics.py` 还会检查各档 `features` 键集合一致、面积平方缩放、质心线性缩放、
`bbox_ratio` 与高度无关，以及生成脚本的字节级幂等。另有两个反向测试守住另一边：把参考眼
格数放大 1.5 倍必须被缩放一致性断言拒绝；h96 眼睛少 100 格必须超出 `area_limit`。

## 验收指标（32 行实测）

| 指标 | 要求 | 实测 |
|---|---|---|
| 每只眼格数 | ≥ 4 | 43 / 43 |
| 鼻子格数 | ≥ 2 | 10 |
| 耳峰间凹陷 | ≥ 2 行 | 5（v1.5 换窗口后不变） |
| 圆 bbox 比 | 1.0 ± 0.05 | 1.000 |
| 确定性 | 两次调用完全相同 | 是（dataclass 相等） |
| 32 → 64 放大 | 眼面积约 ×4、几何保持 | 43 → 163（×3.79），鼻 10 → 34，凹陷 5 → 10 |

## 错误码

`build_mask` 抛共享的 `PipelineError`（`codeart.contracts`），`stage` 恒为 `shape`，
并带 `Diagnostic(code, stage, message, location=...)`：

```python
from codeart import ErrorCode, PipelineError

try:
    build_mask(ShapeSpec("circle"), SizeRequest(0), FontMetrics())
except PipelineError as exc:
    assert exc.diagnostic.code is ErrorCode.INVALID_SIZE
    assert exc.diagnostic.stage == "shape"
    assert exc.diagnostic.location == "SizeRequest.height_rows"
```

`ShapeError` 保留为 `PipelineError` 的**同义别名**（`ShapeError is PipelineError`），
所以 `except ShapeError` 与 `except StageError` 都还能接住 B 的失败；`exc.code` 仍返回纯字符串
错误码以兼容旧调用方。`diagnostic.location` 指出出错的请求字段或产出物——图案错误没有源码行号。

| code | 触发条件 |
|---|---|
| `INVALID_SHAPE` | 未知 `kind`；`text != "CODE"`；`inner_radius` 非 `None`（暂不支持环形）；`cell_aspect` 或字符像素宽高比不为 `0.5`；生成的 mask 没有任何可填格 |
| `INVALID_SIZE` | `height_rows` 不是正整数；字符度量非法（`cell_aspect`、`cell_width_px`、`cell_height_px` 非有限值或 `≤ 0`，或只给了宽没给高） |

### 空 mask 守卫

`build_mask` 返回前会校验网格：如果没有任何可填格（等价于每一行的 spans 都为空），直接抛
`PipelineError(INVALID_SHAPE)`，`location="Mask.allowed"`，而不是把一个永远填不满的画布交给 C。

## 跑测试

```bash
python -m pytest tests/test_shapes.py -q     # 44 passed
```

覆盖：三种图案在 32/64 行生成、spans 重建一致性、孔洞不可填、多区间行、上面的验收指标、
确定性、`cell_aspect`/`scale` 的推导契约、`INVALID_SHAPE` / `INVALID_SIZE` 错误码、空 mask 守卫、
`ctx` 鸭子类型钩子、v1.5 不对称耳尖用例、精确的孔洞边界格数，以及 fixture 回归。
