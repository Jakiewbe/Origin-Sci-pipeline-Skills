# OriginPro 2024 (.opju) 无头工程与原生直出架构指南

> **架构铁律**：本管线在默认模式下（`skip_origin=False`）由 **OriginPro 2024 (`10.1.0.178`, `originpro 1.1.15` + `OriginExt 1.2.5`)** 100% 原生构建可编辑 `.opju` 工程，并在同一无头会话末尾通过 `expGraph`（`tr.Margin:=2`）直接导出像素完全同源的 `600 DPI` LZW 无损 `.tif`、`300 DPI .png` 及 `_qa_previews/*_preview.jpg`。

---

## 1. 会话生命周期、命名洁净与 3 条 `OriginExt` 崩溃红线

1. **进程零残留铁律（`op.set_show(False)` + `try ... finally: op.exit()`）**：
   - 在安装有 `originpro` 的 Python 环境（由 `invoke_sciorigin.ps1` 自动探测）中导入 `originpro as op` 会拉起后台 `Origin.ApplicationSI`（`Origin64.exe`）。所有建图与导出逻辑必须包裹在 [origin_builder.py](../scripts/origin_builder.py) / [origin_renderer.py](../scripts/origin_renderer.py) 的会话保护块内；批量处理在单次会话中通过 `op.new()` 切换，严禁频繁冷启动 COM。
   - 原位更新可能被占用的 `.opju` 时，先备份原文件并 `op.save(tmp_path)`，待 **`op.exit()` 彻底释放句柄后再移动覆盖目标路径**。
2. **内部短名与元数据规范**：
   - `wks.name`、`ms.name` 与图页 `gp.name` **只允许纯 ASCII 字母数字（禁止含下划线 `_`、空格、括号或连字符，长度 `≤ 24`）**，否则 Origin 会静默截断改名导致 `plotxy` 找不到目标；完整科学名称（含样品代号、化学式、括号说明）一律写入 `lname`（Long Name），列名称与单位通过 `wks.set_label(col_idx, text, 'L')` 与 `'U'` 写入。
3. **3 条致命 `OriginExt` COM 崩溃守卫（实测必避）**：
   - **守卫 A（禁对 `gl.plot_list()[i]` 读属性或调命令）**：在 `OriginExt 1.2.5` 下访问 `gl.plot_list()[i].color` / `.transparency` 或调 `.set_cmd()` 会触发 `OriginExt::OriginObject::GetIndex ==> 灾难性故障 (E_UNEXPECTED)`。`gl.plot_list()` 仅用于 `len(...)` 计数；修改已有曲线一律走 `GLayer` 1-based LabTalk 索引：`gl.set_int(f"plot{k}.color", c_int)`、`gl.lt_exec(f"range rr = !{k}; set rr -w 1400;")`。
   - **守卫 B（`expGraph` / `save_fig` 使 `Plot.obj` 句柄失效）**：调用 `expGraph` 或 `gp.save_fig(...)` 会使此前持有的 `Plot.obj` COM 指针失效，其后再读写 `p.obj.Theme` 必抛灾难性故障。**导图必须在当前图页全部样式与 `Theme` 提交彻底完成后最后执行**。
   - **守卫 C（严禁递归遍历 `TreeNode.Children`）**：`p.obj.Theme` 包含二进制色表节点，递归遍历 `.Children` 会导致 Origin RPC 服务直接崩溃退出；仅按已知路径定向调用 `SetIntValue(val, "Key")` / `SetDoubleValue(val, "Key")` / `SetStrValue(val, "Key")`（注意 SWIG 参数顺序：**值在前、键名在后**）。

---

## 2. 数据容器设计（`WSheet` 与 `MSheet`）

1. **异构多曲线对比：优先 `XYXY` 成对列 + `Raw_Unshifted` 追溯表**：
   - 多样品 XRD、短脉冲瞬态、EIS 或 `dQ/dV` 的横坐标网格往往不完全对齐；采用 `wks.from_list(2*i, x, axis='X')` + `wks.from_list(2*i+1, y, axis='Y')` 保留每条曲线真实采样点，不强行重采样插值，并在附加工作表保存未平移/未归一化的原始数据。
