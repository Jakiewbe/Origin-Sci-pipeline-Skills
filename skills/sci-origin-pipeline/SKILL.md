---
name: sci-origin-pipeline
description: >-
  Cross-material scientific characterization, electrochemistry kinetics, and declarative chart-grammar
  workflow. Use whenever inspecting, auditing, fitting, transforming, or delivering 100% OriginPro-native
  editable projects (.opju) and headless expGraph figures (600dpi LZW .tif + 300dpi .png + QA previews)
  alongside structured Source-Data Excel workbooks (.xlsx) for XPS, Raman, XRD, FTIR, EPR, BET, particle
  size, powder conductivity, EIS/DRT, pulse/galvanostatic battery testing, or summary tables/matrices.
---

# SciOrigin Pipeline · 跨材料科研分析与 OriginPro 原生出图总控

本 Skill 固定科研数据分析与成图的**提问、决策、敏感性审查与交付核验流程**。每次先看实际数据和研究问题，再决定方法、参数与结论边界。

> **核心渲染与双套主题定位**：内置两套像素严格对齐的全局出版主题，由 `style_preset` 一键切换：
> 1. **默认粗体新罗马主题** [style_publication_minimal.json](./presets/style_publication_minimal.json)（别名 `"minimal"` / `"tnr"`）：`3.0 pt` 四周闭合粗框、`3.0 pt` 主曲线（`-w 1500`）、全图 `Times New Roman` **100% 加粗**，统一字号层级（坐标轴标题 `28 pt`、坐标刻度 `24 pt`、框内图注 `22 pt`、图中标注/数值 `22 pt`）；
> 2. **轻量常规 Arial 主题** [style_arial_clean.json](./presets/style_arial_clean.json)（别名 `"arial"` / `"arial_clean"`）：`1.5 pt` 四周闭合细框、`2.0 pt` 主曲线（`-w 1000`）、全图 `Arial` **常规不加粗**，保持完全相同的 `28 / 24 / 22 / 22 pt` 字号与画幅坐标。
>
> 全系图表统一锁定 **`10.40×7.80 in`（`3120×2339 px` @ 300 DPI，严格 `4:3` 外画幅）**，等宽/等高并排拼图零缩放失真：其中 `4:3` 标准矩形单图内框为 `(2.15, 0.95, 6.40, 4.80) in`，`1:1` 等比例正方形单图（EIS Nyquist、原位云图、热力图）内框居中锁定为 `4.80×4.80 in`（上下黑框边 `0.95..5.75 in` 零像素偏差）；配合 100% 框内无框图注、纯 2D 实心/白芯圆点（`-k 2 -kf 1/2`）及统一浅彩实色填充 + `1.5 pt` 深色描边柱/箱体，由 **OriginPro 2024 原生构建 100% 可编辑 `.opju` 工程并通过 `expGraph`（`tr.Margin:=2`）直出 `600 DPI` LZW `.tif`、`300 DPI .png` 与 `_qa_previews/*_preview.jpg`**。`--skip-origin` 仅作无 Origin 环境离线兜底。

---

## 一、识别目标并选择路径

先判定用户本次处于哪条任务线，仅加载对应工作卡：

| 任务类型 | 激活路径 | 核心要求 |
| :--- | :--- | :--- |
| **只整理数据** | **工作卡一**（必要时加 **卡四**） | 打开实际文件核对样品、列、单位与缺项，按要求交付表格，不做过度解释。 |
| **从原始数据探索规律** | **卡一 → 卡二 → 卡三 → 卡四** | 先核对数据、论证方法、对敏感选项试算并审查证据链，最后按一致口径由 Origin 原生出图交付。 |
| **审查已有分析** | **卡一 + 卡三** | 对照原始数据、既有处理参数表和最终结果，找出影响结论的最敏感假设或异常。 |
| **从汇总表/矩阵或已有结果直接出图** | **卡一 + 卡四** | 核对数据列、平行测点聚合或矩阵维度与声明式图型映射（如 `bar_grouped_gradient`、`dual_y_combo`、`contour_pseudocolor_2d`、`replot_deconv`），沿用既有定量结果直接构建 `.opju` 与出版成图，不擅自重拟合。 |

---

## 二、四张工作卡（按当前阶段按需读取）

