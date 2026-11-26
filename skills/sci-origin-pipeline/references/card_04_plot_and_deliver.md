# 工作卡四 · 出图与交付

**核心回答**：**拿到图和数据表的人能复核结果吗？**

---

## 执行清单

1. **100% OriginPro 原生同源直出、双套主题与 9 种顶刊栏宽规格**
   - **双套全局出版预设**（由 [origin_theme.py](../scripts/origin_theme.py) 驱动）：默认采用 [style_publication_minimal.json](../presets/style_publication_minimal.json)（`Times New Roman` 全局加粗、`3.0 pt` 四周闭合粗框与主线）；传 `"style_preset": "arial"` 切换为 [style_arial_clean.json](../presets/style_arial_clean.json)（`Arial` 常规不加粗、`1.5 pt` 闭合细框 / `2.0 pt` 主线）。
   - **9 种顶刊物理印刷栏宽规格**（[journal_specs.json](../presets/journal_specs.json)）：默认 `"presentation_4_3"`（`10.40 × 7.80 in`，字号 `28 / 24 / 22 / 22 pt`）；投稿排版时可通过 CLI `--journal-spec <spec_id>` 或配置 `"journal_spec"` 一键精确缩放画布尺寸、内框英寸坐标、线宽、点径、字号与子图角标格式（`nature_single_89mm`、`nature_double_183mm`、`science_single_55mm`、`science_double_184mm`、`cell_single_85mm`、`cell_double_174mm`、`acs_single_3.25in`、`ieee_single_3.5in`）。
   - **内框几何铁律（`4:3` 等比例 vs `1:1` 矩阵框）**：在标准 `10.40 × 7.80 in` 画布下，常规 1D 图表与 **EIS Nyquist 阻抗谱**统一锁定 **`(2.15, 0.95, 6.40, 4.80) in` 标准 `4:3` 矩形内框**（Nyquist 通过固定 `ΔZ' : Δ(-Z'') = 4 : 3` 实现物理 `1 Ω = 1 Ω` 等比例正圆阻抗弧，与常规 1D 图保持 0 像素框线对齐）；**二维伪彩云图（`contour_pseudocolor_2d`）、二维矢量场（`vector_quiver_field`）与矩阵热力图（`matrix_heatmap`）**居中锁定 **`(2.80, 0.95, 4.80, 4.80) in` 严格 `1:1` 正方形内框** + 右侧等高 64 阶 `GLayer` 色标尺。
   - **原生全套交付产物**：默认无头会话构建 **100% 双击可编辑 `.opju`**（[origin_renderer.py](../scripts/origin_renderer.py) / [origin_builder.py](../scripts/origin_builder.py)），经 `expGraph`（`tr.Margin:=2`）同源导出 **`600 DPI` LZW `.tif`**、**`300 DPI .png`**、可选**无损矢量 `.pdf`**（配置 `"export_pdf": true`）及 **`_qa_previews/*_preview.jpg`**。`--skip-origin` 仅作无 Origin 环境下的离线兜底。

