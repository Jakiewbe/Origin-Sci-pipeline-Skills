# 工作卡二 · 选择方法

**核心回答**：**为什么这批数据适合这个方法？**

---

## 执行清单

1. **先按数据特征与研究假设定分析路线，严禁盲套预设**
   - 关键参数逐项标明来源（四选一：`用户指定` | `仪器记录` | `适用文献/统计准则` | `本轮分析假设`）。
   - **材料专属分峰预设启用红线**：[xps_cfx_battery_presets.json](../presets/xps_cfx_battery_presets.json) 仅用于确认属于 `CFx` 含氟碳电极的体系；[raman_carbon_presets.json](../presets/raman_carbon_presets.json) 仅用于具有碳一阶 `D/G` 带（`850–1950 cm^-1`）的体系。对陌生材料或未建模谱区，未要求分峰时先跑 `raw_preview`；明确要求分峰且条件充足时，依据化学态、自旋轨道劈裂与实测包络构建专属 `regions_config`，重叠多解谱区先跑 `model_sensitivity` 试算对比。

2. **跨学科假设检验与生存/诊断评估路由（`stat_engine.py`）**
   - **多组定量比较（`stat_bar_dot_sig` / `stat_violin_raincloud` / `stat_distribution`）**：
     - 先对各组执行 Shapiro-Wilk 正态性检验与 Levene 方差齐性检验：正态且方差齐走 `Student's t`（2 组）或 `One-way ANOVA + Tukey HSD`（`>=3` 组）；正态但异方差走 `Welch's t / Welch ANOVA`；偏态或小样本非正态自动切换 `Mann-Whitney U` 或 `Kruskal-Wallis` 非参数检验；配对设计显式设 `paired: true`（配对 `t` 或 Wilcoxon 符号秩）。
     - **多重假设检验校正**：`>=3` 组两两比较或组学高维筛选（`volcano_plot`）默认启用 `p_adjust: "fdr_bh"`（Benjamini-Hochberg FDR）或 `"holm"` / `"bonferroni"`，严禁将未校正 `p_raw` 混充多重比较后的显著性依据。
   - **生存分析与诊断分类（`kaplan_meier_plot` / `roc_pr_curve`）**：
     - 随访含右删失时间事件数据时选用 `kaplan_meier_plot`：采用 Greenwood `cloglog` 变换构建严格落于 `[0, 1]` 内的 95% 置信带，配合精确超几何方差 Mantel-Cox Log-rank 检验、双臂风险比 `HR (95% CI)` 与底轴刻度对齐的 `Number at risk` 表。
     - 二分类模型或生物标志物评估选用 `roc_pr_curve`：报告 Hanley-McNeil `AUROC ± 95% CI` 与 Youden $J = \text{TPR} - \text{FPR}$ 最优截断点；当正负样本极度失衡时，同步选用 `curve_kind: "pr"` 评估 `AUPRC` 与阳性率基线。

3. **通用科学曲线拟合与坐标系选型（`curve_models.py` + `chart_grammar.py`）**
   - **参数化机理/经验拟合（`xy_fit_and_band` / `dose_response_4pl`）**：按物理化学机理从 9 类模型（`linear`, `poly2`, `poly3`, `power`, `exp_decay`, `arrhenius`, `michaelis_menten`, `dose_response_4pl`, `langmuir`）中选型，统一由 Jacobian Delta-Method 计算 95% 置信阴影带并输出 `R² / adj_R² / RMSE / AIC / BIC`；抑制剂/激动剂浓度跨越多个数量级时使用 `dose_response_4pl`（`log10` 横轴 + `IC50` 垂落导引）。
   - **特殊与非笛卡尔坐标系选型**：
     - 双时域/跨量级离群值（如超快瞬态吸收飞秒至纳秒演化）→ `broken_axis_plot`（原生 `AxisSpec.breaks`，严禁手工截断拼接伪造线性间距）；
     - 严格物理倒数或非线性映射双横轴（如光学波长 `nm` 联动顶轴光子能量 `1239.84193/x eV`，或温度 `K` 联动 `1000/T`）→ `dual_x_optical_spectrum`；
     - 三组分闭合相图（`A+B+C=100%`）→ `ternary_diagram`；角分布辐射/各向异性（`0–360°`）或多维指标基准（`>=3` 极轴）→ `polar_radar_plot`（`polar` / `radar`）；地学/海洋共享深度或年代轴多指标测井 → `multi_track_profile`；二维空间流场/电磁/涡旋场 → `vector_quiver_field`。

## 本卡输出（交给工作卡三）

- `选用模式、统计检验/拟合模型及匹配依据`
- `关键参数表与来源标注（含多重校正方法、基线/约束或坐标系公式）`
- `待比较的候选模型或敏感性分支（如有）`