2. **单指标多样品不同语义色渐变柱：`1 + 2N` 对角稀疏工作表**：
   - 列轴设为 `wks.cols_axis("X" + "YE" * N)`（第 `0` 列存语义样品名，后接 `N` 对 `Y_i, SD_i`，第 `i` 行仅填第 `i` 对数值，其余填 `""`），逐对 `gl.add_plot(wks, coly=1+2*i, colx=0, colyerr=2+2*i, type='c')` 且**不调用 `gl.group()`**，即可让每根柱子居中于对应类目并拥有独立的双色渐变、误差棒与柱顶同色标签。
3. **二维连续场与热力图：矩阵簿 `MBook / MSheet`**：
   - `mb = op.new_book("m")` → `ms = mb[0]` → `ms.from_np(z_matrix)`：输入数组必须满足 **`z_matrix.shape == (ny, nx)`**（列数 `nx` 对应横轴 `[x1, x2]`，行数 `ny` 对应纵轴 `[y1, y2]`），随后赋 `ms.xymap = (x1, x2, y1, y2)` 并通过 `ms.set_label('x'/'y', text, 'L')` 写入物理轴标签。
4. **统计分布（箱线/抖动散点/小提琴）**：
   - 各组平行样写入多 `Y` 列（`wks.cols_axis("Y" * K)`，列 Long Name 即分类名），用 `op.make_DataRange("Y", (wks, 0), "S", "Y", (wks, 1), ...)` 打包范围。

---

## 3. 原生图型码（`IDM_PLOT_*`）与页面/图层物理单位体系

### 3.1 `gl.add_plot` / `gl.add_mplot` 整数图型码速查
`originpro` 除支持简写（`"l": 200`, `"s": 201`, `"y": 202`, `"c": 203`, `"contour": 226`）外，原生支持直接传入 `oPlotIDs.h` 中的任意整数 `IDM_PLOT_*`：
- `200` / `201` / `202`：折线（光谱包络/瀑布/脉冲）/ 散点（XPS `Raw` `-k 20`）/ 点线（EIS、Ragone、双 Y 前景元素线）
- `203` + 模板 `"COLUMN"`：簇状并排分组柱状图（`IDM_PLOT_COLUMN`）
- **`213` + 模板 `"STACKCOLUMN"` / `"StackColP"`**：**绝对值堆积柱 / 100% 百分比堆积柱（`IDM_PLOT_COLUMN_STACK`）**——**严禁误传 `203` 或调用 `layer -g`**！
- `206` + 模板 `"BOX+DATA+OVERLAP"` / `"ViolinBox"`：箱线+抖动散点 / 小提琴图（添加后调 `gl.group(False)` 解组逐列赋语义色）
- `226` + 模板 `"CONTOUR"`：矩阵连续伪彩等高线云图（原位 DRT $\gamma(\tau)$、原位 XRD/Raman）
- `105` + 模板 `"Heat_Map_With_Labels"`（或 `"HeatMap"`）：带单元格数值标注的离散矩阵热力图
- `243` + 模板 `"TriContour"`：非规则散点 `XYZ` 三角剖分等高线图

### 3.2 `GraphPage` 与 `GLayer` 单位枚举严格区分（高频踩坑点）
- **`GraphPage` 页面尺寸（设物理英寸必须用 `Units = 0`）**：
  ```python
  gp.obj.Units = 0   # 0 = Inch（严禁执行 page.unit=2，Page 的 unit=2 是 Pixel，会把整页缩成 7x5 px！）
  gp.obj.Width = 10.40   # 4:3 单图族为 10.40 x 7.80 in；1:1 正方单图族为 9.00 x 7.80 in
  gp.obj.Height = 7.80
  ```
- **`GLayer` 图层定位单位（`layer.unit`）**：
  - `layer.unit = 2`：`Inch`（全系单面板主图统一采用物理英寸精确定位：`4:3` 矩形内框 `(2.15, 0.95, 6.40, 4.80) in`，`1:1` 正方形内框 `(2.15, 0.95, 4.80, 4.80) in`，保证跨图高度与上下边沿像素零误差）；
  - `layer.unit = 1`：`% of Page`（用于全页 `[0..100, 0..100]` 零上划线 `tr.Label` 透明排版覆盖层 `gl_ov`）；
  - `layer.unit = 7`：`% of Linked Parent Layer`（专用于 `gp.add_layer(6)` 内插放大图，随主图框自动等比锚定）。