1. **工作卡一 · 核对数据** → [card_01_inspect_data.md](./references/card_01_inspect_data.md)
   回答：**这批数据是什么，能支持用户想做的比较吗？**（实开文件检查谱区/工步/列单位/重复层级/矩阵维度，明确缺项如活性物质质量对结论的影响。）
2. **工作卡二 · 选择方法** → [card_02_choose_method.md](./references/card_02_choose_method.md)
   回答：**为什么这批数据适合这个方法？**（记录参数来源；严禁未核对材料体系即套用特定领域分峰预设；陌生谱区先出原谱预览；敏感分歧先试算对比。）
3. **工作卡三 · 审查结论** → [card_03_audit_conclusions.md](./references/card_03_audit_conclusions.md)
   回答：**哪一条原始证据支持这个结论？哪些选择会改变它？**（核查触界、残差、低信噪比、脉冲压降负值/自热标记与多模型波动区间；审计标记同步落入最终图表和汇总表。）
4. **工作卡四 · 出图与交付** → [card_04_plot_and_deliver.md](./references/card_04_plot_and_deliver.md)
   回答：**拿到图和数据表的人能复核结果吗？**（默认启用 `style_publication_minimal` 与 Origin 原生 `expGraph` 直出、坐标与表格单位严格一致、审查缩略预览、如实列出生成与跳过项。）

### 卡片间简洁交接信息（按任务复杂度决定仅汇报或写入交付物）
- `研究问题` | `数据来源` | `样品与单位` | `关键方法选择（含来源依据）` | `结论、原始证据与灵敏度边界`

---

## 三、何时向用户确认

**仅在缺失信息确实会改变分组、计算口径或主要结论时暂停确认**（不因材料陌生而在条件充足时机械阻断）：
1. **缺失硬性前提或样本映射歧义**（如新威测试缺少活性物质质量、对照组归属不明）：有依据部分先交付（如原始 `mAh` 对比），受影响换算标注缺项并向用户确认。
2. **多组合理方案显著改变核心结论**：先抽取代表数据试算对比（`model_sensitivity`），呈现波动区间后由用户定夺是否批量运行。
3. **未建模谱区且用户未指定分解要求时**：先交付 `raw_preview` 原谱预览与信噪比读数；若用户已明确提出材料体系分析目标且现有数据/测试信息足够，直接按卡二依据数据特征与文献原则制定参数并推进，无需反复停下确认。

---

## 四、领域案例、参考规范与确定性执行引擎

- **领域参考与 Origin 原生工艺手册（按需读取，不通用套用材料预设）**：
  - Li/CFx 氟化碳电极完整决策案例（含 F 1s 四组候选模型）：[case_cfx_xps_and_f1s_models.md](./references/case_cfx_xps_and_f1s_models.md)
  - XPS/Raman 分峰规则：[xps_raman_deconvolution_guide.md](./references/xps_raman_deconvolution_guide.md)
  - 衍射/物性与一次电池边界：[electrochem_and_characterization_guide.md](./references/electrochem_and_characterization_guide.md)
  - OriginPro `.opju` 无头构建与多图型底层架构规范：[origin_opju_architecture.md](./references/origin_opju_architecture.md)
  - 出版级审美延展准则、原生渐变柱/RIFF 色板/`expGraph` 工艺与 COM 避坑手册：[publication_visual_and_origin_craft.md](./references/publication_visual_and_origin_craft.md)
  - 声明式图型语法目录与配置示例：[chart_catalog.json](./presets/chart_catalog.json) | 默认极简主题：[style_publication_minimal.json](./presets/style_publication_minimal.json)
