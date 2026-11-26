from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def audit_deconv_region(
    reg_name: str,
    fit_res: Dict[str, Any],
    reg_cfg: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Run physical sanity checks (SNR, NRMSE, Center & FWHM bound-pinning) and store flags on fit_res."""
    findings: List[Dict[str, str]] = []
    flag_tags: List[str] = []

    dy_noise = float((fit_res["y_raw"][1:] - fit_res["y_raw"][:-1]).std() / 1.4142) if len(fit_res["y_raw"]) > 5 else 1.0
    net_max = float((fit_res["y_fit"] - fit_res["baseline"]).max())
    snr = net_max / max(dy_noise, 1e-9)
    fit_res["snr"] = round(snr, 2)

    if snr < 3.5:
        findings.append(
            {
                "level": "INFO_TRACE_SIGNAL",
                "region": reg_name,
                "detail": f"Low peak SNR ({snr:.1f} < 3.5): spectrum is near background/detection limit; treat fitted peak area as trace or absent.",
            }
        )
        flag_tags.append(f"TRACE_SIGNAL(SNR={snr:.1f})")
    elif fit_res["nrmse_pct"] > 3.8:
        findings.append(
            {
                "level": "WARN_HIGH_NRMSE",
                "region": reg_name,
                "detail": f"NRMSE = {fit_res['nrmse_pct']:.2f}% (> 3.8%): check baseline window or missing component.",
            }
        )
        flag_tags.append(f"HIGH_NRMSE({fit_res['nrmse_pct']:.2f}%)")

    cfg_by_name = {c["name"]: c for c in reg_cfg.get("components", [])}
    bound_hits_cen: List[str] = []
    bound_hits_fwhm: List[str] = []
    if snr >= 3.5:
        for m in fit_res["components"]:
            c_spec = cfg_by_name.get(m["name"])
            if not c_spec or m["area_pct"] < 0.2:
                continue
            c_lo, c_hi = float(c_spec["center_bounds"][0]), float(c_spec["center_bounds"][1])
            c_tol = max(0.015 * max(c_hi - c_lo, 0.05), 0.005)
            hit_side_c = "lower" if abs(m["center"] - c_lo) <= c_tol else ("upper" if abs(m["center"] - c_hi) <= c_tol else None)
            if hit_side_c:
                m_bound_str = f"{m['name']}@{hit_side_c}({m['center']:.2f})"
                bound_hits_cen.append(m_bound_str)
                findings.append(
                    {
                        "level": "WARN_CENTER_AT_BOUND",
                        "region": reg_name,
                        "detail": (
                            f"Component '{m['name']}' center pinned at {hit_side_c} bound "
                            f"({m['center']:.3f} in [{c_lo:.2f}, {c_hi:.2f}], area={m['area_pct']:.2f}%); "
                            "overlapped neighbor may distort area ratios."
                        ),
                    }
                )

            if m["area_pct"] >= 2.0:
                w_lo, w_hi = float(c_spec["fwhm_bounds"][0]), float(c_spec["fwhm_bounds"][1])
                w_tol = 0.015 * max(w_hi - w_lo, 0.05)
                if abs(m["fwhm"] - w_hi) <= w_tol:
                    bound_hits_fwhm.append(f"{m['name']}@upper({m['fwhm']:.2f})")
                    findings.append(
                        {
                            "level": "WARN_FWHM_UPPER_BOUND",
                            "region": reg_name,
                            "detail": f"Component '{m['name']}' hit upper FWHM bound ({m['fwhm']:.3f} vs {w_hi:.3f}); check if it is absorbing adjacent shoulder/background.",
                        }
                    )
                elif abs(m["fwhm"] - w_lo) <= w_tol:
                    bound_hits_fwhm.append(f"{m['name']}@lower({m['fwhm']:.2f})")
                    findings.append(
                        {
                            "level": "WARN_FWHM_LOWER_BOUND",
                            "region": reg_name,
                            "detail": f"Component '{m['name']}' hit lower FWHM bound ({m['fwhm']:.3f} vs {w_lo:.3f}).",
                        }
                    )

    if bound_hits_cen:
        flag_tags.append("CEN_BOUND:" + ",".join(bound_hits_cen))
    if bound_hits_fwhm:
        flag_tags.append("FWHM_BOUND:" + ",".join(bound_hits_fwhm))
    if "校正未确认" in str(fit_res.get("charge_anchor_note", "")):
        flag_tags.append("CHARGE_REF_UNCONFIRMED")

    fit_res["audit_flags"] = flag_tags
    fit_res["audit_summary"] = "; ".join(flag_tags) if flag_tags else "PASS"
    return findings


def audit_xps_inter_region_charging(
    regions_results: Dict[str, Dict[str, Any]],
    cross_check_cfg: Optional[Dict[str, Any]] = None,
    primary_anchor_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Cross-check inter-region BE separation ONLY when a domain-specific cross_check_anchor rule
    is supplied by the selected preset (prevents hardcoding CFx/LiF rules on unrelated materials).
    """
    findings: List[Dict[str, str]] = []
    if not cross_check_cfg:
        return findings

    ref_reg = (primary_anchor_cfg or {}).get("region", "C1s")
    ref_comp = (primary_anchor_cfg or {}).get("component", "C-C/C=C")
    tgt_reg = cross_check_cfg.get("region")
    tgt_comp = cross_check_cfg.get("component")
    if not tgt_reg or not tgt_comp or ref_reg not in regions_results or tgt_reg not in regions_results:
        return findings

    ref_map = {m["name"]: m for m in regions_results[ref_reg]["components"]}
    tgt_map = {m["name"]: m for m in regions_results[tgt_reg]["components"]}
    r_m = ref_map.get(ref_comp)
    t_m = tgt_map.get(tgt_comp)
    min_r = float(cross_check_cfg.get("min_cc_pct", 5.0))
    min_t = float(cross_check_cfg.get("min_target_pct", 8.0))
    exp_sep = float(cross_check_cfg.get("expected_separation_from_CC_eV", 400.2))
    tol = float(cross_check_cfg.get("tolerance_eV", 0.65))

    if r_m and t_m and r_m["area_pct"] >= min_r and t_m["area_pct"] >= min_t:
        delta_be = t_m["center"] - r_m["center"]
        if abs(delta_be - exp_sep) > tol:
            findings.append(
                {
                    "level": "WARN_DIFFERENTIAL_CHARGING",
                    "region": f"{ref_reg}+{tgt_reg}",
                    "detail": (
                        f"BE({tgt_reg} {tgt_comp}) - BE({ref_reg} {ref_comp}) = {delta_be:.2f} eV "
                        f"(expected {exp_sep:.1f} ± {tol:.2f} eV). Possible differential charging."
                    ),
                }
            )
    return findings


def audit_neware_mass(rate_items: List[Dict[str, Any]], capacity_basis: str) -> List[Dict[str, str]]:
    """Report missing active mass explicitly whenever any cell lacks mass_mg and cannot use mAh/g."""
    missing_names = [it.get("source_file") or it.get("name", "unknown") for it in rate_items if not it.get("has_active_mass")]
    if not missing_names:
        return []
    return [
        {
            "level": "WARN_MISSING_ACTIVE_MASS",
            "region": "Neware_Mass",
            "detail": (
                f"Active mass (mg) is missing for {len(missing_names)}/{len(rate_items)} series ({', '.join(missing_names)}). "
                f"Specific capacity (mAh/g) and specific energy (Wh/kg) cannot be computed without the mass denominator; "
                f"pipeline enforced '{capacity_basis}' basis (raw Capacity mAh / Energy mWh)."
            ),
        }
    ]


def verify_deliverable_files(paths_list: List[str]) -> List[Dict[str, str]]:
    """Verify generated .opju, .xlsx, .tif, .png, and .jpg deliverables exist and pass binary/structural checks."""
    issues: List[Dict[str, str]] = []
    for p_str in paths_list:
        if not p_str:
            continue
        p = Path(p_str)
        if not p.exists():
            issues.append({"level": "ERROR_MISSING_FILE", "file": str(p), "detail": "Expected output file does not exist."})
            continue
        sz = p.stat().st_size
        ext = p.suffix.lower()
        if sz == 0:
            issues.append({"level": "ERROR_EMPTY_FILE", "file": str(p), "detail": "Output file is 0 bytes."})
            continue

        if ext == ".opju":
            head = p.read_bytes()[:8]
            if not head.startswith(b"CPYUA") or sz < 512:
                issues.append({"level": "ERROR_INVALID_OPJU", "file": str(p), "detail": f"Invalid .opju header/size ({head!r}, {sz} B)."})
        elif ext in (".png", ".tif", ".tiff", ".jpg", ".jpeg"):
            try:
                from PIL import Image
                with Image.open(p) as im:
                    im.verify()
                if ext == ".jpg" and "_preview" in p.name and sz > 180 * 1024:
                    issues.append({"level": "WARN_PREVIEW_LARGE", "file": str(p), "detail": f"QA preview is {sz//1024} KB (>180 KB)."})
            except Exception as exc:
                issues.append({"level": "ERROR_CORRUPT_IMAGE", "file": str(p), "detail": f"Image verification failed ({ext}): {exc}"})
        elif ext == ".pdf":
            head = p.read_bytes()[:8]
            if not head.startswith(b"%PDF-") or sz < 512:
                issues.append({"level": "ERROR_INVALID_PDF", "file": str(p), "detail": f"Invalid .pdf header/size ({head!r}, {sz} B)."})
        elif ext == ".xlsx":
            try:
                import openpyxl
                wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
                n_sheets = len(wb.sheetnames)
                wb.close()
                if n_sheets == 0:
                    issues.append({"level": "ERROR_INVALID_XLSX", "file": str(p), "detail": "Workbook contains 0 sheets."})
            except Exception as exc:
                issues.append({"level": "ERROR_CORRUPT_XLSX", "file": str(p), "detail": f"Excel workbook verification failed: {exc}"})
    return issues


_ERROR_BAR_TOKEN_RE = re.compile(
    r"(?:\bSD\b|\bSEM\b|S\.D\.|S\.E\.M\.|\b95%\s*CI\b|\bCI95\b|\bCI\b|\bIQR\b|\bSE\b)",
    re.IGNORECASE,
)


def audit_statistical_rigor(fig_spec_or_report: Any) -> List[Dict[str, str]]:
    """
    Audit cross-discipline statistical reporting rigor on a `FigureSpec` (or its dict)
    or a standalone `stat_engine.run_group_comparisons` report dictionary:
      1. Small-sample (`n < 5`) pure bar charts without individual replicate dot overlay.
      2. Plotted error bars without explicit error-bar type declaration (`SD`, `SEM`, `95% CI`).
      3. Multiple pairwise comparisons (`>= 2` tests) without multiplicity adjustment.
    """
    findings: List[Dict[str, str]] = []
    if fig_spec_or_report is None:
        return findings

    if hasattr(fig_spec_or_report, "to_dict") and callable(fig_spec_or_report.to_dict):
        obj: Dict[str, Any] = fig_spec_or_report.to_dict()
    elif isinstance(fig_spec_or_report, dict):
        obj = fig_spec_or_report
    else:
        return findings

    is_figure = "panels" in obj and isinstance(obj.get("panels"), list)
    fig_meta: Dict[str, Any] = obj.get("meta") if isinstance(obj.get("meta"), dict) else {}
    stat_reports: List[Dict[str, Any]] = []

    if not is_figure and ("comparisons" in obj or "summary" in obj):
        stat_reports.append(obj)
        # Standalone report check for pure-bar hint if supplied
        summary_rows = obj.get("summary") or []
        small_grps = [
            f"{r.get('group', '?')} (n={r.get('n')})"
            for r in summary_rows
            if isinstance(r, dict) and r.get("n") is not None and 0 < int(r["n"]) < 5
        ]
        mark_hint = str(obj.get("mark") or obj.get("chart_mark") or "").strip().lower()
        if small_grps and mark_hint in ("bar", "bar_grouped_gradient", "bar_stacked", "pure_bar"):
            findings.append(
                {
                    "level": "WARN_SMALL_SAMPLE_BAR_NO_DOTS",
                    "region": "Statistical_Rigor",
                    "detail": (
                        f"Small sample size detected ({', '.join(small_grps)}) on a pure bar chart without replicate dots; "
                        "use 'stat_bar_dot_sig' (mark='bar_dot_error') to overlay individual data points."
                    ),
                }
            )
    else:
        if isinstance(fig_meta.get("stat_report"), dict):
            stat_reports.append(fig_meta["stat_report"])

        pure_bar_marks = {"bar_grouped_gradient", "bar_stacked", "bar_stacked_100pct"}
        dot_capable_marks = {"bar_dot_error", "violin_box", "stat_distribution", "stat_box_jitter", "scatter", "line_scatter"}

        for p_idx, panel in enumerate(obj.get("panels", [])):
            if not isinstance(panel, dict):
                continue
            pid = str(panel.get("panel_id") or f"panel_{p_idx + 1}")
            p_meta = panel.get("meta") if isinstance(panel.get("meta"), dict) else {}
            if isinstance(p_meta.get("stat_report"), dict) and p_meta["stat_report"] not in stat_reports:
                stat_reports.append(p_meta["stat_report"])

            layers = panel.get("layers") or []
            marks_in_panel = {str(ly.get("mark", "")).lower() for ly in layers if isinstance(ly, dict)}
            has_pure_bar = bool(marks_in_panel & pure_bar_marks)
            has_dot_overlay = bool(marks_in_panel & dot_capable_marks)

            # Collect group sample sizes from series metadata or attached stat_report
            small_sample_labels: List[str] = []
            p_stat = p_meta.get("stat_report") if isinstance(p_meta.get("stat_report"), dict) else fig_meta.get("stat_report")
            if isinstance(p_stat, dict):
                for s_row in p_stat.get("summary") or []:
                    if isinstance(s_row, dict) and s_row.get("n") is not None and 0 < int(s_row["n"]) < 5:
                        small_sample_labels.append(f"{s_row.get('group', '?')} (n={int(s_row['n'])})")

            has_error_bars = False
            declared_err_type = bool(
                fig_meta.get("error_bar_type")
                or fig_meta.get("error_type")
                or p_meta.get("error_bar_type")
                or p_meta.get("error_type")
            )

            y1_lbl = str((panel.get("y1_axis") or {}).get("label") or "")
            y2_lbl = str((panel.get("y2_axis") or {}).get("label") or "")
            notes_blob = " ".join(str(x) for x in (obj.get("audit_notes") or []))
            if _ERROR_BAR_TOKEN_RE.search(f"{y1_lbl} {y2_lbl} {notes_blob}"):
                declared_err_type = True

            for ly in layers:
                if not isinstance(ly, dict):
                    continue
                ly_mark = str(ly.get("mark", "")).lower()
                st_ov = ly.get("style_overrides") if isinstance(ly.get("style_overrides"), dict) else {}
                if st_ov.get("error_type") or st_ov.get("error_bar_type"):
                    declared_err_type = True

                for s in ly.get("series") or []:
                    if not isinstance(s, dict):
                        continue
                    s_meta = s.get("meta") if isinstance(s.get("meta"), dict) else {}
                    if s_meta.get("error_type") or s_meta.get("error_bar_type"):
                        declared_err_type = True

                    y_err = s.get("y_err")
                    if isinstance(y_err, list) and any(isinstance(v, (int, float)) and abs(float(v)) > 0.0 for v in y_err):
                        has_error_bars = True
                    elif ly_mark == "bar_dot_error" and y_err is not None:
                        has_error_bars = True

                    n_val: Optional[int] = None
                    if s_meta.get("n") is not None:
                        try:
                            n_val = int(s_meta["n"])
                        except (TypeError, ValueError):
                            n_val = None
                    elif isinstance(s_meta.get("raw_points"), list):
                        n_val = len(s_meta["raw_points"])
                    if n_val is not None and 0 < n_val < 5:
                        lbl = f"{s.get('name', 'series')} (n={n_val})"
                        if lbl not in small_sample_labels:
                            small_sample_labels.append(lbl)
                    if isinstance(s_meta.get("group_ns"), list):
                        for g_idx, gn in enumerate(s_meta["group_ns"]):
                            try:
                                gni = int(gn)
                            except (TypeError, ValueError):
                                continue
                            if 0 < gni < 5:
                                small_sample_labels.append(f"group_{g_idx + 1} (n={gni})")

            if has_pure_bar and not has_dot_overlay and small_sample_labels:
                findings.append(
                    {
                        "level": "WARN_SMALL_SAMPLE_BAR_NO_DOTS",
                        "region": pid,
                        "detail": (
                            f"Small sample size ({', '.join(small_sample_labels)}) plotted as pure bars without individual "
                            "replicate points; journals (Nature/Cell/PLOS) require dot-overlaid bars ('stat_bar_dot_sig')."
                        ),
                    }
                )

            if has_error_bars and not declared_err_type:
                findings.append(
                    {
                        "level": "WARN_UNDECLARED_ERROR_BAR_TYPE",
                        "region": pid,
                        "detail": (
                            "Error bars are present without an explicit definition (SD, SEM, or 95% CI); "
                            "declare `error_bar` in config/metadata or state `(mean ± SD)` in the axis/caption."
                        ),
                    }
                )

    # Check multiple-comparison adjustment across all collected stat reports
    builtin_posthoc_tokens = ("tukey", "dunnett", "games-howell", "games_howell", "scheffe", "sidak")
    for rep in stat_reports:
        comps = rep.get("comparisons") or []
        if len(comps) >= 2:
            p_adj_method = str(rep.get("p_adjust_method") or "").strip().lower()
            all_builtin_posthoc = all(
                any(tok in str(c.get("test", "")).lower() for tok in builtin_posthoc_tokens)
                for c in comps
                if isinstance(c, dict)
            )
            if p_adj_method in ("", "none", "unadjusted", "raw") and not all_builtin_posthoc:
                findings.append(
                    {
                        "level": "WARN_UNADJUSTED_MULTIPLE_COMPARISONS",
                        "region": "Statistical_Rigor",
                        "detail": (
                            f"{len(comps)} pairwise hypothesis tests were evaluated without multiple-comparison "
                            f"correction (p_adjust_method={p_adj_method or 'none'!r}); use 'fdr_bh', 'holm', 'bonferroni', or Tukey HSD."
                        ),
                    }
                )

    return findings


def audit_survival_and_roc(payload: Any) -> List[Dict[str, str]]:
    """
    Audit clinical survival (Kaplan-Meier) and diagnostic ROC/PR payloads for statistical pitfalls:
      1. Censored-only KM arm (0 observed events -> undefined median survival & singular HR).
      2. Underpowered KM arm (< 5 total events -> unstable Greenwood log-log CI & Log-Rank approximation).
      3. Negative survival times in raw KM arm inputs.
      4. ROC single-class degeneracy (all y_true == 0 or all y_true == 1 -> undefined TPR/FPR).
      5. Small minority-class sample count (< 5 positive or negative cases) in ROC evaluation.
    """
    import numpy as np

    findings: List[Dict[str, str]] = []
    if payload is None:
        return findings

    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        obj: Dict[str, Any] = payload.to_dict()
    elif isinstance(payload, dict):
        obj = payload
    else:
        return findings

    km_arms = obj.get("arms") or obj.get("groups") or []
    if isinstance(km_arms, list):
        for idx, arm in enumerate(km_arms):
            if not isinstance(arm, dict):
                continue
            has_km_keys = ("event" in arm) or ("n_events" in arm) or ("censored_time" in arm)
            if not has_km_keys:
                continue
            arm_name = str(arm.get("name") or f"Arm_{idx + 1}")

            if arm.get("time") is not None and "event" in arm:
                t_arr = np.asarray(arm["time"], dtype=float).ravel()
                t_fin = t_arr[np.isfinite(t_arr)]
                if t_fin.size > 0 and np.any(t_fin < 0.0):
                    findings.append(
                        {
                            "level": "ERROR_KM_NEGATIVE_TIME",
                            "region": arm_name,
                            "detail": f"Survival arm '{arm_name}' contains negative follow-up time(s).",
                        }
                    )

            n_events: Optional[int] = None
            if arm.get("n_events") is not None:
                n_events = int(arm["n_events"])
            elif arm.get("event") is not None:
                ev_arr = np.asarray(arm["event"], dtype=float).ravel()
                ev_fin = ev_arr[np.isfinite(ev_arr)]
                n_events = int(np.sum(ev_fin == 1.0))

            if n_events is not None:
                if n_events == 0:
                    findings.append(
                        {
                            "level": "ERROR_KM_CENSORED_ONLY_ARM",
                            "region": arm_name,
                            "detail": (
                                f"Kaplan-Meier arm '{arm_name}' has 0 observed events (100% right-censored); "
                                "median survival and Pike hazard ratio are undefined."
                            ),
                        }
                    )
                elif 0 < n_events < 5:
                    findings.append(
                        {
                            "level": "WARN_KM_LOW_EVENTS",
                            "region": arm_name,
                            "detail": (
                                f"Kaplan-Meier arm '{arm_name}' has only {n_events} observed event(s) (< 5); "
                                "Greenwood 95% CIs and asymptotic Mantel-Cox Log-Rank p-values have low power."
                            ),
                        }
                    )

    roc_items: List[Dict[str, Any]] = []
    if isinstance(obj.get("models"), list):
        roc_items.extend(it for it in obj["models"] if isinstance(it, dict))
    if isinstance(obj.get("curves"), list):
        roc_items.extend(it for it in obj["curves"] if isinstance(it, dict))
    if "y_true" in obj and ("y_score" in obj or "fpr" in obj):
        roc_items.append(obj)

    for idx, mdl in enumerate(roc_items):
        mdl_name = str(mdl.get("name") or f"Model_{idx + 1}")
        n_pos: Optional[int] = None
        n_neg: Optional[int] = None

        if mdl.get("y_true") is not None:
            yt = np.asarray(mdl["y_true"], dtype=float).ravel()
            yt_fin = yt[np.isfinite(yt)]
            n_pos = int(np.sum(yt_fin == 1.0))
            n_neg = int(np.sum(yt_fin == 0.0))
            uniq = np.unique(yt_fin)
            if uniq.size < 2 or n_pos == 0 or n_neg == 0:
                findings.append(
                    {
                        "level": "ERROR_ROC_SINGLE_CLASS",
                        "region": mdl_name,
                        "detail": (
                            f"ROC model '{mdl_name}' exhibits single-class degeneracy "
                            f"(n_pos={n_pos}, n_neg={n_neg}); both positive and negative cases are required."
                        ),
                    }
                )
                continue
        elif mdl.get("n_pos") is not None and mdl.get("n_neg") is not None:
            n_pos = int(mdl["n_pos"])
            n_neg = int(mdl["n_neg"])
            if n_pos <= 0 or n_neg <= 0:
                findings.append(
                    {
                        "level": "ERROR_ROC_SINGLE_CLASS",
                        "region": mdl_name,
                        "detail": (
                            f"ROC model '{mdl_name}' has non-positive class count "
                            f"(n_pos={n_pos}, n_neg={n_neg}); ROC curve is degenerate."
                        ),
                    }
                )
                continue

        if n_pos is not None and n_neg is not None and min(n_pos, n_neg) < 5:
            findings.append(
                {
                    "level": "WARN_ROC_SMALL_CLASS_COUNT",
                    "region": mdl_name,
                    "detail": (
                        f"ROC model '{mdl_name}' has < 5 samples in minority class "
                        f"(n_pos={n_pos}, n_neg={n_neg}); Hanley-McNeil analytic CI may be coarse."
                    ),
                }
            )

    return findings
