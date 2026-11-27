---
name: sci-origin-pipeline
description: >-
  All-science universal data analytics, statistical inference, survival/ROC evaluation, scientific curve fitting,
  material characterization, electrochemistry kinetics, chemical spectroscopy/catalysis, optical/ultrafast physics,
  geoscience profiles, and 100% OriginPro-native Cartesian + non-Cartesian plotting workflow. Use whenever inspecting,
  auditing, fitting, testing hypotheses, or delivering editable Origin projects (.opju) and headless expGraph figures
  (600dpi LZW .tif + 300dpi .png + lossless vector .pdf + QA previews) across 6 domain packs, 41 modes, dual themes,
  9 journal column specs (Nature/Science/Cell/ACS/IEEE), and bilingual EN/ZH Source_Data.xlsx workbooks.
---

# SciOrigin Pipeline v8.0 · 全科研领域数据分析与 OriginPro 原生出图总控

本 Skill 固定跨学科科研数据分析与成图的**核对数据、选择方法、统计/模型敏感性审查与原生出版交付闭环**。每次先看真实数据和研究问题，再决定方法、检验口径与结论边界。

> **双套签名主题 × 9 种顶刊物理栏宽规格 × 像素锁定几何**：
> 1. **双套全局出版预设**（`style_preset` 一键切换）：
>    - **默认粗体新罗马预设** [style_publication_minimal.json](./presets/style_publication_minimal.json)（别名 `"minimal"` / `"tnr"`）：`3.0 pt` 闭合粗框、`3.0 pt` 主曲线（`-w 1500`）、全图 `Times New Roman` **100% 加粗**；
>    - **轻量常规无衬线预设** [style_arial_clean.json](./presets/style_arial_clean.json)（别名 `"arial"` / `"arial_clean"`）：`1.5 pt` 闭合细框、`2.0 pt` 主曲线（`-w 1000`）、全图 `Arial` **常规不加粗**。
> 2. **9 种期刊物理栏宽规格** [journal_specs.json](./presets/journal_specs.json)（CLI `--journal-spec <spec_id>` 或配置 `"journal_spec"`）：默认 `"presentation_4_3"`（`10.40×7.80 in`，字号 `28/24/22/22 pt`），支持一键等比缩放至 `nature_single_89mm`、`nature_double_183mm`、`science_single_55mm`、`science_double_184mm`、`cell_single_85mm`、`cell_double_174mm`、`acs_single_3.25in` 与 `ieee_single_3.5in`（自动适配物理栏宽、字号、线宽、点径与子图角标格式）。
> 3. **画幅与内框几何锁定**：默认 `10.40×7.80 in`（`4:3` 外画幅）下，常规 1D 图表与 **EIS Nyquist 阻抗谱**统一锁定 **`(2.15, 0.95, 6.40, 4.80) in` 标准 `4:3` 矩形内框**（Nyquist 按 `ΔZ' : Δ(-Z'') = 4 : 3` 跨度实现 `1 Ω = 1 Ω` 物理等比例正圆弧，与常规 1D 图 0 像素框线偏差）；**二维连续云图、二维矢量场底图与相关性矩阵热力图**居中锁定 **`(2.80, 0.95, 4.80, 4.80) in` 严格 `1:1` 正方形内框** + 右侧等高 64 阶色标尺（上下黑框边 `0.95..5.75 in` 零像素错位）。全系由 **OriginPro 2024 原生构建 100% 可编辑 `.opju` 工程并通过 `expGraph`（`tr.Margin:=2`）同源直出 `600 DPI` LZW `.tif`、`300 DPI .png`、可选无损矢量 `.pdf`（`export_pdf: true`）与 `_qa_previews/*_preview.jpg`**。`--skip-origin` 仅作无 Origin 环境离线兜底。

---

## 一、识别目标并选择路径

先判定用户本次处于哪条任务线，仅加载对应工作卡：

