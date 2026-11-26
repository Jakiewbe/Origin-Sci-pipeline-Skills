from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks

_TRAPZ = getattr(np, "trapezoid", getattr(np, "trapz", None))


def linear_baseline(x: np.ndarray, y: np.ndarray, edge_pts: int = 6) -> np.ndarray:
    """Endpoint-averaged linear background."""
    k = max(1, min(edge_pts, len(y) // 6))
    x0, y0 = float(np.mean(x[:k])), float(np.mean(y[:k]))
    x1, y1 = float(np.mean(x[-k:])), float(np.mean(y[-k:]))
    if abs(x1 - x0) < 1e-12:
        return np.full_like(y, y0)
    slope = (y1 - y0) / (x1 - x0)
    return y0 + slope * (x - x0)


def shirley_baseline(x: np.ndarray, y: np.ndarray, edge_pts: int = 6, max_iter: int = 80, tol: float = 1e-6) -> np.ndarray:
    """Iterative Shirley step background for XPS core-level spectra (assumes x sorted ascending in BE)."""
    k = max(1, min(edge_pts, len(y) // 6))
    y_low = float(np.mean(y[:k]))
    y_high = float(np.mean(y[-k:]))

    bg = np.linspace(y_low, y_high, len(y))
    dx = np.gradient(x)

    for _ in range(max_iter):
        net = np.maximum(y - bg, 0.0)
        total_area = float(np.sum(net * dx))
        if total_area <= 1e-12:
            break
        cum_area = np.cumsum(net * dx)
        bg_new = y_low + (y_high - y_low) * (cum_area / total_area)
        if np.max(np.abs(bg_new - bg)) < tol * max(abs(y_high - y_low), 1.0):
            bg = bg_new
            break
        bg = bg_new
    return bg


def pseudo_voigt_area(x: np.ndarray, area: float, center: float, fwhm: float, eta: float) -> np.ndarray:
    """Area-normalized Pseudo-Voigt profile: integral over (-inf, +inf) equals `area`."""
    w = max(fwhm, 1e-6)
    sigma = w / (2.0 * np.sqrt(2.0 * np.log(2.0)))
    gauss = (1.0 / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    gamma = 0.5 * w
    lorentz = (1.0 / np.pi) * (gamma / ((x - center) ** 2 + gamma ** 2))
    return area * ((1.0 - eta) * gauss + eta * lorentz)


def auto_estimate_xps_charge_shift(
    x: np.ndarray,
    y: np.ndarray,
    target_eV: float = 284.8,
    search_window: Tuple[float, float] = (283.4, 286.0),
    fallback_target_eV: Optional[float] = None,
    fallback_window: Tuple[float, float] = (286.8, 293.5),
) -> Tuple[float, str]:
    """
    Safe XPS charge-shift estimator:
    1) Rejects flat or noise-only spectra (zero dynamic span or overall SNR < 3.5) with 0.0 eV shift.
    2) Uses primary anchor (C-C/C=C at target_eV) when prominence in search_window >= 8% of dynamic range and above noise.
    3) Uses secondary fallback ONLY when explicitly passed via fallback_target_eV AND a true peak >= 3.5*noise exists inside fallback_window.
    """
    if len(y) < 8 or float(np.ptp(y)) <= 1e-9:
        return 0.0, "FLAT_SPECTRUM_SHIFT_ZERO"

    bg_full = linear_baseline(x, y)
    net_full = np.maximum(y - bg_full, 0.0)
    dy_noise = float(np.std(np.diff(y)) / 1.4142) if len(y) > 5 else 0.0
    max_net = float(np.max(net_full))
    if max_net <= 1e-9 or (dy_noise > 0.0 and (max_net / dy_noise) < 3.5):
        return 0.0, "LOW_SNR_NOISE_SPECTRUM_SHIFT_ZERO"

    full_span = max_net
    noise_floor = max(3.5 * dy_noise, 1e-9)

    mask_cc = (x >= search_window[0]) & (x <= search_window[1])
    if np.sum(mask_cc) >= 5:
        xw, nw = x[mask_cc], net_full[mask_cc]
        prom_min = max(0.03 * full_span, 2.0 * dy_noise)
        peaks, _ = find_peaks(nw, distance=3, prominence=prom_min)
        if len(peaks) > 0:
            best_pk = int(peaks[int(np.argmax(nw[peaks]))])
            if float(nw[best_pk]) >= max(0.08 * full_span, noise_floor):
                obs_eV = float(xw[best_pk])
                shift = float(np.clip(target_eV - obs_eV, -3.5, 3.5))
                return shift, f"PrimaryAnchor({obs_eV:.2f}->{target_eV:.2f}eV)"

    # Optional secondary anchor ONLY when explicitly provided by caller/preset AND an interior peak exists (never window-edge tail)
    if fallback_target_eV is not None:
        mask_fb = (x >= fallback_window[0]) & (x <= fallback_window[1])
        if np.sum(mask_fb) >= 5:
            xfb, nfb = x[mask_fb], net_full[mask_fb]
            prom_fb = max(0.03 * full_span, 2.0 * dy_noise)
            peaks_fb, _ = find_peaks(nfb, distance=3, prominence=prom_fb)
            if len(peaks_fb) > 0:
                best_fb = int(peaks_fb[int(np.argmax(nfb[peaks_fb]))])
                if float(nfb[best_fb]) >= max(0.08 * full_span, noise_floor):
                    obs_fb = float(xfb[best_fb])
                    shift = float(np.clip(float(fallback_target_eV) - obs_fb, -4.0, 4.0))
                    return shift, f"FALLBACK_Anchor({obs_fb:.2f}->{float(fallback_target_eV):.2f}eV, weak_primary)"

    return 0.0, "NO_INTERIOR_ANCHOR_PEAK_SHIFT_ZERO"


def deconvolve_spectrum(
    x_raw: np.ndarray,
    y_raw: np.ndarray,
    region_preset: Dict[str, Any],
    charge_shift_eV: float = 0.0,
    laser_nm: float = 532.0,
) -> Dict[str, Any]:
    """
    Run constrained baseline subtraction + Pseudo-Voigt multi-peak fitting with
    intra-shell FWHM coherence regularization to prevent overlapped broad-peak cannibalization.
    """
    x_shifted = x_raw + charge_shift_eV
    win_min, win_max = region_preset["x_window"]
    mask = (x_shifted >= min(win_min, win_max)) & (x_shifted <= max(win_min, win_max))
    if np.sum(mask) < 12:
        raise ValueError(f"Spectrum has fewer than 12 points inside window [{win_min}, {win_max}]")

    x = x_shifted[mask]
    y = y_raw[mask]
    order = np.argsort(x)
    x, y = x[order], y[order]

    bg_type = region_preset.get("baseline", "linear").lower()
    bg = shirley_baseline(x, y) if bg_type == "shirley" else linear_baseline(x, y)

    net_y = y - bg
    net_span = max(float(np.max(net_y) - np.min(net_y)), 1e-6)
    total_pos_area = max(float(_TRAPZ(np.maximum(net_y, 0.0), x)), 1e-6)

    comps_cfg = region_preset["components"]
    n_comp = len(comps_cfg)

    p0: List[float] = []
    lb: List[float] = []
    ub: List[float] = []
    etas: List[float] = []
    nominal_fwhms: List[float] = []

    for c in comps_cfg:
        c0 = float(c["center"])
        cb_min, cb_max = float(c["center_bounds"][0]), float(c["center_bounds"][1])
        w0 = float(c["fwhm"])
        wb_min, wb_max = float(c["fwhm_bounds"][0]), float(c["fwhm_bounds"][1])
        eta = float(c.get("eta", 0.25))
        etas.append(eta)
        nominal_fwhms.append(w0)

        idx_near = int(np.argmin(np.abs(x - c0)))
        local_h = max(float(net_y[idx_near]), 0.02 * float(np.max(net_y)))
        a0 = max(local_h * w0 * 1.06, 1e-4 * total_pos_area)

        p0.extend([a0, np.clip(c0, cb_min, cb_max), np.clip(w0, wb_min, wb_max)])
        lb.extend([0.0, cb_min, wb_min])
        ub.extend([total_pos_area * 3.0, cb_max, wb_max])

    # Physical FWHM coherence regularization: prevents minor/overlapped shoulders from bloating into fake baseline pads
    reg_strength = float(region_preset.get("fwhm_reg_strength", 0.035 if n_comp >= 3 else 0.0))
    max_rel_spread = float(region_preset.get("max_fwhm_rel_spread", 0.28))
    nom_w_arr = np.asarray(nominal_fwhms, dtype=float)

    def residuals_fn(params: np.ndarray) -> np.ndarray:
        model = np.zeros_like(x)
        fwhm_vec = np.empty(n_comp, dtype=float)
        for i in range(n_comp):
            area_i, cen_i, fwhm_i = params[3 * i : 3 * i + 3]
            fwhm_vec[i] = fwhm_i
            model += pseudo_voigt_area(x, area_i, cen_i, fwhm_i, etas[i])
        data_res = model - net_y
        if reg_strength <= 0.0 or n_comp < 2:
            return data_res

        # 1) Gentle prior anchoring each FWHM near its physical nominal width
        prior_pen = (reg_strength * net_span) * ((fwhm_vec - nom_w_arr) / nom_w_arr)
        # 2) Soft coherence penalty when a component's FWHM/nominal ratio deviates > max_rel_spread from shell median
        ratios = fwhm_vec / nom_w_arr
        med_r = float(np.median(ratios))
        excess = np.maximum(np.abs(ratios - med_r) - max_rel_spread, 0.0)
        coherence_pen = (reg_strength * 3.0 * net_span) * excess
        return np.concatenate([data_res, prior_pen, coherence_pen])

    res = least_squares(residuals_fn, np.asarray(p0), bounds=(np.asarray(lb), np.asarray(ub)), max_nfev=6000)
    popt = res.x

    comp_curves_net: List[np.ndarray] = []
    comp_curves_with_bg: List[np.ndarray] = []
    comp_metrics: List[Dict[str, Any]] = []
    integrated_areas: List[float] = []

    for i, c in enumerate(comps_cfg):
        area_param, cen_i, fwhm_i = popt[3 * i : 3 * i + 3]
        curve_net = pseudo_voigt_area(x, float(area_param), float(cen_i), float(fwhm_i), etas[i])
        win_area = float(_TRAPZ(curve_net, x))
        peak_h = float(np.max(curve_net))
        comp_curves_net.append(curve_net)
        comp_curves_with_bg.append(bg + curve_net)
        integrated_areas.append(win_area)
        comp_metrics.append(
            {
                "name": c["name"],
                "label": c.get("label", c["name"]),
                "color": c.get("color", "#2E5B88"),
                "center": float(cen_i),
                "fwhm": float(fwhm_i),
                "eta": etas[i],
                "height": peak_h,
                "area": win_area,
                "in_subgroup": bool(c.get("in_subgroup", False)),
                "note": c.get("note", ""),
            }
        )

    sum_area = max(sum(integrated_areas), 1e-12)
    subgroup_area = sum(m["area"] for m in comp_metrics if m["in_subgroup"])

    for m in comp_metrics:
        m["area_pct"] = 100.0 * m["area"] / sum_area
        m["subgroup_pct"] = (100.0 * m["area"] / subgroup_area) if (m["in_subgroup"] and subgroup_area > 0) else None

    net_fit = np.sum(comp_curves_net, axis=0) if comp_curves_net else np.zeros_like(x)
    total_fit = bg + net_fit
    resid = y - total_fit
    dyn_range = max(float(np.max(y) - np.min(y)), 1e-9)
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    nrmse_pct = 100.0 * rmse / dyn_range
    ss_res = float(np.sum(resid ** 2))
    ss_tot = max(float(np.sum((y - np.mean(y)) ** 2)), 1e-12)
    r_squared = 1.0 - ss_res / ss_tot

    extra_ratios: Dict[str, float] = {}
    by_name = {m["name"]: m for m in comp_metrics}
    if "D" in by_name and "G" in by_name and by_name["G"]["area"] > 0 and by_name["G"]["height"] > 0:
        ad_ag = by_name["D"]["area"] / by_name["G"]["area"]
        hd_hg = by_name["D"]["height"] / by_name["G"]["height"]
        idx_d = int(np.argmin(np.abs(x - by_name["D"]["center"])))
        idx_g = int(np.argmin(np.abs(x - by_name["G"]["center"])))
        id_ig_raw = float(net_y[idx_d] / max(net_y[idx_g], 1e-9))
        la_nm = (2.4e-10 * (laser_nm ** 4)) / max(ad_ag, 1e-6)
        extra_ratios = {
            "I_D_I_G_raw_net": id_ig_raw,
            "H_D_H_G_deconv": hd_hg,
            "A_D_A_G_area": ad_ag,
            "La_nm": la_nm,
        }

    return {
        "x": x,
        "y_raw": y,
        "baseline": bg,
        "y_fit": total_fit,
        "residuals": resid,
        "comp_curves_net": comp_curves_net,
        "comp_curves_with_bg": comp_curves_with_bg,
        "components": comp_metrics,
        "charge_shift_eV": float(charge_shift_eV),
        "nrmse_pct": nrmse_pct,
        "r_squared": r_squared,
        "subgroup_name": region_preset.get("subgroup_name"),
        "invert_x": bool(region_preset.get("invert_x", False)),
        "x_label": region_preset.get("x_label", "X"),
        "y_label": region_preset.get("y_label", "Intensity (a.u.)"),
        "extra_ratios": extra_ratios,
    }


def aggregate_replicate_deconvolutions(
    replicate_items: List[Tuple[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    """Aggregate 1..N spot replicates: compute Mean ± SD and select closest representative spot."""
    n_rep = len(replicate_items)
    ddof = 1 if n_rep > 1 else 0
    comp_names = [m["name"] for m in replicate_items[0][1]["components"]]

    area_mat = np.array([[m["area_pct"] for m in fit["components"]] for _, fit in replicate_items], dtype=float)
    mean_area = np.mean(area_mat, axis=0)
    sd_area = np.std(area_mat, axis=0, ddof=ddof)

    dists = np.linalg.norm(area_mat - mean_area[None, :], axis=1)
    rep_idx = int(np.argmin(dists))
    rep_file_label, rep_fit = replicate_items[rep_idx]

    ratio_keys = list(rep_fit.get("extra_ratios", {}).keys())
    ratio_stats: Dict[str, Dict[str, float]] = {}
    for rk in ratio_keys:
        vals = np.array([fit["extra_ratios"][rk] for _, fit in replicate_items], dtype=float)
        ratio_stats[rk] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals, ddof=ddof))}

    comp_stats: Dict[str, Dict[str, Optional[float]]] = {}
    for c_i, cname in enumerate(comp_names):
        sub_vals = [fit["components"][c_i]["subgroup_pct"] for _, fit in replicate_items]
        has_sub = all(v is not None for v in sub_vals)
        cen_vals = np.array([fit["components"][c_i]["center"] for _, fit in replicate_items], dtype=float)
        fwhm_vals = np.array([fit["components"][c_i]["fwhm"] for _, fit in replicate_items], dtype=float)
        comp_stats[cname] = {
            "area_pct_mean": float(mean_area[c_i]),
            "area_pct_sd": float(sd_area[c_i]),
            "subgroup_pct_mean": float(np.mean(sub_vals)) if has_sub else None,
            "subgroup_pct_sd": float(np.std(sub_vals, ddof=ddof)) if has_sub else None,
            "center_mean": float(np.mean(cen_vals)),
            "fwhm_mean": float(np.mean(fwhm_vals)),
        }

    return {
        "n_replicates": n_rep,
        "representative_index": rep_idx,
        "representative_source": rep_file_label,
        "representative_fit": rep_fit,
        "component_stats": comp_stats,
        "ratio_stats": ratio_stats,
    }


def analyze_xrd_features(
    x_2theta: np.ndarray,
    y_counts: np.ndarray,
    markers: List[Dict[str, Any]],
    wavelength_angstrom: float = 1.5406,
    window_deg: float = 1.5,
) -> List[Dict[str, Any]]:
    results = []
    bg = linear_baseline(x_2theta, y_counts, edge_pts=10)
    net = np.maximum(y_counts - bg, 0.0)
    max_net = max(float(np.max(net)), 1.0)

    for mk in markers:
        pos0 = float(mk["pos"])
        mask = (x_2theta >= pos0 - window_deg) & (x_2theta <= pos0 + window_deg)
        if np.sum(mask) < 3:
            continue
        xw, nw = x_2theta[mask], net[mask]
        idx = int(np.argmax(nw))
        two_theta = float(xw[idx])
        theta_rad = np.radians(two_theta / 2.0)
        d_angstrom = float(wavelength_angstrom / (2.0 * np.sin(theta_rad))) if theta_rad > 1e-6 else np.nan
        results.append(
            {
                "marker_label": mk["label"],
                "nominal_2theta_deg": pos0,
                "observed_2theta_deg": two_theta,
                "d_spacing_A": d_angstrom,
                "net_intensity": float(nw[idx]),
                "rel_intensity_pct": 100.0 * float(nw[idx]) / max_net,
            }
        )
    return results


def analyze_epr_derivative(x: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
    edge = max(5, len(y) // 12)
    dc_offset = 0.5 * (float(np.median(y[:edge])) + float(np.median(y[-edge:])))
    y_corr = y - dc_offset

    idx_max = int(np.argmax(y_corr))
    idx_min = int(np.argmin(y_corr))
    lo, hi = min(idx_max, idx_min), max(idx_max, idx_min)

    x_zero = float(0.5 * (x[idx_max] + x[idx_min]))
    if hi > lo:
        seg_x = x[lo : hi + 1]
        seg_y = y_corr[lo : hi + 1]
        sign_changes = np.where(np.diff(np.signbit(seg_y)))[0]
        if len(sign_changes) > 0:
            k = int(sign_changes[len(sign_changes) // 2])
            y0, y1 = float(seg_y[k]), float(seg_y[k + 1])
            if abs(y1 - y0) > 1e-15:
                x_zero = float(seg_x[k] - y0 * (seg_x[k + 1] - seg_x[k]) / (y1 - y0))

    return {
        "y_corrected": y_corr,
        "center_zero_crossing": x_zero,
        "x_peak_pos": float(x[idx_max]),
        "x_peak_neg": float(x[idx_min]),
        "peak_to_peak_width": float(abs(x[idx_min] - x[idx_max])),
        "peak_to_peak_amplitude": float(y_corr[idx_max] - y_corr[idx_min]),
    }
