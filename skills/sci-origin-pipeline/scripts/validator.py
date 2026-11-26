from __future__ import annotations

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