| 任务类型 | 激活路径 | 核心要求 |
| :--- | :--- | :--- |
| **只整理数据 / 格式嗅探转换** | **工作卡一**（必要时加 **卡四**） | 打开真实文件核对样品、列单位、重复层级与缺项，按中/英规范交付结构化表格，不做过度解释。 |
| **从原始实验/队列数据探索规律** | **卡一 → 卡二 → 卡三 → 卡四** | 先核对数据、论证分峰/统计检验/曲线拟合方法、审查敏感性与多重校正边界，最后由 Origin 原生同源交付。 |
| **审查已有分析或统计结论** | **卡一 + 卡三** | 对照原始数据、处理参数与统计检验表，找出参数触界、未做多重比较校正、高删失率或分母缺项等脆弱点。 |
| **从汇总表/矩阵/已有结果直接出图** | **卡一 + 卡四** | 核对数据列、平行样聚合或二维/三元/极坐标维度与声明式图型映射（含 `replot_deconv`），沿用既有定量结果直接构建 `.opju` 与出版成图，不擅自重拟合。 |

---

## 二、四张工作卡（按当前阶段按需读取）

1. **工作卡一 · 核对数据** → [card_01_inspect_data.md](./references/card_01_inspect_data.md)
   回答：**这批数据是什么，能支持用户想做的比较吗？**（6 大学科包自动嗅探 `.xls/.ndax/.jdx/.s2p/.fcs/.mzml/.h5ad/.jsonl/CSV`，核对技术重复 vs 生物学独立样本、生存删失编码、三元闭合与物理分母缺项。）
2. **工作卡二 · 选择方法** → [card_02_choose_method.md](./references/card_02_choose_method.md)
   回答：**为什么这批数据适合这个方法？**（记录参数依据；严禁跨材料盲套分峰预设；正态/方差齐性自动路由参数/非参数检验与 BH-FDR 校正；匹配 9 类科学曲线拟合与非笛卡尔/断轴/双 X 坐标系。）
3. **工作卡三 · 审查结论** → [card_03_audit_conclusions.md](./references/card_03_audit_conclusions.md)
   回答：**哪一条原始证据支持这个结论？哪些选择会改变它？**（核查 `CEN_BOUND` 触界、弱信号 `SNR < 3.5`、`p_raw` vs `p_adj`、生存尾部风险人数与 ROC 类别失衡；审计标记同步落入实图与 `Source_Data.xlsx`。）
4. **工作卡四 · 出图与交付** → [card_04_plot_and_deliver.md](./references/card_04_plot_and_deliver.md)
   回答：**拿到图和数据表的人能复核结果吗？**（按目标预设与 `journal_spec` 原生直出 `.opju` + `.tif/.png/.pdf` + 中/英文 `Source_Data.xlsx`，必读 `_qa_previews/*_preview.jpg` 逐像素终审。）

### 卡片间简洁交接信息
- `研究问题` | `数据来源与学科包` | `样品、重复层级与单位` | `关键方法选择（含统计/模型依据）` | `稳健结论、敏感区间与审计标记`

---

## 三、何时向用户确认

**仅在缺失信息确实会改变分组、计算口径或主要结论时暂停确认**：
1. **缺失硬性前提或样本映射歧义**（如电池倍率缺活性物质质量 `mg`、生存数据事件/删失编码 `0/1` 反转不明、对照组归属不明）：有依据部分先交付（如原始 `mAh`），受影响换算标注缺项并向用户确认。
2. **多组合理方案显著改变核心结论**：先抽取代表数据试算对比（如 `model_sensitivity`），呈现波动区间后由用户拍板。
3. **未建模陌生谱区且用户未指定分解要求时**：先交付 `raw_preview` 原谱预览与 `SNR`；若用户已明确分析目标且条件充足，直接按卡二制定物理约束或统计模型推进，不机械反复追问。

---

