# 出版级出图质感规范与 OriginPro 2024 原生渲染实战手册

> **核心定位**：SciOrigin 默认以 **100% OriginPro 2024 原生构建可编辑 `.opju` + 无头 `expGraph`（`tr.Margin:=2`，`600 DPI` LZW `.tif` + `300 DPI .png`）同源直出** 作为正式出版成图流水线；全局默认主题为 [style_publication_minimal.json](../presets/style_publication_minimal.json)。
> **配套核心模块**：[origin_theme.py](../scripts/origin_theme.py)（语义色板、刻度决策矩阵、1052B RIFF `.pal` 生成器）、[chart_grammar.py](../scripts/chart_grammar.py)（声明式图型语法）、[origin_renderer.py](../scripts/origin_renderer.py) / [origin_builder.py](../scripts/origin_builder.py)（Origin COM 原生渲染引擎）；[pubstyle.py](../scripts/pubstyle.py) 仅作 `--skip-origin` 无 Origin 环境下的离线兜底参考。

---

## 一、出版级质感审美与 6 条跨图型视觉延展准则

为将“**做减法、蓝/红明暗成对语义色板、原生柔白竖向渐变+同色粗体柱顶标、无冗余刻度、贴肩无箭头标注、`Times New Roman` 全局加粗 + `3.0 pt` 闭合粗框**”从单一光谱/柱图推广至电化学动力学与二维场等全部科研图型，严格执行以下 6 条视觉准则：

### 1. 分轴型刻度保留决策矩阵（精准做减法，不误删定量标尺）
- **全局不变铁律**：
  - 四周闭合实线框：常规单图 `3.0 pt`，内插子图 `1.6 pt`，多面板拼版子图 `1.8–2.2 pt`；
  - **所有启用刻度一律朝内**（`ticks=1`）；**顶轴一律无刻度**（`x2.ticks=0`）；非双 Y 图**右轴一律无刻度**（`y2.ticks=0`）；**背景网格线一律关闭**；**删去图内冗余大标题**（不写 `"Raman"`、`"XPS"` 等标题，信息由轴标题与图例承担）；
  - **直接编辑原生坐标轴标题 `XB`、`YL`、`YR`**（如 `go.Text = "\\b(...)"`、`XB.show=1; XB.fsize=28; XB.frame=0;`），**严禁** `label -r XB/YL/YR` 后新建浮动文本 `XBT/YLT/YRT`，以保留随图层缩放自动居中及双击编辑能力。
- **按物理轴类型的 6 档刻度矩阵（`origin_theme.resolve_axis_tick_policy`）**：
  1. **无量纲任意强度轴 `intensity_arbitrary`**（Raman / XRD / FTIR / XPS / EPR / 定性 DRT 叠谱）：左 Y 轴主副刻度与刻度数字**全关**（`layer.y.ticks=0; layer.y.showMinorTicks=0; layer.y.showLabels=0;`），仅留轴标题 `Intensity (a.u.)`；底 X 轴保留朝内主刻度（XPS 等连续精细能谱可按需保留 1 个朝内副刻度）。
  2. **离散分类轴 `categorical`**（分组柱、堆积柱、箱线图的样品组轴）：底 X 分类轴刻度线**全关**（`layer.x.ticks=0;`），直接写清洗后的语义样品名（如 `Pristine`、`1 C 60s`、`100 C 2s`，自动剥离 `A:`、`B:`、`batch1_` 冗余前缀）；左 Y 定量数值轴（如 $I_D/I_G$、压降 `V`、占比 `0–100%`）**保留朝内主刻度与数字，关闭副刻度**。
  3. **连续物理量定量轴 `quantitative`**（恒流充放电、短脉冲 `t–V`、Nyquist、BET、电导率、`dQ/dV`）：底 X 与左 Y 均开启朝内主刻度与数字；**仅当 `scale == "log10"`（如双对数 Ragone、激光粒度、Bode 频率轴、GITT $D_{\text{Li}^+}$）时开启朝内对数次刻度**（`showMinorTicks=1`），线性坐标轴一律关闭次刻度。
  4. **双 Y 轴左轴 `dual_y_left` 与右轴 `dual_y_right`**：左 Y 与右 Y 均保留朝内主刻度与数字（关副刻度），**强制全高同底零点对齐**（`align_zero=True`）；Layer 1 设 `layer.y.showAxes=1`（仅画左轴线，避免右侧黑框与右轴层重影），Layer 2（`gp.add_layer(2)`）设 `layer.x.showAxes=0` 并将右轴线、右轴刻度数字及 `YR` 标题同步染成右轴主数据系的语义色（如 `#3E86DE` 或 `#A02333`），左轴保持碳黑 `#111111`（纯黑安全编码 `(1,1,1)`）。
  5. **局部放大/子分布内插轴 `inset`**：采用 `gp.add_layer(6)` + `layer.unit=7`（相对父图框内部宽高百分比定位）、`1.6 pt` 四周闭合框、不透明纯白底色 `#FFFFFF` 遮挡背后穿过的主图曲线、保留 `≤4` 个稀疏朝内主刻度（刻度字号约 `15 pt`）；同物理量局部放大（`mode="zoom"`）时**省略重复的横纵轴标题文字**。

