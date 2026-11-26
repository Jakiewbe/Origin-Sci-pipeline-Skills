# 工作卡四 · 出图与交付

**核心回答**：**拿到图和数据表的人能复核结果吗？**

---

## 执行清单

1. **100% OriginPro 原生渲染与全局极简主题复用**
   - **默认视觉预设**：全局默认采用 [style_publication_minimal.json](../presets/style_publication_minimal.json)（`3.0 pt` 四周闭合粗边框、`Times New Roman` 全局加粗、蓝/红明暗成对语义色板、分轴型刻度决策矩阵，由 [origin_theme.py](../scripts/origin_theme.py) 统一驱动）；仅在用户明确需要常规细框四周副刻度风格时切换 [style_academic_acs_nature.json](../presets/style_academic_acs_nature.json)。详细审美与避坑准则见 [publication_visual_and_origin_craft.md](./publication_visual_and_origin_craft.md)。
   - **原生 `.opju` + 无头 `expGraph` 像素同源直出**：默认模式下（未传 `--skip-origin`），所有模式均由 **OriginPro 2024 原生构建可编辑 `.opju`**（通过 [origin_renderer.py](../scripts/origin_renderer.py) 与 [origin_builder.py](../scripts/origin_builder.py)，遵循 [Origin 架构规范](./origin_opju_architecture.md)），并直接调用无头 `expGraph`（固定 `tr.Margin:=2` 整页物理边界）同源导出 **`600 DPI` LZW 无损 `.tif`**、**`300 DPI .png`** 以及等比缩放至长边 `≤960 px` 的 **`_qa_previews/*_preview.jpg`**。
   - **离线兜底边界**：`--skip-origin`（回退调用 Matplotlib `plotter.py` / `pubstyle.py`）**仅作为无 Origin 环境或用户显式跳过 `.opju` 时的离线兜底**，绝不作为常规终稿首选。

2. **按真实数据、汇总表格与计算口径精准映射图型**
   - 确保图的横纵坐标名称、量纲单位、对数/倒序设定与工作卡一～三保持绝对一致（例如缺失活性物质质量时，图轴写 `Capacity (mAh)`、Excel 表列写 `放电容量 (mAh)` 与 `N/A (缺质量)`，严禁继续标成 `mAh g^-1`；对数坐标轴如 Ragone / 粒度必须开启朝内对数次刻度，线性定量轴则关闭次刻度）。
   - **从汇总表/矩阵按声明式图型语法直接出图**：对于已整理好的定量汇总表（`.xlsx/.xls/.csv`，含平行测点长表自动 `Mean ± SD` 聚合）、电化学瞬态数据或二维矩阵，直接选用 [chart_catalog.json](../presets/chart_catalog.json) 中的通用图型语法模式出图与导出 Source-Data 工作簿，不擅自重跑底层分峰：
     - 分类与构成对比：`bar_grouped_gradient`（原生两步提交柔白竖向渐变柱 + 误差棒 + 同色粗体柱顶数字）、`bar_stacked` / `bar_stacked_100pct`（三明治平涂语义色带 + `0.8 pt` 纯白分隔线）；
     - 复合坐标与局部细节：`dual_y_combo`（双 Y 同底零点对齐 + 右轴语义染色）、`curve_with_inset`（`gp.add_layer(6)` 父图框百分比定位白底内插放大图 / 子分布图，支持 `equal_aspect` 1:1 正方形锁定）；
     - 电化学动力学与二维场：`electrochem_kinetics`（`pulse_align` 短脉冲归零压降分解、`galvanostatic_dqdv` 充放电与微分容量联图、`ragone` 双对数图）、`contour_pseudocolor_2d`（零本底纯白蓝红连续色阶二维伪彩云图 + 可选 `side_panel` 1D 联动曲线）、以及通用多面板组合入口 `chart_grammar`；
     - **新增 4 类高颜值模板图型（模式 20–23）**：
       - `xy_fit_and_band`（模式 20）：XY 散点 + `type=9` 透明置信带（`transparency=72`，`-w 80` 超细同色边框关闭填充）+ `-w 1500` 拟合实线 + `-k 20`（sz=9.5）3D 高光实测球 + 框内空白角无框加粗回归方程与 `R\+(2)` 标注；**注**：置信带不用 `-l 0`（会关闭填充！）；
       - `bode_dual_panel`（模式 21）：EIS Bode 单页上下双 Layer（`Page 8.6×7.2 in`），上层 `|Z|`（`rect=[17.5,8.0,74.0,37.5]%`，`x.showLabels=0` 保留朝内对数主次刻度）、下层 `-Phase`（`rect=[17.5,49.5,74.0,37.5]%`，共享 `log(Freq/Hz)` 底轴标）；3.0 pt 粗框、`-k 20` 球点线、顶框正上方居中共享无框横排图例（`fontsize=18.5`）；
       - `stat_distribution`（模式 22，`mark="stat_distribution"`）：加载 Origin 内置模板 `BOX+DATA+OVERLAP`（短名无后缀）；`type=206` DataRange + `gl.group(False)` 解组；逐组赋成对语义色、`transparency=35` + `1.8 pt` 描边（`set rr -w 900`）+ 同色抖动散点；
       - `matrix_heatmap`（模式 23，`mark="matrix_heatmap"`）：加载内置模板 `Heat_Map_With_Labels`；`type=105` MatrixPlot；`MeshLineWidth=0.8`（白色单元格分隔线）；`set rhm -Z 1 -Zfs 20 -Zbold 1`（粗体 20 pt 格内数值）；近正方图框 `[15.5,11.3,56.5,71.8]%`；右侧 SPECTRUM1 色标尺 `fsize=20 Bold, 2.2 pt` 边框；
     - 已有分峰工作簿重画：使用 `replot_deconv` 或 `xy_trend`，仅做表图一致性与面积闭合核对。
   - 陌生谱区或仅需原始预览时使用 `raw_preview`，不强加未确认的分峰填充色块。

