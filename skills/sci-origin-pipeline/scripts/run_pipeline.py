from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PRESET_DIR = SCRIPT_DIR.parent / "presets"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import chart_grammar
import electrochem_transforms
import excel_exporter
import fitting
import origin_builder
import origin_renderer
import origin_theme
import parsers
import validator


def _get_plotter() -> Any:
    """Lazy-import `plotter` ONLY when `--skip-origin` offline fallback is explicitly requested."""
    import plotter

    return plotter


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "raw_preview": {
        "mode": "raw_preview",
        "style_preset": "style_publication_minimal",
        "modality": "XPS",
        "sample_name": "Sample_A",
        "input_file": "path/to/Spectrum.xls",
        "output_dir": "path/to/new_output_folder",
        "regions": ["O1s"],
        "auto_charge_ref": False,
        "build_opju": True,
    },
    "deconvolve": {
        "mode": "deconvolve",
        "style_preset": "style_publication_minimal",
        "modality": "XPS",
        "sample_name": "Sample_A",
        "method_rationale": "State why this preset or inline regions_config matches the sample system and research question.",
        "input_file": "path/to/Avantage_Export.xls",
        "output_dir": "path/to/new_output_folder",
        "preset_file": "<REQUIRED: choose matching preset (e.g. xps_cfx_battery_presets.json ONLY for Li/CFx) or omit and provide inline regions_config>",
        "regions": ["C1s"],
        "auto_charge_ref": True,
    },
    "model_sensitivity": {
        "mode": "model_sensitivity",
        "style_preset": "style_publication_minimal",
        "modality": "XPS",
        "sample_name": "Sample_1",
        "method_rationale": "Compare multiple candidate models on an overlapped region before batch execution.",
        "input_file": "path/to/Avantage_Export.xls",
        "output_dir": "path/to/new_output_folder",
        "preset_file": "xps_cfx_battery_presets.json",
        "region": "F1s",
        "auto_charge_ref": True,
        "build_opju": True,
    },
    "replot_deconv": {
        "mode": "replot_deconv",
        "style_preset": "style_publication_minimal",
        "sample_name": "Sample_1",
        "input_file": "path/to/Existing_Fitted_Workbook.xlsx",
        "output_dir": "path/to/new_output_folder",
        "sheets": ["C1s", "F1s"],
        "invert_x": True,
        "build_opju": True,
    },
    "batch_deconvolve": {
        "mode": "batch_deconvolve",
        "style_preset": "style_publication_minimal",
        "modality": "Raman",
        "title": "Batch1_Raman_Cohort",
        "method_rationale": "State why the chosen preset matches all samples in this cohort.",
        "output_dir": "path/to/new_output_folder",
        "preset_file": "<REQUIRED: choose matching preset or provide inline region_config>",
        "region": "FirstOrder",
        "grid_ncols": 3,
        "samples": [
            {"id": "S1", "name": "Sample 1", "replicates": ["S1_spot1.txt", "S1_spot2.txt", "S1_spot3.txt"]},
            {"id": "S2", "name": "Sample 2", "replicates": ["S2_spot1.txt", "S2_spot2.txt", "S2_spot3.txt"]},
        ],
        "comparisons": [{"label": "S2 - S1", "from": "S1", "to": "S2"}],
    },
    "waterfall": {
        "mode": "waterfall",
        "style_preset": "style_publication_minimal",
        "modality": "XRD",
        "title": "XRD_Waterfall_Comparison",
        "output_dir": "path/to/new_output_folder",
        "x_label": "$2\\theta$ (deg.)",
        "y_label": "Intensity (a.u.)",
        "x_window": [8.0, 72.0],
        "invert_x": False,
        "markers": [{"pos": 13.4, "label": "CF$_x$ (001)"}],
        "series": [{"name": "Sample A", "file": "A.rasx"}],
    },
    "nyquist": {
        "mode": "nyquist",
        "style_preset": "style_publication_minimal",
        "modality": "EIS",
        "title": "EIS_Nyquist",
        "output_dir": "path/to/new_output_folder",
        "add_hf_inset": True,
        "series": [{"name": "Cell 1", "file": "eis_1.txt"}],
    },
    "bet_porosity": {
        "mode": "bet_porosity",
        "style_preset": "style_publication_minimal",
        "title": "BET_and_BJH",
        "output_dir": "path/to/new_output_folder",
        "isotherm_file": "Isotherm.csv",
        "psd_file": "BJH_Adsorption.csv",
        "bet_surface_area_m2_g": 150.0,
    },
    "particle_size": {
        "mode": "particle_size",
        "style_preset": "style_publication_minimal",
        "title": "Mastersizer_PSD",
        "sample_name": "Sample",
        "input_file": "Mastersizer.xls",
        "output_dir": "path/to/new_output_folder",
        "x_limits": [0.5, 200.0],
    },
    "epr_spectrum": {
        "mode": "epr_spectrum",
        "style_preset": "style_publication_minimal",
        "title": "EPR_Derivative",
        "sample_name": "Sample",
        "input_file": "sample_epr.asc",
        "output_dir": "path/to/new_output_folder",
    },
    "conductivity": {
        "mode": "conductivity",
        "style_preset": "style_publication_minimal",
        "title": "Conductivity_vs_Pressure",
        "sample_name": "Sample",
        "input_file": "powder_conductivity.xlsx",
        "output_dir": "path/to/new_output_folder",
        "log_conductivity": True,
    },
    "xy_trend": {
        "mode": "xy_trend",
        "style_preset": "style_publication_minimal",
        "title": "XY_Trend_Comparison",
        "output_dir": "path/to/new_output_folder",
        "x_label": "X",
        "y_label": "Y",
        "log_x": False,
        "log_y": False,
        "invert_x": False,
        "series": [{"name": "Series 1", "file": "data.xlsx", "sheet": 0, "x_col": 0, "y_col": 1}],
    },
    "neware_galvanostatic": {
        "mode": "neware_galvanostatic",
        "style_preset": "style_publication_minimal",
        "title": "Neware_Rate_Discharge",
        "output_dir": "path/to/new_output_folder",
        "capacity_basis": "auto",
        "voltage_cutoff": 1.5,
        "series": [
            {"name": "0.1 C", "file": "cell_0.1C.ndax"},
            {"name": "0.5 C", "file": "cell_0.5C.ndax"},
        ],
    },
    "composite_figure": {
        "mode": "composite_figure",
        "style_preset": "style_publication_minimal",
        "title": "Fig_MultiModal_Characterization",
        "output_dir": "path/to/new_output_folder",
        "ncols": 2,
        "panels": [
            {
                "panel_id": "Panel_a",
                "panel_title": "Panel A",
                "type": "waterfall",
                "modality": "XRD",
                "x_label": "$2\\theta$ (deg.)",
                "x_window": [8, 72],
                "series": [{"name": "Sample A", "file": "A.rasx"}],
            },
            {
                "panel_id": "Panel_b",
                "panel_title": "EIS Nyquist",
                "type": "nyquist",
                "series": [{"name": "Cell #1", "file": "eis.txt"}],
            },
        ],
    },
    "xy_fit_and_band": {
        "mode": "xy_fit_and_band",
        "style_preset": "style_publication_minimal",
        "title": "XY_Fit_With_CI_Band",
        "output_dir": "path/to/new_output_folder",
        "x_label": "X",
        "y_label": "Y",
        "fit_model": "linear",
        "ci_level": 0.95,
        "series": [{"name": "Series 1", "file": "data.xlsx", "x_col": 0, "y_col": 1}],
    },
    "bode_dual_panel": {
        "mode": "bode_dual_panel",
        "style_preset": "style_publication_minimal",
        "title": "EIS_Bode_Plot",
        "output_dir": "path/to/new_output_folder",
        "series": [{"name": "Cell 1", "file": "eis_1.bin"}],
    },
    "stat_distribution": {
        "mode": "stat_distribution",
        "style_preset": "style_publication_minimal",
        "title": "Statistical_Distribution",
        "output_dir": "path/to/new_output_folder",
        "input_file": "summary.xlsx",
        "group_col": "Sample",
        "value_col": "Value",
    },
    "matrix_heatmap": {
        "mode": "matrix_heatmap",
        "style_preset": "style_publication_minimal",
        "title": "Matrix_Heatmap",
        "output_dir": "path/to/new_output_folder",
        "input_file": "matrix_data.xlsx",
    },
}

GRAMMAR_SUBTYPE_ALIASES = (
    "pulse_align",
    "galvanostatic_dqdv",
    "ragone",
    "electrochem_kinetics:pulse_align",
    "electrochem_kinetics:galvanostatic_dqdv",
    "electrochem_kinetics:ragone",
)

ALL_INIT_TEMPLATE_MODES = sorted(
    set(TEMPLATES.keys()) | set(chart_grammar.SUPPORTED_GRAMMAR_MODES) | set(GRAMMAR_SUBTYPE_ALIASES)
)


def cmd_scan(args: argparse.Namespace) -> Dict[str, Any]:
    return parsers.scan_directory(args.target)


def cmd_inspect(args: argparse.Namespace) -> Dict[str, Any]:
    return parsers.inspect_data_file(args.target)


def _normalize_with_exclusions(
    x: np.ndarray,
    y: np.ndarray,
    normalize_each: bool,
    norm_exclude_windows: Optional[List[List[float]]] = None,
    clip_top_factor: Optional[float] = None,
) -> np.ndarray:
    """Pure-NumPy waterfall curve normalization (zero matplotlib dependency)."""
    if not normalize_each:
        return y.copy()
    ref_mask = np.ones(len(x), dtype=bool)
    if norm_exclude_windows:
        for w in norm_exclude_windows:
            lo, hi = min(w[0], w[1]), max(w[0], w[1])
            ref_mask &= ~((x >= lo) & (x <= hi))
    y_ref = y[ref_mask] if np.sum(ref_mask) >= 5 else y
    ymin_i = float(np.percentile(y_ref, 2.0))
    ymax_i = float(np.max(y_ref))
    span_i = max(ymax_i - ymin_i, 1e-9)
    y_norm = (y - ymin_i) / span_i
    if clip_top_factor is not None and clip_top_factor > 0:
        y_norm = np.minimum(y_norm, float(clip_top_factor))
    return y_norm