### 2. 分组渐变柱 vs 堆积三明治平涂白线的分工法则
- **单组/簇状分组对比柱（`bar_grouped_gradient`）**：
  - 采用 **OriginPro 原生竖向柔白渐变填充** + 去生硬黑边框（`-pbc -4`）+ 细黑误差棒（`set re -w 600;`，即 `1.2 pt`）+ 原生 `tr.Label` 柱顶同色加粗数值标签。
  - **亮度自适应混色（`origin_theme.compute_gradient_pair_and_label_color`）**：深/中色柱（`luminance < 0.65`，如 `#3E86DE`, `#6579BE`, `#D84B5C`, `#A02333`）柱顶取主色、柱底混入 `45%` 纯白 `#FFFFFF`、柱顶数字取主色；浅色柱（`luminance >= 0.65`，如 `#C5DBF5`, `#E8A3AF`, `#D8DEE9`）柱顶取浅主色、柱底按冷暖混入 `35%` `#3E86DE` 或 `#D84B5C` 轻微加深稳住重心，且柱顶数字自动加深一档，确保白纸背景上清晰锐利。柱总数 `≤7` 时字号 `21–22 pt`；多组密集并列柱自动收窄至 `16 pt` 防数字碰撞。
- **绝对值堆积柱 / 100% 百分比堆积柱（`bar_stacked` / `bar_stacked_100pct`）**：
  - **严禁对堆积柱每截各自做竖向渐变**（多层渐变会产生刺眼横纹并模糊定量分界），统一采用**高质感平涂实色 + 层间 `0.8 pt` 纯白 `#FFFFFF` 细分隔边线**。
  - **三明治语义色带（`sandwich_stack`）**：不引入绿/黄/橙杂色，按物理角色自下而上排布——**底层惰性背景/基准项**（如导电炭 `C-C`、`PVDF`、热力学压降 $\Delta E_0$）用中性冷灰/冰蓝（`#D8DEE9`、`#C5DBF5`）→ **中层常规共价/慢速极化项**用蓝紫系（`#6579BE`、`#3E86DE`）→ **顶层核心活性产物/强脉冲主导项**（如 `LiF`、半离子 `C-F`、$\Delta V_{0,\text{pol}}$）用暖红系（`#E8A3AF`、`#D84B5C`、`#A02333`），一眼呈现蓝红消长演化。

### 3. 双 Y 轴复合图的“前景–背景”层次分离与物理相关性筛选
- 当底层/右轴为堆积柱或分组柱、前景/左轴叠加元素含量或效率折线时，前景折线必须采用**高明度反差深色实线**（如深酒红 `#A02333`、碳黑 `#111111`、宝石蓝 `#3E86DE`，`-w 1400`）+ **Origin 原生 3D 高光球形点（`-k 20`, `-z 12`）**，严禁折线与所穿过柱段同色“隐身”。
- 左轴顶部预留 `25%–30%` 净空，将折线图例与柱图图例做成无框透明块（`background=0; frame=0;`）紧凑收纳在**图框内部上方空白区**（绝不飞出顶框外导致多面板组图边距失控）。
- **物理相关性筛选**：仅绘制该谱区实际包含对应化学态分峰的关联元素折线——例如 `C 1s` 未分出含 Li 峰时**自动过滤不画 `Li (at.%)`**（仅留 `F`、`C`）；`F 1s` 含 `LiF` 峰时可同时展示 `F`、`C`、`Li`。

### 4. 成对语义色板与连续多曲线簇（`>5` 条）蓝红渐进色序
- **标准 9 色语义调色板（跨全套图表锁定同一样品颜色）**：
  | 角色键 | Hex 色值 | 语义定位与典型用途 |
  | :--- | :--- | :--- |
  | `ice` | `#C5DBF5` | 原始态 / 轻载对照 / 堆积次底层 |
  | `blue` | `#3E86DE` | 常规主对照 / G 峰导线与标签 / XPS `Fitting` 总拟合包络线 |
  | `indigo` | `#6579BE` | 中间过渡态 / 常规次组 / 恢复电位参考线 |
  | `pink` | `#E8A3AF` | 轻度脉冲处理 / D 峰导线与标签 |
  | `rose` | `#D84B5C` | 脉冲 / 重点改性处理组 |
  | `wine` | `#A02333` | 极端高倍率脉冲 / 深色对比焦点 / 强前景折线 |
  | `slate` | `#D8DEE9` | 惰性基底 / 导电剂背景（堆积最底层） |
  | `ink` | `#111111` | 坐标轴主色 / XPS `Raw` 黑球（Origin 内安全映射 `(1,1,1)` = `16843009`） |
  | `charcoal` | `#222222` | 基线 / 细描边 |