2. **按真实数据与学科语义精准映射 41 种模式与无障碍色板**
   - **坐标量纲与刻度矩阵严格对齐**：任意强度轴（光谱叠谱/核磁积分）隐去左 Y 刻度数字；分类轴隐去底 X 刻度短线；定量轴仅在 `scale == "log10"` 时开启朝内对数次刻度；缺失分母时图轴与表格同步降级（如 `Capacity (mAh)`）。
   - **27 种声明式全学科图型语法直出**（详见 [chart_catalog.json](../presets/chart_catalog.json)，已有定量结果或汇总表直接建图，不擅自重拟合）：
     - *分类、构成与复合层*：`bar_grouped_gradient`、`bar_stacked`、`bar_stacked_100pct`（Y 轴刻度截断于 `0..100`）、`dual_y_combo`（全高零基线对齐 + 右轴语义染色）、`curve_with_inset`（`layer.unit=7` 纯白底 `zoom`/`subchart` 内插层）、`chart_grammar`（任意 `nrows × ncols` 不等宽组图）；
     - *生物统计、组学、药理与临床生存/ROC*：`stat_distribution`、`stat_bar_dot_sig`（均值±SD/SEM 描边柱 + 白芯圆点平行样 + 防碰撞显著性星号横杠）、`stat_violin_raincloud`（原生 Violin KDE + 内嵌四分位白盒）、`volcano_plot`（三态火山散点 + 双翼防碰撞引线）、`dose_response_4pl`（`log10` 浓度 4PL S 曲线 + 95% CI 带 + `IC50` 垂落虚线）、`kaplan_meier_plot`（Step-Horz 阶梯生存率 + Greenwood `cloglog` 95% CI 带 + 右删失竖线 + 对齐 `Number at risk` 表）、`roc_pr_curve`（`AUROC ± 95% CI` + Youden 最优截断空心点 / `AUPRC`）、`forest_ablation_plot`（倒序分类纵轴 + 水平 95% CI 森林图）；
     - *化学催化、超快/光学物理、地学测井与非笛卡尔场*：`xy_fit_and_band`（9 类回归模型 + 95% CI 带 + `slope_triangle` 斜率三角）、`free_energy_diagram`（加粗自由能台阶 + 虚线跃迁 + 可选 `TS‡` 样条鞍点）、`nmr_spectrum`（反演 `ppm` 核磁谱 + 抬升阶梯积分）、`broken_axis_plot`（原生 X/Y 跨尺度断轴）、`dual_x_optical_spectrum`（如底轴 `nm` 公式联动顶轴 `1239.84193/x eV`）、`ternary_diagram`（原生 `Ternary` 三元相图）、`polar_radar_plot`（原生 `Polar` 极坐标方向图与正多边形蛛网 `radar` 雷达图）、`multi_track_profile`（共享反演深度轴多道剖面 + 跨道阴影层位带）、`electrochem_kinetics`、`bode_dual_panel`、`contour_pseudocolor_2d`、`matrix_heatmap`、`vector_quiver_field`（等比 2D 矢量箭头 + 模值伪彩底图）。
   - **色盲友好与感知均匀 1052B RIFF `.pal` 色板**：支持 `paired_semantic`、`sandwich_stack`、`sequential_blue_red`、`pseudocolor_zero_white`、`diverging_blue_white_red`，以及离散色盲安全色板 `okabe_ito`、`tol_muted` 和连续感知均匀色阶 `viridis`、`cividis`、`batlow`、`vik`、`magma`。
   - **中英双语顶刊 `Source_Data.xlsx`**：设 `"locale": "en"` 输出英文标准工作簿（`Raw_Data`、`Summary_Statistics`、`Statistical_Tests` 精确 `p_raw/p_adj`、`Curve_Fit_Summary` `IC50/R²/AIC/BIC`、`Figure_Manifest`），默认 `"zh"` 保持中文兼容。

3. **视觉像素终审与手改 `.opju` 保护门禁**
   - **只读 `_qa_previews/*_preview.jpg` 逐项目检**（严禁直读大幅 `.tif`/`.png` 原图或重复读取未变图片）：确认无标签/引线/风险表/色标尺重叠，无坐标轴标题顶部假黑横线（`YL/XB/YR/XT.frame=0`），无误重建右上角带框默认图例或极坐标残留 `BBUTN1` 按钮，且画布四周边距匀称（`tr.Margin:=2`）。
   - **用户手改 `.opju` 保护**：在既有精修 `.opju` 上增量加图前必须先备份并用 `snapshot_origin_graph_state` 锁定既有图页状态零变动；结束会话后确认 `Origin64` 进程零残留。

4. **诚实与克制交付清单**
   - 仅将本轮实际生成且通过 `validator` 完整性校验（含 `.pdf` `%PDF` 头校验与 `.xlsx` 落盘核验）和 `_qa_previews` 视觉审查的文件列入已完成清单；当用户指定只交付 `.opju` 等单一产物时按需精简目录，不残留多余报告或临时图件。