## 四、6 大可插拔学科包、41 种模式与确定性执行引擎

- **参考规范与 Origin 原生工艺手册（按需读取）**：
  - OriginPro `.opju` 无头架构与 3 条 `OriginExt` 防崩溃守卫：[origin_opju_architecture.md](./references/origin_opju_architecture.md)
  - 出版级审美准则、1052B RIFF 色板与 COM 实战手册：[publication_visual_and_origin_craft.md](./references/publication_visual_and_origin_craft.md)
  - XPS/Raman 分峰指南：[xps_raman_deconvolution_guide.md](./references/xps_raman_deconvolution_guide.md) | 氟化碳 F 1s 四模型敏感性案例：[case_cfx_xps_and_f1s_models.md](./references/case_cfx_xps_and_f1s_models.md)
  - 电化学与表征边界：[electrochem_and_characterization_guide.md](./references/electrochem_and_characterization_guide.md)
  - 27 种声明式图型目录：[chart_catalog.json](./presets/chart_catalog.json) | 9 种期刊栏宽规格：[journal_specs.json](./presets/journal_specs.json)
- **CLI 总控命令**（通过 [invoke_sciorigin.ps1](./scripts/invoke_sciorigin.ps1) 自动定位含 `originpro` 的 Python 环境）：
  - `scan <dir>` | `inspect <file_or_dir>` | `list-modes` | `list-packs` | `init-template <mode>` | `run <task_config.json> [--journal-spec <spec_id>] [--skip-origin]`
- **6 大可插拔学科扩展包（[scripts/packs/](./scripts/packs/)）**：
  1. `materials_electrochem`：XPS/Raman/XRD/FTIR/BET/EPR/粒度/电导率/新威恒流与 EIS（`.xls/.xlsx/.vms/.vgd/.rasx/.asc/.spa/.z60/.cor/.ndax/.nda/.dsc/.dta/.qps`）
  2. `biomed_omics`：平行样假设检验、Kaplan-Meier 生存、火山图、4PL `IC50`、ROC/PR、流式/质谱/单细胞元数据（`.fcs/.mzml/.h5ad/.csv/.tsv/.xlsx`）
  3. `chem_catalysis`：JCAMP-DX 波谱（NMR/IR/UV-Vis）、电/热催化自由能台阶与阿伦尼乌斯动力学（`.jdx/.dx/.jcamp/.csv/.tsv/.xlsx`）
  4. `physics_optics_mech`：Touchstone 射频网络（`.s1p/.s2p`）、光学 `nm ↔ eV` 双 X 轴、超快断轴动力学、极坐标辐射与固体应力–应变
  5. `geo_env`：三元物相闭合（`A+B+C=100%`）、海洋 CTD / 钻孔地层多道同步深度剖面与二维流场/矢量场
  6. `ml_ai4s`：训练指标流（`.jsonl`）、消融实验 95% CI 森林图、多分类器 ROC/PR 与六维能力雷达基准
- **A. 仪器表征解析与物理约束分峰管线（14 种）**：
  `raw_preview` | `deconvolve` | `model_sensitivity` | `batch_deconvolve` | `replot_deconv` | `waterfall` | `nyquist` | `bet_porosity` | `particle_size` | `epr_spectrum` | `conductivity` | `neware_galvanostatic` | `xy_trend` | `composite_figure`