- **连续多曲线簇（`sequential_blue_red`）**：当同一面板内有序物理曲线 `>5` 条（如 `0.1 C → 90 C` 倍率放电簇、`100 C → 225 C` 短脉冲簇、原位时间序列）时，弃用跳跃色，沿 `#C5DBF5 → #6579BE → #3E86DE → #D84B5C → #A02333` 单调线性插值过渡，配合图内一根同色趋势引导箭头替代冗长图例。

### 5. 二维伪彩云图与热力图的“零本底纯白”连续色阶
- **单向强度云图 `pseudocolor_zero_white`**（原位 DRT $\gamma(\tau)$ 演化云图、原位 XRD/Raman 伪彩图）：延续“做减法留白”原则，**零本底强制设为纯白 `#FFFFFF`**（绝不用深黑或深蓝涂满整幅背景），随信号增强沿 `#FFFFFF → #C5DBF5 → #6579BE → #D84B5C → #A02333` 过渡，并彻底关闭等高线黑线（`ColorMap.LineShow=0`）。
- **双极发散矩阵 `diverging_blue_white_red`**（残差矩阵、相关性热图）：以 `0` 为纯白中心，沿 `#3E86DE → #C5DBF5 → #FFFFFF → #E8A3AF → #D84B5C → #A02333` 对称展开。

### 6. 贴肩无箭头标注、XPS 单谱细节、阴影误差带与多面板物理字号
- **贴肩标注与等粗导线**：谱线与贯穿参考虚线等粗（`2.8–3.0 pt`，Origin `-w 1400~1500`），峰位标签（如 `D`/`G` 或 `dQ/dV` 平台峰）贴近峰肩（约 `77%` 高度处）并与导线同色；短脉冲压降分解（$\Delta V_{0,\text{app}}, \Delta V_{\text{slow,app}}$）采用水平特征电位虚线 + 紧凑双端横杠竖向跨度标注（`span_v`）。
- **XPS/Raman 单谱分峰细节**：`Raw` 原始点用黑色 `(1,1,1)` **3D 高光球形符号**（`-k 20, -z 9`）；`Fitting` 总包络线用**宝石蓝 `#3E86DE`**（`-w 1500`）；子峰锚定基线半透明填充 `p.set_fill_area(above=c, type=9, below=c)`；峰标签到峰顶采用同色**无箭头细实线**（`arrow=0; linewidth=1.8;`）。
- **均值±SD 半透明误差带**：采用 `2.8–3.2 pt` 均值实线 + 同色 `72%` 透明度平滑 `type=9` 阴影带，自定义图例仅引用均值曲线。
- **多子图拼版（`a/b/c/d`）物理印刷字号**：按期刊栏宽（单栏 `88 mm` / 一栏半 `140 mm` / 双栏 `180 mm`）锁定字号，框外左上角粗体无括号 `a, b, c, d`（`11.5 pt`），轴标题 `10.0 pt`，刻度/图例 `8.5 pt`，框线与谱线 `1.8 pt`。

---

## 二、OriginPro 2024 核心原生渲染配方与实测规范

### 1. 两步提交 `OriginExt.TreeNode` 实现任意主色→柔白竖向渐变柱 + 原生柱顶同色标签
- **SWIG C++ 必守参数顺序（值在前、键名在后！）**：
  `node.SetIntValue(int(val), "KeyName")`、`node.SetDoubleValue(float(val), "KeyName")`、`node.SetStrValue(str(val), "KeyName")`（写反为 `("KeyName", val)` 会直接抛 `TypeError`）。
- **两步提交物化机制（必须在 `expGraph` / `save_fig` 之前完成）**：新建柱图默认 `ShadingMode=0`，此时 `Theme` 树中尚未物化 `GradColor` / `GradLightness` / `GradDirection` 子节点；必须**先提交一次 `ShadingMode` 触发节点物化**，再重取 `p.obj.Theme` 写入渐变终点色与原生柱顶标签 `tr.Label`：

