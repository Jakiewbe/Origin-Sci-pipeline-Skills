from __future__ import annotations

import dataclasses
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


HEADER_FILL = PatternFill(start_color="EAF1F8", end_color="EAF1F8", fill_type="solid")
HEADER_FONT = Font(name="Times New Roman", size=11, bold=True, color="1B365D")
BODY_FONT = Font(name="Times New Roman", size=10.5)


def _safe_save_wb(wb: openpyxl.Workbook, out_p: Path) -> str:
    """Save workbook safely; if locked by Excel on Windows, write timestamped fallback instead of crashing."""
    out_p.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(out_p)
        return str(out_p)
    except PermissionError:
        stamp = time.strftime("%H%M%S")
        alt = out_p.with_name(f"{out_p.stem}_unlocked_{stamp}{out_p.suffix}")
        wb.save(alt)
        return str(alt)


def _style_worksheet(ws: openpyxl.worksheet.worksheet.Worksheet) -> None:
    ws.freeze_panes = "A2"
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
    for col_idx, col_cells in enumerate(ws.columns, start=1):
        max_len = max((len(str(c.value or "")) for c in col_cells[:60]), default=10)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 4, 13), 36)


def export_deconv_workbook(
    regions_results: Dict[str, Dict[str, Any]],
    out_xlsx: str | Path,
    sample_name: str = "Sample",
) -> str:
    """Export Origin-ready deconvolution Excel workbook with `<Comp> (含基线)` columns + parameter summary sheet."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    summary_rows: List[List[Any]] = []

    for reg_name, res in regions_results.items():
        ws = wb.create_sheet(title=reg_name[:31])
        x = res["x"]
        y_raw = res["y_raw"]
        y_fit = res["y_fit"]
        bg = res["baseline"]
        resid = res["residuals"]
        comps = res["components"]
        curves_bg = res["comp_curves_with_bg"]
        curves_net = res["comp_curves_net"]

        headers = [
            res.get("x_label", "X"),
            "Raw",
            "Fitting",
            "Backgnd.",
            *[f"{m['name']} (含基线)" for m in comps],
            "Residuals",
            *[f"Net_{m['name']}" for m in comps],
        ]
        ws.append(headers)

        idxs = range(len(x) - 1, -1, -1) if res.get("invert_x", False) else range(len(x))
        for i in idxs:
            ws.append(
                [
                    float(x[i]),
                    float(y_raw[i]),
                    float(y_fit[i]),
                    float(bg[i]),
                    *[float(c_bg[i]) for c_bg in curves_bg],
                    float(resid[i]),
                    *[float(c_net[i]) for c_net in curves_net],
                ]
            )
        _style_worksheet(ws)

        audit_status = res.get("audit_summary") or "PASS"
        snr_val = res.get("snr")
        charge_note = res.get("charge_anchor_note", "")
        for m in comps:
            summary_rows.append(
                [
                    sample_name,
                    reg_name,
                    m["name"],
                    round(m["center"], 4),
                    round(m["fwhm"], 4),
                    round(m["area"], 4),
                    round(m["area_pct"], 3),
                    round(m["subgroup_pct"], 3) if m["subgroup_pct"] is not None else None,
                    round(res.get("charge_shift_eV", 0.0), 4),
                    charge_note,
                    round(res["nrmse_pct"], 4),
                    round(res["r_squared"], 5),
                    snr_val,
                    audit_status,
                    m.get("note", ""),
                ]
            )

    ws_sum = wb.create_sheet(title="分峰参数与比例汇总")
    ws_sum.append(
        [
            "样品 (Sample)",
            "谱区 (Region)",
            "组分名称 (Component)",
            "峰位 Center",
            "半峰宽 FWHM",
            "积分面积 Area",
            "占谱区总面积 (%)",
            "占子体系内部 (%)",
            "荷电校正平移 (eV)",
            "荷电校正说明 (Charge Ref)",
            "拟合残差 NRMSE (%)",
            "决定系数 R^2",
            "谱区信噪比 SNR",
            "质检与审计标记 (Audit Status)",
            "物理说明",
        ]
    )
    for r in summary_rows:
        ws_sum.append(r)
    _style_worksheet(ws_sum)

    return _safe_save_wb(wb, out_p)


def export_batch_deconv_master_workbook(
    cohort_aggregates: List[Dict[str, Any]],
    all_individual_rows: List[Dict[str, Any]],
    out_xlsx: str | Path,
    comparisons: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Export project-wide cohort master workbook (Replicate Mean±SD + Representative + Individual Spots + Path Deltas)."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws_main = wb.active
    ws_main.title = "均值标准差与代表谱主表"

    comp_names = list(cohort_aggregates[0]["agg"]["component_stats"].keys())
    ratio_keys = list(cohort_aggregates[0]["agg"]["ratio_stats"].keys())

    headers = ["样品代号", "工步/状态说明", "测点数 (n)", "代表测点文件"]
    for rk in ratio_keys:
        headers.extend([f"{rk}_均值", f"{rk}_SD"])
    for cn in comp_names:
        headers.extend([f"{cn}_占比均值(%)", f"{cn}_占比SD(%)"])
    ws_main.append(headers)

    by_sample_id: Dict[str, Dict[str, Any]] = {}
    for entry in cohort_aggregates:
        sid = entry["id"]
        by_sample_id[sid] = entry
        agg = entry["agg"]
        row: List[Any] = [
            sid,
            entry.get("name", sid),
            agg["n_replicates"],
            Path(agg["representative_source"]).name,
        ]
        for rk in ratio_keys:
            row.extend([round(agg["ratio_stats"][rk]["mean"], 4), round(agg["ratio_stats"][rk]["sd"], 4)])
        for cn in comp_names:
            cs = agg["component_stats"][cn]
            row.extend([round(cs["area_pct_mean"], 3), round(cs["area_pct_sd"], 3)])
        ws_main.append(row)
    _style_worksheet(ws_main)

    if comparisons:
        ws_cmp = wb.create_sheet(title="关键路径差值对比")
        cmp_headers = ["对比路径", "起始样品", "目标样品"]
        for rk in ratio_keys:
            cmp_headers.append(f"Δ({rk})")
        for cn in comp_names:
            cmp_headers.append(f"Δ({cn}_%)")
        ws_cmp.append(cmp_headers)
        for cp in comparisons:
            s_from, s_to = cp["from"], cp["to"]
            if s_from in by_sample_id and s_to in by_sample_id:
                a_from = by_sample_id[s_from]["agg"]
                a_to = by_sample_id[s_to]["agg"]
                crow: List[Any] = [cp.get("label", f"{s_to} - {s_from}"), s_from, s_to]
                for rk in ratio_keys:
                    crow.append(round(a_to["ratio_stats"][rk]["mean"] - a_from["ratio_stats"][rk]["mean"], 4))
                for cn in comp_names:
                    crow.append(
                        round(
                            a_to["component_stats"][cn]["area_pct_mean"] - a_from["component_stats"][cn]["area_pct_mean"],
                            3,
                        )
                    )
                ws_cmp.append(crow)
        _style_worksheet(ws_cmp)

    if all_individual_rows:
        ws_ind = wb.create_sheet(title="全部单测点分峰明细")
        keys = list(all_individual_rows[0].keys())
        ws_ind.append(keys)
        for r in all_individual_rows:
            ws_ind.append([r.get(k) for k in keys])
        _style_worksheet(ws_ind)

    return _safe_save_wb(wb, out_p)


def export_waterfall_workbook(
    processed_curves: List[Dict[str, Any]],
    out_xlsx: str | Path,
    x_header: str = "X",
    feature_rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Export XYXY multi-sample raw & stacked-offset Excel workbook."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "XYXY_瀑布图偏移与原始数据"

    headers: List[str] = []
    max_len = max(len(c["x"]) for c in processed_curves)
    for c in processed_curves:
        nm = c["name"]
        headers.extend([f"{nm}_{x_header}", f"{nm}_Offset_Y", f"{nm}_Raw_Y"])
    ws.append(headers)

    for row_i in range(max_len):
        row_vals: List[Any] = []
        for c in processed_curves:
            if row_i < len(c["x"]):
                row_vals.extend([float(c["x"][row_i]), float(c["y_offset"][row_i]), float(c["y_raw"][row_i])])
            else:
                row_vals.extend([None, None, None])
        ws.append(row_vals)
    _style_worksheet(ws)

    if feature_rows:
        ws_f = wb.create_sheet(title="特征峰与结构指标汇总")
        keys = list(feature_rows[0].keys())
        ws_f.append(keys)
        for fr in feature_rows:
            ws_f.append([fr.get(k) for k in keys])
        _style_worksheet(ws_f)

    return _safe_save_wb(wb, out_p)


def export_nyquist_workbook(
    eis_series: List[Dict[str, Any]],
    out_xlsx: str | Path,
) -> str:
    """Export EIS Nyquist & Bode data sheets plus key Rs / semicircle summary."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    summary_rows = []
    for item in eis_series:
        nm = item["name"]
        ws = wb.create_sheet(title=nm[:31])
        ws.append(["Frequency (Hz)", "Z' (Ohm)", "-Z'' (Ohm)", "|Z| (Ohm)", "Phase (deg)"])
        f_arr, zr, nzi, zm, ph = item["freq_Hz"], item["z_real"], item["neg_z_imag"], item["z_mod"], item["phase_deg"]
        for i in range(len(f_arr)):
            ws.append([float(f_arr[i]), float(zr[i]), float(nzi[i]), float(zm[i]), float(ph[i])])
        _style_worksheet(ws)

        rs_est = float(zr[0])
        peak_idx = int(np.argmax(nzi[: max(5, len(nzi) * 2 // 3)]))
        valley_idx = peak_idx + int(np.argmin(nzi[peak_idx:])) if peak_idx + 1 < len(nzi) else peak_idx
        rct_span_est = max(0.0, float(zr[valley_idx] - rs_est))
        summary_rows.append(
            [nm, float(np.max(f_arr)), float(np.min(f_arr)), round(rs_est, 4), round(float(zr[valley_idx]), 4), round(rct_span_est, 4)]
        )

    ws_s = wb.create_sheet(title="阻抗关键指标初筛")
    ws_s.append(["样品名称", "最高频率 (Hz)", "最低频率 (Hz)", "高频实部起点 Z'_HF (Ohm)", "中频谷值实部 Z'_valley (Ohm)", "半圆跨度初估 (Ohm)"])
    for r in summary_rows:
        ws_s.append(r)
    _style_worksheet(ws_s)

    return _safe_save_wb(wb, out_p)


def export_bet_workbook(isotherm: Dict[str, Any], psd: Dict[str, Any], out_xlsx: str | Path, bet_area: Optional[float] = None) -> str:
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "N2_吸脱附等温线"
    ws1.append(["Adsorption_P/P0", "Adsorption_Vol (cm^3/g STP)", "Desorption_P/P0", "Desorption_Vol (cm^3/g STP)"])
    n_max = max(len(isotherm["ads_p_p0"]), len(isotherm["des_p_p0"]))
    for i in range(n_max):
        ax = float(isotherm["ads_p_p0"][i]) if i < len(isotherm["ads_p_p0"]) else None
        ay = float(isotherm["ads_vol"][i]) if i < len(isotherm["ads_vol"]) else None
        dx = float(isotherm["des_p_p0"][i]) if i < len(isotherm["des_p_p0"]) else None
        dy = float(isotherm["des_vol"][i]) if i < len(isotherm["des_vol"]) else None
        ws1.append([ax, ay, dx, dy])
    _style_worksheet(ws1)

    ws2 = wb.create_sheet(title="孔径分布_PSD")
    ws2.append(["Pore Diameter (nm)", "Differential Pore Volume", "Cumulative Pore Volume (cm^3/g)"])
    for d, dv, cv in zip(psd["diameter_nm"], psd["diff_vol"], psd["cum_pore_vol"]):
        ws2.append([float(d), float(dv), float(cv)])
    _style_worksheet(ws2)

    ws3 = wb.create_sheet(title="比表与孔结构指标")
    ws3.append(["BET 比表面积 (m^2/g)", "最大吸附量 (cm^3/g STP)", "最可几孔径峰值 (nm)"])
    pk_d = float(psd["diameter_nm"][int(np.argmax(psd["diff_vol"]))])
    ws3.append([bet_area, round(isotherm["max_vol_cm3_g"], 3), round(pk_d, 3)])
    _style_worksheet(ws3)

    return _safe_save_wb(wb, out_p)


def export_particle_size_workbook(ps_data: Dict[str, Any], out_xlsx: str | Path, sample_name: str = "Sample") -> str:
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "激光粒度对数分布"
    ws1.append(["Particle Size (um)", "Differential Volume (%)", "Cumulative Volume (%)"])
    for s, dv, cv in zip(ps_data["size_um"], ps_data["diff_vol_pct"], ps_data["cum_vol_pct"]):
        ws1.append([float(s), float(dv), float(cv)])
    _style_worksheet(ws1)

    ws2 = wb.create_sheet(title="特征粒径汇总")
    meta = ps_data.get("metrics", {})
    ws2.append(["Sample", "D10 (um)", "D50 (um)", "D90 (um)", "D[4,3] (um)", "Span"])
    ws2.append([sample_name, meta.get("D10_um"), meta.get("D50_um"), meta.get("D90_um"), meta.get("D43_um"), meta.get("Span")])
    _style_worksheet(ws2)

    return _safe_save_wb(wb, out_p)


def export_epr_workbook(x: np.ndarray, y_raw: np.ndarray, epr_metrics: Dict[str, Any], out_xlsx: str | Path, x_label: str = "g-factor") -> str:
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "EPR_一阶微分谱"
    ws1.append([x_label, "Raw_dI/dB", "Baseline_Corrected_dI/dB"])
    for xv, yr, yc in zip(x, y_raw, epr_metrics["y_corrected"]):
        ws1.append([float(xv), float(yr), float(yc)])
    _style_worksheet(ws1)

    ws2 = wb.create_sheet(title="EPR_顺磁特征参数")
    ws2.append(["零点交叉中心 (g0 或 B0)", "正峰位置", "负峰位置", "峰-峰宽度 Δpp", "峰-峰幅值"])
    ws2.append(
        [
            round(epr_metrics["center_zero_crossing"], 5),
            round(epr_metrics["x_peak_pos"], 5),
            round(epr_metrics["x_peak_neg"], 5),
            round(epr_metrics["peak_to_peak_width"], 5),
            round(epr_metrics["peak_to_peak_amplitude"], 5),
        ]
    )
    _style_worksheet(ws2)

    return _safe_save_wb(wb, out_p)


def export_conductivity_workbook(cond_data: Dict[str, Any], out_xlsx: str | Path) -> str:
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "粉体电导与压实密度"
    ws.append(["Pressure (MPa)", "Compact Density (g/cm^3)", "Resistivity (GOhm·cm)", cond_data["conductivity_label"]])
    for pr, dn, rs, cd in zip(cond_data["pressure_MPa"], cond_data["density_g_cm3"], cond_data["resistivity"], cond_data["conductivity"]):
        ws.append([float(pr), float(dn) if np.isfinite(dn) else None, float(rs) if np.isfinite(rs) else None, float(cd)])
    _style_worksheet(ws)
    return _safe_save_wb(wb, out_p)


def export_neware_rate_workbook(
    rate_items: List[Dict[str, Any]],
    out_xlsx: str | Path,
    capacity_basis: str = "specific_mAh_g",
) -> str:
    """Export Neware galvanostatic rate curves (XYXY) + metrics sheet; strictly honors missing active mass."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws_c = wb.active
    use_spec = capacity_basis == "specific_mAh_g"
    ws_c.title = "XYXY_倍率放电曲线"

    headers: List[str] = []
    q_key = "specific_capacity_mAh_g" if use_spec else "capacity_mAh"
    x_unit_lbl = "SpecCap (mAh/g)" if use_spec else "Cap (mAh)"
    max_len = max(len(it[q_key]) for it in rate_items)
    for it in rate_items:
        nm = it["name"]
        headers.extend([f"{nm}_{x_unit_lbl}", f"{nm}_Voltage (V)"])
    ws_c.append(headers)

    for r_i in range(max_len):
        row: List[Any] = []
        for it in rate_items:
            q_arr, v_arr = it[q_key], it["voltage_V"]
            if r_i < len(q_arr):
                row.extend([round(float(q_arr[r_i]), 5), round(float(v_arr[r_i]), 5)])
            else:
                row.extend([None, None])
        ws_c.append(row)
    _style_worksheet(ws_c)

    ws_m = wb.create_sheet(title="电化学性能指标汇总")
    ws_m.append(
        [
            "倍率/样品名称",
            "活性物质质量 (mg)",
            "平均放电电流 (mA)",
            "原始放电容量 (mAh)",
            "放电比容量 (mAh/g)",
            "中值放电电压 (V)",
            "原始放电能量 (mWh)",
            "放电比能量 (Wh/kg)",
            "计算口径与缺项说明",
            "原始文件",
        ]
    )
    for it in rate_items:
        has_m = bool(it.get("has_active_mass"))
        status_note = "完整 (含质量分母)" if has_m else "缺失活性物质质量分母，比容量/比能量不可计算，按原始 mAh/mWh 比较"
        ws_m.append(
            [
                it["name"],
                round(it["mass_mg"], 4) if has_m else "缺失",
                round(it["mean_current_mA"], 4),
                round(it["max_capacity_mAh"], 4),
                round(it["max_capacity_mAh_g"], 2) if (has_m and it.get("max_capacity_mAh_g") is not None) else "N/A (缺质量)",
                round(it["median_voltage_V"], 4),
                round(it["max_energy_mWh"], 4),
                round(it["max_energy_Wh_kg"], 2) if (has_m and it.get("max_energy_Wh_kg") is not None) else "N/A (缺质量)",
                status_note,
                it.get("source_file", ""),
            ]
        )
    _style_worksheet(ws_m)
    return _safe_save_wb(wb, out_p)


def export_raw_preview_workbook(
    regions_raw: Dict[str, Dict[str, Any]],
    out_xlsx: str | Path,
    sample_name: str = "Sample",
) -> str:
    """Export raw unfitted spectra and signal quality inspection summary."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sum_rows = []
    for reg, d in regions_raw.items():
        ws = wb.create_sheet(title=f"{reg}_Raw"[:31])
        ws.append([d.get("x_label", "X"), d.get("y_label", "Intensity")])
        xv, yv = d["x"], d["y"]
        idxs = range(len(xv) - 1, -1, -1) if d.get("invert_x", False) else range(len(xv))
        for i in idxs:
            ws.append([float(xv[i]), float(yv[i])])
        _style_worksheet(ws)
        sum_rows.append(
            [
                sample_name,
                reg,
                round(float(xv.min()), 2),
                round(float(xv.max()), 2),
                round(float(d.get("peak_x", xv[int(np.argmax(yv))])), 2),
                d.get("snr"),
                "TRACE_SIGNAL (SNR < 3.5)" if (d.get("snr") is not None and d["snr"] < 3.5) else "SIGNAL_OK (Unfitted Raw Preview)",
            ]
        )
    ws_s = wb.create_sheet(title="原始谱区探测汇总")
    ws_s.append(["样品", "谱区", "X_min", "X_max", "最大峰位", "估计SNR", "数据状态"])
    for r in sum_rows:
        ws_s.append(r)
    _style_worksheet(ws_s)
    return _safe_save_wb(wb, out_p)


def export_model_sensitivity_workbook(
    model_rows: List[Dict[str, Any]],
    comp_ranges: List[Dict[str, Any]],
    out_xlsx: str | Path,
) -> str:
    """Export multi-candidate model comparison & component sensitivity swing table."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "候选模型参数与触界明细"
    if model_rows:
        keys1 = list(model_rows[0].keys())
        ws1.append(keys1)
        for r in model_rows:
            ws1.append([r.get(k) for k in keys1])
    _style_worksheet(ws1)

    ws2 = wb.create_sheet(title="组分面积比例敏感性区间")
    if comp_ranges:
        keys2 = list(comp_ranges[0].keys())
        ws2.append(keys2)
        for r in comp_ranges:
            ws2.append([r.get(k) for k in keys2])
    _style_worksheet(ws2)
    return _safe_save_wb(wb, out_p)


def export_composite_source_data_workbook(panels_rendered: List[Dict[str, Any]], out_xlsx: str | Path) -> str:
    """Export Nature/ACS-compliant multi-sheet Source Data Excel workbook covering every panel (a)..(n)."""
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    deconv_summary_rows: List[List[Any]] = []

    for idx, p in enumerate(panels_rendered):
        letter = chr(ord("a") + idx)
        raw_title = f"Panel_{letter}_{p.get('panel_id', p['panel_type'])}"
        sheet_title = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in raw_title)[:31]
        ws = wb.create_sheet(title=sheet_title)
        ptype = p["panel_type"]

        if ptype == "deconvolve":
            res = p["fit_result"]
            comps = res["components"]
            ws.append([res.get("x_label", "X"), "Raw", "Fitting", "Backgnd.", *[f"{m['name']} (含基线)" for m in comps], "Residuals"])
            idxs = range(len(res["x"]) - 1, -1, -1) if res.get("invert_x") else range(len(res["x"]))
            for i in idxs:
                ws.append(
                    [
                        float(res["x"][i]),
                        float(res["y_raw"][i]),
                        float(res["y_fit"][i]),
                        float(res["baseline"][i]),
                        *[float(cb[i]) for cb in res["comp_curves_with_bg"]],
                        float(res["residuals"][i]),
                    ]
                )
            pid = p.get("panel_id", f"Panel_{letter}")
            reg_lbl = p.get("panel_title") or pid
            for m in comps:
                deconv_summary_rows.append(
                    [
                        f"({letter}) {pid}",
                        reg_lbl,
                        m["name"],
                        round(m["center"], 4),
                        round(m["fwhm"], 4),
                        round(m["area_pct"], 3),
                        round(m["subgroup_pct"], 3) if m["subgroup_pct"] is not None else None,
                        round(res.get("charge_shift_eV", 0.0), 4),
                        res.get("charge_anchor_note", ""),
                        round(res["nrmse_pct"], 4),
                        round(res["r_squared"], 5),
                        res.get("snr"),
                        res.get("audit_summary") or "PASS",
                    ]
                )
        elif ptype == "waterfall":
            proc = p["processed_curves"]
            hdrs = []
            for c in proc:
                hdrs.extend([f"{c['name']}_X", f"{c['name']}_Offset_Y", f"{c['name']}_Raw_Y"])
            ws.append(hdrs)
            m_len = max(len(c["x"]) for c in proc)
            for r_i in range(m_len):
                r_vals: List[Any] = []
                for c in proc:
                    if r_i < len(c["x"]):
                        r_vals.extend([float(c["x"][r_i]), float(c["y_offset"][r_i]), float(c["y_raw"][r_i])])
                    else:
                        r_vals.extend([None, None, None])
                ws.append(r_vals)
        elif ptype == "nyquist":
            eis_s = p["eis_series"]
            hdrs = []
            for s in eis_s:
                hdrs.extend([f"{s['name']}_Freq_Hz", f"{s['name']}_Z_real_Ohm", f"{s['name']}_Neg_Z_imag_Ohm"])
            ws.append(hdrs)
            m_len = max(len(s["freq_Hz"]) for s in eis_s)
            for r_i in range(m_len):
                r_vals = []
                for s in eis_s:
                    if r_i < len(s["freq_Hz"]):
                        r_vals.extend([float(s["freq_Hz"][r_i]), float(s["z_real"][r_i]), float(s["neg_z_imag"][r_i])])
                    else:
                        r_vals.extend([None, None, None])
                ws.append(r_vals)
        elif ptype == "xy_series":
            s_list = p["series_list"]
            hdrs = []
            for s in s_list:
                hdrs.extend([f"{s['name']}_X", f"{s['name']}_Y"])
            ws.append(hdrs)
            m_len = max(len(s["x"]) for s in s_list)
            for r_i in range(m_len):
                r_vals = []
                for s in s_list:
                    if r_i < len(s["x"]):
                        r_vals.extend([float(s["x"][r_i]), float(s["y"][r_i])])
                    else:
                        r_vals.extend([None, None])
                ws.append(r_vals)

        _style_worksheet(ws)

    if deconv_summary_rows:
        ws_ds = wb.create_sheet(title="分峰与荷电校正汇总")
        ws_ds.append(
            [
                "面板 (Panel)",
                "谱区/标题 (Region)",
                "组分名称 (Component)",
                "峰位 Center",
                "半峰宽 FWHM",
                "占谱区总面积 (%)",
                "占子体系内部 (%)",
                "荷电校正平移 (eV)",
                "荷电校正说明 (Charge Ref)",
                "拟合残差 NRMSE (%)",
                "决定系数 R^2",
                "谱区信噪比 SNR",
                "质检与审计标记 (Audit Status)",
            ]
        )
        for r in deconv_summary_rows:
            ws_ds.append(r)
        _style_worksheet(ws_ds)

    return _safe_save_wb(wb, out_p)


def export_xy_series_workbook(series_list: List[Dict[str, Any]], out_xlsx: str | Path, x_header: str = "X", y_header: str = "Y") -> str:
    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "XYXY_曲线数据汇总"
    headers: List[str] = []
    max_len = max(len(s["x"]) for s in series_list)
    for s in series_list:
        nm = s["name"]
        headers.extend([f"{nm}_{x_header}", f"{nm}_{y_header}"])
    ws.append(headers)
    for r_i in range(max_len):
        row: List[Any] = []
        for s in series_list:
            if r_i < len(s["x"]):
                row.extend([float(s["x"][r_i]), float(s["y"][r_i])])
            else:
                row.extend([None, None])
        ws.append(row)
    _style_worksheet(ws)
    return _safe_save_wb(wb, out_p)


# ---------------------------------------------------------------------------
# Multi-Chart Grammar Source Data Workbook Exporter
# ---------------------------------------------------------------------------

def _to_plain_dict(obj: Any) -> Any:
    """Convert Dataclass / `.to_dict()` / nested containers into plain dicts/lists while keeping numpy arrays."""
    if obj is None or isinstance(obj, (str, int, float, bool, np.ndarray, pd.DataFrame)):
        return obj
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return _to_plain_dict(obj.to_dict())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_plain_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain_dict(v) for v in obj]
    return obj


def _excel_scalar(val: Any) -> Any:
    """Convert numpy/pandas scalars to openpyxl-safe Python scalars; map NaN/Inf to None."""
    if val is None:
        return None
    if isinstance(val, (bool, np.bool_)):
        return bool(val)
    if isinstance(val, (int, np.integer)):
        return int(val)
    if isinstance(val, (float, np.floating)):
        fv = float(val)
        return fv if np.isfinite(fv) else None
    if isinstance(val, str):
        return val
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return str(val)


def _clean_header_text(raw: Any) -> str:
    """Strip LaTeX wrappers (`$...$`, `\\mathrm{...}`) for crisp Excel column headers."""
    s = str(raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"\\(?:mathrm|mathit|mathbf|mathsf|text)\{([^{}]*)\}", r"\1", s)
    s = s.replace("$", "").replace("{", "").replace("}", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _format_col_header(
    name: str,
    unit: Optional[str] = None,
    axis_badge: Optional[str] = None,
) -> str:
    """Compose `<Name> (<Unit>) [Left-Y/Right-Y]` without duplicating existing parenthesized units."""
    base = _clean_header_text(name) or "Value"
    u = _clean_header_text(unit) if unit else ""
    if u and f"({u})" not in base and f"[{u}]" not in base:
        # Also avoid duplicating if base already ends with `(...)` containing same unit token
        trailing_paren = re.search(r"\(([^()]+)\)\s*$", base)
        if not (trailing_paren and u.lower() in trailing_paren.group(1).lower()):
            base = f"{base} ({u})"
    if axis_badge:
        base = f"{base} [{axis_badge}]"
    return base


def _unique_sheet_title(wb: openpyxl.Workbook, raw_title: str) -> str:
    """Sanitize and deduplicate Excel worksheet title within the 31-character limit."""
    cleaned = re.sub(r"[\[\]:*?/\\]+", "_", str(raw_title or "Sheet").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_") or "Sheet"
    cand = cleaned[:31]
    existing = set(wb.sheetnames)
    if cand not in existing:
        return cand
    idx = 2
    while True:
        suffix = f"_{idx}"
        cand_i = f"{cleaned[: 31 - len(suffix)]}{suffix}"
        if cand_i not in existing:
            return cand_i
        idx += 1


def _normalize_axis_key(axis_raw: Any) -> str:
    s = str(axis_raw or "y1").strip().lower()
    if s in ("y2", "right", "right_y", "yr", "secondary"):
        return "y2"
    return "y1"


def _extract_panel_axes_meta(panel: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Extract `{x, y1, y2}` `{label, unit}` metadata across all supported AxisSpec layouts."""
    meta: Dict[str, Dict[str, str]] = {
        "x": {"label": "", "unit": ""},
        "y1": {"label": "", "unit": ""},
        "y2": {"label": "", "unit": ""},
    }

    def _ingest_axis(slot: str, ax_obj: Any) -> None:
        if not isinstance(ax_obj, dict):
            if isinstance(ax_obj, str) and ax_obj.strip():
                meta[slot]["label"] = _clean_header_text(ax_obj)
            return
        lbl = ax_obj.get("label") or ax_obj.get("title") or ax_obj.get("name") or ""
        unit = ax_obj.get("unit") or ""
        if lbl:
            meta[slot]["label"] = _clean_header_text(lbl)
        if unit:
            meta[slot]["unit"] = _clean_header_text(unit)

    axes_container = panel.get("axes")
    if isinstance(axes_container, dict):
        for k, v in axes_container.items():
            kl = k.lower()
            if kl in ("x", "bottom", "xb"):
                _ingest_axis("x", v)
            elif kl in ("y", "y1", "left", "left_y", "yl"):
                _ingest_axis("y1", v)
            elif kl in ("y2", "right", "right_y", "yr"):
                _ingest_axis("y2", v)
    elif isinstance(axes_container, list):
        for item in axes_container:
            if isinstance(item, dict):
                pos = str(item.get("axis") or item.get("position") or item.get("side") or "").lower()
                if pos in ("x", "bottom"):
                    _ingest_axis("x", item)
                elif pos in ("y2", "right", "right_y"):
                    _ingest_axis("y2", item)
                elif pos in ("y", "y1", "left", "left_y"):
                    _ingest_axis("y1", item)

    for k_x in ("x_axis", "xaxis"):
        if k_x in panel:
            _ingest_axis("x", panel[k_x])
    for k_y1 in ("y_axis", "y1_axis", "left_y", "yaxis"):
        if k_y1 in panel:
            _ingest_axis("y1", panel[k_y1])
    for k_y2 in ("y2_axis", "right_y", "secondary_y"):
        if k_y2 in panel:
            _ingest_axis("y2", panel[k_y2])

    if not meta["x"]["label"] and panel.get("x_label"):
        meta["x"]["label"] = _clean_header_text(panel["x_label"])
    if not meta["x"]["unit"] and panel.get("x_unit"):
        meta["x"]["unit"] = _clean_header_text(panel["x_unit"])
    if not meta["y1"]["label"] and panel.get("y_label"):
        meta["y1"]["label"] = _clean_header_text(panel["y_label"])
    if not meta["y1"]["unit"] and panel.get("y_unit"):
        meta["y1"]["unit"] = _clean_header_text(panel["y_unit"])
    if not meta["y2"]["label"] and panel.get("y2_label"):
        meta["y2"]["label"] = _clean_header_text(panel["y2_label"])
    if not meta["y2"]["unit"] and panel.get("y2_unit"):
        meta["y2"]["unit"] = _clean_header_text(panel["y2_unit"])

    return meta


def _write_1d_series_to_sheet(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    series_entries: List[Dict[str, Any]],
    axes_meta: Dict[str, Dict[str, str]],
    has_dual_y: bool,
    panel_categories: Optional[List[Any]] = None,
) -> None:
    """Write 1D series entries (categorical, shared numeric X, or independent XYXY) into `ws`."""
    if not series_entries:
        ws.append(["Info"])
        ws.append(["Empty layer / no 1D series"])
        _style_worksheet(ws)
        return

    x_lbl_base = axes_meta["x"]["label"] or "X"
    x_unit_base = axes_meta["x"]["unit"]
    has_extra_cols = any(bool(e.get("extra_cols")) or bool(e.get("swap_depth_first")) for e in series_entries)

    # Determine if all series share categorical X or identical numeric X
    resolved_cats: Optional[List[str]] = None
    if not has_extra_cols and panel_categories is not None and len(panel_categories) > 0:
        cand_cats = [str(c) for c in panel_categories]
        if all(len(e["y"]) == len(cand_cats) and (e["x"] is None or len(e["x"]) == len(cand_cats)) for e in series_entries):
            resolved_cats = cand_cats
    elif not has_extra_cols:
        first_cats = series_entries[0].get("categories")
        if first_cats is not None and len(first_cats) > 0:
            cand_cats = [str(c) for c in first_cats]
            if all(
                len(e["y"]) == len(cand_cats)
                and (
                    e.get("categories") == first_cats
                    or e["x"] is None
                    or [str(v) for v in e["x"]] == cand_cats
                )
                for e in series_entries
            ):
                resolved_cats = cand_cats
        elif series_entries[0]["x"] is not None and len(series_entries[0]["x"]) > 0:
            x0 = series_entries[0]["x"]
            if all(isinstance(v, str) for v in x0):
                cand_cats = [str(v) for v in x0]
                if all(
                    e["x"] is not None and len(e["x"]) == len(cand_cats) and [str(v) for v in e["x"]] == cand_cats
                    for e in series_entries
                ):
                    resolved_cats = cand_cats

    shared_numeric_x: Optional[np.ndarray] = None
    if not has_extra_cols and resolved_cats is None and all(e["x"] is not None and len(e["x"]) == len(series_entries[0]["x"]) for e in series_entries):
        try:
            x0_arr = np.asarray(series_entries[0]["x"], dtype=float).ravel()
            if len(x0_arr) > 0 and np.all(np.isfinite(x0_arr)):
                all_match = True
                for e in series_entries[1:]:
                    xk_arr = np.asarray(e["x"], dtype=float).ravel()
                    if not (len(xk_arr) == len(x0_arr) and np.allclose(x0_arr, xk_arr, rtol=0.0, atol=1e-9)):
                        all_match = False
                        break
                if all_match:
                    shared_numeric_x = x0_arr
        except (TypeError, ValueError):
            shared_numeric_x = None

    if resolved_cats is not None or shared_numeric_x is not None:
        n_rows = len(resolved_cats) if resolved_cats is not None else len(shared_numeric_x)  # type: ignore[arg-type]
        cat_default_lbl = axes_meta["x"]["label"] or ("Category" if resolved_cats is not None else "X")
        headers: List[str] = [_format_col_header(cat_default_lbl, x_unit_base)]
        col_vectors: List[List[Any]] = [
            list(resolved_cats) if resolved_cats is not None else [_excel_scalar(v) for v in shared_numeric_x]  # type: ignore[union-attr]
        ]

        for entry in series_entries:
            ax_key = entry["axis"]
            badge = ("Right-Y" if ax_key == "y2" else "Left-Y") if has_dual_y else None
            eff_unit = entry["unit"] or axes_meta[ax_key]["unit"]
            s_name = entry["name"]

            headers.append(_format_col_header(s_name, eff_unit, axis_badge=badge))
            col_vectors.append([_excel_scalar(v) for v in entry["y"]])

            if entry["y_err"] is not None:
                headers.append(_format_col_header(f"{s_name}_Err", eff_unit, axis_badge=badge))
                col_vectors.append([_excel_scalar(v) for v in entry["y_err"]])
            if entry["y_low"] is not None and entry["y_high"] is not None:
                headers.append(_format_col_header(f"{s_name}_Lower", eff_unit, axis_badge=badge))
                col_vectors.append([_excel_scalar(v) for v in entry["y_low"]])
                headers.append(_format_col_header(f"{s_name}_Upper", eff_unit, axis_badge=badge))
                col_vectors.append([_excel_scalar(v) for v in entry["y_high"]])
            if entry["y_fit"] is not None:
                headers.append(_format_col_header(f"{s_name}_Fit", eff_unit, axis_badge=badge))
                col_vectors.append([_excel_scalar(v) for v in entry["y_fit"]])

        ws.append(headers)
        for r_i in range(n_rows):
            ws.append([vec[r_i] if r_i < len(vec) else None for vec in col_vectors])
        _style_worksheet(ws)
        return

    # Independent XYXY multi-series layout
    headers = []
    col_blocks: List[List[List[Any]]] = []
    max_rows = 0

    for entry in series_entries:
        ax_key = entry["axis"]
        badge = ("Right-Y" if ax_key == "y2" else "Left-Y") if has_dual_y else None
        eff_y_unit = entry["unit"] or axes_meta[ax_key]["unit"]
        eff_x_lbl = entry["x_label"] or x_lbl_base
        eff_x_unit = entry["x_unit"] or x_unit_base
        s_name = entry["name"]

        y_vals = list(entry["y"])
        if entry["x"] is not None:
            x_vals = list(entry["x"])
        elif entry.get("categories") is not None:
            x_vals = list(entry["categories"])
        else:
            x_vals = list(range(1, len(y_vals) + 1))

        n_cur = min(len(x_vals), len(y_vals))
        for _ex_hdr, _ex_u, ex_vals in (entry.get("extra_cols") or []):
            max_rows = max(max_rows, len(ex_vals))
        max_rows = max(max_rows, n_cur)

        if entry.get("swap_depth_first"):
            d_lbl = entry.get("depth_label") or axes_meta[ax_key]["label"] or "Depth"
            headers.append(_format_col_header(f"{s_name}_{d_lbl}" if len(series_entries) > 1 else d_lbl, eff_y_unit))
            headers.append(_format_col_header(entry.get("y_header_override") or eff_x_lbl or s_name, eff_x_unit, axis_badge=badge))
            block_cols: List[List[Any]] = [
                [_excel_scalar(y_vals[i]) for i in range(n_cur)],
                [_excel_scalar(x_vals[i]) for i in range(n_cur)],
            ]
        else:
            headers.append(_format_col_header(f"{s_name}_{eff_x_lbl}", eff_x_unit))
            headers.append(_format_col_header(entry.get("y_header_override") or s_name, eff_y_unit, axis_badge=badge))
            block_cols = [
                [_excel_scalar(x_vals[i]) for i in range(n_cur)],
                [_excel_scalar(y_vals[i]) for i in range(n_cur)],
            ]

        if entry["y_err"] is not None:
            headers.append(_format_col_header(f"{s_name}_Err", eff_y_unit, axis_badge=badge))
            err_v = list(entry["y_err"])
            block_cols.append([_excel_scalar(err_v[i]) if i < len(err_v) else None for i in range(n_cur)])
        if entry["y_low"] is not None and entry["y_high"] is not None:
            lo_v, hi_v = list(entry["y_low"]), list(entry["y_high"])
            headers.append(_format_col_header(f"{s_name}_Lower", eff_y_unit, axis_badge=badge))
            block_cols.append([_excel_scalar(lo_v[i]) if i < len(lo_v) else None for i in range(n_cur)])
            headers.append(_format_col_header(f"{s_name}_Upper", eff_y_unit, axis_badge=badge))
            block_cols.append([_excel_scalar(hi_v[i]) if i < len(hi_v) else None for i in range(n_cur)])
        if entry["y_fit"] is not None:
            fit_v = list(entry["y_fit"])
            headers.append(_format_col_header(f"{s_name}_Fit", eff_y_unit, axis_badge=badge))
            block_cols.append([_excel_scalar(fit_v[i]) if i < len(fit_v) else None for i in range(n_cur)])
        for ex_hdr, ex_u, ex_vals in (entry.get("extra_cols") or []):
            headers.append(_format_col_header(ex_hdr, ex_u, axis_badge=badge))
            block_cols.append([_excel_scalar(v) for v in ex_vals])

        col_blocks.append(block_cols)

    ws.append(headers)
    for r_i in range(max_rows):
        row_out: List[Any] = []
        for blk in col_blocks:
            for col_vec in blk:
                row_out.append(col_vec[r_i] if r_i < len(col_vec) else None)
        ws.append(row_out)
    _style_worksheet(ws)


def _write_2d_matrix_to_sheet(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    mat_spec: Dict[str, Any],
    axes_meta: Dict[str, Dict[str, str]],
) -> None:
    """Write a 2D field/contour/heatmap matrix (`z_matrix` of shape `(ny, nx)`) into `ws`."""
    z_raw = mat_spec.get("matrix_z")
    if z_raw is None:
        z_raw = mat_spec.get("z_matrix")
    if z_raw is None:
        z_raw = mat_spec.get("values")
    z_arr = np.asarray(z_raw, dtype=float)
    if z_arr.ndim != 2:
        raise ValueError(f"Expected 2D matrix array in matrix layer, got shape={z_arr.shape}.")

    x_raw = mat_spec.get("matrix_x", mat_spec.get("x_grid"))
    y_raw = mat_spec.get("matrix_y", mat_spec.get("y_grid"))
    x_labels = mat_spec.get("x_labels") or mat_spec.get("cols")
    y_labels = mat_spec.get("y_labels") or mat_spec.get("rows")

    ny_cand, nx_cand = z_arr.shape
    if x_raw is not None and y_raw is not None:
        x_arr = np.asarray(x_raw, dtype=float).ravel()
        y_arr = np.asarray(y_raw, dtype=float).ravel()
        if z_arr.shape == (len(y_arr), len(x_arr)):
            z_mat = z_arr
        elif z_arr.shape == (len(x_arr), len(y_arr)):
            z_mat = z_arr.T
        else:
            raise ValueError(
                f"2D matrix shape {z_arr.shape} mismatches x_grid ({len(x_arr)}) and y_grid ({len(y_arr)})."
            )
    else:
        z_mat = z_arr
        x_arr = np.arange(1, nx_cand + 1, dtype=float) if x_raw is None else np.asarray(x_raw, dtype=float).ravel()
        y_arr = np.arange(1, ny_cand + 1, dtype=float) if y_raw is None else np.asarray(y_raw, dtype=float).ravel()

    ny, nx = z_mat.shape
    x_hdr = _format_col_header(
        mat_spec.get("x_label") or axes_meta["x"]["label"] or "X",
        mat_spec.get("x_unit") or axes_meta["x"]["unit"],
    )
    y_hdr = _format_col_header(
        mat_spec.get("y_label") or axes_meta["y1"]["label"] or "Y / State",
        mat_spec.get("y_unit") or axes_meta["y1"]["unit"],
    )
    z_hdr = _format_col_header(
        mat_spec.get("z_label") or mat_spec.get("colorbar_label") or "Z",
        mat_spec.get("z_unit"),
    )

    corner = f"{x_hdr} \\ {y_hdr} [{z_hdr}]"
    col_headers: List[str] = [corner]
    for j in range(ny):
        if y_labels is not None and j < len(y_labels) and str(y_labels[j]).strip():
            col_headers.append(str(y_labels[j]).strip())
        else:
            col_headers.append(f"{y_hdr}={y_arr[j]:.6g}")
    ws.append(col_headers)

    for i in range(nx):
        if x_labels is not None and i < len(x_labels) and str(x_labels[i]).strip():
            x_cell: Any = str(x_labels[i]).strip()
        else:
            x_cell = _excel_scalar(x_arr[i])
        row_vals = [x_cell] + [_excel_scalar(z_mat[j, i]) for j in range(ny)]
        ws.append(row_vals)

    _style_worksheet(ws)


def _extract_layer_series_entries(
    layer: Dict[str, Any],
    default_axis: str = "y1",
    panel_categories: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Normalize `SeriesSpec` / `stacks` items inside a `LayerSpec` dict into uniform export records."""
    layer_axis = _normalize_axis_key(layer.get("axis") or layer.get("y_axis") or layer.get("target_axis") or default_axis)
    layer_cats = layer.get("categories") if layer.get("categories") is not None else panel_categories
    layer_unit = layer.get("unit") or ("%" if "100pct" in str(layer.get("mark") or layer.get("geom") or layer.get("kind") or "") else None)

    raw_list = layer.get("series")
    if raw_list is None:
        raw_list = layer.get("stacks")
    if not raw_list:
        # Check if layer itself holds direct `x` & `y` arrays
        if ("y" in layer or "values" in layer) and not isinstance(layer.get("values"), list) and layer.get("matrix_z") is None:
            raw_list = [layer]
        elif ("y" in layer or "values" in layer) and layer.get("matrix_z") is None and layer.get("z_matrix") is None:
            y_cand = layer.get("y", layer.get("values"))
            if y_cand is not None and np.asarray(y_cand).ndim == 1:
                raw_list = [layer]
            else:
                return []
        else:
            return []

    entries: List[Dict[str, Any]] = []
    for idx, s in enumerate(raw_list):
        if not isinstance(s, dict):
            continue
        y_raw = s.get("y")
        if y_raw is None:
            y_raw = s.get("values")
        if y_raw is None:
            continue
        y_arr_check = np.asarray(y_raw)
        if y_arr_check.ndim != 1 or len(y_arr_check) == 0:
            continue

        sm = s.get("meta") if isinstance(s.get("meta"), dict) else {}
        if sm.get("is_chance_line") or sm.get("is_optimal_point") or sm.get("is_ts_barrier"):
            continue

        s_axis = _normalize_axis_key(s.get("axis") or layer_axis)
        s_name = str(s.get("name") or s.get("label") or f"Series_{idx + 1}").strip()
        x_raw = s.get("x")
        s_cats = s.get("categories") if s.get("categories") is not None else layer_cats
        y_err = s.get("y_err") if s.get("y_err") is not None else s.get("errors", s.get("err"))
        y_low = s.get("y_low") if s.get("y_low") is not None else s.get("lower")
        y_high = s.get("y_high") if s.get("y_high") is not None else s.get("upper")
        y_fit = s.get("y_fit") if s.get("y_fit") is not None else s.get("fit_y")

        eff_x_lbl = s.get("x_label") or layer.get("x_label")
        y_hdr_override: Optional[str] = None
        extra_cols: List[Tuple[str, Optional[str], List[Any]]] = []
        swap_depth = bool(sm.get("track_index") is not None and sm.get("depth_label"))

        # Preserve ternary C component (`A + B + C = 100%`)
        if sm.get("ternary_c") is not None:
            comp_lbls = sm.get("component_labels") or ["Component_A", "Component_B", "Component_C"]
            eff_x_lbl = str(comp_lbls[0])
            y_hdr_override = f"{s_name}_{comp_lbls[1]}"
            extra_cols.append((f"{s_name}_{comp_lbls[2]}", s.get("z_unit") or "%", list(sm["ternary_c"])))

        # Preserve 2D vector field `(u, v, x_end, y_end, magnitude)`
        if sm.get("u") is not None and sm.get("v") is not None:
            eff_x_lbl = eff_x_lbl or "X"
            y_hdr_override = f"{s_name}_Y"
            extra_cols.append((f"{s_name}_U", None, list(sm["u"])))
            extra_cols.append((f"{s_name}_V", None, list(sm["v"])))
            if sm.get("x_end") is not None and sm.get("y_end") is not None:
                extra_cols.append((f"{s_name}_X_End", s.get("x_unit"), list(sm["x_end"])))
                extra_cols.append((f"{s_name}_Y_End", s.get("y_unit"), list(sm["y_end"])))
            if sm.get("magnitude") is not None:
                extra_cols.append((f"{s_name}_Magnitude", None, list(sm["magnitude"])))

        # Preserve Kaplan-Meier right-censored tick coordinates if non-empty
        if layer.get("mark") == "km_step" and sm.get("censored_x"):
            extra_cols.append((f"{s_name}_Censored_Time", s.get("x_unit"), list(sm["censored_x"])))
            if sm.get("censored_y") is not None:
                extra_cols.append((f"{s_name}_Censored_Survival", s.get("y_unit") or layer_unit, list(sm["censored_y"])))

        entries.append(
            {
                "name": s_name,
                "x": x_raw,
                "y": y_raw,
                "categories": s_cats,
                "y_err": y_err,
                "y_low": y_low,
                "y_high": y_high,
                "y_fit": y_fit,
                "axis": s_axis,
                "unit": s.get("unit") or s.get("y_unit") or layer_unit,
                "x_label": eff_x_lbl,
                "x_unit": s.get("x_unit") or layer.get("x_unit"),
                "y_header_override": y_hdr_override,
                "extra_cols": extra_cols,
                "swap_depth_first": swap_depth,
                "depth_label": sm.get("depth_label"),
                "role": s.get("role"),
                "metrics": s.get("metrics") or sm,
            }
        )
    return entries


def _collect_feature_and_guide_rows(
    panel_label: str,
    obj: Dict[str, Any],
    kinetics_rows: List[Dict[str, Any]],
    guide_rows: List[Dict[str, Any]],
) -> None:
    """Harvest pulse/dQ-dV kinetics metrics, peak positions, guides, and span annotations from spec dicts."""
    if not isinstance(obj, dict):
        return

    # 1. Pulse decomposition or explicit kinetics metrics block
    for m_key in ("metrics", "kinetics_metrics", "pulse_metrics", "dqdv_metrics", "meta"):
        m_dict = obj.get(m_key)
        if isinstance(m_dict, dict):
            _extract_metric_fields(panel_label, m_dict, kinetics_rows)
    _extract_metric_fields(panel_label, obj, kinetics_rows)

    # 2. Guides & double-ended span annotations
    for g_key in ("guides", "horizontal_guides", "span_annotations"):
        g_list = obj.get(g_key)
        if isinstance(g_list, list):
            for g in g_list:
                if not isinstance(g, dict):
                    continue
                kind = str(g.get("kind") or g.get("type") or g.get("orientation") or "guide")
                lbl = str(g.get("label") or g.get("display_label") or g.get("name") or "")
                val = g.get("value", g.get("delta_v"))
                x_pos = g.get("x")
                y0 = g.get("y_start", g.get("y"))
                y1 = g.get("y_end")
                guide_rows.append(
                    {
                        "面板 (Panel)": panel_label,
                        "标注类型 (Guide Type)": kind,
                        "名称/标签 (Label)": lbl,
                        "X 位置 (X)": _excel_scalar(x_pos),
                        "起点/位置 Y0": _excel_scalar(y0 if y0 is not None else val),
                        "终点 Y1": _excel_scalar(y1),
                        "跨度/数值 (Span / Value)": _excel_scalar(val if val is not None else g.get("span")),
                    }
                )


def _extract_metric_fields(
    panel_label: str,
    d: Dict[str, Any],
    kinetics_rows: List[Dict[str, Any]],
) -> None:
    """Extract pulse voltage decomposition scalars and dQ/dV peak tables if present in `d`."""
    pulse_keys = ("v_before", "v_instant", "v_pulse_end", "v_final", "delta_v0_app", "delta_v_slow_app")
    if any(k in d and isinstance(d[k], (int, float, np.number)) for k in pulse_keys):
        row = {
            "面板/来源 (Panel / Source)": panel_label,
            "指标类别 (Metric Kind)": "Pulse_Voltage_Decomposition",
            "V_before (V)": _excel_scalar(d.get("v_before")),
            "V_instant (V)": _excel_scalar(d.get("v_instant")),
            "V_pulse_end (V)": _excel_scalar(d.get("v_pulse_end")),
            "V_final (V)": _excel_scalar(d.get("v_final")),
            "ΔV0,app (V)": _excel_scalar(d.get("delta_v0_app")),
            "ΔVslow,app (V)": _excel_scalar(d.get("delta_v_slow_app")),
            "ΔVtotal,app (V)": _excel_scalar(
                d.get("delta_v_total_app")
                if d.get("delta_v_total_app") is not None
                else (
                    float(d["v_before"] - d["v_pulse_end"])
                    if isinstance(d.get("v_before"), (int, float, np.number))
                    and isinstance(d.get("v_pulse_end"), (int, float, np.number))
                    else None
                )
            ),
            "脉冲起点 t_start (s)": _excel_scalar(d.get("t_pulse_start")),
            "脉冲脉宽 Duration (s)": _excel_scalar(d.get("t_pulse_duration_s")),
            "dQ/dV 特征峰位 (V)": None,
            "dQ/dV 峰值强度": None,
        }
        if row not in kinetics_rows:
            kinetics_rows.append(row)

    peaks_det = d.get("peaks_detail")
    if isinstance(peaks_det, list) and peaks_det:
        for pk in peaks_det:
            if isinstance(pk, dict) and "voltage_v" in pk:
                row = {
                    "面板/来源 (Panel / Source)": panel_label,
                    "指标类别 (Metric Kind)": f"dQdV_Peak ({pk.get('polarity', 'peak')})",
                    "V_before (V)": None,
                    "V_instant (V)": None,
                    "V_pulse_end (V)": None,
                    "V_final (V)": None,
                    "ΔV0,app (V)": None,
                    "ΔVslow,app (V)": None,
                    "ΔVtotal,app (V)": None,
                    "脉冲起点 t_start (s)": None,
                    "脉冲脉宽 Duration (s)": None,
                    "dQ/dV 特征峰位 (V)": _excel_scalar(pk.get("voltage_v")),
                    "dQ/dV 峰值强度": _excel_scalar(pk.get("dq_dv")),
                }
                if row not in kinetics_rows:
                    kinetics_rows.append(row)
    elif isinstance(d.get("peak_positions"), (list, tuple, np.ndarray)) and len(d["peak_positions"]) > 0:
        for pv in d["peak_positions"]:
            row = {
                "面板/来源 (Panel / Source)": panel_label,
                "指标类别 (Metric Kind)": "dQdV_Peak",
                "V_before (V)": None,
                "V_instant (V)": None,
                "V_pulse_end (V)": None,
                "V_final (V)": None,
                "ΔV0,app (V)": None,
                "ΔVslow,app (V)": None,
                "ΔVtotal,app (V)": None,
                "脉冲起点 t_start (s)": None,
                "脉冲脉宽 Duration (s)": None,
                "dQ/dV 特征峰位 (V)": _excel_scalar(pv),
                "dQ/dV 峰值强度": None,
            }
            if row not in kinetics_rows:
                kinetics_rows.append(row)


def _write_dataframe_sheet(ws: openpyxl.worksheet.worksheet.Worksheet, df: pd.DataFrame) -> None:
    """Write a pandas DataFrame into `ws` with clean headers and NaN-safe cells."""
    include_index = bool(df.index.name and str(df.index.name).strip())
    headers = ([str(df.index.name).strip()] if include_index else []) + [str(c).strip() for c in df.columns]
    ws.append(headers)
    for idx_val, row in df.iterrows():
        cells = ([_excel_scalar(idx_val)] if include_index else []) + [_excel_scalar(v) for v in row.tolist()]
        ws.append(cells)
    _style_worksheet(ws)


def _export_english_source_data_workbook(
    wb: openpyxl.Workbook,
    spec: Dict[str, Any],
    panels: List[Dict[str, Any]],
    summary_tables: Optional[Dict[str, pd.DataFrame]],
    audit_notes: Optional[List[Any]],
    out_p: Path,
) -> str:
    """
    Export Nature / Science / Cell-compliant English Source-Data `.xlsx` workbook (`locale='en'`):
    - `Raw_Data` (and `Raw_Data_<tag>` for additional panels)
    - `Summary_Statistics`
    - `Statistical_Tests` (when `stat_report` comparisons or omnibus tests exist)
    - `Curve_Fit_Summary` (when `curve_fits` records exist)
    - `Figure_Manifest`
    """
    fig_meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    stat_summary_rows: List[Dict[str, Any]] = []
    stat_test_rows: List[Dict[str, Any]] = []
    curve_fit_rows: List[Dict[str, Any]] = []
    manifest_guide_rows: List[Dict[str, Any]] = []
    fallback_summary_rows: List[Dict[str, Any]] = []
    seen_stat_reports: set[int] = set()
    seen_curve_fits: set[Tuple[str, str]] = set()

    def _harvest_stat_report(panel_label: str, sr: Any, err_bar_type: str) -> None:
        if not isinstance(sr, dict) or id(sr) in seen_stat_reports:
            return
        seen_stat_reports.add(id(sr))
        omn_test = sr.get("omnibus_test", "none")
        omn_stat = _excel_scalar(sr.get("omnibus_stat"))
        omn_p = _excel_scalar(sr.get("omnibus_p"))
        padj_m = str(sr.get("p_adjust_method", "fdr_bh"))

        for s_row in sr.get("summary") or []:
            if not isinstance(s_row, dict):
                continue
            stat_summary_rows.append(
                {
                    "Panel": panel_label,
                    "Group": str(s_row.get("group", "")),
                    "n": _excel_scalar(s_row.get("n")),
                    "Mean": _excel_scalar(s_row.get("mean")),
                    "SD": _excel_scalar(s_row.get("sd")),
                    "SEM": _excel_scalar(s_row.get("sem")),
                    "CI95_HalfWidth": _excel_scalar(s_row.get("ci95_half")),
                    "Median": _excel_scalar(s_row.get("median")),
                    "Q25": _excel_scalar(s_row.get("q25")),
                    "Q75": _excel_scalar(s_row.get("q75")),
                    "IQR": _excel_scalar(s_row.get("iqr")),
                    "Min": _excel_scalar(s_row.get("min")),
                    "Max": _excel_scalar(s_row.get("max")),
                    "Shapiro_p": _excel_scalar(s_row.get("shapiro_p")),
                    "Is_Normal": _excel_scalar(s_row.get("is_normal")),
                    "Error_Bar_Type": err_bar_type or "SD",
                }
            )

        comparisons = sr.get("comparisons") or []
        if comparisons:
            for c_row in comparisons:
                if not isinstance(c_row, dict):
                    continue
                stat_test_rows.append(
                    {
                        "Panel": panel_label,
                        "Group_1": str(c_row.get("group1", "")),
                        "Group_2": str(c_row.get("group2", "")),
                        "Test_Method": str(c_row.get("test", "")),
                        "Statistic": _excel_scalar(c_row.get("statistic")),
                        "df": _excel_scalar(c_row.get("df")),
                        "p_raw": _excel_scalar(c_row.get("p_raw")),
                        "p_adj": _excel_scalar(c_row.get("p_adj")),
                        "p_adjust_method": padj_m,
                        "Significance": str(c_row.get("stars", "")),
                        "Significant": _excel_scalar(c_row.get("significant")),
                        "Effect_Size": _excel_scalar(c_row.get("effect_size")),
                        "Effect_Type": str(c_row.get("effect_type", "")),
                        "Omnibus_Test": str(omn_test),
                        "Omnibus_Statistic": omn_stat,
                        "Omnibus_p": omn_p,
                    }
                )
        elif omn_test and str(omn_test).lower() != "none":
            stat_test_rows.append(
                {
                    "Panel": panel_label,
                    "Group_1": "All_Groups",
                    "Group_2": "All_Groups",
                    "Test_Method": str(omn_test),
                    "Statistic": omn_stat,
                    "df": None,
                    "p_raw": omn_p,
                    "p_adj": omn_p,
                    "p_adjust_method": padj_m,
                    "Significance": "",
                    "Significant": bool(omn_p is not None and omn_p < 0.05),
                    "Effect_Size": None,
                    "Effect_Type": "",
                    "Omnibus_Test": str(omn_test),
                    "Omnibus_Statistic": omn_stat,
                    "Omnibus_p": omn_p,
                }
            )

    def _harvest_curve_fits(panel_label: str, cf_list: Any) -> None:
        if not isinstance(cf_list, list):
            return
        for cf in cf_list:
            if not isinstance(cf, dict):
                continue
            nm = str(cf.get("name", "Series"))
            mdl = str(cf.get("model", ""))
            dedup_key = (panel_label, f"{nm}::{mdl}")
            if dedup_key in seen_curve_fits:
                continue
            seen_curve_fits.add(dedup_key)
            km = cf.get("key_metrics") if isinstance(cf.get("key_metrics"), dict) else {}
            params = cf.get("params") if isinstance(cf.get("params"), dict) else {}
            pse = cf.get("param_se") if isinstance(cf.get("param_se"), dict) else {}
            param_str = "; ".join(f"{k}={float(v):.6g}" for k, v in params.items() if isinstance(v, (int, float)))
            se_str = "; ".join(f"{k}={float(v):.6g}" for k, v in pse.items() if isinstance(v, (int, float)))
            rec: Dict[str, Any] = {
                "Panel": panel_label,
                "Series": nm,
                "Model": mdl,
                "Equation": str(cf.get("equation_text") or cf.get("equation_str") or ""),
                "R2": _excel_scalar(cf.get("r2")),
                "Adj_R2": _excel_scalar(cf.get("adj_r2")),
                "RMSE": _excel_scalar(cf.get("rmse")),
                "AIC": _excel_scalar(cf.get("aic")),
                "BIC": _excel_scalar(cf.get("bic")),
            }
            for k_m, v_m in km.items():
                rec[str(k_m)] = _excel_scalar(v_m)
            for k_p, v_p in params.items():
                if str(k_p) not in rec:
                    rec[f"Param_{k_p}"] = _excel_scalar(v_p)
            rec["Parameters"] = param_str
            rec["Parameter_SE"] = se_str
            curve_fit_rows.append(rec)

    fig_err_type = str(fig_meta.get("error_bar_type", ""))
    at_risk_tables: List[Tuple[str, Dict[str, Any]]] = []
    if fig_meta.get("stat_report"):
        _harvest_stat_report("Figure", fig_meta["stat_report"], fig_err_type)
    if isinstance(fig_meta.get("statistical_tests"), list):
        for st_r in fig_meta["statistical_tests"]:
            if isinstance(st_r, dict):
                stat_test_rows.append({str(k): _excel_scalar(v) for k, v in st_r.items()})
    if fig_meta.get("curve_fits"):
        _harvest_curve_fits("Figure", fig_meta["curve_fits"])
    if isinstance(fig_meta.get("at_risk_table"), dict):
        at_risk_tables.append(("Figure", fig_meta["at_risk_table"]))

    for p_idx, panel in enumerate(panels):
        tag = str(panel.get("tag") or panel.get("panel_id") or panel.get("id") or chr(ord("a") + p_idx)).strip()
        p_name = str(panel.get("title") or panel.get("name") or spec.get("title") or f"Panel_{tag}").strip()
        panel_display = f"({tag}) {p_name}"
        p_meta = panel.get("meta") if isinstance(panel.get("meta"), dict) else {}

        if p_meta.get("stat_report"):
            # Dedup by content if figure-level already harvested identical summary/comparisons
            if not stat_summary_rows:
                _harvest_stat_report(panel_display, p_meta["stat_report"], str(p_meta.get("error_bar_type") or fig_err_type))
        if isinstance(p_meta.get("statistical_tests"), list) and not stat_test_rows:
            for st_r in p_meta["statistical_tests"]:
                if isinstance(st_r, dict):
                    stat_test_rows.append({str(k): _excel_scalar(v) for k, v in st_r.items()})
        if isinstance(p_meta.get("at_risk_table"), dict) and not at_risk_tables:
            at_risk_tables.append((panel_display, p_meta["at_risk_table"]))
        if p_meta.get("curve_fits") and not curve_fit_rows:
            _harvest_curve_fits(panel_display, p_meta["curve_fits"])

        for g in panel.get("guides") or []:
            if isinstance(g, dict):
                manifest_guide_rows.append(
                    {
                        "Panel": panel_display,
                        "Guide_Kind": str(g.get("kind", "guide")),
                        "Label": str(g.get("label", "")),
                        "X_or_X1": _excel_scalar(g.get("x", g.get("x1"))),
                        "X2": _excel_scalar(g.get("x2", g.get("x_end"))),
                        "Value_or_Y": _excel_scalar(g.get("value", g.get("y", g.get("y_bar")))),
                    }
                )

        axes_meta = _extract_panel_axes_meta(panel)
        x_ax_dict = panel.get("x_axis") if isinstance(panel.get("x_axis"), dict) else {}
        panel_cats = panel.get("categories") or p_meta.get("categories") or x_ax_dict.get("categories")
        raw_layers = panel.get("layers")
        layers = [ly for ly in raw_layers if isinstance(ly, dict)] if isinstance(raw_layers, list) and raw_layers else [panel]

        raw_sheet_name = "Raw_Data" if p_idx == 0 else _unique_sheet_title(wb, f"Raw_Data_{tag}")
        ws_raw = wb.create_sheet(title=_unique_sheet_title(wb, raw_sheet_name))

        # Specialized structured Raw_Data layouts for replicate distributions, volcano plots, and forest plots
        replicate_groups: List[Tuple[str, List[Any]]] = []
        volcano_rows: List[List[Any]] = []
        forest_items = p_meta.get("forest_items") if isinstance(p_meta.get("forest_items"), list) else None
        rds_items = p_meta.get("rds_summary") if isinstance(p_meta.get("rds_summary"), list) else None

        for ly in layers:
            for s in ly.get("series") or []:
                if not isinstance(s, dict):
                    continue
                sm = s.get("meta") if isinstance(s.get("meta"), dict) else {}
                if isinstance(sm.get("raw_points"), list) and sm["raw_points"]:
                    replicate_groups.append((str(s.get("name", "Group")), list(sm["raw_points"])))
                elif isinstance(sm.get("point_labels"), list) and s.get("x") and s.get("y"):
                    reg = str(sm.get("regulation") or s.get("name") or "")
                    for lbl_v, xv, yv in zip(sm["point_labels"], s["x"], s["y"]):
                        volcano_rows.append([str(lbl_v), reg, _excel_scalar(xv), _excel_scalar(yv)])

        if replicate_groups:
            y_unit = axes_meta["y1"]["unit"]
            max_n = max(len(vals) for _, vals in replicate_groups)
            headers = ["Replicate_Index"] + [_format_col_header(gn, y_unit) for gn, _ in replicate_groups]
            ws_raw.append(headers)
            for r_i in range(max_n):
                row_r: List[Any] = [r_i + 1]
                for _, vals in replicate_groups:
                    row_r.append(_excel_scalar(vals[r_i]) if r_i < len(vals) else None)
                ws_raw.append(row_r)
            _style_worksheet(ws_raw)
        elif volcano_rows:
            x_hdr = _format_col_header(axes_meta["x"]["label"] or "log2_Fold_Change", axes_meta["x"]["unit"])
            y_hdr = _format_col_header(axes_meta["y1"]["label"] or "neg_log10_p", axes_meta["y1"]["unit"])
            ws_raw.append(["Feature_ID", "Regulation", x_hdr, y_hdr])
            for vr in volcano_rows:
                ws_raw.append(vr)
            _style_worksheet(ws_raw)
            v_sum = p_meta.get("volcano_summary")
            if isinstance(v_sum, dict):
                for bk in ("Up", "Down", "NS"):
                    if f"n_{bk.lower()}" in v_sum or bk in v_sum:
                        fallback_summary_rows.append(
                            {
                                "Panel": panel_display,
                                "Category": bk,
                                "Count": _excel_scalar(v_sum.get(f"n_{bk.lower()}", v_sum.get(bk))),
                                "FC_Cutoff": _excel_scalar(v_sum.get("fc_cutoff")),
                                "p_Cutoff": _excel_scalar(v_sum.get("p_cutoff")),
                            }
                        )
        elif forest_items:
            x_hdr = _format_col_header(axes_meta["x"]["label"] or "Estimate", axes_meta["x"]["unit"])
            ws_raw.append(["Item", x_hdr, "CI95_Low", "CI95_High", "Formatted_95CI", "p_value"])
            for fi in forest_items:
                if isinstance(fi, dict):
                    ws_raw.append(
                        [
                            str(fi.get("name", "")),
                            _excel_scalar(fi.get("estimate")),
                            _excel_scalar(fi.get("ci_low")),
                            _excel_scalar(fi.get("ci_high")),
                            str(fi.get("formatted_ci", "")),
                            _excel_scalar(fi.get("p_value")),
                        ]
                    )
                    fallback_summary_rows.append(
                        {
                            "Panel": panel_display,
                            "Item": str(fi.get("name", "")),
                            "Estimate": _excel_scalar(fi.get("estimate")),
                            "CI95_Low": _excel_scalar(fi.get("ci_low")),
                            "CI95_High": _excel_scalar(fi.get("ci_high")),
                            "Formatted_95CI": str(fi.get("formatted_ci", "")),
                        }
                    )
            _style_worksheet(ws_raw)
        else:
            all_1d_entries: List[Dict[str, Any]] = []
            matrix_layers: List[Dict[str, Any]] = []
            for ly in layers:
                has_mat = any(ly.get(mk) is not None for mk in ("matrix_z", "z_matrix")) or (
                    ly.get("values") is not None and np.asarray(ly.get("values")).ndim == 2
                )
                if has_mat:
                    matrix_layers.append(ly)
                all_1d_entries.extend(_extract_layer_series_entries(ly, default_axis="y1", panel_categories=panel_cats))

            used_axes = {e["axis"] for e in all_1d_entries}
            has_dual_y = ("y1" in used_axes and "y2" in used_axes) or bool(axes_meta["y2"]["label"] and "y2" in used_axes)
            if all_1d_entries:
                _write_1d_series_to_sheet(
                    ws_raw,
                    all_1d_entries,
                    axes_meta=axes_meta,
                    has_dual_y=has_dual_y,
                    panel_categories=panel_cats,
                )
                if matrix_layers:
                    ws_mat_bg = wb.create_sheet(title=_unique_sheet_title(wb, f"{raw_sheet_name}_Matrix"))
                    _write_2d_matrix_to_sheet(ws_mat_bg, matrix_layers[0], axes_meta=axes_meta)
                for ent in all_1d_entries:
                    arr = np.asarray(ent["y"], dtype=float)
                    arr = arr[np.isfinite(arr)]
                    if arr.size > 0:
                        ent_meta = ent.get("metrics") if isinstance(ent.get("metrics"), dict) else {}
                        sum_rec: Dict[str, Any] = {
                            "Panel": panel_display,
                            "Series": str(ent["name"]),
                            "n_points": int(arr.size),
                            "Mean": _excel_scalar(np.mean(arr)),
                            "SD": _excel_scalar(np.std(arr, ddof=1) if arr.size > 1 else 0.0),
                            "Min": _excel_scalar(np.min(arr)),
                            "Max": _excel_scalar(np.max(arr)),
                        }
                        if ent_meta.get("median_survival") is not None or ent_meta.get("n_events") is not None:
                            sum_rec["Median_Survival"] = _excel_scalar(ent_meta.get("median_survival"))
                            sum_rec["Events"] = _excel_scalar(ent_meta.get("n_events"))
                            sum_rec["Censored"] = _excel_scalar(ent_meta.get("n_censored"))
                        if ent_meta.get("auroc") is not None:
                            sum_rec["AUROC"] = _excel_scalar(ent_meta.get("auroc"))
                            sum_rec["CI95_Low"] = _excel_scalar(ent_meta.get("ci_low"))
                            sum_rec["CI95_High"] = _excel_scalar(ent_meta.get("ci_high"))
                        fallback_summary_rows.append(sum_rec)
            elif matrix_layers:
                _write_2d_matrix_to_sheet(ws_raw, matrix_layers[0], axes_meta=axes_meta)
            else:
                ws_raw.append(["Panel", "Note"])
                ws_raw.append([panel_display, "No raw data attached"])
                _style_worksheet(ws_raw)

        if rds_items:
            for rds in rds_items:
                if isinstance(rds, dict):
                    fallback_summary_rows.append(
                        {
                            "Panel": panel_display,
                            "Pathway": str(rds.get("pathway", "")),
                            "RDS_Step_From": str(rds.get("step_from", "")),
                            "RDS_Step_To": str(rds.get("step_to", "")),
                            "G_From_eV": _excel_scalar(rds.get("g_from")),
                            "G_To_eV": _excel_scalar(rds.get("g_to")),
                            "Delta_G_RDS_eV": _excel_scalar(rds.get("delta_g_max")),
                        }
                    )

    # 2. Summary_Statistics
    ws_sum = wb.create_sheet(title=_unique_sheet_title(wb, "Summary_Statistics"))
    rows_for_sum = stat_summary_rows if stat_summary_rows else fallback_summary_rows
    if rows_for_sum:
        sum_headers: List[str] = []
        for r in rows_for_sum:
            for k in r.keys():
                if k not in sum_headers:
                    sum_headers.append(k)
        ws_sum.append(sum_headers)
        for r in rows_for_sum:
            ws_sum.append([r.get(k) for k in sum_headers])
    else:
        ws_sum.append(["Title", "Mode", "Note"])
        ws_sum.append([str(spec.get("title", "")), str(spec.get("mode", "")), "Summary statistics not applicable"])
    _style_worksheet(ws_sum)

    # 3. Statistical_Tests (emitted whenever stat_report / test rows exist)
    if stat_test_rows:
        ws_tests = wb.create_sheet(title=_unique_sheet_title(wb, "Statistical_Tests"))
        test_headers: List[str] = []
        for tr in stat_test_rows:
            for k in tr.keys():
                if k not in test_headers:
                    test_headers.append(k)
        ws_tests.append(test_headers)
        for tr in stat_test_rows:
            ws_tests.append([tr.get(k) for k in test_headers])
        _style_worksheet(ws_tests)

    # 3b. At_Risk_Table (for Kaplan-Meier survival cohorts)
    for _ar_lbl, ar_tbl in at_risk_tables:
        ar_times = ar_tbl.get("times")
        ar_rows = ar_tbl.get("rows")
        if isinstance(ar_times, list) and isinstance(ar_rows, list) and ar_times and ar_rows:
            ws_ar = wb.create_sheet(title=_unique_sheet_title(wb, "At_Risk_Table"))
            ws_ar.append(["Arm"] + [f"t={_excel_scalar(tv)}" for tv in ar_times])
            for ar_r in ar_rows:
                if isinstance(ar_r, dict):
                    ws_ar.append([str(ar_r.get("name", "Arm"))] + [_excel_scalar(c) for c in (ar_r.get("counts") or [])])
            _style_worksheet(ws_ar)

    # 4. Curve_Fit_Summary (emitted whenever curve_fits records exist)
    if curve_fit_rows:
        ws_cf = wb.create_sheet(title=_unique_sheet_title(wb, "Curve_Fit_Summary"))
        cf_headers: List[str] = []
        for cr in curve_fit_rows:
            for k in cr.keys():
                if k not in cf_headers:
                    cf_headers.append(k)
        ws_cf.append(cf_headers)
        for cr in curve_fit_rows:
            ws_cf.append([cr.get(k) for k in cf_headers])
        _style_worksheet(ws_cf)

    # 5. Optional caller-provided summary DataFrames
    if summary_tables:
        for tbl_name, df_tbl in summary_tables.items():
            if isinstance(df_tbl, pd.DataFrame) and not df_tbl.empty:
                ws_t = wb.create_sheet(title=_unique_sheet_title(wb, tbl_name))
                _write_dataframe_sheet(ws_t, df_tbl)

    # 6. Figure_Manifest
    ws_man = wb.create_sheet(title=_unique_sheet_title(wb, "Figure_Manifest"))
    ws_man.append(["Field", "Value", "Extra_1", "Extra_2", "Extra_3"])
    ws_man.append(["Figure_Title", str(spec.get("title", "")), None, None, None])
    ws_man.append(["Chart_Mode", str(spec.get("mode", "")), str(spec.get("subtype") or ""), None, None])
    ws_man.append(["Style_Preset", str(spec.get("style_preset", "")), None, None, None])
    ws_man.append(["Locale", "en", f"Panels={len(panels)}", fig_err_type or None, None])
    for gr in manifest_guide_rows:
        ws_man.append(
            [
                f"Guide ({gr['Panel']})",
                gr["Guide_Kind"],
                gr["Label"],
                gr["X_or_X1"],
                gr["Value_or_Y"],
            ]
        )
    if audit_notes:
        for n_i, note in enumerate(audit_notes, start=1):
            note_txt = note.get("note", str(note)) if isinstance(note, dict) else str(note)
            ws_man.append([f"Audit_Note_{n_i}", note_txt, None, None, None])
    _style_worksheet(ws_man)

    return _safe_save_wb(wb, out_p)


def export_multi_chart_workbook(
    figure_spec_dict: Dict[str, Any],
    out_xlsx: str | Path,
    summary_tables: Optional[Dict[str, pd.DataFrame]] = None,
    audit_notes: Optional[List[str]] = None,
    locale: Optional[str] = None,
) -> str:
    """
    Export a publication-ready multi-sheet Source Data `.xlsx` workbook from a Chart Grammar `FigureSpec`
    (dict or Dataclass):
    - When `locale='en'` (or `fig_spec.meta.get('locale') == 'en'`), outputs Nature/Science/Cell-compliant
      English tabs (`Raw_Data`, `Summary_Statistics`, `Statistical_Tests`, `Curve_Fit_Summary`, `Figure_Manifest`).
    - When `locale='zh'` (default for legacy material sheets), preserves 100% backward-compatible Chinese
      panel/kinetics/guide/audit sheets.
    """
    spec = _to_plain_dict(figure_spec_dict)
    if not isinstance(spec, dict):
        raise TypeError(f"figure_spec_dict must be a dict or FigureSpec dataclass, got {type(figure_spec_dict)}")

    out_p = Path(out_xlsx)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    raw_panels = spec.get("panels")
    if isinstance(raw_panels, list) and len(raw_panels) > 0:
        panels = [p for p in raw_panels if isinstance(p, dict)]
    else:
        panels = [spec]

    resolved_locale = str(locale or "").strip().lower()
    if not resolved_locale:
        spec_meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
        cand_loc = spec_meta.get("locale") or spec.get("locale")
        if not cand_loc:
            for p_chk in panels:
                pm_chk = p_chk.get("meta") if isinstance(p_chk.get("meta"), dict) else {}
                if pm_chk.get("locale"):
                    cand_loc = pm_chk.get("locale")
                    break
        resolved_locale = str(cand_loc or "zh").strip().lower()

    if resolved_locale.startswith("en"):
        return _export_english_source_data_workbook(wb, spec, panels, summary_tables, audit_notes, out_p)

    kinetics_rows: List[Dict[str, Any]] = []
    guide_rows: List[Dict[str, Any]] = []
    _collect_feature_and_guide_rows("Figure", spec, kinetics_rows, guide_rows)

    for p_idx, panel in enumerate(panels):
        tag = str(panel.get("tag") or panel.get("panel_id") or panel.get("id") or chr(ord("a") + p_idx)).strip()
        p_name = str(panel.get("title") or panel.get("name") or panel.get("mode") or f"Panel_{tag}").strip()
        base_sheet_prefix = f"Panel_{tag}_{p_name}" if not p_name.lower().startswith("panel_") else p_name
        panel_display = f"({tag}) {p_name}"

        axes_meta = _extract_panel_axes_meta(panel)
        p_meta_zh = panel.get("meta") if isinstance(panel.get("meta"), dict) else {}
        x_ax_dict = panel.get("x_axis") if isinstance(panel.get("x_axis"), dict) else {}
        panel_cats = panel.get("categories") or p_meta_zh.get("categories") or x_ax_dict.get("categories")
        _collect_feature_and_guide_rows(panel_display, panel, kinetics_rows, guide_rows)

        # Gather layers (supporting explicit `layers`, legacy `left_y`/`right_y`, or direct panel fields)
        raw_layers = panel.get("layers")
        layers: List[Dict[str, Any]] = []
        if isinstance(raw_layers, list) and raw_layers:
            layers.extend([ly for ly in raw_layers if isinstance(ly, dict)])
        else:
            if isinstance(panel.get("left_y"), dict) and (panel["left_y"].get("series") or panel["left_y"].get("stacks")):
                ly_l = dict(panel["left_y"])
                ly_l.setdefault("axis", "y1")
                layers.append(ly_l)
            if isinstance(panel.get("right_y"), dict) and (panel["right_y"].get("series") or panel["right_y"].get("stacks")):
                ly_r = dict(panel["right_y"])
                ly_r.setdefault("axis", "y2")
                layers.append(ly_r)
            if not layers:
                layers.append(panel)

        all_1d_entries: List[Dict[str, Any]] = []
        matrix_layers: List[Dict[str, Any]] = []

        for ly in layers:
            _collect_feature_and_guide_rows(panel_display, ly, kinetics_rows, guide_rows)
            has_mat = any(ly.get(mk) is not None for mk in ("matrix_z", "z_matrix")) or (
                ly.get("values") is not None and np.asarray(ly.get("values")).ndim == 2
            )
            if has_mat:
                matrix_layers.append(ly)
            entries_1d = _extract_layer_series_entries(ly, default_axis="y1", panel_categories=panel_cats)
            for ent in entries_1d:
                if isinstance(ent.get("metrics"), dict):
                    _extract_metric_fields(f"{panel_display}:{ent['name']}", ent["metrics"], kinetics_rows)
            all_1d_entries.extend(entries_1d)

        used_axes = {e["axis"] for e in all_1d_entries}
        has_dual_y = ("y1" in used_axes and "y2" in used_axes) or bool(axes_meta["y2"]["label"] and "y2" in used_axes)

        # 1. Write 1D series sheet for this panel if any 1D series exist
        if all_1d_entries:
            ws_1d = wb.create_sheet(title=_unique_sheet_title(wb, base_sheet_prefix))
            _write_1d_series_to_sheet(
                ws_1d,
                all_1d_entries,
                axes_meta=axes_meta,
                has_dual_y=has_dual_y,
                panel_categories=panel_cats,
            )

        # 2. Write 2D matrix sheet(s) for this panel if any 2D field/heatmap layers exist
        for m_i, m_ly in enumerate(matrix_layers):
            m_suffix = "" if (not all_1d_entries and len(matrix_layers) == 1) else (f"_Mat{m_i + 1}" if len(matrix_layers) > 1 else "_Matrix")
            ws_m = wb.create_sheet(title=_unique_sheet_title(wb, f"{base_sheet_prefix}{m_suffix}"))
            _write_2d_matrix_to_sheet(ws_m, m_ly, axes_meta=axes_meta)

        # Fallback empty placeholder if neither 1D nor 2D data was populated on the panel
        if not all_1d_entries and not matrix_layers:
            ws_empty = wb.create_sheet(title=_unique_sheet_title(wb, base_sheet_prefix))
            ws_empty.append(["Panel", "Note"])
            ws_empty.append([panel_display, "No series or matrix data attached"])
            _style_worksheet(ws_empty)

        # 3. Export linked 1D side_panel (e.g., voltage profile beside in-situ 2D contour)
        side_p = panel.get("side_panel")
        if isinstance(side_p, dict):
            side_axes = _extract_panel_axes_meta(side_p)
            side_entries: List[Dict[str, Any]] = []
            if isinstance(side_p.get("layers"), list):
                for sly in side_p["layers"]:
                    if isinstance(sly, dict):
                        side_entries.extend(_extract_layer_series_entries(sly, default_axis="y1"))
            else:
                side_entries.extend(_extract_layer_series_entries(side_p, default_axis="y1"))
            if side_entries:
                ws_side = wb.create_sheet(title=_unique_sheet_title(wb, f"Panel_{tag}_Side1D"))
                _write_1d_series_to_sheet(ws_side, side_entries, axes_meta=side_axes, has_dual_y=False)

        # 4. Export insets (subchart series sheets + zoom-box guide records)
        insets = panel.get("insets")
        if isinstance(insets, list):
            for in_idx, ins in enumerate(insets):
                if not isinstance(ins, dict):
                    continue
                xlim = ins.get("xlim") or ins.get("x_limits")
                ylim = ins.get("ylim") or ins.get("y_limits")
                if xlim is not None or ylim is not None:
                    guide_rows.append(
                        {
                            "面板 (Panel)": panel_display,
                            "标注类型 (Guide Type)": f"inset_{ins.get('mode', 'zoom')}",
                            "名称/标签 (Label)": str(ins.get("title") or f"Inset_{in_idx + 1}"),
                            "X 位置 (X)": str(xlim) if xlim is not None else None,
                            "起点/位置 Y0": _excel_scalar(ylim[0]) if isinstance(ylim, (list, tuple)) and len(ylim) >= 2 else None,
                            "终点 Y1": _excel_scalar(ylim[1]) if isinstance(ylim, (list, tuple)) and len(ylim) >= 2 else None,
                            "跨度/数值 (Span / Value)": str(ylim) if ylim is not None else None,
                        }
                    )
                sub_target = ins.get("sub_spec") if isinstance(ins.get("sub_spec"), dict) else ins
                ins_axes = _extract_panel_axes_meta(sub_target)
                ins_entries: List[Dict[str, Any]] = []
                if isinstance(sub_target.get("layers"), list):
                    for ily in sub_target["layers"]:
                        if isinstance(ily, dict):
                            ins_entries.extend(_extract_layer_series_entries(ily, default_axis="y1"))
                else:
                    ins_entries.extend(_extract_layer_series_entries(sub_target, default_axis="y1"))
                if ins_entries:
                    ws_ins = wb.create_sheet(title=_unique_sheet_title(wb, f"Panel_{tag}_Inset{in_idx + 1}"))
                    _write_1d_series_to_sheet(ws_ins, ins_entries, axes_meta=ins_axes, has_dual_y=False)

    # 5. Export harvested Pulse / dQ-dV kinetics feature metrics
    if kinetics_rows:
        ws_kin = wb.create_sheet(title=_unique_sheet_title(wb, "脉冲与微分容量特征指标"))
        kin_headers = list(kinetics_rows[0].keys())
        ws_kin.append(kin_headers)
        for kr in kinetics_rows:
            ws_kin.append([kr.get(k) for k in kin_headers])
        _style_worksheet(ws_kin)

    # 6. Export reference guides & span annotations
    if guide_rows:
        ws_g = wb.create_sheet(title=_unique_sheet_title(wb, "参考线与跨度标注汇总"))
        g_headers = list(guide_rows[0].keys())
        ws_g.append(g_headers)
        for gr in guide_rows:
            ws_g.append([gr.get(k) for k in g_headers])
        _style_worksheet(ws_g)

    # 6b. Export survival At-Risk table & statistical tests in Chinese workbook when present
    spec_meta_zh = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    ar_zh = spec_meta_zh.get("at_risk_table")
    if isinstance(ar_zh, dict) and isinstance(ar_zh.get("times"), list) and isinstance(ar_zh.get("rows"), list):
        ws_ar_zh = wb.create_sheet(title=_unique_sheet_title(wb, "风险集人数表_AtRisk"))
        ws_ar_zh.append(["组别 (Arm)"] + [f"t={_excel_scalar(tv)}" for tv in ar_zh["times"]])
        for ar_r in ar_zh["rows"]:
            if isinstance(ar_r, dict):
                ws_ar_zh.append([str(ar_r.get("name", "Arm"))] + [_excel_scalar(c) for c in (ar_r.get("counts") or [])])
        _style_worksheet(ws_ar_zh)

    st_zh = spec_meta_zh.get("statistical_tests")
    if isinstance(st_zh, list) and st_zh:
        ws_st_zh = wb.create_sheet(title=_unique_sheet_title(wb, "统计检验与ROC生存汇总"))
        st_hdrs: List[str] = []
        for sr_i in st_zh:
            if isinstance(sr_i, dict):
                for k in sr_i.keys():
                    if k not in st_hdrs:
                        st_hdrs.append(k)
        if st_hdrs:
            ws_st_zh.append(st_hdrs)
            for sr_i in st_zh:
                if isinstance(sr_i, dict):
                    ws_st_zh.append([_excel_scalar(sr_i.get(k)) for k in st_hdrs])
            _style_worksheet(ws_st_zh)

    # 7. Export caller-provided summary DataFrames
    if summary_tables:
        for tbl_name, df_tbl in summary_tables.items():
            if isinstance(df_tbl, pd.DataFrame) and not df_tbl.empty:
                ws_t = wb.create_sheet(title=_unique_sheet_title(wb, tbl_name))
                _write_dataframe_sheet(ws_t, df_tbl)

    # 8. Export caller-provided audit notes
    if audit_notes:
        ws_aud = wb.create_sheet(title=_unique_sheet_title(wb, "数据审计与处理说明"))
        ws_aud.append(["序号 (No.)", "审计与处理说明 (Audit Note)"])
        for n_i, note in enumerate(audit_notes, start=1):
            ws_aud.append([n_i, str(note)])
        _style_worksheet(ws_aud)

    return _safe_save_wb(wb, out_p)