3. **跨载体一致性与 Origin 原生实图门禁复核**
   - 核对图像标签、图注标记、Source-Data `.xlsx` 数值与方法摘要页、`quality_audit.json` 与 `.opju` 工作表/矩阵列名称及单位完全一致，弱信号/触界/缺项提示均已落盘。
   - **双 Y 轴物理相关性与前景分离排版**：左/右轴须同图框全高同底零点对齐（如左轴元素含量 `at.%` `-k 20` 3D 高光球深色实线置于前景、右轴分峰占比 `%` 100% 堆积柱置于底层），两块无框图例（`background=0; frame=0;`）紧凑置于图框内部上方空白区，且仅展示该谱区实际存在对应分峰的关联元素（例如 `C 1s` 未分含 Li 峰时不画 `Li (at.%)`）。
   - **视觉终审门禁（只读 `_qa_previews/*_preview.jpg`）**：必须检查由 Origin `expGraph` 直出转换的 `_qa_previews/*_preview.jpg`（禁止直接读取大幅高分辨率 `.tif`/`.png` 或重复读取未变化图片），逐项确认：
     1. 柱顶标签水平居中、同色清晰，且坐标轴标题/图例上方**无 `Light Grids` 系统主题残留的假顶部黑横线**（须通过 `YL.frame=0; XB.frame=0; YR.frame=0;` 与 `background=0; frame=0;` 彻底关闭）；
     2. 无误调 `legend -r;` 重建出的右上角带框默认图例遮挡曲线；
     3. 画布四周边距匀称（`tr.Margin:=2`），无画布外隐藏对象撑爆尺寸、无文字截断或数字撞车。
   - **用户手改 `.opju` 保护**：当基于用户手工精修过的 `.opju` 增量加图或修改样式时，先完整备份原工程并从精修图反推真实属性，**严禁改动用户已调好的图**（操作前后须用 `snapshot_origin_graph_state` 核对受保护图的 `DataPlots` 数、`GraphObjects` 数与 X/Y 坐标范围完全不变）。

4. **诚实与克制交付清单**
   - 只有在本轮实际生成并经 `validator`（`passed_file_integrity == True`）与 `_qa_previews/*_preview.jpg` 核验通过的文件才能列入完成清单；显式传 `--skip-origin` 跳过的 `.opju` 或因缺少素材未验证的环节，必须单独明确说明。
   - **按需精简交付与目录洁净**：当用户明确指定只交付 `.opju` 等特定文件时，仅交付所要求文件且**不附带未请求的冗余报告**，用于视觉验收的 `expGraph` 预览小图仅放临时/质检目录，不在正式数据目录残留多余 `.png`/`.tif`。