```python
def apply_origin_bar_gradient_and_label(
    p,
    c_prim: int,
    c_bottom: int | None = None,
    *,
    shading_mode: int = 2,      # 2=双色显式渐变(单指标多色柱首选), 1=单色明度渐变(多序列分组柱首选)
    grad_lightness: int = 90,   # shading_mode=1 时生效(设88~92确保浅色柱也柔和向白过渡)
    grad_dir: int = 0,          # 0=竖向顶主色->底柔白
    gap: int = 22,
    border_color: int = -4,     # -4=Border Color None(无黑框)
    border_width: float = 1.0,
    label_color: int | None = None,
    label_size: float = 21.0,
    label_fmt: str = ".2",
    has_yerr: bool = True,
) -> None:
    # 第一步：提交 ShadingMode 物化渐变子节点
    tr = p.obj.Theme
    fill = tr.Pattern.Fill
    fill.SetIntValue(int(c_prim), "FillColor")
    fill.SetIntValue(int(shading_mode), "ShadingMode")
    p.obj.Theme = tr

    # 第二步：重取 Theme 写入 GradColor/GradLightness、柱间距与原生柱顶同色加粗标签
    tr = p.obj.Theme
    fill = tr.Pattern.Fill
    fill.SetIntValue(int(c_prim), "FillColor")
    fill.SetIntValue(int(shading_mode), "ShadingMode")
    fill.SetIntValue(int(grad_dir), "GradDirection")
    if shading_mode == 2 and c_bottom is not None:
        fill.SetIntValue(int(c_bottom), "GradColor")
    elif shading_mode == 1:
        fill.SetIntValue(int(grad_lightness), "GradLightness")

    if tr.Pattern.Border is not None:
        tr.Pattern.Border.SetIntValue(int(border_color), "Color")
        tr.Pattern.Border.SetDoubleValue(float(border_width), "Width")
    if tr.Spacing is not None:
        tr.Spacing.SetIntValue(int(gap), "Gap")

    if label_color is not None and tr.Label is not None:
        lbl = tr.Label
        lbl.SetIntValue(1, "Enable")
        lbl.SetIntValue(3, "PosColumn")          # 3 = Outside End (柱顶正上方自动居中)
        lbl.SetDoubleValue(float(label_size), "Size")
        lbl.SetIntValue(1, "Bold")
        lbl.SetIntValue(int(label_color), "Color")
        lbl.SetIntValue(0, "FrameType")          # 0 = 无边框(彻底免疫假顶线)
        lbl.SetIntValue(0, "WhiteOut")
        lbl.SetIntValue(1, "Form")               # 1 = Y 数值
        lbl.SetStrValue(str(label_fmt), "FormatString")
        lbl.SetIntValue(18 if has_yerr else 8, "YOffset")

    p.obj.Theme = tr
    p.set_cmd(f"-pbc {int(border_color)}")
```

- **两类柱图调用分工**：
  1. **单指标多样品不同语义色柱（如 Raman $I_D/I_G$）**：构建 `1 + 2N` 对角稀疏工作表 `X + (Y_i, YErr_i)*N`（`wks.cols_axis("X" + "YE"*N)`），逐对 `add_plot(..., type="c")` **不调用 `gl.group()`**，逐柱传 `shading_mode=2` 与 `compute_gradient_pair_and_label_color` 算出的 `(c_top, c_bottom, c_lbl)`；
  2. **多序列并排簇状分组柱**：`gl.group()` 会用组长 `plot1` 的 `Theme` 覆盖整组并重置边框色，因此必须严格按 **① `add_plot` 全部序列并调 `gl.group()` → ② `write_discrete_riff_pal` + `stretchpal=0` 绑定各序列离散主色 → ③ 对组长调 `shading_mode=1, grad_lightness=90, border_color=-4`** 顺序执行。

### 2. 1052 字节 Microsoft RIFF `.pal` 动态色板注入法
Origin 内置 `STACKCOLUMN` / `StackColP` / `COLUMN` / `CONTOUR` 模板默认绑定系统色板（如 `Candy`），单设 `-cl` 无法改填充色表。通过 `origin_theme.write_discrete_riff_pal` 或 `write_continuous_riff_pal` 在临时目录写出标准 **1052 字节** 256 槽 RIFF `.pal` 二进制文件（保存 `.opju` 后色板自动内嵌固化，零外部依赖）：
- **离散色板（堆积柱 / 簇状分组柱）**：`gl.set_str("plot1.colorlist", pal_path); gl.set_int("plot1.cmap.stretchpal", 0); gl.set_int("plot1.colorinc", 1);`（`stretchpal=0` 按槽位逐列取色，不拉伸；堆积柱边界设 `0.8 pt` 纯白 `#FFFFFF`）。
- **连续色板（2D 伪彩等高线 / 热力图）**：`p.colormap = str(continuous_pal_path)`（自动设 `stretchpal=1`），随后 `tr = p.obj.Theme; tr.ColorMap.SetIntValue(0, "LineShow"); p.obj.Theme = tr` 彻底关闭等高黑线，并对 `GraphObjects("SPECTRUM1")` 色标尺设置粗体字号与标题。