---

## 4. 六类核心图型的 OriginPro 原生构建范式

1. **竖向柔白渐变柱 + 原生柱顶同色标签（`bar_grouped_gradient`）**：
   - 两步提交 `p.obj.Theme`：第一步设 `tr.Pattern.Fill.SetIntValue(c_top, "FillColor")` 与 `SetIntValue(2, "ShadingMode")` 并赋回 `p.obj.Theme = tr` 物化渐变子节点；第二步重取 `Theme` 写入 `SetIntValue(0, "GradDirection")`、`SetIntValue(c_bottom, "GradColor")`（多序列并排柱在 `gl.group()` + 离散 RIFF `.pal` 之后对组长设 `ShadingMode=1, GradLightness=90`）以及 `tr.Label`（`Enable=1, PosColumn=3, Bold=1, Color=c_lbl, FrameType=0, YOffset=18`），最后设 `-pbc -4` 与误差棒 `set re -w 600;`（注意 `-w` 为 `1/500 pt`，严禁传 `-ew 1200`）。
2. **堆积柱与三明治 RIFF 色板（`bar_stacked` / `bar_stacked_100pct`）**：
   - `gp = op.new_graph(template="STACKCOLUMN" | "StackColP")` → `op.lt_exec(f"plotxy iy:={wks.lt_range(False)}!(1,2:{1+K}) plot:=213 ogl:=[{gp.name}]1!;")` → 调用 `origin_theme.write_discrete_riff_pal` 写出 1052B 三明治语义 `.pal`，设置 `gl.set_str("plot1.colorlist", pal_path); gl.set_int("plot1.cmap.stretchpal", 0); gl.set_int("plot1.colorinc", 1);`，并将柱段边框设为纯白 `#FFFFFF`、`0.8 pt` 分隔线。
3. **双 Y 轴全高同底复合图（`dual_y_combo`）**：
   - `gl1 = gp[0]` 设 `layer.x.showAxes=3; layer.y.showAxes=1;`（仅左黑轴，防右侧黑线叠压右轴）；`gl2 = gp.add_layer(2)` 设相同百分比 `rect` 与 `layer.x.link=1; layer.x.showAxes=0; layer.y2.showAxes=2;`，将 `layer.y2.color`、`layer.y2.label.color` 与原生 `YR.color` 统一绑定右轴主色，两块无框自定义图例（`background=0; frame=0;`）置于图框内上方净空区。
4. **局部放大 / 子图内插层（`curve_with_inset`）**：
   - `gl_in = gp.add_layer(6)` → `layer.unit=7; layer.left=...; layer.top=...; layer.width=...; layer.height=...; layer.color=white_int;`（不透明纯白背景）+ `1.6 pt` 闭合框 + 稀疏朝内主刻度。
5. **均值±SD 半透明阴影误差带**：
   - 依次向图层添加 `Upper (!1, type="l")`、`Lower (!2, type="l")`、`Mean (!3, type="l")`；对 `p_up` 执行 `p_up.set_fill_area(above=c_int, type=9, below=c_int)`（必须同时传 `above` 与 `below`）、`p_up.transparency=72`、`p_lo.transparency=100`，边线设 `set r1 -w 100; set r2 -w 100;`（严禁设 `-l 0`），图例仅绑定 `\l(3)`。
6. **二维伪彩等高线云图（`contour_pseudocolor_2d`）**：
   - `gp = op.new_graph(template="CONTOUR")` → `p = gl.add_mplot(ms, 0, type=226)` → 赋 1052B 零本底纯白蓝红连续 RIFF `.pal`（`p.colormap = pal_path`）→ `tr = p.obj.Theme; tr.ColorMap.SetIntValue(0, "LineShow"); p.obj.Theme = tr` 关闭全部等高黑线 → 精修 `SPECTRUM1` 色标尺；若配 `side_panel`，在同页并排双 `GLayer` 对齐状态/时间纵轴。

---

## 5. 图例/文本洁净控制与无头 `expGraph` 出版直出规范