- **确定性执行引擎（完成卡一、卡二匹配判断后调用）**：
  - 入口脚本：[invoke_sciorigin.ps1](./scripts/invoke_sciorigin.ps1)（自动定位含 `originpro` 的 Python 环境；默认走 [origin_renderer.py](./scripts/origin_renderer.py) / [origin_builder.py](./scripts/origin_builder.py) + [origin_theme.py](./scripts/origin_theme.py) 原生建图并 `expGraph` 直出；仅离线环境传 `--skip-origin`）
  - 数据转换与语法编译：[electrochem_transforms.py](./scripts/electrochem_transforms.py)（宽表/平行样聚合、`dQ/dV` 求导、短脉冲归零压降分解、2D 矩阵加载） + [chart_grammar.py](./scripts/chart_grammar.py)
  - 核心命令：`scan <dir>` | `inspect <file_or_dir>` | `init-template <mode>` | `run <task_config.json> [--skip-origin]`
  - **模态解析与分峰流水线（14 种）**：`raw_preview` | `deconvolve` | `model_sensitivity` | `batch_deconvolve` | `replot_deconv` | `waterfall` | `nyquist` | `bet_porosity` | `particle_size` | `epr_spectrum` | `conductivity` | `neware_galvanostatic` | `xy_trend` | `composite_figure`
  - **通用声明式图型语法模式（12 种，支持从汇总表格/电化学瞬态/二维矩阵直接出图）**：
    - `bar_grouped_gradient`：单指标多样品或簇状分组统一浅彩实色柱 + `1.5 pt` 同系深色描边 + SD 误差棒 + 柱顶数值标签（`24 pt` 分类 X 标签长词自动 `30°` 斜排）
    - `bar_stacked` / `bar_stacked_100pct`：绝对值堆积柱 / 100% 归一化百分比堆积柱（浅彩实色分层 + `1.5 pt` 深色描边；`ylim=(0,128)` 留出框内图注白区且刻度严格截断于 `0..100`）
    - `dual_y_combo`：通用双 Y 轴复合图（如左轴 100% 堆积柱 + 右轴 `-k 2` 纯 2D 圆点线元素含量，全高零点对齐 + 右轴语义染色 + 框内顶部双行无框图注）
    - `curve_with_inset`：主曲线簇 + 局部放大 `zoom` 或独立 `subchart` 内插图（支持 Nyquist `equal_aspect` 1:1 `4.50×4.50 in` 正方形锁定、纯白不透明内插底色与虚线 ZoomBox 导引线）
    - `electrochem_kinetics`：统一电化学动力学模式，含子类型 `pulse_align`（短脉冲归零对齐 + $\Delta V_{0,\text{app}} / \Delta V_{\text{slow,app}}$ 跨度标注）、`galvanostatic_dqdv`（恒流充放电 + Savitzky-Golay `dQ/dV` 联图）、`ragone`（双对数能量–功率密度图）
    - `contour_pseudocolor_2d`：二维连续伪彩云图（260×260 双线性平滑插值、零本底纯白蓝红连续色阶、右侧等高 64 色带原生 `GLayer` 色标尺，彻底杜绝宋体与胶囊框残留）
    - `chart_grammar`：多面板不等宽网格（`nrows/ncols/width_ratios`）与任意多图层叠加的通用声明式入口
    - `xy_fit_and_band`：XY 纯 2D 散点（`-k 2`）+ `type=9` 浅彩 95% 置信带 + 拟合实线 + 框内空白角无框图注及回归方程与 $R^2$ 标注
    - `bode_dual_panel`：EIS Bode 单页上下双 Layer（外包络 `0.95..5.75 in` 与单图 0 像素对齐；上层 `|Z|` 框内顶部共享横排图注，下层 `-Phase` 共享 `log(Freq/Hz)` 轴标）
    - `stat_distribution`（`mark="stat_distribution"`）：Tukey `BoxGeom` 五数概括浅彩箱体 + 中位粗横杠 + T 型须线 + 同色确定性对称抖动纯 2D 实测圆点（`-k 2`）
    - `matrix_heatmap`（`mark="matrix_heatmap"`）：`1:1` `4.80×4.80 in` 正方形相关性热力图 + `0.8 pt` 纯白网格线 + 格内自适应黑白字色数值 + 右侧等高 64 色带 `GLayer` 色标尺

---

## 五、交付核验门禁

- 逐项检查 `quality_audit.json` 与 Origin `expGraph` 导出缩略生成的 `_qa_previews/*_preview.jpg`（长边 `≤960 px`，严禁直接读取大幅 `.tif`/`.png` 原图），确认无默认图例重出、无文本假边框横线、无异常裁边留白，且弱信号、参数触界、缺失质量等审计标记已同步体现于实图与 Source-Data `.xlsx` 汇总表。
- 只报告本轮实际运行并经校验存在的文件与指标；显式传 `--skip-origin` 跳过的 `.opju`（回退离线渲染）或缺少素材的未验证项必须单独说明。