### 3. 无头 `expGraph` 直出 `600 DPI` LZW `.tif` + `300 DPI .png` 精确配方
- **规避亿级像素裁边炸弹**：在双 Y 轴或隐藏反轴标题（`YR`/`XT` 默认隐藏坐标远在 `x=1040`）的图页上，传 `tr.Margin:=0`（Border）或 `1`（Tight）会把画布外隐藏对象一并框入，导致导出暴涨至 `34536 × 3306 px`！必须建图时显式设定页面物理英寸尺寸（`gp.obj.Units = 0; gp.obj.Width = 8.0; gp.obj.Height = 6.0;`），导出统一固定 **`tr.Margin:=2`（Page 整页物理边界）**。
- **LZW 与色彩空间参数铁律**：`tr2.TIF.compression:=LZW` **必须传字符串 `LZW`**（传整数 `1..4` 会退化为数十 MB 未压缩裸图）；**严禁传 `tr2.TIF.ColorSpace:=0`**（`ColorSpace` 为字符串节点且默认即为 `RGB`，传整数 `0` 会使 `expGraph` 静默放弃写出文件）；导出路径通过 `op.po.LT_set_str("__LASTEXP", "")` 与 `op.po.LT_get_str("__LASTEXP")` 回读，并用 `PIL.Image` 等比缩放到长边 `<=960 px`（`quality=80`）写出 `_qa_previews/{stem}_preview.jpg`。

### 4. 用户手改 `.opju` 工程保护规范
- 当基于用户已手工精修的 `.opju` 增量加图或抽取样式时，先完整备份原 `.opju`，再用 COM 只读提取真实属性；对用户点名保留的图严格执行“只读不写”，操作前后通过 `snapshot_origin_graph_state` 断言 `DataPlots` 数、`GraphObjects` 数与 X/Y 轴范围零偏移。

---

## 三、Origin COM / LabTalk 实战避坑全表（32 条必查红线）