def _prepare_waterfall_curves(
    series_list: List[Dict[str, Any]],
    style: Dict[str, Any],
    *,
    x_window: Optional[Tuple[float, float]] = None,
    normalize_each: bool = True,
    offset_step: float = 1.18,
    norm_exclude_windows: Optional[List[List[float]]] = None,
    clip_top_factor: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Compute normalized & vertically stacked waterfall curves without touching matplotlib."""
    processed: List[Dict[str, Any]] = []
    for idx, item in enumerate(series_list):
        x = np.asarray(item["x"], dtype=float)
        y = np.asarray(item["y"], dtype=float)
        if x_window is not None:
            lo, hi = min(x_window), max(x_window)
            mask = (x >= lo) & (x <= hi)
            x, y = x[mask], y[mask]
        span_raw = max(float(np.max(y) - np.min(y)), 1e-9)
        y_norm = _normalize_with_exclusions(x, y, normalize_each, norm_exclude_windows, clip_top_factor)
        step_val = offset_step if normalize_each else offset_step * span_raw
        y_off = y_norm + idx * step_val
        processed.append(
            {
                "name": item["name"],
                # Preserve user-explicit colors; None lets build_waterfall_opju assign from its palette
                "color": item.get("color") or None,
                "x": x,
                "y_raw": y,
                "y_offset": y_off,
            }
        )
    return processed


def _load_explicit_preset_and_regions(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Require an explicit preset_file or inline regions_config/region_config.
    Never falls back silently to material-specific presets when no method/scheme is selected.
    """
    preset_spec = cfg.get("preset_file")
    inline_regions = cfg.get("regions_config")
    if inline_regions is None and "region_config" in cfg and "region" in cfg:
        inline_regions = {cfg["region"]: cfg["region_config"]}

    preset_data: Dict[str, Any] = {}
    if preset_spec and not str(preset_spec).startswith("<REQUIRED"):
        pf = Path(preset_spec)
        if not pf.is_absolute():
            pf = PRESET_DIR / pf
        if not pf.exists():
            raise FileNotFoundError(f"Configured preset_file not found: {pf}")
        preset_data = json.loads(pf.read_text(encoding="utf-8"))

    merged_regions = dict(preset_data.get("regions", {}))
    if isinstance(inline_regions, dict):
        merged_regions.update(inline_regions)

    if not merged_regions:
        raise ValueError(
            "No deconvolution preset or inline region_config selected. "
            "Follow Work Card 1 & 2: inspect your file (`inspect`) or run `raw_preview` first, "
            "then explicitly specify a matching `preset_file` or custom `regions_config`."
        )
    return preset_data, merged_regions


def _resolve_xps_charge_referencing(
    input_path: Path,
    cfg: Dict[str, Any],
    preset_data: Dict[str, Any],
    findings: List[Dict[str, str]],
    finding_region: str = "C1s",
    override_manual_shift: Optional[float] = None,
    default_auto: bool = True,
) -> Tuple[float, str, Optional[Dict[str, Any]]]:
    anchor_cfg = cfg.get("charge_anchor") or preset_data.get("charge_referencing", {}).get("primary_anchor")
    manual_raw = override_manual_shift if override_manual_shift is not None else cfg.get("charge_shift_eV")
    has_manual = manual_raw is not None
    manual_val = float(manual_raw) if has_manual else 0.0

    auto_setting = cfg.get("auto_charge_ref")
    use_auto = default_auto if auto_setting is None else bool(auto_setting)
    if override_manual_shift is not None or (auto_setting is False) or (has_manual and auto_setting is None):
        note = f"ManualShift({manual_val:+.2f}eV)" if has_manual else "ManualShift(+0.00eV, zero)"
        return manual_val, note, anchor_cfg

    if not use_auto:
        return manual_val, (f"ManualShift({manual_val:+.2f}eV)" if has_manual else "manual_or_zero"), anchor_cfg

    if not anchor_cfg:
        note = f"校正未确认(无锚点配置; 保留手动校正 {manual_val:+.2f}eV)" if has_manual else "校正未确认(无锚点配置; 保持 0.00eV)"
        findings.append({"level": "WARN_CHARGE_REF_UNCONFIRMED", "region": finding_region, "detail": note})
        return manual_val, note, None

    anc_raw = parsers.parse_xps_avantage(input_path, anchor_cfg["region"])
    fb_ev = anchor_cfg.get("fallback_target_eV")
    fb_win = tuple(anchor_cfg.get("fallback_window_eV", [286.8, 293.5]))
    shift, raw_note = fitting.auto_estimate_xps_charge_shift(
        anc_raw["x"],
        anc_raw["y"],
        target_eV=float(anchor_cfg["target_eV"]),
        search_window=tuple(anchor_cfg["search_window_eV"]),
        fallback_target_eV=float(fb_ev) if fb_ev is not None else None,
        fallback_window=fb_win,
    )

    if raw_note.startswith("PrimaryAnchor("):
        return shift, raw_note, anchor_cfg
    if raw_note.startswith("FALLBACK_Anchor("):
        findings.append({"level": "INFO_CHARGE_ANCHOR_FALLBACK", "region": finding_region, "detail": raw_note})
        return shift, raw_note, anchor_cfg

    if has_manual:
        note = f"校正未确认({raw_note}; 保留手动校正 {manual_val:+.2f}eV)"
        shift_out = manual_val
    else:
        note = f"校正未确认({raw_note}; 保持 0.00eV)"
        shift_out = 0.0
    findings.append({"level": "WARN_CHARGE_REF_UNCONFIRMED", "region": finding_region, "detail": note})
    return shift_out, note, anchor_cfg


def _resolve_capacity_axis_label(
    requested_label: Optional[str],
    cap_basis: str,
    findings: List[Dict[str, str]],
    origin_plain: bool = False,
) -> str:
    if cap_basis == "specific_mAh_g":
        canonical = "Specific Capacity (mAh g^-1)" if origin_plain else "Specific Capacity ($\\mathrm{mAh\\ g^{-1}}$)"
    else:
        canonical = "Capacity (mAh)"

    if requested_label:
        req_norm = requested_label.strip().lower()
        per_gram_tokens = ("/g", "g^-1", "g^{-1}", "g⁻¹")
        has_mah = "mah" in req_norm
        has_per_gram = any(tok in req_norm for tok in per_gram_tokens)
        is_compatible = (has_mah and has_per_gram) if cap_basis == "specific_mAh_g" else (
            has_mah and not has_per_gram and "specific" not in req_norm and "比容量" not in req_norm
        )
        if not is_compatible:
            findings.append(
                {
                    "level": "WARN_UNIT_LABEL_OVERRIDDEN",
                    "region": "Neware_Axis",
                    "detail": f"Configured x_label '{requested_label}' does not match calculation basis '{cap_basis}'; enforced '{canonical}'.",
                }
            )
            return canonical
        return canonical if origin_plain else requested_label
    return canonical


def _finalize_audit(
    out_dir: Path,
    payload: Dict[str, Any],
    expected_files: List[str],
    extra_findings: List[Dict[str, str]],
    do_origin: Optional[bool] = None,
) -> Dict[str, Any]:
    file_issues = validator.verify_deliverable_files(expected_files)
    all_findings = extra_findings + file_issues
    passed_integrity = not any(f["level"].startswith("ERROR_") for f in file_issues)
    audit_obj = {
        "passed_file_integrity": passed_integrity,
        "finding_count": len(all_findings),
        "findings": all_findings,
    }
    audit_path = out_dir / "quality_audit.json"
    audit_path.write_text(json.dumps(audit_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    if not passed_integrity:
        payload["status"] = "failed_integrity"
    if do_origin is False or ("opju" in payload and payload["opju"] is None):
        payload["opju"] = None
        payload.setdefault("skipped_formats", [])
        if "opju" not in payload["skipped_formats"]:
            payload["skipped_formats"].append("opju")
    payload["quality_audit"] = audit_obj
    payload["quality_audit_file"] = str(audit_path)
    return payload


def _extract_1d_xy_from_file_item(item: Dict[str, Any], parent_block: Dict[str, Any]) -> Tuple[List[float], List[float]]:
    """Load numeric `(x, y)` arrays from a tabular/EIS/Neware/XRD/FTIR/XY file referenced by a series spec."""
    import pandas as pd

    fpath = Path(item.get("file") or parent_block.get("input_file"))
    modality = str(item.get("modality") or parent_block.get("modality") or "").strip().upper()
    ext = fpath.suffix.lower()

    if modality == "EIS":
        pr = parsers.parse_eis(fpath)
        return pr["z_real"].tolist(), pr["neg_z_imag"].tolist()
    if modality == "XRD":
        pr = parsers.parse_xrd(fpath)
        return pr["x"].tolist(), pr["y"].tolist()
    if modality == "FTIR":
        pr = parsers.parse_ftir(fpath)
        return pr["x"].tolist(), pr["y"].tolist()
    if ext == ".ndax":
        nd = parsers.parse_neware_auto(fpath, mass_mg_override=item.get("mass_mg"))
        dc = parsers.extract_primary_discharge_curve(nd, voltage_cutoff=item.get("voltage_cutoff"))
        qk = "specific_capacity_mAh_g" if dc.get("has_active_mass") else "capacity_mAh"
        return dc[qk].tolist(), dc["voltage_V"].tolist()

    if ext in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv"):
        df = electrochem_transforms.load_tabular_sheet(
            fpath,
            sheet=item.get("sheet", parent_block.get("sheet", 0)),
            header_row=item.get("header_row", parent_block.get("header_row", 0)),
        )
        xc_ref = item.get("x_col", parent_block.get("x_col", 0))
        yc_ref = item.get("y_col", parent_block.get("y_col", 1))
        xc = electrochem_transforms._resolve_col_name(df, xc_ref)
        yc = electrochem_transforms._resolve_col_name(df, yc_ref)
        xv = pd.to_numeric(df[xc], errors="coerce").to_numpy(dtype=float)
        yv = pd.to_numeric(df[yc], errors="coerce").to_numpy(dtype=float)
        m = np.isfinite(xv) & np.isfinite(yv)
        return xv[m].tolist(), yv[m].tolist()

    pr_xy = parsers.parse_xy_text(
        fpath,
        despike=bool(item.get("despike", False)),
        x_col=int(item.get("x_col", parent_block.get("x_col", 0))),
        y_col=int(item.get("y_col", parent_block.get("y_col", 1))),
    )
    return pr_xy["x"].tolist(), pr_xy["y"].tolist()


def _apply_tabular_series_extraction(
    block: Dict[str, Any],
    loaded_tables: Dict[str, Any],
    summary_tables: Dict[str, Any],
    summary_name: str,
    force_100: bool = False,
) -> None:
    """Load tabular sheet and aggregate replicates / filter / normalize via `electrochem_transforms.extract_table_series`."""
    inp = block.get("input_file")
    if not inp:
        return
    df = electrochem_transforms.load_tabular_sheet(
        inp,
        sheet=block.get("sheet", 0),
        header_row=block.get("header_row", 0),
    )
    loaded_tables[str(inp)] = df
    loaded_tables.setdefault("main", df)

    list_key = "stacks" if "stacks" in block else ("series" if "series" in block else None)
    if list_key is None or block.get("x_col") is None:
        return

    raw_items = block.get(list_key, [])
    if not raw_items or not all(
        isinstance(it, dict)
        and it.get("values") is None
        and it.get("y") is None
        and any(it.get(k) is not None for k in ("y_col", "col", "column", "value_col"))
        for it in raw_items
    ):
        return

    specs_for_ext = []
    for it in raw_items:
        sp = dict(it)
        if "y_err_col" in sp and "y_err" not in sp:
            sp["y_err"] = sp["y_err_col"]
        specs_for_ext.append(sp)

    norm_flag = bool(force_100 or block.get("normalize_100", False))
    ext = electrochem_transforms.extract_table_series(
        df,
        x_col=block["x_col"],
        series_specs=specs_for_ext,
        sample_filter=block.get("sample_filter"),
        label_map=block.get("label_map"),
        normalize_100=norm_flag,
        clean_sample_prefix=bool(block.get("clean_sample_prefix", True)),
    )
    block["categories"] = ext["categories"]
    for orig_it, ext_s in zip(raw_items, ext["series"]):
        orig_it["values"] = ext_s["values"].tolist()
        if ext_s["errors"] is not None:
            orig_it["y_err"] = ext_s["errors"].tolist()
        if ext_s.get("unit") and not orig_it.get("y_unit"):
            orig_it["y_unit"] = ext_s["unit"]
    summary_tables[summary_name] = ext["table_df"]


def _preload_grammar_config_data(
    cfg: Dict[str, Any],
    findings: List[Dict[str, str]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[str]]:
    """
    Preload external tabular / matrix / pulse / dQ-dV / spectroscopic files into `work_cfg`
    and `loaded_tables` using `electrochem_transforms` before calling `chart_grammar.compile_config_to_figure_spec`.
    """
    import pandas as pd

    work_cfg = copy.deepcopy(cfg)
    mode = str(work_cfg["mode"]).strip()
    loaded_tables: Dict[str, Any] = {}
    summary_tables: Dict[str, Any] = {}
    audit_notes: List[str] = list(work_cfg.get("audit_notes", []))

    # 1. 2D Contour / Pseudocolor Matrix
    if mode == "contour_pseudocolor_2d":
        has_inline_mat = work_cfg.get("matrix_z") is not None or work_cfg.get("z_matrix") is not None
        if not has_inline_mat and any(
            work_cfg.get(k) is not None for k in ("input_file", "matrix_file", "file_path", "curves", "series", "files")
        ):
            mat_in = dict(work_cfg)
            mat_in.pop("mode", None)
            if work_cfg.get("matrix_mode"):
                mat_in["mode"] = work_cfg["matrix_mode"]
            if work_cfg.get("matrix_file") and not mat_in.get("file_path"):
                mat_in["file_path"] = work_cfg["matrix_file"]
            mat_res = electrochem_transforms.load_2d_field_matrix(mat_in)
            loaded_tables["main"] = mat_res
            loaded_tables["matrix"] = mat_res
            if work_cfg.get("input_file"):
                loaded_tables[str(work_cfg["input_file"])] = mat_res
            if mat_res.get("y_is_categorical") and mat_res.get("y_labels") and not work_cfg.get("state_labels"):
                work_cfg["state_labels"] = mat_res["y_labels"]
            if mat_res.get("nan_imputed_count", 0) > 0:
                audit_notes.append(f"2D matrix imputed {mat_res['nan_imputed_count']} missing/trailing NaN entries.")

        side_cfg = work_cfg.get("side_panel")
        if isinstance(side_cfg, dict):
            if side_cfg.get("file") and side_cfg.get("x") is None and side_cfg.get("y") is None:
                sx, sy = _extract_1d_xy_from_file_item(side_cfg, side_cfg)
                side_cfg["x"] = sx
                side_cfg["y"] = sy
            for s_it in side_cfg.get("series", []):
                if isinstance(s_it, dict) and s_it.get("file") and s_it.get("y") is None:
                    sx, sy = _extract_1d_xy_from_file_item(s_it, side_cfg)
                    s_it["x"] = sx
                    s_it["y"] = sy

        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 2. Bar Modes (`bar_grouped_gradient`, `bar_stacked`, `bar_stacked_100pct`)
    if mode in ("bar_grouped_gradient", "bar_stacked", "bar_stacked_100pct"):
        _apply_tabular_series_extraction(
            work_cfg,
            loaded_tables,
            summary_tables,
            summary_name="柱状图统计汇总",
            force_100=(mode == "bar_stacked_100pct"),
        )
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 3. Dual-Y Combo
    if mode == "dual_y_combo":
        for side_name in ("left_y", "right_y"):
            side_b = work_cfg.get(side_name)
            if isinstance(side_b, dict):
                for inherited in ("input_file", "sheet", "header_row", "x_col", "sample_filter", "label_map"):
                    if inherited in work_cfg and inherited not in side_b:
                        side_b[inherited] = work_cfg[inherited]
                geom_s = str(side_b.get("geom", side_b.get("mark", "line_scatter"))).lower()
                _apply_tabular_series_extraction(
                    side_b,
                    loaded_tables,
                    summary_tables,
                    summary_name=f"双Y轴_{side_name}",
                    force_100=(geom_s == "bar_stacked_100pct"),
                )
                # For line_scatter with `values` populated by extract_table_series, alias `y`
                for s_it in side_b.get("series", side_b.get("curves", [])):
                    if isinstance(s_it, dict):
                        if s_it.get("y") is None and s_it.get("values") is not None:
                            s_it["y"] = s_it["values"]
                        elif s_it.get("y") is None and s_it.get("file") and side_b.get("x_col") is None:
                            sx, sy = _extract_1d_xy_from_file_item(s_it, side_b)
                            s_it["x"] = sx
                            s_it["y"] = sy
                if side_b.get("categories") and not work_cfg.get("categories"):
                    work_cfg["categories"] = side_b["categories"]
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 4. Electrochem Kinetics (`pulse_align`, `galvanostatic_dqdv`, `ragone`)
    if mode == "electrochem_kinetics":
        subtype = str(work_cfg.get("subtype", "pulse_align")).strip().lower()
        raw_s = work_cfg.get("series", work_cfg.get("curves", []))
        pulse_rows: List[Dict[str, Any]] = []

        if subtype == "pulse_align":
            for idx, c_it in enumerate(raw_s):
                if not isinstance(c_it, dict):
                    continue
                need_file = c_it.get("y") is None and (c_it.get("file") or work_cfg.get("input_file"))
                if need_file:
                    tx, vy = _extract_1d_xy_from_file_item(c_it, work_cfg)
                    t_scale = float(c_it.get("time_scale", work_cfg.get("time_scale", 1.0)))
                    tx = [v * t_scale for v in tx]
                    decomp = electrochem_transforms.align_and_decompose_pulse(
                        tx,
                        vy,
                        t_pulse_start=c_it.get("t_pulse_start", work_cfg.get("t_pulse_start")),
                        t_pulse_end=c_it.get("t_pulse_end", work_cfg.get("t_pulse_end")),
                        pre_window_s=float(c_it.get("pre_window_s", work_cfg.get("pre_window_s", 1.0))),
                    )
                    c_it["x"] = decomp["t_windowed"].tolist()
                    c_it["y"] = decomp["v_windowed"].tolist()
                    c_it["already_aligned"] = True
                    c_it.setdefault("meta", {}).update(
                        {
                            k: decomp[k]
                            for k in (
                                "v_before",
                                "v_instant",
                                "v_pulse_end",
                                "v_final",
                                "delta_v0_app",
                                "delta_v_slow_app",
                                "delta_v_total_app",
                                "t_pulse_start",
                                "t_pulse_duration_s",
                            )
                        }
                    )
                    pulse_rows.append({"Curve": c_it.get("name", f"Pulse_{idx+1}"), **c_it["meta"]})
                    if idx == 0 or c_it.get("primary_decomposition"):
                        loaded_tables["pulse_decomposition"] = decomp
                elif bool(c_it.get("decompose", work_cfg.get("auto_decompose", False))) and c_it.get("x") and c_it.get("y"):
                    decomp = electrochem_transforms.align_and_decompose_pulse(
                        c_it["x"],
                        c_it["y"],
                        t_pulse_start=c_it.get("t_pulse_start", work_cfg.get("t_pulse_start")),
                        t_pulse_end=c_it.get("t_pulse_end", work_cfg.get("t_pulse_end")),
                        pre_window_s=float(c_it.get("pre_window_s", work_cfg.get("pre_window_s", 1.0))),
                    )
                    c_it["x"] = decomp["t_windowed"].tolist()
                    c_it["y"] = decomp["v_windowed"].tolist()
                    c_it["already_aligned"] = True
                    loaded_tables.setdefault("pulse_decomposition", decomp)

            if pulse_rows:
                summary_tables["脉冲极化分解指标"] = pd.DataFrame(pulse_rows)
            return work_cfg, loaded_tables, summary_tables, audit_notes

        if subtype == "galvanostatic_dqdv":
            dqdv_built: List[Dict[str, Any]] = []
            auto_guides: List[Dict[str, Any]] = list(work_cfg.get("dqdv_guides", []))
            for idx, c_it in enumerate(raw_s):
                if not isinstance(c_it, dict):
                    continue
                if c_it.get("y") is None and (c_it.get("file") or work_cfg.get("input_file")):
                    qx, vy = _extract_1d_xy_from_file_item(c_it, work_cfg)
                    c_it["x"] = qx
                    c_it["y"] = vy
                if not work_cfg.get("dqdv_series") and c_it.get("x") is not None and c_it.get("y") is not None and len(c_it["x"]) >= 6:
                    dq_res = electrochem_transforms.compute_dq_dv(
                        voltage=c_it["y"],
                        capacity=c_it["x"],
                        smooth_window=int(work_cfg.get("smooth_window", 11)),
                        polyorder=int(work_cfg.get("polyorder", 2)),
                        min_dv=float(work_cfg.get("min_dv", 1e-3)),
                    )
                    dq_y = dq_res["abs_dq_dv"] if bool(work_cfg.get("abs_dqdv", False)) else dq_res["dq_dv"]
                    dqdv_built.append(
                        {
                            "name": c_it.get("name", f"Series_{idx+1}"),
                            "x": dq_res["voltage_v"].tolist(),
                            "y": dq_y.tolist(),
                            "color": c_it.get("color"),
                            "role": c_it.get("role"),
                            "meta": {"peaks_detail": dq_res["peaks_detail"], "peak_positions": dq_res["peak_positions"]},
                        }
                    )
                    if idx == 0:
                        loaded_tables["dq_dv"] = dq_res
                    if dq_res["peak_positions"] and not auto_guides and idx == 0:
                        for pk_v in dq_res["peak_positions"][:2]:
                            auto_guides.append(
                                {
                                    "kind": "vline",
                                    "value": float(pk_v),
                                    "label": f"{float(pk_v):.2f} V",
                                    "color": c_it.get("color", "#D84B5C"),
                                    "line_style": "dashed",
                                }
                            )
            if dqdv_built and not work_cfg.get("dqdv_series"):
                work_cfg["dqdv_series"] = dqdv_built
            if auto_guides and not work_cfg.get("dqdv_guides"):
                work_cfg["dqdv_guides"] = auto_guides
            return work_cfg, loaded_tables, summary_tables, audit_notes

        # subtype == "ragone"
        for c_it in raw_s:
            if isinstance(c_it, dict) and c_it.get("y") is None and (c_it.get("file") or work_cfg.get("input_file")):
                rx, ry = _extract_1d_xy_from_file_item(c_it, work_cfg)
                c_it["x"] = rx
                c_it["y"] = ry
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 5. Curve With Inset
    if mode == "curve_with_inset":
        main_b = work_cfg.get("main", work_cfg)
        for s_it in main_b.get("series", main_b.get("curves", [])):
            if isinstance(s_it, dict) and s_it.get("y") is None and (s_it.get("file") or main_b.get("input_file")):
                mx, my = _extract_1d_xy_from_file_item(s_it, main_b)
                s_it["x"] = mx
                s_it["y"] = my
        insets_l = work_cfg.get("insets") or ([work_cfg["inset"]] if work_cfg.get("inset") else [])
        for ins_b in insets_l:
            if isinstance(ins_b, dict) and str(ins_b.get("mode", "zoom")).lower() in ("subchart", "subpanel"):
                sub_b = ins_b.get("sub_spec", ins_b)
                for s_it in sub_b.get("series", sub_b.get("curves", [])):
                    if isinstance(s_it, dict) and s_it.get("y") is None and (s_it.get("file") or sub_b.get("input_file")):
                        ix, iy = _extract_1d_xy_from_file_item(s_it, sub_b)
                        s_it["x"] = ix
                        s_it["y"] = iy
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 6. Universal Multi-Panel `chart_grammar`
    if mode == "chart_grammar":
        for p_idx, p_cfg in enumerate(work_cfg.get("panels", [])):
            if not isinstance(p_cfg, dict):
                continue
            if p_cfg.get("panel_mode"):
                sub_c = copy.deepcopy(p_cfg)
                sub_c["mode"] = sub_c.pop("panel_mode")
                pre_sub, sub_lt, sub_st, sub_notes = _preload_grammar_config_data(sub_c, findings)
                pre_sub["panel_mode"] = pre_sub.pop("mode")
                p_cfg.clear()
                p_cfg.update(pre_sub)
                loaded_tables.update(sub_lt)
                for k_s, v_s in sub_st.items():
                    summary_tables[f"P{p_idx+1}_{k_s}"] = v_s
                audit_notes.extend(sub_notes)
            else:
                for l_idx, l_cfg in enumerate(p_cfg.get("layers", [])):
                    if not isinstance(l_cfg, dict):
                        continue
                    mk = str(l_cfg.get("mark", "line_scatter")).lower()
                    if mk in ("bar_grouped_gradient", "bar_stacked", "bar_stacked_100pct"):
                        _apply_tabular_series_extraction(
                            l_cfg,
                            loaded_tables,
                            summary_tables,
                            summary_name=f"P{p_idx+1}_L{l_idx+1}",
                            force_100=(mk == "bar_stacked_100pct"),
                        )
                    elif mk == "contour_pseudocolor" and l_cfg.get("matrix_z") is None and l_cfg.get("input_file"):
                        m_res = electrochem_transforms.load_2d_field_matrix(l_cfg)
                        l_cfg["matrix_x"] = m_res["matrix_x"]
                        l_cfg["matrix_y"] = m_res["matrix_y"]
                        l_cfg["matrix_z"] = m_res["matrix_z"]
                    else:
                        for s_it in l_cfg.get("series", l_cfg.get("curves", [])):
                            if isinstance(s_it, dict) and s_it.get("y") is None and (s_it.get("file") or l_cfg.get("input_file")):
                                sx, sy = _extract_1d_xy_from_file_item(s_it, l_cfg)
                                s_it["x"] = sx
                                s_it["y"] = sy

    # 7. xy_fit_and_band: load XY series, run CI-band fitting
    if mode == "xy_fit_and_band":
        for s_it in work_cfg.get("series", []):
            if isinstance(s_it, dict) and s_it.get("y") is None and (s_it.get("file") or work_cfg.get("input_file")):
                sx, sy = _extract_1d_xy_from_file_item(s_it, work_cfg)
                s_it["x"] = sx
                s_it["y"] = sy
        if work_cfg.get("x") is None or work_cfg.get("y") is None:
            s_list_fit = work_cfg.get("series", [])
            if s_list_fit and isinstance(s_list_fit[0], dict) and s_list_fit[0].get("x") is not None and s_list_fit[0].get("y") is not None:
                work_cfg["x"] = s_list_fit[0]["x"]
                work_cfg["y"] = s_list_fit[0]["y"]
            elif work_cfg.get("input_file"):
                sx_top, sy_top = _extract_1d_xy_from_file_item(work_cfg, work_cfg)
                work_cfg["x"] = sx_top
                work_cfg["y"] = sy_top
        try:
            fit_fn = getattr(electrochem_transforms, "fit_xy_with_ci95", None)
            if fit_fn is not None:
                fit_model_name = str(work_cfg.get("model") or work_cfg.get("fit_model") or "linear")
                n_grid_pts = int(work_cfg.get("n_grid", 200))
                for s_it in work_cfg.get("series", []):
                    if isinstance(s_it, dict) and s_it.get("x") is not None and s_it.get("y") is not None:
                        fit_res = fit_fn(
                            np.asarray(s_it["x"], dtype=float),
                            np.asarray(s_it["y"], dtype=float),
                            model=fit_model_name,
                            n_grid=n_grid_pts,
                        )
                        s_it["x_fit"] = fit_res.get("x_fit", [])
                        s_it["y_fit"] = fit_res.get("y_fit", [])
                        s_it["fit_y"] = fit_res.get("y_fit", [])
                        s_it["y_low"] = fit_res.get("y_low", [])
                        s_it["y_high"] = fit_res.get("y_high", [])
                        s_it["ci_band_lower"] = fit_res.get("y_low", [])
                        s_it["ci_band_upper"] = fit_res.get("y_high", [])
        except Exception as _e:
            audit_notes.append({"note": f"xy_fit_and_band CI fitting skipped: {_e}"})
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 8. bode_dual_panel: parse EIS files and extract freq/|Z|/phase for Bode plot
    if mode == "bode_dual_panel":
        for s_it in work_cfg.get("series", []):
            if not isinstance(s_it, dict):
                continue
            fpath_raw = s_it.get("file") or work_cfg.get("input_file")
            if fpath_raw and s_it.get("freq_Hz") is None:
                try:
                    fpath = Path(fpath_raw)
                    if fpath.suffix.lower() in (".bin", ".txt", ".csv", ".mpt", ".dta"):
                        pr = parsers.parse_eis(fpath)
                        s_it["freq_Hz"] = pr["freq_Hz"].tolist() if hasattr(pr["freq_Hz"], "tolist") else list(pr["freq_Hz"])
                        s_it["z_mod"] = pr["z_mod"].tolist() if hasattr(pr["z_mod"], "tolist") else list(pr["z_mod"])
                        s_it["phase_deg"] = pr["phase_deg"].tolist() if hasattr(pr["phase_deg"], "tolist") else list(pr["phase_deg"])
                        s_it["z_real"] = pr["z_real"].tolist() if hasattr(pr["z_real"], "tolist") else list(pr["z_real"])
                        s_it["neg_z_imag"] = pr["neg_z_imag"].tolist() if hasattr(pr["neg_z_imag"], "tolist") else list(pr["neg_z_imag"])
                except Exception as _e:
                    audit_notes.append({"note": f"bode_dual_panel EIS parse failed for {fpath_raw}: {_e}"})
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 9. stat_distribution: load columns from summary Excel or long-table groupby
    if mode == "stat_distribution":
        import pandas as pd
        inp = work_cfg.get("input_file")
        if inp:
            try:
                df_stat = electrochem_transforms.load_tabular_sheet(
                    inp,
                    sheet=work_cfg.get("sheet", 0),
                    header_row=work_cfg.get("header_row", 0),
                )
                loaded_tables[str(inp)] = df_stat
                group_col = work_cfg.get("group_col")
                value_col = work_cfg.get("value_col")
                s_filt = work_cfg.get("sample_filter")
                lbl_map = work_cfg.get("label_map") or {}
                work_df_s = df_stat.copy()
                if isinstance(s_filt, dict):
                    for fk, fv in s_filt.items():
                        if fk in work_df_s.columns:
                            allowed_v = {str(x).strip() for x in (fv if isinstance(fv, (list, tuple, set)) else [fv])}
                            work_df_s = work_df_s.loc[work_df_s[fk].astype(str).str.strip().isin(allowed_v)].copy()
                extracted_series: List[Dict[str, Any]] = []
                if group_col and value_col and group_col in work_df_s.columns and value_col in work_df_s.columns:
                    if isinstance(s_filt, (list, tuple)):
                        allowed_g = [str(x).strip() for x in s_filt]
                        work_df_s = work_df_s.loc[work_df_s[group_col].astype(str).str.strip().isin(set(allowed_g))].copy()
                        order_lk = {k: idx_k for idx_k, k in enumerate(allowed_g)}
                        work_df_s["_rk_"] = work_df_s[group_col].astype(str).str.strip().map(lambda v: order_lk.get(v, 999))
                        work_df_s = work_df_s.sort_values("_rk_", kind="mergesort").drop(columns=["_rk_"])
                    for grp_name, grp_df in work_df_s.groupby(group_col, sort=False):
                        vals = pd.to_numeric(grp_df[value_col], errors="coerce").dropna().tolist()
                        g_raw = str(grp_name).strip()
                        g_clean = origin_theme.clean_semantic_sample_name(g_raw)
                        disp_nm = str(lbl_map.get(g_raw, lbl_map.get(g_clean, g_clean)))
                        if vals:
                            summary_tables[disp_nm] = pd.DataFrame({disp_nm: vals})
                            extracted_series.append({"name": disp_nm, "y": vals})
                else:
                    for col in work_df_s.columns:
                        vals = pd.to_numeric(work_df_s[col], errors="coerce").dropna().tolist()
                        if vals:
                            c_str = str(col).strip()
                            disp_nm = str(lbl_map.get(c_str, c_str))
                            summary_tables[disp_nm] = pd.DataFrame({disp_nm: vals})
                            extracted_series.append({"name": disp_nm, "y": vals})
                if not work_cfg.get("series") and extracted_series:
                    work_cfg["series"] = extracted_series
            except Exception as _e:
                audit_notes.append({"note": f"stat_distribution load failed: {_e}"})
        return work_cfg, loaded_tables, summary_tables, audit_notes

    # 10. matrix_heatmap: load 2D matrix for contour/heatmap rendering
    if mode == "matrix_heatmap":
        if work_cfg.get("matrix_z") is None:
            try:
                load_fn = getattr(electrochem_transforms, "load_2d_field_matrix", None)
                if load_fn is not None:
                    m_res = load_fn(work_cfg)
                    _mx = m_res.get("matrix_x")
                    _my = m_res.get("matrix_y")
                    _mz = m_res.get("matrix_z")
                    _xl = m_res.get("x_labels")
                    _yl = m_res.get("y_labels")
                    work_cfg["matrix_x"] = _mx.tolist() if hasattr(_mx, "tolist") else list(_mx) if _mx is not None else None
                    work_cfg["matrix_y"] = _my.tolist() if hasattr(_my, "tolist") else list(_my) if _my is not None else None
                    work_cfg["matrix_z"] = _mz.tolist() if hasattr(_mz, "tolist") else (_mz if _mz is None else list(_mz))
                    if _xl is not None and not work_cfg.get("x_labels"):
                        work_cfg["x_labels"] = [str(v) for v in (_xl.tolist() if hasattr(_xl, "tolist") else list(_xl))]
                    if _yl is not None and not work_cfg.get("y_labels"):
                        work_cfg["y_labels"] = [str(v) for v in (_yl.tolist() if hasattr(_yl, "tolist") else list(_yl))]
                else:
                    import pandas as pd
                    inp = work_cfg.get("input_file")
                    if inp:
                        df_m = electrochem_transforms.load_tabular_sheet(inp, sheet=work_cfg.get("sheet", 0))
                        loaded_tables[str(inp)] = df_m
                        z_arr = df_m.to_numpy(dtype=float)
                        work_cfg["matrix_z"] = z_arr.tolist()
                        work_cfg["matrix_x"] = list(range(1, z_arr.shape[1] + 1))
                        work_cfg["matrix_y"] = list(range(1, z_arr.shape[0] + 1))
                        if not work_cfg.get("x_labels"):
                            work_cfg["x_labels"] = [str(c) for c in df_m.columns]
                        if not work_cfg.get("y_labels"):
                            work_cfg["y_labels"] = [str(idx) for idx in df_m.index]
            except Exception as _e:
                audit_notes.append({"note": f"matrix_heatmap load failed: {_e}"})
        return work_cfg, loaded_tables, summary_tables, audit_notes

    return work_cfg, loaded_tables, summary_tables, audit_notes


def _run_grammar_mode(
    cfg: Dict[str, Any],
    out_dir: Path,
    raw_out_dir: Path,
    skip_origin: bool,
    findings: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Execute declarative Chart Grammar modes end-to-end via OriginPro native rendering + Source Data export."""
    style_g = origin_theme.load_theme(cfg.get("style_preset"))
    origin_builder.set_active_style(style_g)
    work_cfg, loaded_tables, summary_tables, audit_notes = _preload_grammar_config_data(cfg, findings)
    fig_spec = chart_grammar.compile_config_to_figure_spec(work_cfg, loaded_tables=loaded_tables)

    stem = origin_renderer._sanitize_file_stem(fig_spec.title, default=f"SciOrigin_{fig_spec.mode}")
    xlsx_path = excel_exporter.export_multi_chart_workbook(
        fig_spec,
        raw_out_dir / f"Source_Data_{stem}.xlsx",
        summary_tables=summary_tables or None,
        audit_notes=audit_notes or None,
    )
    expected_files: List[str] = [xlsx_path]

    if not skip_origin:
        opju_target = out_dir / f"{stem}.opju"
        render_res = origin_renderer.render_figure_spec_origin(
            fig_spec,
            out_dir=out_dir,
            out_opju=opju_target,
            export_images=True,
        )
        opju_path = render_res["opju"]
        if opju_path:
            expected_files.append(opju_path)
        expected_files.extend(render_res["all_exported_files"])
        figures_payload: Any = (
            {"primary": render_res["primary_figures"], "panels": render_res["panel_figures"]}
            if render_res["panel_figures"]
            else render_res["primary_figures"]
        )
        do_origin_flag = bool(opju_path is not None)
    else:
        opju_path = None
        figures_payload = {}
        do_origin_flag = False

    payload: Dict[str, Any] = {
        "status": "success",
        "mode": fig_spec.mode,
        "subtype": fig_spec.subtype,
        "style_preset": fig_spec.style_preset,
        "title": fig_spec.title,
        "xlsx": xlsx_path,
        "opju": opju_path,
        "figures": figures_payload,
        "metrics": fig_spec.summary_metrics,
    }
    return _finalize_audit(out_dir, payload, expected_files, findings, do_origin=do_origin_flag)


def cmd_run_config(config_path: str | Path, skip_origin: bool = False) -> Dict[str, Any]:
    cfg_p = Path(config_path).resolve()
    cfg = json.loads(cfg_p.read_text(encoding="utf-8-sig"))
    mode = str(cfg["mode"]).strip()

    out_dir = Path(cfg["output_dir"]).resolve()
    raw_out_dir = out_dir / "原始数据"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_out_dir.mkdir(parents=True, exist_ok=True)

    findings: List[Dict[str, str]] = []
    expected_files: List[str] = []

    # 1. Route all declarative Chart Grammar modes directly
    if mode in chart_grammar.SUPPORTED_GRAMMAR_MODES:
        return _run_grammar_mode(cfg, out_dir, raw_out_dir, skip_origin=skip_origin, findings=findings)

    # 2. Load unified Origin theme (defaults to `style_publication_minimal.json`) and activate runtime spec
    style = origin_theme.load_theme(cfg.get("style_preset"))
    origin_builder.set_active_style(style)
    minimal_ticks = bool(style.get("minimal_axes", True))
    box_thickness = float(style.get("figure_box_linewidth", 3.0))

    # Default (`skip_origin=False`): 100% OriginPro native rendering + `expGraph` direct export (zero matplotlib!)
    use_origin_native = not bool(skip_origin)
    want_opju_saved = use_origin_native and bool(cfg.get("build_opju", True))

    if mode == "deconvolve":
        preset_data, merged_regions = _load_explicit_preset_and_regions(cfg)
        sample_name = cfg.get("sample_name", "Sample")
        modality = cfg.get("modality", "XPS").upper()
        input_path = Path(cfg["input_file"])

        regions_to_run = cfg.get("regions", list(merged_regions.keys()))
        missing_regs = [r for r in regions_to_run if r not in merged_regions]
        if missing_regs:
            raise KeyError(
                f"Region(s) {missing_regs} have no model definition in chosen preset/regions_config. "
                "Do not force-fit unmodeled regions; use mode='raw_preview' first or provide explicit `regions_config`."
            )

        charge_shift, charge_anchor_note, anchor_cfg = (
            _resolve_xps_charge_referencing(input_path, cfg, preset_data, findings, finding_region="C1s")
            if modality == "XPS"
            else (0.0, "non_xps", None)
        )

        regions_results: Dict[str, Dict[str, Any]] = {}
        figure_outputs: Dict[str, Dict[str, str]] = {}
        metrics_digest: Dict[str, Any] = {}

        for reg in regions_to_run:
            reg_cfg = merged_regions[reg]
            parsed = parsers.parse_xps_avantage(input_path, reg) if modality == "XPS" else parsers.parse_xy_text(input_path, despike=True)
            shift_use = charge_shift if modality == "XPS" else 0.0
            fit_res = fitting.deconvolve_spectrum(
                parsed["x"],
                parsed["y"],
                reg_cfg,
                charge_shift_eV=shift_use,
                laser_nm=float(preset_data.get("laser_wavelength_nm", 532.0)),
            )
            fit_res["charge_anchor_note"] = charge_anchor_note if modality == "XPS" else "non_xps"
            findings.extend(validator.audit_deconv_region(reg, fit_res, reg_cfg))
            regions_results[reg] = fit_res
            metrics_digest[reg] = {
                "nrmse_pct": round(fit_res["nrmse_pct"], 3),
                "r_squared": round(fit_res["r_squared"], 5),
                "snr": fit_res.get("snr"),
                "audit_summary": fit_res.get("audit_summary"),
                "charge_shift_eV": round(shift_use, 4),
                "charge_anchor": fit_res["charge_anchor_note"],
                "components": [
                    {
                        "name": m["name"],
                        "center": round(m["center"], 3),
                        "fwhm": round(m["fwhm"], 3),
                        "area_pct": round(m["area_pct"], 2),
                        "subgroup_pct": round(m["subgroup_pct"], 2) if m["subgroup_pct"] is not None else None,
                    }
                    for m in fit_res["components"]
                ],
                "extra_ratios": {k: round(v, 3) for k, v in fit_res["extra_ratios"].items()},
            }

        if modality == "XPS":
            cross_cfg = preset_data.get("charge_referencing", {}).get("cross_check_anchor")
            findings.extend(validator.audit_xps_inter_region_charging(regions_results, cross_check_cfg=cross_cfg, primary_anchor_cfg=anchor_cfg))

        xlsx_path = excel_exporter.export_deconv_workbook(
            regions_results, raw_out_dir / f"{sample_name}_{modality}拟合数据汇总.xlsx", sample_name=sample_name
        )
        expected_files.append(xlsx_path)

        if use_origin_native:
            opju_dest = (out_dir / f"{sample_name}_{modality}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{sample_name}_{modality}.opju")
            saved_opju = origin_builder.build_deconv_opju(
                regions_results,
                opju_dest,
                sample_name=sample_name,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                stem_template=f"{{sample}}_{{reg}}_{modality}",
                region_titles=cfg.get("region_titles"),
                exported_figures_out=figure_outputs,
            )
            opju_path = saved_opju if want_opju_saved else None
            for fg in figure_outputs.values():
                expected_files.extend(fg.values())
            if opju_path:
                expected_files.append(opju_path)
        else:
            plt_mod = _get_plotter()
            for reg, fit_res in regions_results.items():
                reg_title = cfg.get("region_titles", {}).get(reg, reg)
                figure_outputs[reg] = plt_mod.plot_deconvolution(
                    fit_res, out_dir / f"{sample_name}_{reg}_{modality}", region_title=reg_title, sample_title=sample_name, style=style
                )
                expected_files.extend(figure_outputs[reg].values())
            opju_path = None

        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "sample": sample_name, "charge_anchor": charge_anchor_note, "xlsx": xlsx_path, "opju": opju_path, "figures": figure_outputs, "metrics": metrics_digest},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "batch_deconvolve":
        preset_data, merged_regions = _load_explicit_preset_and_regions(cfg)
        modality = cfg.get("modality", "Raman").upper()
        title = cfg.get("title", f"Batch_{modality}")
        reg_name = cfg["region"]
        if reg_name not in merged_regions:
            raise KeyError(f"Region '{reg_name}' not found in chosen preset/regions_config.")
        reg_cfg = merged_regions[reg_name]
        laser_nm = float(preset_data.get("laser_wavelength_nm", 532.0))

        cohort_aggregates: List[Dict[str, Any]] = []
        all_individual_rows: List[Dict[str, Any]] = []
        panel_items: List[Dict[str, Any]] = []

        for s_spec in cfg["samples"]:
            sid = s_spec["id"]
            sname = s_spec.get("name", sid)
            rep_files = s_spec.get("replicates") or [s_spec["file"]]
            rep_fits: List[Tuple[str, Dict[str, Any]]] = []

            for rf in rep_files:
                rf_p = Path(rf)
                if modality == "XPS":
                    shift, anc_note, _ = _resolve_xps_charge_referencing(
                        rf_p, cfg, preset_data, findings, finding_region=f"{sid}:C1s", override_manual_shift=s_spec.get("charge_shift_eV")
                    )
                    parsed = parsers.parse_xps_avantage(rf_p, reg_name)
                else:
                    shift, anc_note = 0.0, "non_xps"
                    parsed = parsers.parse_xy_text(rf_p, despike=True)

                f_res = fitting.deconvolve_spectrum(parsed["x"], parsed["y"], reg_cfg, charge_shift_eV=shift, laser_nm=laser_nm)
                f_res["charge_anchor_note"] = anc_note
                findings.extend(validator.audit_deconv_region(f"{sid}:{rf_p.name}", f_res, reg_cfg))
                rep_fits.append((str(rf_p), f_res))

                ind_row: Dict[str, Any] = {
                    "Sample_ID": sid,
                    "Sample_Name": sname,
                    "Spot_File": rf_p.name,
                    "NRMSE_pct": round(f_res["nrmse_pct"], 3),
                    "R_squared": round(f_res["r_squared"], 5),
                }
                for rk, rv in f_res["extra_ratios"].items():
                    ind_row[rk] = round(rv, 4)
                for m in f_res["components"]:
                    ind_row[f"{m['name']}_Center"] = round(m["center"], 3)
                    ind_row[f"{m['name']}_FWHM"] = round(m["fwhm"], 3)
                    ind_row[f"{m['name']}_AreaPct"] = round(m["area_pct"], 3)
                all_individual_rows.append(ind_row)

            agg = fitting.aggregate_replicate_deconvolutions(rep_fits)
            cohort_aggregates.append({"id": sid, "name": sname, "agg": agg})
            panel_items.append({"name": sname, "fit": agg["representative_fit"]})

            sub_raw = raw_out_dir / "单样品代表谱"
            excel_exporter.export_deconv_workbook({reg_name: agg["representative_fit"]}, sub_raw / f"{sid}_{modality}_代表谱数据.xlsx", sample_name=sid)

        comp_defs = reg_cfg["components"]
        comp_labels = [c.get("label", c["name"]) for c in comp_defs]
        comp_names_plain = [c["name"] for c in comp_defs]
        comp_colors = [c.get("color", "#3E86DE") for c in comp_defs]
        sample_short_labels = [e["id"] for e in cohort_aggregates]
        pct_matrix = np.array(
            [[e["agg"]["component_stats"][cn]["area_pct_mean"] for cn in comp_names_plain] for e in cohort_aggregates],
            dtype=float,
        )

        master_xlsx = excel_exporter.export_batch_deconv_master_workbook(
            cohort_aggregates,
            all_individual_rows,
            raw_out_dir / f"全部样品_{title}_分峰统计总表.xlsx",
            comparisons=cfg.get("comparisons"),
        )
        expected_files.append(master_xlsx)

        if use_origin_native:
            batch_figs: Dict[str, Dict[str, str]] = {}
            opju_dest = (out_dir / f"{title}_Master.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}_Master.opju")
            saved_opju = origin_builder.build_batch_deconv_opju(
                cohort_aggregates,
                reg_name,
                comp_names_plain,
                comp_colors,
                pct_matrix,
                opju_dest,
                project_title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                grid_ncols=int(cfg.get("grid_ncols", 3)),
                export_dir=out_dir,
                exported_figures_out=batch_figs,
            )
            opju_path = saved_opju if want_opju_saved else None
            grid_figs = batch_figs["panel_grid"]
            bar_figs = batch_figs["stacked_bar"]
            expected_files.extend([*grid_figs.values(), *bar_figs.values()])
            if opju_path:
                expected_files.append(opju_path)
        else:
            plt_mod = _get_plotter()
            grid_figs = plt_mod.plot_deconv_grid(
                panel_items, out_dir / f"{title}_PanelGrid", ncols=int(cfg.get("grid_ncols", 3)), style=style
            )
            bar_figs = plt_mod.plot_stacked_bar(
                sample_short_labels, comp_labels, comp_colors, pct_matrix, out_dir / f"{title}_StackedBar", y_label=f"{reg_name} Area Fraction (%)", style=style
            )
            expected_files.extend([*grid_figs.values(), *bar_figs.values()])
            opju_path = None

        cohort_summary = [
            {
                "id": e["id"],
                "representative_spot": Path(e["agg"]["representative_source"]).name,
                "ratios_mean": {k: round(v["mean"], 3) for k, v in e["agg"]["ratio_stats"].items()},
                "area_pct_mean": {k: round(v["area_pct_mean"], 2) for k, v in e["agg"]["component_stats"].items()},
            }
            for e in cohort_aggregates
        ]
        return _finalize_audit(
            out_dir,
            {
                "status": "success",
                "mode": mode,
                "n_samples": len(cohort_aggregates),
                "total_spectra_fitted": len(all_individual_rows),
                "master_xlsx": master_xlsx,
                "opju": opju_path,
                "figures": {"panel_grid": grid_figs, "stacked_bar": bar_figs},
                "cohort_summary": cohort_summary,
            },
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "waterfall":
        modality = cfg.get("modality", "XRD").upper()
        title = cfg.get("title", f"{modality}_Waterfall")
        invert_x = bool(cfg.get("invert_x", modality in ("FTIR", "XPS")))
        x_label = cfg.get("x_label", "$2\\theta$ (deg.)" if modality == "XRD" else "Wavenumber (cm$^{-1}$)")
        y_label = cfg.get("y_label", "Intensity (a.u.)")
        x_win = tuple(cfg["x_window"]) if "x_window" in cfg else None
        markers = cfg.get("markers", [])

        raw_series = []
        feature_rows: List[Dict[str, Any]] = []
        for s_item in cfg["series"]:
            fp = Path(s_item["file"])
            if modality == "XRD":
                parsed = parsers.parse_xrd(fp)
                if markers:
                    for ft in fitting.analyze_xrd_features(parsed["x"], parsed["y"], markers):
                        feature_rows.append({"Sample": s_item["name"], **ft})
            elif modality == "FTIR":
                parsed = parsers.parse_ftir(fp)
            else:
                parsed = parsers.parse_xy_text(fp)
            raw_series.append({"name": s_item["name"], "x": parsed["x"], "y": parsed["y"], "color": s_item.get("color")})

        if use_origin_native:
            # Adaptive offset_step based on number of curves when not explicitly set
            n_s = len(raw_series)
            default_step = 0.58 if n_s <= 2 else (0.52 if n_s <= 4 else 0.46)
            proc_curves = _prepare_waterfall_curves(
                raw_series,
                style,
                x_window=x_win,
                normalize_each=bool(cfg.get("normalize_each", True)),
                offset_step=float(cfg.get("offset_step", default_step)),
                norm_exclude_windows=cfg.get("norm_exclude_windows"),
                clip_top_factor=cfg.get("clip_top_factor"),
            )
            fig_paths: Dict[str, str] = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_waterfall_opju(
                proc_curves,
                opju_dest,
                x_label=x_label,
                y_label=y_label,
                invert_x=invert_x,
                project_title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                markers=markers,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            plt_mod = _get_plotter()
            fig_paths, proc_curves = plt_mod.plot_waterfall(
                raw_series,
                out_dir / title,
                x_label=x_label,
                y_label=y_label,
                invert_x=invert_x,
                x_window=x_win,
                markers=markers,
                normalize_each=bool(cfg.get("normalize_each", True)),
                offset_step=float(cfg.get("offset_step", 1.18)),
                norm_exclude_windows=cfg.get("norm_exclude_windows"),
                clip_top_factor=cfg.get("clip_top_factor"),
                style=style,
            )
            opju_path = None

        xlsx_path = excel_exporter.export_waterfall_workbook(
            proc_curves, raw_out_dir / f"{title}_原始与偏移汇总.xlsx", x_header=modality, feature_rows=feature_rows or None
        )
        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths, "feature_count": len(feature_rows)},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "nyquist":
        title = cfg.get("title", "EIS_Nyquist")
        pal = style["series_palette"]
        add_inset = bool(cfg.get("add_hf_inset", True))
        eis_series = []
        for idx, s_item in enumerate(cfg["series"]):
            parsed = parsers.parse_eis(s_item["file"])
            eis_series.append({"name": s_item["name"], "color": s_item.get("color") or pal[idx % len(pal)], **parsed})

        xlsx_path = excel_exporter.export_nyquist_workbook(eis_series, raw_out_dir / f"{title}_阻抗数据汇总.xlsx")
        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_nyquist_opju(
                eis_series,
                opju_dest,
                project_title=title,
                add_hf_inset=add_inset,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_nyquist(eis_series, out_dir / title, add_hf_inset=add_inset, style=style)
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "bet_porosity":
        title = cfg.get("title", "BET_Porosity")
        iso = parsers.parse_bet_isotherm(cfg["isotherm_file"])
        psd = parsers.parse_bet_psd(cfg["psd_file"])
        bet_sa = cfg.get("bet_surface_area_m2_g")
        xlsx_path = excel_exporter.export_bet_workbook(iso, psd, raw_out_dir / f"{title}_吸脱附与孔径汇总.xlsx", bet_area=bet_sa)

        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_bet_opju(
                iso,
                psd,
                opju_dest,
                title=title,
                bet_surface_area_m2_g=bet_sa,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_bet_dual(iso, psd, out_dir / title, bet_surface_area_m2_g=bet_sa, style=style)
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths, "max_adsorbed_cm3_g": round(iso["max_vol_cm3_g"], 2)},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "particle_size":
        title = cfg.get("title", "Particle_Size_Distribution")
        sample_name = cfg.get("sample_name", "Sample")
        ps = parsers.parse_mastersizer_xls(cfg["input_file"])
        xlims = tuple(cfg["x_limits"]) if "x_limits" in cfg else None
        xlsx_path = excel_exporter.export_particle_size_workbook(ps, raw_out_dir / f"{title}_粒度分布汇总.xlsx", sample_name=sample_name)

        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_particle_size_opju(
                ps,
                opju_dest,
                title=title,
                x_limits=xlims,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_particle_size_log(
                ps, out_dir / title, sample_title=sample_name, x_limits=xlims or (0.5, 200.0), style=style
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths, "metrics": ps["metrics"]},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "epr_spectrum":
        title = cfg.get("title", "EPR_Derivative")
        sample_name = cfg.get("sample_name", "Sample")
        parsed = parsers.parse_epr(cfg["input_file"])
        epr_m = fitting.analyze_epr_derivative(parsed["x"], parsed["y"])
        xlsx_path = excel_exporter.export_epr_workbook(
            parsed["x"], parsed["y"], epr_m, raw_out_dir / f"{title}_顺磁数据汇总.xlsx", x_label=parsed.get("x_label", "g-factor").replace("$", "")
        )

        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_epr_opju(
                parsed["x"],
                epr_m,
                opju_dest,
                x_label=parsed.get("x_label", "g-factor"),
                title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_epr_derivative(
                parsed["x"], epr_m, out_dir / title, x_label=parsed.get("x_label", "$g$-factor"), sample_title=sample_name, style=style
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {
                "status": "success",
                "mode": mode,
                "xlsx": xlsx_path,
                "opju": opju_path,
                "figures": fig_paths,
                "zero_crossing_center": round(epr_m["center_zero_crossing"], 5),
                "peak_to_peak_width": round(epr_m["peak_to_peak_width"], 5),
            },
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "conductivity":
        title = cfg.get("title", "Powder_Conductivity")
        sample_name = cfg.get("sample_name", "Sample")
        log_cond = bool(cfg.get("log_conductivity", True))
        cond = parsers.parse_conductivity_xlsx(cfg["input_file"])
        xlsx_path = excel_exporter.export_conductivity_workbook(cond, raw_out_dir / f"{title}_电导与压实汇总.xlsx")

        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_conductivity_opju(
                cond,
                opju_dest,
                title=title,
                log_conductivity=log_cond,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_conductivity_pressure(
                cond, out_dir / title, sample_title=sample_name, log_conductivity=log_cond, style=style
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "xy_trend":
        import pandas as pd

        title = cfg.get("title", "XY_Trend")
        x_label = cfg.get("x_label", "X")
        y_label = cfg.get("y_label", "Y")
        log_x = bool(cfg.get("log_x", False))
        log_y = bool(cfg.get("log_y", False))
        invert_x = bool(cfg.get("invert_x", False))
        show_mk = bool(cfg.get("show_markers", True))
        pal = style["series_palette"]

        series_list: List[Dict[str, Any]] = []
        for idx, s_spec in enumerate(cfg["series"]):
            fp = Path(s_spec["file"])
            xc = s_spec.get("x_col", 0)
            yc = s_spec.get("y_col", 1)
            if fp.suffix.lower() in (".xlsx", ".xlsm", ".xls", ".csv", ".tsv"):
                df = electrochem_transforms.load_tabular_sheet(
                    fp, sheet=s_spec.get("sheet", 0), header_row=s_spec.get("header", 0 if isinstance(xc, str) else None)
                )
                xc_n = electrochem_transforms._resolve_col_name(df, xc)
                yc_n = electrochem_transforms._resolve_col_name(df, yc)
                xv = pd.to_numeric(df[xc_n], errors="coerce").to_numpy(dtype=float)
                yv = pd.to_numeric(df[yc_n], errors="coerce").to_numpy(dtype=float)
                mask = np.isfinite(xv) & np.isfinite(yv)
                xv, yv = xv[mask], yv[mask]
            else:
                parsed = parsers.parse_xy_text(fp, despike=False, x_col=int(xc), y_col=int(yc))
                xv, yv = parsed["x"], parsed["y"]
            series_list.append(
                {
                    "name": re.sub(r'\.(ndax|nda|bin|mpt|dta)$', '', s_spec["name"], flags=re.IGNORECASE),
                    "x": xv,
                    "y": yv,
                    "color": s_spec.get("color") or pal[idx % len(pal)],
                }
            )

        xlsx_path = excel_exporter.export_xy_series_workbook(series_list, raw_out_dir / f"{title}_曲线数据汇总.xlsx")
        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_xy_trend_opju(
                series_list,
                opju_dest,
                x_label=x_label,
                y_label=y_label,
                log_x=log_x,
                log_y=log_y,
                invert_x=invert_x,
                show_markers=show_mk,
                title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_xy_multi_series(
                series_list,
                out_dir / title,
                x_label=x_label,
                y_label=y_label,
                log_x=log_x,
                log_y=log_y,
                invert_x=invert_x,
                show_markers=show_mk,
                style=style,
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_paths},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "neware_galvanostatic":
        title = cfg.get("title", "Neware_Rate_Discharge")
        v_cut = cfg.get("voltage_cutoff")
        req_basis = cfg.get("capacity_basis", "auto")
        pal = style["series_palette"]

        rate_items: List[Dict[str, Any]] = []
        for idx, s_spec in enumerate(cfg["series"]):
            fp = Path(s_spec["file"])
            nd = parsers.parse_neware_auto(fp, mass_mg_override=s_spec.get("mass_mg"))
            dc = parsers.extract_primary_discharge_curve(nd, voltage_cutoff=v_cut)
            col = s_spec.get("color") or pal[idx % len(pal)]
            rate_items.append({"name": re.sub(r'\.(ndax|nda|bin|mpt|dta)$', '', s_spec["name"], flags=re.IGNORECASE), "color": col, "source_file": fp.name, **dc})

        all_have_mass = all(bool(it["has_active_mass"]) for it in rate_items)
        if req_basis == "specific_mAh_g" and not all_have_mass:
            missing_l = [it["source_file"] for it in rate_items if not it["has_active_mass"]]
            raise ValueError(f"capacity_basis='specific_mAh_g' requested, but active mass (mg) is missing for: {missing_l}")
        cap_basis = "raw_mAh" if (req_basis == "raw_mAh" or not all_have_mass) else "specific_mAh_g"
        findings.extend(validator.audit_neware_mass(rate_items, cap_basis))

        q_key = "specific_capacity_mAh_g" if cap_basis == "specific_mAh_g" else "capacity_mAh"
        plot_x_label = _resolve_capacity_axis_label(cfg.get("x_label"), cap_basis, findings, origin_plain=False)
        origin_xl = _resolve_capacity_axis_label(cfg.get("x_label"), cap_basis, [], origin_plain=True)

        plot_series = [
            {
                "name": it["name"],
                "x": it[q_key],
                "y": it["voltage_V"],
                "color": it["color"],
                "plot_type": "l",
            }
            for it in rate_items
        ]
        xlsx_path = excel_exporter.export_neware_rate_workbook(
            rate_items, raw_out_dir / f"{title}_倍率放电与能量汇总.xlsx", capacity_basis=cap_basis
        )

        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_xy_trend_opju(
                plot_series,
                opju_dest,
                x_label=origin_xl,
                y_label=cfg.get("y_label", "Voltage (V vs. Li/Li^+)").replace("$", ""),
                show_markers=False,
                title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_xy_multi_series(
                plot_series,
                out_dir / title,
                x_label=plot_x_label,
                y_label=cfg.get("y_label", "Voltage (V vs. Li/Li$^+$)"),
                show_markers=False,
                style=style,
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        metrics_out = [
            {
                "name": it["name"],
                "has_active_mass": it["has_active_mass"],
                "mass_mg": it["mass_mg"],
                "capacity_mAh": round(it["max_capacity_mAh"], 4),
                "specific_capacity_mAh_g": round(it["max_capacity_mAh_g"], 2) if it.get("max_capacity_mAh_g") is not None else None,
                "median_voltage_V": round(it["median_voltage_V"], 4),
                "energy_mWh": round(it["max_energy_mWh"], 4),
                "specific_energy_Wh_kg": round(it["max_energy_Wh_kg"], 1) if it.get("max_energy_Wh_kg") is not None else None,
            }
            for it in rate_items
        ]
        return _finalize_audit(
            out_dir,
            {
                "status": "success",
                "mode": mode,
                "capacity_basis": cap_basis,
                "xlsx": xlsx_path,
                "opju": opju_path,
                "figures": fig_paths,
                "electrochem_metrics": metrics_out,
            },
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "raw_preview":
        sample_name = cfg.get("sample_name", "Sample")
        modality = cfg.get("modality", "XPS").upper()
        input_path = Path(cfg["input_file"])
        regions = cfg.get("regions", ["C1s"])
        shift_use, shift_note, _ = (
            _resolve_xps_charge_referencing(input_path, cfg, {}, findings, finding_region="C1s", default_auto=False)
            if modality == "XPS"
            else (0.0, "non_xps", None)
        )

        raw_regions: Dict[str, Dict[str, Any]] = {}
        fig_outputs: Dict[str, Dict[str, str]] = {}
        preview_metrics: Dict[str, Any] = {}
        for reg in regions:
            parsed = parsers.parse_xps_avantage(input_path, reg) if modality == "XPS" else parsers.parse_xy_text(input_path, despike=True)
            xv = parsed["x"] + (shift_use if modality == "XPS" else 0.0)
            yv = parsed["y"]
            if "x_window" in cfg:
                wlo, whi = min(cfg["x_window"]), max(cfg["x_window"])
                m = (xv >= wlo) & (xv <= whi)
                if np.sum(m) >= 5:
                    xv, yv = xv[m], yv[m]
            snr_val = parsers._estimate_snr_quick(yv)
            pk_x = float(xv[int(np.argmax(yv - fitting.linear_baseline(xv, yv)))])
            inv_x = bool(cfg.get("invert_x", modality in ("XPS", "FTIR")))
            xl = cfg.get("x_label", "Binding Energy (eV)" if modality == "XPS" else "Wavenumber (cm$^{-1}$)")
            yl = cfg.get("y_label", "Intensity (Counts / s)" if modality == "XPS" else "Intensity (a.u.)")
            raw_regions[reg] = {
                "x": xv,
                "y": yv,
                "invert_x": inv_x,
                "x_label": xl,
                "y_label": yl,
                "snr": snr_val,
                "peak_x": pk_x,
            }
            preview_metrics[reg] = {
                "x_range": [round(float(xv.min()), 2), round(float(xv.max()), 2)],
                "max_peak_pos": round(pk_x, 2),
                "approx_snr": snr_val,
                "trace_signal_flag": snr_val < 3.5,
            }
            if snr_val < 3.5:
                findings.append({"level": "INFO_TRACE_SIGNAL", "region": reg, "detail": f"Raw spectrum SNR={snr_val:.1f} < 3.5 (near background/noise)."})

        xlsx_path = excel_exporter.export_raw_preview_workbook(raw_regions, raw_out_dir / f"{sample_name}_{modality}_RawPreview.xlsx", sample_name=sample_name)
        expected_files.append(xlsx_path)

        if use_origin_native:
            opju_dest = (out_dir / f"{sample_name}_{modality}_RawPreview.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{sample_name}_{modality}_RawPreview.opju")
            saved_opju = origin_builder.build_raw_preview_opju(
                raw_regions,
                opju_dest,
                sample_name=sample_name,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                exported_figures_out=fig_outputs,
            )
            opju_path = saved_opju if want_opju_saved else None
            for fg in fig_outputs.values():
                expected_files.extend(fg.values())
            if opju_path:
                expected_files.append(opju_path)
        else:
            plt_mod = _get_plotter()
            for reg, d in raw_regions.items():
                fig_outputs[reg] = plt_mod.plot_raw_spectrum(
                    d["x"],
                    d["y"],
                    out_dir / f"{sample_name}_{reg}_RawPreview",
                    region_title=cfg.get("region_titles", {}).get(reg, reg),
                    sample_title=sample_name,
                    x_label=d["x_label"],
                    y_label=d["y_label"],
                    invert_x=d["invert_x"],
                    snr=d["snr"],
                    peak_x=d["peak_x"],
                    style=style,
                )
                expected_files.extend(fig_outputs[reg].values())
            opju_path = None

        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "sample": sample_name, "charge_anchor": shift_note, "xlsx": xlsx_path, "opju": opju_path, "figures": fig_outputs, "preview_metrics": preview_metrics},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "model_sensitivity":
        preset_data, _ = _load_explicit_preset_and_regions(cfg)
        sample_name = cfg.get("sample_name", "Sample")
        modality = cfg.get("modality", "XPS").upper()
        reg_name = cfg["region"]
        input_path = Path(cfg["input_file"])

        cand_models = cfg.get("models") or preset_data.get("candidate_models", {}).get(reg_name)
        if not cand_models or not isinstance(cand_models, dict):
            raise KeyError(f"No candidate_models defined for region '{reg_name}' in preset or config.")

        shift_use, shift_note, _ = (
            _resolve_xps_charge_referencing(input_path, cfg, preset_data, findings, finding_region="C1s")
            if modality == "XPS"
            else (0.0, "non_xps", None)
        )
        parsed = parsers.parse_xps_avantage(input_path, reg_name) if modality == "XPS" else parsers.parse_xy_text(input_path, despike=True)

        panel_items: List[Dict[str, Any]] = []
        model_rows: List[Dict[str, Any]] = []
        comp_pct_collector: Dict[str, Dict[str, Any]] = {}
        model_summaries: Dict[str, Any] = {}

        for mid, rcfg in cand_models.items():
            f_res = fitting.deconvolve_spectrum(parsed["x"], parsed["y"], rcfg, charge_shift_eV=shift_use)
            f_res["charge_anchor_note"] = shift_note
            findings.extend(validator.audit_deconv_region(f"{reg_name}:{mid}", f_res, rcfg))
            panel_items.append({"name": mid, "fit": f_res})
            model_summaries[mid] = {
                "title": rcfg.get("title", mid),
                "rationale": rcfg.get("rationale", ""),
                "nrmse_pct": round(f_res["nrmse_pct"], 3),
                "r_squared": round(f_res["r_squared"], 5),
                "audit_summary": f_res.get("audit_summary"),
                "components": [
                    {
                        "name": m["name"],
                        "center": round(m["center"], 3),
                        "fwhm": round(m["fwhm"], 3),
                        "area_pct": round(m["area_pct"], 2),
                        "subgroup_pct": round(m["subgroup_pct"], 2) if m["subgroup_pct"] is not None else None,
                    }
                    for m in f_res["components"]
                ],
            }
            for m in f_res["components"]:
                model_rows.append(
                    {
                        "Model_ID": mid,
                        "NRMSE_pct": round(f_res["nrmse_pct"], 3),
                        "R_squared": round(f_res["r_squared"], 5),
                        "Component": m["name"],
                        "Center_eV": round(m["center"], 3),
                        "FWHM_eV": round(m["fwhm"], 3),
                        "Area_pct": round(m["area_pct"], 2),
                        "Subgroup_pct": round(m["subgroup_pct"], 2) if m["subgroup_pct"] is not None else None,
                        "Audit_Flags": f_res.get("audit_summary"),
                        "Rationale": rcfg.get("rationale", ""),
                    }
                )
                comp_pct_collector.setdefault(m["name"], {"total": [], "sub": []})
                comp_pct_collector[m["name"]]["total"].append((mid, round(m["area_pct"], 2)))
                if m["subgroup_pct"] is not None:
                    comp_pct_collector[m["name"]]["sub"].append((mid, round(m["subgroup_pct"], 2)))

        comp_ranges = []
        for cname, bucket in comp_pct_collector.items():
            tot_vals = [v for _, v in bucket["total"]]
            sub_vals = [v for _, v in bucket["sub"]]
            comp_ranges.append(
                {
                    "Component": cname,
                    "Models_Present": len(tot_vals),
                    "AreaPct_Min": min(tot_vals),
                    "AreaPct_Max": max(tot_vals),
                    "AreaPct_Swing": round(max(tot_vals) - min(tot_vals), 2),
                    "SubgroupPct_Min": min(sub_vals) if sub_vals else None,
                    "SubgroupPct_Max": max(sub_vals) if sub_vals else None,
                    "Sensitivity_Note": "MODEL_SENSITIVE (>10% swing)" if (max(tot_vals) - min(tot_vals) > 10.0) else "ROBUST (<=10% swing)",
                }
            )

        title = cfg.get("title", f"{sample_name}_{reg_name}_CandidateModels")
        xlsx_path = excel_exporter.export_model_sensitivity_workbook(
            model_rows, comp_ranges, raw_out_dir / f"{title}_模型敏感性与触界对比.xlsx"
        )
        expected_files.append(xlsx_path)

        if use_origin_native:
            grid_figs = {}
            opju_dest = (out_dir / f"{title}.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}.opju")
            saved_opju = origin_builder.build_deconv_grid_opju(
                panel_items,
                opju_dest,
                ncols=int(cfg.get("grid_ncols", 2)),
                project_title=title,
                minimal_ticks=minimal_ticks,
                box_thickness=2.2,
                export_dir=out_dir,
                export_stem=f"{title}_Grid",
                exported_figures_out=grid_figs,
            )
            opju_path = saved_opju if want_opju_saved else None
            expected_files.extend(grid_figs.values())
            if opju_path:
                expected_files.append(opju_path)
        else:
            grid_figs = _get_plotter().plot_deconv_grid(
                panel_items, out_dir / f"{title}_Grid", ncols=int(cfg.get("grid_ncols", 2)), style=style
            )
            expected_files.extend(grid_figs.values())
            opju_path = None

        return _finalize_audit(
            out_dir,
            {
                "status": "success",
                "mode": mode,
                "sample": sample_name,
                "region": reg_name,
                "charge_anchor": shift_note,
                "xlsx": xlsx_path,
                "opju": opju_path,
                "figures": {"comparison_grid": grid_figs},
                "model_summaries": model_summaries,
                "component_sensitivity_ranges": comp_ranges,
            },
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "replot_deconv":
        sample_name = cfg.get("sample_name", "Sample")
        input_path = Path(cfg["input_file"])
        sheets = cfg["sheets"]
        pal = style["deconv_colors"]["components"]
        regions_results = {}
        fig_outputs = {}
        replot_digest: Dict[str, Any] = {}

        for sh_name in sheets:
            fit_res = parsers.parse_fitted_deconv_excel(input_path, sh_name, palette=pal, invert_x=cfg.get("invert_x"))
            regions_results[sh_name] = fit_res
            replot_digest[sh_name] = {
                "nrmse_pct": round(fit_res["nrmse_pct"], 4),
                "r_squared": round(fit_res["r_squared"], 5),
                "components": [{"name": m["name"], "peak_at_x": round(m["center"], 3), "area_pct": round(m["area_pct"], 2)} for m in fit_res["components"]],
            }

        if use_origin_native:
            opju_dest = (out_dir / f"{sample_name}_Replotted.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{sample_name}_Replotted.opju")
            saved_opju = origin_builder.build_deconv_opju(
                regions_results,
                opju_dest,
                sample_name=sample_name,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                export_dir=out_dir,
                stem_template="{sample}_{reg}_Replot",
                region_titles=cfg.get("region_titles"),
                exported_figures_out=fig_outputs,
            )
            opju_path = saved_opju if want_opju_saved else None
            for fg in fig_outputs.values():
                expected_files.extend(fg.values())
            if opju_path:
                expected_files.append(opju_path)
        else:
            plt_mod = _get_plotter()
            for sh_name, fit_res in regions_results.items():
                reg_title = cfg.get("region_titles", {}).get(sh_name, sh_name)
                fig_outputs[sh_name] = plt_mod.plot_deconvolution(
                    fit_res, out_dir / f"{sample_name}_{sh_name}_Replot", region_title=reg_title, sample_title=sample_name, style=style
                )
                expected_files.extend(fig_outputs[sh_name].values())
            opju_path = None

        return _finalize_audit(
            out_dir,
            {"status": "success", "mode": mode, "sample": sample_name, "source_table": str(input_path), "opju": opju_path, "figures": fig_outputs, "replot_metrics": replot_digest},
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    if mode == "composite_figure":
        title = cfg.get("title", "Paper_Composite_Figure")
        pal = style["series_palette"]
        panels_rendered: List[Dict[str, Any]] = []
        panel_charge_refs: Dict[str, Dict[str, Any]] = {}

        for p_cfg in cfg["panels"]:
            ptype = p_cfg["type"]
            pid = p_cfg.get("panel_id", ptype)
            ptitle = p_cfg.get("panel_title", "")

            if ptype == "deconvolve":
                mod = p_cfg.get("modality", "XPS").upper()
                pdata, merged_regs = _load_explicit_preset_and_regions(p_cfg)
                reg = p_cfg["region"]
                if reg not in merged_regs:
                    raise KeyError(
                        f"Region '{reg}' in composite panel '{pid}' has no model definition in chosen preset/regions_config."
                    )
                rcfg = merged_regs[reg]
                inp = Path(p_cfg["input_file"])
                if mod == "XPS":
                    shift, shift_note, _ = _resolve_xps_charge_referencing(inp, p_cfg, pdata, findings, finding_region=f"{pid}:{reg}")
                else:
                    shift, shift_note = 0.0, "non_xps"
                parsed = parsers.parse_xps_avantage(inp, reg) if mod == "XPS" else parsers.parse_xy_text(inp, despike=True)
                f_res = fitting.deconvolve_spectrum(
                    parsed["x"],
                    parsed["y"],
                    rcfg,
                    charge_shift_eV=shift,
                    laser_nm=float(pdata.get("laser_wavelength_nm", 532.0)),
                )
                f_res["charge_anchor_note"] = shift_note
                findings.extend(validator.audit_deconv_region(f"{pid}:{reg}", f_res, rcfg))
                if mod == "XPS":
                    panel_charge_refs[pid] = {
                        "region": reg,
                        "charge_shift_eV": round(shift, 4),
                        "charge_anchor": shift_note,
                    }
                panels_rendered.append({"panel_id": pid, "panel_title": ptitle, "panel_type": "deconvolve", "fit_result": f_res, "right_title": p_cfg.get("right_title", "")})

            elif ptype == "waterfall":
                mod = p_cfg.get("modality", "XRD").upper()
                inv_x = bool(p_cfg.get("invert_x", mod in ("FTIR", "XPS")))
                x_win = tuple(p_cfg["x_window"]) if "x_window" in p_cfg else None
                off_step = float(p_cfg.get("offset_step", 1.18))
                proc_c = []
                for s_i, s_it in enumerate(p_cfg["series"]):
                    fp = Path(s_it["file"])
                    pr = parsers.parse_xrd(fp) if mod == "XRD" else (parsers.parse_ftir(fp) if mod == "FTIR" else parsers.parse_xy_text(fp))
                    xv, yv = pr["x"], pr["y"]
                    if x_win is not None:
                        m = (xv >= min(x_win)) & (xv <= max(x_win))
                        xv, yv = xv[m], yv[m]
                    yn = _normalize_with_exclusions(
                        xv,
                        yv,
                        bool(p_cfg.get("normalize_each", True)),
                        p_cfg.get("norm_exclude_windows"),
                        p_cfg.get("clip_top_factor"),
                    )
                    proc_c.append({"name": s_it["name"], "color": s_it.get("color") or pal[s_i % len(pal)], "x": xv, "y_raw": yv, "y_offset": yn + s_i * off_step})
                panels_rendered.append(
                    {
                        "panel_id": pid,
                        "panel_title": ptitle,
                        "panel_type": "waterfall",
                        "processed_curves": proc_c,
                        "invert_x": inv_x,
                        "offset_step": off_step,
                        "x_label": p_cfg.get("x_label", "$2\\theta$ (deg.)" if mod == "XRD" else "Wavenumber (cm$^{-1}$)"),
                        "y_label": p_cfg.get("y_label", "Intensity (a.u.)"),
                        "markers": p_cfg.get("markers", []),
                    }
                )

            elif ptype == "nyquist":
                eis_s = []
                for s_i, s_it in enumerate(p_cfg["series"]):
                    pr = parsers.parse_eis(s_it["file"])
                    eis_s.append({"name": s_it["name"], "color": s_it.get("color") or pal[s_i % len(pal)], **pr})
                panels_rendered.append({"panel_id": pid, "panel_title": ptitle, "panel_type": "nyquist", "eis_series": eis_s, "add_hf_inset": bool(p_cfg.get("add_hf_inset", True))})

            elif ptype == "neware_galvanostatic":
                s_list = []
                dcs = []
                v_cut = p_cfg.get("voltage_cutoff")
                for s_i, s_it in enumerate(p_cfg["series"]):
                    nd = parsers.parse_neware_auto(s_it["file"], mass_mg_override=s_it.get("mass_mg"))
                    dc = parsers.extract_primary_discharge_curve(nd, voltage_cutoff=v_cut)
                    dcs.append((s_i, s_it, dc))
                all_m = all(dc["has_active_mass"] for _, _, dc in dcs)
                q_k = "specific_capacity_mAh_g" if all_m else "capacity_mAh"
                p_basis = "specific_mAh_g" if all_m else "raw_mAh"
                if not all_m:
                    findings.extend(validator.audit_neware_mass([{"source_file": Path(s_it["file"]).name, **dc} for _, s_it, dc in dcs], p_basis))
                for s_i, s_it, dc in dcs:
                    s_list.append({"name": s_it["name"], "x": dc[q_k], "y": dc["voltage_V"], "color": s_it.get("color") or pal[s_i % len(pal)]})
                p_xl = _resolve_capacity_axis_label(p_cfg.get("x_label"), p_basis, findings, origin_plain=False)
                panels_rendered.append(
                    {
                        "panel_id": pid,
                        "panel_title": ptitle,
                        "panel_type": "xy_series",
                        "series_list": s_list,
                        "x_label": p_xl,
                        "y_label": p_cfg.get("y_label", "Voltage (V vs. Li/Li$^+$)"),
                        "legend_loc": p_cfg.get("legend_loc", "upper right"),
                    }
                )

        xlsx_path = excel_exporter.export_composite_source_data_workbook(panels_rendered, raw_out_dir / f"Source_Data_{title}.xlsx")
        if use_origin_native:
            fig_paths = {}
            opju_dest = (out_dir / f"{title}_Composite.opju") if want_opju_saved else (Path(tempfile.gettempdir()) / f"_tmp_{title}_Composite.opju")
            saved_opju = origin_builder.build_composite_opju(
                panels_rendered,
                opju_dest,
                title=title,
                ncols=int(cfg.get("ncols", 2)),
                minimal_ticks=minimal_ticks,
                box_thickness=2.2,
                export_dir=out_dir,
                export_stem=title,
                exported_figures_out=fig_paths,
            )
            opju_path = saved_opju if want_opju_saved else None
        else:
            fig_paths = _get_plotter().plot_composite_figure(
                panels_rendered, out_dir / title, ncols=int(cfg.get("ncols", 2)), style=style
            )
            opju_path = None

        expected_files.extend([*fig_paths.values(), xlsx_path, *([opju_path] if opju_path else [])])
        return _finalize_audit(
            out_dir,
            {
                "status": "success",
                "mode": mode,
                "n_panels": len(panels_rendered),
                "source_data_xlsx": xlsx_path,
                "opju": opju_path,
                "figures": fig_paths,
                "panel_charge_refs": panel_charge_refs,
            },
            expected_files,
            findings,
            do_origin=want_opju_saved,
        )

    supported_all = sorted(set(TEMPLATES.keys()) | set(chart_grammar.SUPPORTED_GRAMMAR_MODES))
    raise ValueError(f"Unsupported pipeline mode: {mode}. Supported: {supported_all}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SciOrigin Cross-Material Scientific Workflow Execution Engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan directory and classify experimental modalities")
    p_scan.add_argument("target", help="Directory path to scan")

    p_insp = sub.add_parser("inspect", help="Inspect file sheets/regions/units/SNR/active-mass before method choice")
    p_insp.add_argument("target", help="File or directory path to inspect")

    p_tpl = sub.add_parser("init-template", help="Print a ready-to-fill JSON task config template for a mode")
    p_tpl.add_argument("mode", choices=ALL_INIT_TEMPLATE_MODES, help="Pipeline mode name")

    p_run = sub.add_parser("run", help="Execute a JSON pipeline task specification")
    p_run.add_argument("config", help="Path to JSON task config file")
    p_run.add_argument("--skip-origin", action="store_true", help="Offline fallback: skip OriginPro and render figures via matplotlib")

    args = parser.parse_args()
    if args.cmd == "scan":
        out = cmd_scan(args)
    elif args.cmd == "inspect":
        out = cmd_inspect(args)
    elif args.cmd == "init-template":
        if args.mode in chart_grammar.SUPPORTED_GRAMMAR_MODES or args.mode in GRAMMAR_SUBTYPE_ALIASES:
            out = chart_grammar.generate_mode_template(args.mode)
        else:
            out = TEMPLATES[args.mode]
    else:
        out = cmd_run_config(args.config, skip_origin=args.skip_origin)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.cmd == "run" and out.get("status") != "success":
        sys.exit(2)


if __name__ == "__main__":
    main()