- **删除默认图例与根除 `Light Grids` 顶部假横线**：
  - 删除或隐藏默认图例一律执行 **`label -r Legend;`** 或 **`Legend.show=0;`**（**严禁调用 `legend -r;`**，`legend -r` 是重建图例！）；
  - 为防止本机 `Origin.ini` 的 `GraphNewGraph=Light Grids` 主题在普通文本对象上方画出多余顶边横线，所有建图页统一对原生轴标题执行 **`YL.frame=0; XB.frame=0; YR.frame=0;`**，自定义图例与标注统一设 **`background=0; frame=0;`**。
- **标准无头 `expGraph` 导出命令（`export_origin_publication_figures`）**：
  ```python
  op.lt_exec(f'win -a "{gp.name}";')
  size_clause = f"tr1.Unit:=0 tr1.Width:={float(width_in)} " if width_in > 0 else ""

  # 1) 600 DPI 24-bit 无损 LZW .tif（compression 必须传字符串 LZW，严禁传 ColorSpace:=0）
  op.po.LT_set_str("__LASTEXP", "")
  op.lt_exec(
      f'expGraph type:=tif filename:="{stem}" path:="{out_dir}" overwrite:=replace '
      f'tr.Margin:=2 {size_clause}'
      f'tr2.TIF.dotsperinch:=600 tr2.TIF.BitsPerPixel:=24 tr2.TIF.compression:=LZW -sw;'
  )
  tif_path = op.po.LT_get_str("__LASTEXP") or str(out_dir / f"{stem}.tif")

  # 2) 300 DPI .png（随后由 PIL.Image 等比缩放到长边 <=960 px 转存 _qa_previews/{stem}_preview.jpg）
  op.po.LT_set_str("__LASTEXP", "")
  op.lt_exec(
      f'expGraph type:=png filename:="{stem}" path:="{out_dir}" overwrite:=replace '
      f'tr.Margin:=2 {size_clause}'
      f'tr2.PNG.dotsperinch:=300 -sw;'
  )
  png_path = op.po.LT_get_str("__LASTEXP") or str(out_dir / f"{stem}.png")
  ```
  完整实战避坑速查表见 [publication_visual_and_origin_craft.md](./publication_visual_and_origin_craft.md)。


---

## 六、`bode_dual_panel` 双 Layer 架构（模式 21）

Bode 图使用单 `GraphPage` 内两个独立 `GraphLayer`，通过 `layer.unit=1`（% 页面）定位，共享逻辑 X 轴（频率）。

### Layer 映射

| Layer | 变量 | `rect` (left, top, width, height %) | X 轴 | Y 轴 |
| :--- | :--- | :--- | :--- | :--- |
| L1（上层）| `\|Z\|` (Ω) | `[17.5, 8.0, 74.0, 37.5]` | log，`x.showLabels=0`（隐藏刻度数字但保留朝内对数主次刻度） | log 或线性 |
| L2（下层）| `-Phase` (°) | `[17.5, 49.5, 74.0, 37.5]` | log，共享 X 轴标（`log(Freq/Hz)`） | 线性 |

### 关键 LabTalk

```labtalk
# 上层：隐藏 X 刻度标签，保留朝内刻度线
layer.x.type=2;         # log10
layer.x.showAxes=3;     # 四周显示刻度
layer.x.showLabels=0;   # 隐藏刻度数字
layer.x.showMinorTicks=1;

# 下层：显示 X 刻度数字与轴标（共享频率轴）
layer.x.type=2;
layer.x.showAxes=3;
layer.x.showLabels=1;   # 显示刻度数字
layer.x.showMinorTicks=1;
```

### 页面与图例

```python
page_w, page_h = 8.6, 7.2   # in
# 添加第二层：gp.add_layer(0)（从父页插入）
# 共享图例：horizontal=True, pos_mode="above_frame"，锚定 L1 顶框正上方
ob.configure_custom_legend(
    gl_top, all_leg, fontsize=18.5, horizontal=True,
    pos_mode="above_frame", layer_rect_pct=(17.5, 8.0, 74.0, 37.5),
    op=op, gp=gp, layer_num_1based=1,
)
```

### 单页两层物理正方性说明

Bode 双层使用 `layer.unit=1`（% 页面）定位，不用 `layer.unit=2`（物理英寸），因两层各自占页面高度的约 37.5%，宽高比约 2:1，这是 Bode 图的标准宽屏版式（非正方形）。正方形锁定（`layer.unit=2; width=height`）仅用于 Nyquist / DRT 等需要物理 1:1 的图型。