| # | 常见陷阱 / 需求 | 已核实正确做法 |
| :--- | :--- | :--- |
| 1 | **`gl.plot_list()[i]` 触发 `E_UNEXPECTED` 灾难性崩溃** | 严禁对 `gl.plot_list()` 返回的 `Plot` 对象读 `.color`/`.transparency` 或调 `.set_cmd()`！只用 `len(gl.plot_list())` 计数；改已有曲线统一用 1-based 索引：`gl.set_int(f"plot{k}.color", c_int)`、`gl.lt_exec(f"range rr = !{k}; set rr -w 1400;")` |
| 2 | **`gp.save_fig` / `expGraph` 后操作 `Plot.obj` 崩溃** | 导出图像会使此前持有的 `Plot.obj` COM 指针失效；`export_origin_publication_figures` **必须放在该图全部样式与 `Theme` 提交彻底完成之后最后执行** |
| 3 | **递归遍历 `TreeNode.Children` 致 Origin RPC 崩溃** | 对含二进制色表叶节点的 `OriginExt.TreeNode` 递归读 `.Children` 会直接干掉后台 `Origin64.exe`；仅按已知路径定向写值 |
| 4 | **`TreeNode.Set*Value` 参数顺序报错** | SWIG C++ 绑定为**值在前、键名在后**：`SetIntValue(int(val), "Key")`、`SetDoubleValue(float(val), "Key")`、`SetStrValue(str(val), "Key")` |
| 5 | **柱体竖向柔白渐变与柱顶同色粗体标签** | 两步提交 `p.obj.Theme`：先设 `ShadingMode=2`（单指标对角表）或 `1`（多序列分组柱，`GradLightness=90`）提交物化子节点，再重取 `Theme` 设 `GradColor` + `tr.Label`（`Enable=1, PosColumn=3, Bold=1, FrameType=0`） |
| 6 | **误用 `legend -r;` 删图例反而重建带框图例** | LabTalk `legend -r` 是 **Reconstruct（重建图例）**！删除/隐藏默认图例必须用 **`label -r Legend;`** 或 **`Legend.show=0;`** |
| 7 | **导出图上轴标题/文本顶部出现假黑横线** | 根因是系统 `Origin.ini` 的 `GraphNewGraph=Light Grids` 主题给普通 `GraphObject` 加了顶框线；所有建图页统一执行 **`YL.frame=0; XB.frame=0; YR.frame=0;`**，自定义图例设 **`background=0; frame=0;`**（原生柱顶 `tr.Label` 天然无此横线） |
| 8 | **页面英寸 vs 图层单位混淆导致画布缩成 `7×5 px` 或插图飞出 48 英寸** | **`GraphPage` 设英寸必须用 `gp.obj.Units = 0; gp.obj.Width = 8.0; gp.obj.Height = 6.0;`**（严禁调 `page.unit=2`，Page 的 `2` 是像素！）；而 `GLayer` 中 `layer.unit=1` 为 `% of Page`、`2` 为 `Inch`（用于 Nyquist 正方形锁定）、`7` 为 `% of Linked Parent Layer`（用于内插图） |
| 9 | **`expGraph` 导出 `34536 × 3306 px` 巨图或 LZW 未压缩** | 统一固定 **`tr.Margin:=2`**（Page 整页边界，免疫画布外远端隐藏 `YR/XT`）；`tr2.TIF.compression:=LZW` 必须传字符串 `LZW`；**严禁传 `tr2.TIF.ColorSpace:=0`** |
| 10 | **`layer -g 2;` 假堆叠 Bug** | `layer -g 2` 含义是“从第 2 条曲线起并排成组”而非堆叠！堆积柱必须用 `STACKCOLUMN` / `StackColP` 模板 + **`plotxy ... plot:=213`**（`IDM_PLOT_COLUMN_STACK`），且**严禁事后调用 `gl.group()` / `layer -g`** |
| 11 | **堆积柱 / 簇状柱 / 伪彩图动态赋色** | 生成 1052B Microsoft RIFF `.pal`：离散柱图赋 `plot1.colorlist` + `plot1.cmap.stretchpal=0` + `plot1.colorinc=1`；连续 2D 伪彩赋 `p.colormap = pal_path` + `tr.ColorMap.SetIntValue(0, "LineShow")` 关等高线 |
| 12 | **双 Y 轴右框重影与上下框双影** | `gl1` 与 `gl2 = gp.add_layer(2)` 共用相同百分比 `rect`；`gl1` 设 `layer.x.showAxes=3; layer.y.showAxes=1;`（关右黑框），`gl2` 设 `layer.x.link=1; layer.x.showAxes=0; layer.y2.showAxes=2;`，并将右轴线、刻度数字与 `YR` 同染右轴主色 |
| 13 | **局部放大内插图创建与白底遮挡** | 使用 `gl_in = gp.add_layer(6)` + `layer.unit=7`（父图框内部百分比定位）+ `layer.color=white_int` 不透明白底遮挡背后曲线 + `1.6 pt` 四周框 |
| 14 | **误差棒线宽 `-ew` 单位陷阱（画出 16.7 英寸黑圆）** | `-w` 单位为 `1/500 pt`（`600` = `1.2 pt`），而 `-ew` 为直接 `pt`（误传 `-ew 1200` 会淹没整幅图）！统一对误差棒 plot 执行 **`set re -w 600;`** |
| 15 | **半透明阴影误差带填充消失或变红** | 建 `Upper (!1)`、`Lower (!2)`、`Mean (!3)` 三条曲线：对 `p_up` 调 `set_fill_area(above=c_int, type=9, below=c_int)`（漏传 `below` 变红）、`p_up.transparency=72`、`p_lo.transparency=100`，边线设 `set r1 -w 100`（**严禁设 `-l 0`** 否则关闭填充），图例用 `\l(3)` |
| 16 | **二维矩阵伪彩坐标映射方向** | `mb = op.new_book("m"); ms = mb[0]; ms.from_np(z_matrix)` 要求 `z_matrix.shape == (ny, nx)`（列数对应 `x1..x2`，行数对应 `y1..y2`），随后设 `ms.xymap = (x1, x2, y1, y2)` 并调 `gl.add_mplot(ms, 0, type=226)` |
| 17 | **箱线图 / 小提琴图逐组语义配色** | 多 `Y` 列通过 `op.make_DataRange(...)` 一次性 `gl.add_plot(dr, type=206)`，随后 **`gl.group(False)` 解组**，逐列设 `plot{k}.color`、`set rr -pf 1; set rr -pfb {c_k};` 与 `transparency=35` |
| 18 | 工作表/图页短名含下划线 `_` 被静默改名 | 短名**只用纯 ASCII 字母数字**（长度 `≤ 24`），完整科学名称与样品说明写入 `lname` |
| 19 | `set %C -l 1 -w 1200` 多参数同行失效 | **每条 `set` 命令只写一个参数**，分条执行 |
| 20 | 纯黑 `(0,0,0)` 在 Origin 中变绿色 | `origin_rgb_int(r,g,b) = 16777216 + r + g*256 + b*65536`；纯黑自动重映射为 **`(1,1,1)`（`16843009`）** |
| 21 | 虚线设置 | 使用 `set <plot> -d 1`（不用 `-l 2`） |
| 22 | 单指标逐柱独立配色 + 独立误差棒 | 对角稀疏列 `X + (Y_i, YErr_i)*N`，仅在对角行填值，逐对 `add_plot(..., type="c")` **不要编组** |
| 23 | 自定义图例排除辅助线与富文本格式 | `label -r Legend;` 后建无框文本（`background=0; frame=0;`），赋值 `"\\l(1) 名称\r\n\\l(2) 名称"`；富文本：`\b(...)` 加粗、`\i(...)` 斜体、`\-(...)` 下标、`\+(...)` 上标 |
| 24 | 原生坐标轴标题保护 | 直接改原生 `XB`/`YL`/`YR`，严禁删后自建浮动文本 |
| 25 | 3D 高光球形符号与 XPS 包络线配色 | 3D 高光球为 **`-k 20`**（XPS `Raw` 用 `-z 9` 黑球 `(1,1,1)`；双 Y 折线用 `-z 12`）；XPS `Fitting` 总拟合线优先用宝石蓝 `#3E86DE`（`31360574`，`-w 1500`） |
| 26 | XPS 锚定基线分峰填充变红 | `p.set_fill_area(above=c, type=9, below=c)` **必须同时传 `above` 与 `below`** |
| 27 | 双 Y 图例位置 | 折线与柱图双图例统一收进**图框内部上方空白区**，不出顶框 |
| 28 | 斜向无箭头引线逗号语法 | `draw -n line -l {x1, y1, x2, y2};`（`arrow=0; linewidth=1.8;`），**坐标间必须用英文逗号分隔**（空格分隔会退化为横线） |
| 29 | 双 Y 元素物理相关性筛选 | 仅绘制该谱区存在对应分峰的元素折线（如 `C 1s` 不画 `Li (at.%)`） |
| 30 | 柱状图去除默认 `0.5 pt` 黑边框 | 执行 `set rr -pbc -4`（`-4` = `Border Color None`；设 `-pbw 0` 会被钳位为 `1.0 pt`） |
| 31 | `originpro` 检索、对象枚举与会话重用 | 查工作簿传类型 `op.find_book("w", "Name")`；枚举对象用 `for go in gl.obj.GraphObjects:`（禁整数下标）；单次 `origin_session()` 内用 `op.new()` 切换项目 |
| 32 | COM 进程清零与锁定 `.opju` 安全覆写 | 全程置于 `try ... finally: op.exit()` 确保零残留 `Origin64.exe`；覆写已有 `.opju` 时先 `op.save(tmp_path)`，待 `op.exit()` 释放句柄后再移动替换；PowerShell 多行脚本用 `@' ... '@ \| python -` |