- **B. 通用声明式笛卡尔 + 非笛卡尔图型语法模式（27 种，总计 41 种模式）**：
  - *分类、构成与复合轴*：`bar_grouped_gradient` | `bar_stacked` | `bar_stacked_100pct` | `dual_y_combo` | `curve_with_inset`（支持 Nyquist `6.40×4.80 in` `4:3` 框内 `1 Ω = 1 Ω` 等比例锁定） | `chart_grammar`（任意 `nrows×ncols` 拼版）
  - *电化学、二维矩阵与矢量场*：`electrochem_kinetics`（`pulse_align` / `galvanostatic_dqdv` / `ragone`） | `bode_dual_panel` | `contour_pseudocolor_2d`（`1:1` 伪彩云图 + 可选 `side_panel`） | `matrix_heatmap`（`1:1` 白格线相关性热图） | `vector_quiver_field`（`1:1` 二维等比 V 型矢量箭头 + 模值伪彩底图）
  - *统计推断、组学、药理与临床生存/ROC*（由 [stat_engine.py](./scripts/stat_engine.py) 与 [curve_models.py](./scripts/curve_models.py) 驱动）：`stat_distribution`（Tukey 箱线+抖动散点） | `stat_bar_dot_sig`（均值±SD/SEM 柱+个体圆点+自动显著性星号横杠） | `stat_violin_raincloud`（原生 Violin KDE + 内嵌四分位白盒 + 显著性横杠） | `volcano_plot`（三态火山图 + 双翼防碰撞引线） | `dose_response_4pl`（`log10` 浓度 4PL S 曲线 + 95% CI 带 + `IC50` 垂落线） | `xy_fit_and_band`（9 类回归模型 + Delta-Method 95% CI 带 + `slope_triangle` 斜率三角） | `kaplan_meier_plot`（Step-Horz 生存曲线 + Greenwood `cloglog` CI 带 + 右删失竖线 + Mantel-Cox `p/HR` + 对齐 `Number at risk` 表） | `roc_pr_curve`（Hanley-McNeil `AUROC ± 95% CI` + Youden 最优截断空心点 / `AUPRC`） | `forest_ablation_plot`（水平 95% CI 消融/亚组森林图）
  - *化学波谱、超快/光学物理、非笛卡尔与地学测井*：`free_energy_diagram`（催化自由能台阶 + 可选 `TS‡` B 样条鞍点） | `nmr_spectrum`（反演 `ppm` 核磁谱 + 悬空阶梯积分 + 多重峰标注） | `broken_axis_plot`（原生 X/Y 跨尺度断轴图） | `dual_x_optical_spectrum`（`1239.84193/x` 等非线性公式联动顶轴光谱） | `ternary_diagram`（原生 `Ternary` 三元相图） | `polar_radar_plot`（`subtype="polar"` 极坐标方向图 / `subtype="radar"` 多维能力雷达图；亦支持别名 `polar_plot` / `radar_plot`） | `multi_track_profile`（共享反演深度轴多道测井/海洋剖面 + 跨道阴影层位带 `horizons`）
- **色板与交付参数**：
  - `color_scheme`：`paired_semantic`、`sandwich_stack`、`sequential_blue_red`、`pseudocolor_zero_white`、`diverging_blue_white_red`、色盲安全离散色板 `okabe_ito`（8 色）/`tol_muted`（10 色），以及感知均匀色阶 `viridis`、`cividis`、`batlow`、`vik`、`magma`。
  - `export_pdf: true` 同步导出无损矢量 `.pdf`；`locale: "en"` 导出顶刊英文 `Source_Data.xlsx`（`Raw_Data`、`Summary_Statistics`、`Statistical_Tests`、`Curve_Fit_Summary`、`Figure_Manifest`），默认 `"zh"` 保持中文兼容。

---

## 五、交付核验门禁

- 逐项检查 `quality_audit.json` 与 `_qa_previews/*_preview.jpg`（长边 `≤960 px`，严禁直接读取大幅 `.tif`/`.png` 原图），确认无文字碰撞、无默认图例或 `BBUTN1` 按钮残留、无文本假顶线，且弱信号、触界、多重校正 `p_adj`、删失/缺项等审计标记已同步落入实图与 `Source_Data.xlsx`。
- 只报告本轮实际运行并经校验存在的文件与指标；显式传 `--skip-origin` 跳过 `.opju` 或缺少素材未验证的环节必须单独说明。