---

## 四、核心主题引擎 API 速查（`scripts/origin_theme.py` & 离线兜底）

| 模块 / 函数 | 作用说明 |
| :--- | :--- |
| `origin_theme.load_theme(preset=None)` | 加载全局主题（默认 `style_publication_minimal.json`，向后兼容 `style_academic_acs_nature.json`） |
| `origin_theme.resolve_series_colors(n, roles, scheme)` | 解析 `paired_semantic`（成对蓝红）、`sandwich_stack`（三明治平涂堆积）、`sequential_blue_red`（`>5` 曲线渐进）等色列 |
| `origin_theme.compute_gradient_pair_and_label_color(hex)` | 计算竖向渐变柱 `(top_hex, bottom_hex, label_hex)`，自动加深浅色柱底与柱顶文字 |
| `origin_theme.resolve_axis_tick_policy(axis_kind, scale, ...)` | 输出 6 类坐标轴刻度矩阵与可直接执行的 Origin LabTalk 样式片段 |
| `origin_theme.hex_to_origin_rgb_int(color)` | 转换 `#RRGGBB` / `(r,g,b)` 为 Origin 整数编码，自动将 `(0,0,0)` 安全映射为 `16843009` |
| `origin_theme.write_discrete_riff_pal` / `write_continuous_riff_pal` | 生成标准 **1052 字节** 256 槽离散或连续插值 Microsoft RIFF `.pal` 色板文件 |
| `origin_theme.format_origin_axis_title` / `clean_semantic_sample_name` | 转换 `\b(...)`/`\-(...)`/`\+(...)` 原生轴标题富文本；自动剥离 `A:`/`B:` 样品前缀 |
| `pubstyle.py`（仅 `--skip-origin` 离线兜底） | 无 Origin 环境时供 Matplotlib 复现同款极简轴框、语义色与渐变柱预览，不用于正式 Origin 交付流 |


---

## 六、14–19 号声明式图型精修要点（v5.1 对齐用户 `.opju` 真值）

### 6.1 字号与图框黄金比例

| 参数 | 单面板 | 双 Y 面板 |
| :--- | :--- | :--- |
| 轴标题 `axis_title_pt` | **27.5 pt** | **26.5 pt** |
| 刻度标签 `tick_label_pt` | **22.0 pt Bold** | **22.0 pt Bold** |
| 分类 X 标签（≤4 组） | **19.5 pt** | **19.5 pt** |
| 分类 X 标签（≤6 组） | **18.5 pt** | **18.5 pt** |
| 分类 X 标签（>6 组） | `max(14.0, min(tick*0.86, 17.5))` | 同左 |
| 框内图例 | **18.5–20.0 pt** | — |
| 双 Y 顶部双排图例 | — | **17.5–18.0 pt** |
| 图框（单面板，常规） | `rect=(17.0, 11.5, 66.0, 71.0)%` | `rect=(16.0, 18.5, 68.0, 66.5)%` |
| 画布（单面板） | 8.6×6.4 in | 8.6×6.4 in |

### 6.2 渐变柱间距与误差棒（14 号 Raman_GradientBar 等）

- **单序列自适应 gap**：N≤2 → `gap=50`，N=3 → `38`，N=4 → `28`，N≥5 → `20`
- **多序列分组柱**：`Overlap=-18`（Theme tree `ShadingMode` 两步提交），`grad_lightness=85`
- **误差棒**：`set re -w 700`（1.4 pt），颜色 `#222222`
- **柱顶数字**：`22.0–22.5 pt Bold`，顶框净空 ≥16%

### 6.3 100% 堆积柱零伪刻度（15 号 `XPS_Stacked100Pct`）

```python
gl.lt_exec("layer.y.inc=20;")
gl.set_ylim(0.0, 100.0)   # 严格 0–100%，无 120% 伪刻度
# 图例：pos_mode="above_frame", horizontal=True, t_p=15.5%
```

### 6.4 双 Y 100% 堆积 + 折线（16 号 `XPS_DualY_Combo`）

- 画布 `8.6×6.4 in`，图框 `rect=(16.0, 18.5, 68.0, 66.5)%`（`t_p=18.5%` 留顶框正上方双排图例空间）
- 100% 堆积侧（通常右轴）：`layer.y.inc=20; gl.set_ylim(0.0, 100.0)` — 彻底消灭 120% 伪刻度
- 两行无框图例排于 `y≈4.5%` 与 `10.5%`（`background=0; frame=0;`）

### 6.5 EIS Nyquist 局部放大与 Zoom 导引线（17 号 `EIS`）

- 轴标题斜体富文本：`\i(Z') (\g(W))` / `-\i(Z'') (\g(W))`
- **ZoomBox→内插图双导引线**（`zoom_connectors`）：从 ZoomBox 右侧两角引向内插图左侧两角，`#8C96A6` 颜色，`-d 2 -w 650`（1.3 pt 细虚线）
- EIS `x.inc` 与 `y.inc` 须同步（`equal_aspect` 保证 1:1 物理正方形）

### 6.6 二维 DRT 伪彩云图 1:1 正方形（19 号 `InSitu_DRT`）

- 画布 `9.6×7.8 in`，`layer.unit=2; left=1.75; top=0.85; width=5.50; height=5.50;`（物理 1:1 正方形）
- SPECTRUM1 色标尺：`fsize=20.0 pt Bold`，`BorderWidth=2.2 pt`
- Z 轴标题：`24.0 pt Bold`，位于 `spec_x_pct+4.2, spec_top_pct-4.2`

---

## 七、20–23 号新模板图型实施规范

### 7.1 `xy_fit_and_band`（模式 20）

- 置信带：`type=9`，`transparency=72`，`-w 80` 超细同色边框（**严禁用 `-l 0`，会关闭填充！**）
- 拟合实线：`-w 1500`（3.0 pt）
- 实测散点：`-k 20`（3D 高光球），`sz=9.5`
- 回归方程标注：从 `panel.meta["regression_equation"]` 与 `panel.meta["r_squared"]` 读取；富文本 `{eq}  R\+(2) = {r2}`，`fontsize=18.5 pt`，置于数据最稀疏角落

### 7.2 `bode_dual_panel`（模式 21）

```
Page: 8.6 × 7.2 in
上层 |Z|  : rect=[17.5, 8.0,  74.0, 37.5]%，x.showLabels=0，log X+Y，3.0 pt 框
下层 -Phase: rect=[17.5, 49.5, 74.0, 37.5]%，共享 X 轴标，3.0 pt 框
共享图例: horizontal, above_frame，fontsize=18.5 pt，对齐上层 rect 顶框正上方
```

### 7.3 `stat_distribution`（模式 22，`mark="stat_distribution"`）

```python
dr = op.make_DataRange(*dr_args)      # 多 Y 列 DataRange
gl.add_plot(dr, type=206)             # BOX+DATA+OVERLAP 模板
gl.group(False)                       # 解组以便逐组独立配色
for k_i in range(1, K + 1):
    c_int = hex_to_origin_rgb_int(color)
    gl.set_int(f"plot{k_i}.color", c_int)
    gl.lt_exec(f"range rr = !{k_i}; set rr -pf 1; set rr -pfb {c_int};")
    gl.set_int(f"plot{k_i}.transparency", 35)
    gl.lt_exec(f"range rr = !{k_i}; set rr -w 900;")  # 1.8 pt 描边
```

### 7.4 `matrix_heatmap`（模式 23，`mark="matrix_heatmap"`）

```python
gp = op.new_graph(lname=page_lname, template="Heat_Map_With_Labels")
p_c = gl_c.add_mplot(ms, 0, type=105)
# 白色单元格分隔线 0.8 pt
tr_hm = p_c.obj.Theme
tr_hm.DataPlot.SetDoubleValue(0.8, "MeshLineWidth")
tr_hm.DataPlot.SetIntValue(hex_to_origin_rgb_int("#FFFFFF"), "MeshLineColor")
p_c.obj.Theme = tr_hm
# 粗体 20 pt 格内数值标签
gl_c.lt_exec("range rhm = !1; set rhm -Z 1; set rhm -Zfs 20; set rhm -Zbold 1;")
# 近正方图框 [15.5, 11.3, 56.5, 71.8]%
# SPECTRUM1: fsize=20 Bold, 2.2 pt 边框
```
