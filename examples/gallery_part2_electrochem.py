"""
gallery_part2_electrochem.py - 100% Analytical Electrochemistry, Impedance & Operando 2D Gallery (Part 2).

Renders 7 publication-grade showcase figures directly in headless OriginPro 2024:
  1. demo_hero_composite_2x2.jpg      - 2x2 Multi-Modal Master Figure (Deconv + Diffraction Stack + Rate Q-V + 4:3 Isometric Nyquist)
  2. demo_rate_galvanostatic.jpg      - 7-rate galvanostatic discharge profiles (0.1 C .. 10 C, deep_blue_to_red)
  3. demo_dqdv_coupled.jpg            - 1x2 coupled charge/discharge Q-V + smoothed dQ/dV redox peaks
  4. demo_pulse_align.jpg             - Zero-aligned short-pulse transients across 6 rates + Delta V_0 & Delta V_slow spans
  5. demo_ragone_loglog.jpg           - Log10-Log10 Ragone energy vs power density across 4 electrode architectures
  6. demo_bode_dual_panel.jpg         - Shared-Log10-frequency 2-layer EIS Bode plot (|Z| & -Phase)
  7. demo_operando_contour_side.jpg   - 2D operando pseudocolor field coupled with synchronized right-hand voltage profile

Zero external or private datasets are read; every curve and 2D field is computed from closed-form equations.
"""
from __future__ import annotations

import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "sci-origin-pipeline" / "scripts"
GALLERY_DIR = REPO_ROOT / "assets" / "gallery"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import chart_grammar as cg  # noqa: E402
import origin_builder as ob  # noqa: E402
import origin_renderer as ornd  # noqa: E402
import origin_theme as ot  # noqa: E402


# ---------------------------------------------------------------------------
# Mathematical / Analytical Curve Generators
# ---------------------------------------------------------------------------


def _pseudo_voigt(x: np.ndarray, center: float, fwhm: float, height: float, eta: float = 0.35) -> np.ndarray:
    """Analytical Pseudo-Voigt peak profile (weighted Gaussian + Lorentzian)."""
    half_w = max(fwhm * 0.5, 1e-6)
    sigma = fwhm / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    gauss = np.exp(-0.5 * ((x - center) / sigma) ** 2)
    lorentz = 1.0 / (1.0 + ((x - center) / half_w) ** 2)
    return height * ((1.0 - eta) * gauss + eta * lorentz)


def _galvanostatic_discharge_curve(
    q_max: float,
    ir_drop: float,
    polar_scale: float,
    n_pts: int = 180,
) -> Tuple[List[float], List[float]]:
    """
    Strictly monotonically decreasing two-stage galvanostatic discharge profile (`dV/dQ < 0` everywhere)
    with crisp upper-to-lower plateau inflection and Nernstian depletion knee terminating at 1.50 V.
    """
    soc = np.linspace(0.0, 1.0, n_pts)
    q = soc * q_max
    v_surf = 0.26 * np.exp(-soc / 0.045)
    v_inflect = 0.44 / (1.0 + np.exp((soc - 0.34) / 0.065))
    slope = 0.14 + 0.10 * polar_scale
    v_base = 2.22 - slope * soc - ir_drop
    v_end_no_knee = (2.22 - slope - ir_drop) + float(v_surf[-1]) + float(v_inflect[-1])
    knee_amp = max(0.10, v_end_no_knee - 1.50)
    v = v_base + v_surf + v_inflect - knee_amp * (soc ** 9.5)
    return np.round(q, 3).tolist(), np.round(v, 4).tolist()


def _randles_warburg_eis(
    freqs: np.ndarray,
    rs: float,
    rct: float,
    cdl: float,
    sigma_w: float,
    c_lim: float | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Closed-form modified Randles-Warburg impedance returning (Z', -Z'', |Z|, -Phase_deg)."""
    omega = 2.0 * np.pi * freqs
    z_faradaic = rct + sigma_w * (1.0 - 1j) / np.sqrt(omega)
    z_tot = rs + 1.0 / (1j * omega * cdl + 1.0 / z_faradaic)
    if c_lim is not None and c_lim > 0.0:
        z_tot = z_tot - 1j / (omega * c_lim)
    zr = z_tot.real
    nzi = -z_tot.imag
    z_mag = np.abs(z_tot)
    neg_phase = np.degrees(np.arctan2(-z_tot.imag, z_tot.real))
    return zr, nzi, z_mag, neg_phase


# ---------------------------------------------------------------------------
# 1. Flagship 2x2 Multi-Modal Master Figure (demo_hero_composite_2x2.jpg)
# ---------------------------------------------------------------------------


def _build_hero_composite_panels() -> List[Dict[str, Any]]:
    """Construct the 4 multi-modal analytical panel payloads for `build_composite_opju`."""
    # (a) Synthetic 3-component Pseudo-Voigt spectrum + Shirley background + envelope
    rng = np.random.default_rng(2026)
    be_x = np.linspace(282.0, 293.0, 220)
    c1 = _pseudo_voigt(be_x, 284.80, 1.22, 1.00, eta=0.28)
    c2 = _pseudo_voigt(be_x, 286.45, 1.38, 0.52, eta=0.34)
    c3 = _pseudo_voigt(be_x, 288.55, 1.48, 0.30, eta=0.36)
    pure_sum = c1 + c2 + c3
    cum_area = np.cumsum(pure_sum)
    shirley_bg = 0.08 + 0.15 * (cum_area / max(float(cum_area[-1]), 1e-9))
    y_fit = shirley_bg + pure_sum
    y_raw = y_fit + rng.normal(0.0, 0.013, size=be_x.size)

    areas = [float(np.trapezoid(c, be_x)) for c in (c1, c2, c3)]
    tot_a = max(sum(areas), 1e-9)
    comp_defs = [
        ("Peak1", "C-C", "#3E86DE", c1, 100.0 * areas[0] / tot_a),
        ("Peak2", "C-O", "#6579BE", c2, 100.0 * areas[1] / tot_a),
        ("Peak3", "C=O", "#D84B5C", c3, 100.0 * areas[2] / tot_a),
    ]
    fit_result = {
        "x": be_x,
        "y_raw": y_raw,
        "baseline": shirley_bg,
        "y_fit": y_fit,
        "residuals": y_raw - y_fit,
        "invert_x": True,
        "x_label": "Binding Energy (eV)",
        "components": [
            {"name": nm, "label": lbl, "color": col, "area_pct": round(ap, 2)}
            for nm, lbl, col, _, ap in comp_defs
        ],
        "comp_curves_with_bg": [shirley_bg + arr for _, _, _, arr, _ in comp_defs],
    }

    # (b) 4-state synthetic diffraction stack (left zone 10..31 deg kept flat for upper-left legend)
    two_theta = np.linspace(10.0, 80.0, 520)
    wf_colors = ot.resolve_series_colors(4, scheme="sequential_blue_red")
    wf_curves: List[Dict[str, Any]] = []
    for idx in range(4):
        frac = idx / 3.0
        p_main = _pseudo_voigt(two_theta, 35.2 - 0.85 * frac, 1.20 + 0.16 * frac, 1.00 - 0.10 * frac, eta=0.45)
        p_sec = _pseudo_voigt(two_theta, 47.8 - 0.45 * frac, 1.40, 0.50 + 0.14 * frac, eta=0.40)
        p_third = _pseudo_voigt(two_theta, 59.4 - 0.35 * frac, 1.55, 0.32 + 0.10 * frac, eta=0.40)
        p_fourth = _pseudo_voigt(two_theta, 70.6 - 0.30 * frac, 1.65, 0.24 + 0.06 * frac, eta=0.40)
        bg_line = 0.03 * np.exp(-(two_theta - 10.0) / 40.0)
        y_stack = bg_line + p_main + p_sec + p_third + p_fourth + idx * 1.18
        wf_curves.append(
            {
                "name": f"State {idx + 1}",
                "x": two_theta,
                "y_offset": y_stack,
                "color": wf_colors[idx],
            }
        )

    # (c) Multi-rate galvanostatic discharge profiles (0.1 C .. 10 C in deep_blue_to_red)
    hero_rate_defs = [
        ("0.1 C", 316.0, 0.02, 0.00, "#08306B"),
        ("0.5 C", 278.0, 0.09, 0.25, "#2171B5"),
        ("1 C", 248.0, 0.15, 0.45, "#6579BE"),
        ("2 C", 214.0, 0.22, 0.65, "#D97B8D"),
        ("5 C", 174.0, 0.30, 0.82, "#D84B5C"),
        ("10 C", 132.0, 0.38, 1.00, "#A02333"),
    ]
    rate_series: List[Dict[str, Any]] = []
    for r_lbl, q_m, ir_d, pl_s, col_hex in hero_rate_defs:
        qx, vy = _galvanostatic_discharge_curve(q_m, ir_d, pl_s, n_pts=160)
        rate_series.append({"name": r_lbl, "x": qx, "y": vy, "color": col_hex})

    # (d) Isometric 1 Ohm = 1 Ohm Nyquist curves inside standard 4:3 [0..600, 0..450] Ohm frame
    freqs_nyq = np.logspace(5.0, -1.2, 40)
    nyq_defs = [
        ("Sample 1", 18.0, 215.0, 1.8e-5, 95.0, 0.032, "#2B6CB0"),
        ("Sample 2", 14.0, 148.0, 2.2e-5, 76.0, 0.038, "#D84B5C"),
        ("Sample 3", 11.0, 96.0, 2.6e-5, 58.0, 0.046, "#6579BE"),
    ]
    eis_series: List[Dict[str, Any]] = []
    for nm, rs, rct, cdl, sw, clim, c_hex in nyq_defs:
        zr, nzi, _, _ = _randles_warburg_eis(freqs_nyq, rs, rct, cdl, sw, c_lim=clim)
        eis_series.append(
            {
                "name": nm,
                "freq_Hz": freqs_nyq,
                "z_real": zr,
                "neg_z_imag": nzi,
                "color": c_hex,
            }
        )

    return [
        {
            "panel_id": "SpectrumDeconv",
            "panel_type": "deconvolve",
            "fit_result": fit_result,
        },
        {
            "panel_id": "DiffractionStack",
            "panel_type": "waterfall",
            "x_label": "2theta (deg.)",
            "y_label": "Intensity (a.u.)",
            "invert_x": False,
            "processed_curves": wf_curves,
        },
        {
            "panel_id": "RateGalvanostatic",
            "panel_type": "xy_series",
            "x_label": "Specific Capacity (mAh g^-1)",
            "y_label": "Voltage (V)",
            "series_list": rate_series,
        },
        {
            "panel_id": "NyquistImpedance",
            "panel_type": "nyquist",
            "add_hf_inset": False,
            "eis_series": eis_series,
        },
    ]


# ---------------------------------------------------------------------------
# 2..7. Declarative Electrochemistry, EIS Bode & Operando 2D FigureSpecs
# ---------------------------------------------------------------------------


def _make_rate_galvanostatic_spec() -> cg.FigureSpec:
    """7-rate constant-current discharge voltage profiles (`0.1 C..10 C`) in `deep_blue_to_red`."""
    rate_defs = [
        ("0.1 C", 318.0, 0.02, 0.00),
        ("0.2 C", 302.0, 0.05, 0.14),
        ("0.5 C", 282.0, 0.09, 0.28),
        ("1 C", 258.0, 0.15, 0.45),
        ("2 C", 228.0, 0.22, 0.62),
        ("5 C", 186.0, 0.30, 0.82),
        ("10 C", 142.0, 0.38, 1.00),
    ]
    series_list: List[cg.SeriesSpec] = []
    for (r_lbl, q_m, ir_d, pl_s), c_hex in zip(rate_defs, ot.DEEP_BLUE_TO_RED_STOPS):
        qx, vy = _galvanostatic_discharge_curve(q_m, ir_d, pl_s, n_pts=180)
        series_list.append(
            cg.SeriesSpec(
                name=r_lbl,
                x=qx,
                y=vy,
                color=c_hex,
                line_style="solid",
                line_width_pt=3.0,
                marker_style="none",
            )
        )

    panel = cg.PanelSpec(
        panel_id="rate_discharge",
        legend_style="corner_upper_right",
        x_axis=cg.AxisSpec(
            which="x",
            label="Specific Capacity (mAh g^-1)",
            axis_kind="quantitative",
            limits=(0.0, 350.0),
            major_step=70.0,
        ),
        y1_axis=cg.AxisSpec(
            which="y1",
            label="Voltage (V)",
            axis_kind="quantitative",
            limits=(1.4, 3.85),
            major_step=0.5,
        ),
        layers=[
            cg.LayerSpec(
                layer_id="rate_curves",
                mark="line_scatter",
                color_scheme="deep_blue_to_red",
                series=series_list,
            )
        ],
    )
    return cg.FigureSpec(
        title="demo_rate_galvanostatic",
        mode="chart_grammar",
        style_preset="style_publication_minimal",
        build_opju=False,
        panels=[panel],
    )


def _make_dqdv_coupled_spec() -> cg.FigureSpec:
    """1x2 coupled charge/discharge Q-V profile + smoothed differential capacity `dQ/dV` redox peaks."""
    v_grid = np.linspace(2.55, 4.35, 360)

    # Analytical anodic (charge > 0) and cathodic (discharge < 0) differential capacity peaks
    dqdv_chg = (
        18.0
        + _pseudo_voigt(v_grid, 3.45, 0.16, 315.0, eta=0.25)
        + _pseudo_voigt(v_grid, 3.92, 0.18, 250.0, eta=0.25)
    )
    dqdv_dis = -(
        18.0
        + _pseudo_voigt(v_grid, 3.35, 0.17, 290.0, eta=0.25)
        + _pseudo_voigt(v_grid, 3.82, 0.19, 232.0, eta=0.25)
    )

    # Integrate dQ/dV analytically so Q(V) and dQ/dV(V) are 100% thermodynamically self-consistent!
    dv = float(v_grid[1] - v_grid[0])
    q_chg = np.cumsum(dqdv_chg) * dv
    q_chg = q_chg - float(q_chg[0])

    v_dis_desc = v_grid[::-1]
    dqdv_dis_mag = -dqdv_dis[::-1]
    q_dis = np.cumsum(dqdv_dis_mag) * dv
    q_dis = q_dis - float(q_dis[0])

    cfg = {
        "mode": "electrochem_kinetics",
        "subtype": "galvanostatic_dqdv",
        "style_preset": "style_publication_minimal",
        "title": "demo_dqdv_coupled",
        "build_opju": False,
        "x_label": "Specific Capacity (mAh g^-1)",
        "y_label": "Voltage (V)",
        "dqdv_x_label": "Voltage (V)",
        "dqdv_y_label": "dQ/dV (mAh g^-1 V^-1)",
        "series": [
            {
                "name": "Charge",
                "x": np.round(q_chg, 3).tolist(),
                "y": np.round(v_grid, 4).tolist(),
                "color": "#2B6CB0",
            },
            {
                "name": "Discharge",
                "x": np.round(q_dis, 3).tolist(),
                "y": np.round(v_dis_desc, 4).tolist(),
                "color": "#D84B5C",
            },
        ],
        "dqdv_series": [
            {
                "name": "Charge",
                "x": np.round(v_grid, 4).tolist(),
                "y": np.round(dqdv_chg, 3).tolist(),
                "color": "#2B6CB0",
            },
            {
                "name": "Discharge",
                "x": np.round(v_grid, 4).tolist(),
                "y": np.round(dqdv_dis, 3).tolist(),
                "color": "#D84B5C",
            },
        ],
        "dqdv_guides": [
            {
                "kind": "hline",
                "value": 0.0,
                "label": "",
                "color": "#666666",
                "line_style": "dotted",
                "line_width_pt": 1.3,
            },
            {
                "kind": "vline",
                "value": 3.45,
                "label": "3.45 V",
                "color": "#2B6CB0",
                "line_style": "dashed",
                "label_side": "right",
                "shoulder_y_frac": 0.88,
                "font_size_pt": 12.5,
            },
            {
                "kind": "vline",
                "value": 3.92,
                "label": "3.92 V",
                "color": "#2B6CB0",
                "line_style": "dashed",
                "label_side": "right",
                "shoulder_y_frac": 0.88,
                "font_size_pt": 12.5,
            },
            {
                "kind": "vline",
                "value": 3.35,
                "label": "3.35 V",
                "color": "#D84B5C",
                "line_style": "dashed",
                "label_side": "left",
                "shoulder_y_frac": 0.12,
                "font_size_pt": 12.5,
            },
        ],
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    # Lock clean ticks & open upper-left legend headroom on both coupled panels
    p_qv, p_dq = spec.panels[0], spec.panels[1]
    p_qv.x_axis.limits = (0.0, 150.0)
    p_qv.x_axis.major_step = 30.0
    p_qv.y1_axis.limits = (2.4, 4.9)
    p_qv.y1_axis.major_step = 0.5
    p_qv.legend_style = "corner_upper_left"

    p_dq.x_axis.limits = (2.5, 4.45)
    p_dq.x_axis.major_step = 0.5
    p_dq.y1_axis.limits = (-380.0, 440.0)
    p_dq.y1_axis.major_step = 200.0
    p_dq.legend_style = "corner_upper_left"
    return spec


def _make_pulse_align_spec() -> cg.FigureSpec:
    """Zero-aligned short-pulse voltage transients across 6 rates + ohmic `Delta V_0` & slow `Delta V_slow` spans."""
    t_pre = np.linspace(-3.2, -0.02, 36)
    t_pulse = np.linspace(0.0, 5.0, 95)
    t_rest = np.linspace(5.02, 10.5, 75)
    t_all = np.concatenate([t_pre, t_pulse, t_rest])

    v_ocv = 3.20
    pulse_defs = [
        ("1 C", 0.05, 0.03),
        ("2 C", 0.10, 0.06),
        ("5 C", 0.19, 0.11),
        ("10 C", 0.31, 0.17),
        ("20 C", 0.46, 0.24),
        ("50 C", 0.74, 0.50),
    ]
    colors = ot.resolve_series_colors(len(pulse_defs), scheme="sequential_blue_red")

    series_cfg: List[Dict[str, Any]] = []
    for (r_lbl, dv0, dv_slow), c_hex in zip(pulse_defs, colors):
        v_pre_arr = np.full_like(t_pre, v_ocv)
        v_on_arr = (v_ocv - dv0) - dv_slow * (1.0 - np.exp(-t_pulse / 1.45))
        v_end_slow = dv_slow * (1.0 - math.exp(-5.0 / 1.45))
        v_off_arr = v_ocv - v_end_slow * np.exp(-(t_rest - 5.0) / 1.85)
        v_full = np.concatenate([v_pre_arr, v_on_arr, v_off_arr])
        series_cfg.append(
            {
                "name": r_lbl,
                "x": np.round(t_all, 4).tolist(),
                "y": np.round(v_full, 4).tolist(),
                "color": c_hex,
                "already_aligned": True,
            }
        )

    # Exact 50 C instantaneous ohmic drop and t=5.0 s polarization endpoints
    v_inst_50c = round(v_ocv - 0.74, 3)  # 2.460 V
    v_end_50c = round(v_inst_50c - 0.50 * (1.0 - math.exp(-5.0 / 1.45)), 3)  # 1.976 V

    cfg = {
        "mode": "electrochem_kinetics",
        "subtype": "pulse_align",
        "style_preset": "style_publication_minimal",
        "title": "demo_pulse_align",
        "build_opju": False,
        "x_label": "Time (s)",
        "y_label": "Voltage (V)",
        "x_limits": [-3.2, 10.5],
        "y_limits": [1.45, 3.45],
        "legend_style": "corner_lower_right",
        "series": series_cfg,
        "guides": [
            {
                "kind": "hline",
                "value": v_inst_50c,
                "label": "",
                "color": "#6579BE",
                "line_style": "dotted",
                "line_width_pt": 1.4,
            },
            {
                "kind": "hline",
                "value": v_end_50c,
                "label": "",
                "color": "#A02333",
                "line_style": "dotted",
                "line_width_pt": 1.4,
            },
            {
                "kind": "span_v",
                "start": v_inst_50c,
                "end": v_ocv,
                "anchor_pos": -0.55,
                "label": "Delta V_0",
                "label_side": "left",
                "color": "#2B6CB0",
                "font_size_pt": 19.0,
            },
            {
                "kind": "span_v",
                "start": v_end_50c,
                "end": v_inst_50c,
                "anchor_pos": -0.55,
                "label": "Delta V_slow",
                "label_side": "left",
                "color": "#A02333",
                "font_size_pt": 19.0,
            },
        ],
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    spec.panels[0].x_axis.major_step = 2.0
    spec.panels[0].y1_axis.major_step = 0.5
    return spec


def _make_ragone_loglog_spec() -> cg.FigureSpec:
    """Log10-Log10 Ragone energy density vs power density comparing 4 synthetic electrode architectures."""
    arch_defs = [
        ("Design A", 410.0, 3800.0, 1.35, 135.0, 9200.0, "#2B6CB0", "circle_solid"),
        ("Design B", 375.0, 12500.0, 1.25, 155.0, 24000.0, "#6579BE", "square_solid"),
        ("Design C", 335.0, 36000.0, 1.18, 185.0, 52000.0, "#D84B5C", "triangle_up"),
        ("Design D", 465.0, 72000.0, 1.15, 210.0, 76000.0, "#A02333", "diamond"),
    ]
    series_cfg: List[Dict[str, Any]] = []
    for nm, e0, p_char, alpha, p_lo, p_hi, c_hex, mk in arch_defs:
        p_arr = np.geomspace(p_lo, p_hi, 11)
        e_arr = e0 * np.exp(-((p_arr / p_char) ** alpha) * 1.65)
        e_arr = np.clip(e_arr, 14.0, 900.0)
        series_cfg.append(
            {
                "name": nm,
                "x": np.round(p_arr, 2).tolist(),
                "y": np.round(e_arr, 2).tolist(),
                "color": c_hex,
                "marker_style": mk,
                "marker_size_pt": 7.5,
            }
        )

    cfg = {
        "mode": "electrochem_kinetics",
        "subtype": "ragone",
        "style_preset": "style_publication_minimal",
        "title": "demo_ragone_loglog",
        "build_opju": False,
        "x_label": "Power Density (W kg^-1)",
        "y_label": "Energy Density (Wh kg^-1)",
        "x_limits": [100.0, 100000.0],
        "y_limits": [10.0, 1000.0],
        "legend_style": "corner_lower_left",
        "series": series_cfg,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_bode_dual_panel_spec() -> cg.FigureSpec:
    """Shared-Log10-frequency 2-layer EIS Bode plot (`|Z|` & `-Phase`) across 3 Randles-Warburg samples."""
    freqs = np.logspace(-2.0, 5.0, 44)
    sample_defs = [
        ("Sample 1", 18.0, 260.0, 2.4e-5, 190.0, "#2B6CB0"),
        ("Sample 2", 14.0, 115.0, 2.8e-5, 125.0, "#D84B5C"),
        ("Sample 3", 11.0, 52.0, 3.2e-5, 82.0, "#6579BE"),
    ]
    series_cfg: List[Dict[str, Any]] = []
    for nm, rs, rct, cdl, sw, c_hex in sample_defs:
        _, _, z_mag, neg_ph = _randles_warburg_eis(freqs, rs, rct, cdl, sw, c_lim=None)
        series_cfg.append(
            {
                "name": nm,
                "freq": np.round(freqs, 6).tolist(),
                "z_mag": np.round(z_mag, 3).tolist(),
                "neg_phase": np.round(neg_ph, 3).tolist(),
                "color": c_hex,
            }
        )

    cfg = {
        "mode": "bode_dual_panel",
        "style_preset": "style_publication_minimal",
        "title": "demo_bode_dual_panel",
        "build_opju": False,
        "x_label": "Frequency (Hz)",
        "z_label": "|Z| (Ohm)",
        "phase_label": "-Phase (deg.)",
        "series": series_cfg,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_operando_contour_side_spec() -> cg.FigureSpec:
    """2D operando structural intensity pseudocolor field coupled with right-hand voltage profile."""
    two_theta = np.linspace(24.5, 29.5, 140)
    states_y = np.linspace(0.0, 20.0, 81)  # State 0 -> 10 (Discharge) -> 20 (Charge)

    z_mat = np.zeros((states_y.size, two_theta.size), dtype=float)
    v_side = np.zeros_like(states_y)

    for idx, st in enumerate(states_y):
        # Reversible normalized depth of discharge u in [0, 1] peaking at State 10
        u = 1.0 - abs(st - 10.0) / 10.0
        hysteresis = 0.08 if st > 10.0 else -0.06
        v_side[idx] = (
            4.18
            - 1.35 * (u ** 0.82)
            - 0.48 / (1.0 + math.exp(-(u - 0.56) / 0.09))
            + hysteresis * math.sin(math.pi * u)
        )

        # Reversible main Bragg reflection shift + intermediate two-phase peak near mid-cycle
        center_main = 26.05 + 1.85 * (u ** 1.08)
        amp_main = 94.0 - 28.0 * math.exp(-0.5 * ((u - 0.62) / 0.20) ** 2)
        width_main = 0.28 + 0.08 * math.sin(math.pi * u)

        amp_inter = 68.0 * math.exp(-0.5 * ((u - 0.64) / 0.19) ** 2)
        center_inter = 25.35 + 0.25 * u

        row_profile = (
            amp_main * np.exp(-0.5 * ((two_theta - center_main) / width_main) ** 2)
            + amp_inter * np.exp(-0.5 * ((two_theta - center_inter) / 0.24) ** 2)
        )
        z_mat[idx, :] = np.clip(row_profile, 0.0, 100.0)

    operando_stops = ["#FFFFFF", "#C5DBF5", "#6579BE", "#D84B5C", "#A02333"]
    cfg = {
        "mode": "contour_pseudocolor_2d",
        "style_preset": "style_publication_minimal",
        "title": "demo_operando_contour_side",
        "build_opju": False,
        "field_name": "OperandoIntensity",
        "x_label": "2theta (deg.)",
        "y_label": "Operando State",
        "z_label": "Intensity (a.u.)",
        "z_limits": [0.0, 100.0],
        "color_stops": operando_stops,
        "hide_contour_lines": True,
        "matrix_x": np.round(two_theta, 4).tolist(),
        "matrix_y": np.round(states_y, 3).tolist(),
        "matrix_z": np.round(z_mat, 3).tolist(),
        "side_panel": {
            "position": "right",
            "name": "Cell Voltage",
            "x_label": "Voltage (V)",
            "y_label": "Operando State",
            "x": np.round(v_side, 4).tolist(),
            "y": np.round(states_y, 3).tolist(),
            "color": "#A02333",
            "marker_style": "none",
        },
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    p_cnt, p_side = spec.panels[0], spec.panels[1]
    p_cnt.x_axis.limits = (24.5, 29.5)
    p_cnt.x_axis.major_step = 1.0
    p_cnt.y1_axis.limits = (0.0, 20.0)
    p_cnt.y1_axis.major_step = 5.0

    p_side.x_axis.limits = (1.8, 4.4)
    p_side.x_axis.major_step = 1.0
    p_side.y1_axis.limits = (0.0, 20.0)
    p_side.y1_axis.major_step = 5.0
    return spec


# ---------------------------------------------------------------------------
# Inter-Process Safe OriginPro Rendering & LANCZOS Downscaling
# ---------------------------------------------------------------------------


def _downscale_png_to_gallery_jpeg(png_path: Path, dst_jpg: Path, long_edge_px: int) -> Tuple[int, int]:
    """Downscale 300 DPI Origin PNG via LANCZOS to RGB JPEG (`quality=90, subsampling=0`)."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as im:
        rgb = im.convert("RGB")
        w0, h0 = rgb.size
        scale = float(long_edge_px) / float(max(w0, h0))
        new_w = max(1, int(round(w0 * scale)))
        new_h = max(1, int(round(h0 * scale)))
        resized = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)
        resized.save(dst_jpg, format="JPEG", quality=90, subsampling=0, optimize=True)
    return new_w, new_h


def _render_single_job_with_retry(
    out_name: str,
    long_edge_px: int,
    gallery_dir: Path,
    render_fn: Callable[[Path], Path],
) -> Path:
    """Execute a single OriginPro figure render inside an isolated temp dir with 5x COM lock retry."""
    dst_jpg = gallery_dir / f"{out_name}.jpg"
    for attempt in range(5):
        try:
            with tempfile.TemporaryDirectory(prefix=f"sciorigin_p2_{out_name}_") as tmp_str:
                tmp_dir = Path(tmp_str)
                png_path = render_fn(tmp_dir)
                if not png_path.exists() or png_path.stat().st_size == 0:
                    raise RuntimeError(f"Origin render produced empty PNG for {out_name}: {png_path}")
                w_px, h_px = _downscale_png_to_gallery_jpeg(png_path, dst_jpg, long_edge_px=long_edge_px)
                size_kb = dst_jpg.stat().st_size / 1024.0
                print(
                    f"[Part 2] Rendered {dst_jpg.name}: {w_px}x{h_px} px ({size_kb:.1f} KB)",
                    flush=True,
                )
                return dst_jpg
        except TimeoutError:
            if attempt == 4:
                raise
            print(f"[Part 2] Lock timeout on {out_name} (attempt {attempt + 1}/5); retrying in 6s...", flush=True)
            time.sleep(6)
    raise RuntimeError(f"Exhausted retries rendering {out_name}")


def generate_part2(
    gallery_dir: Path = GALLERY_DIR,
    only_names: List[str] | None = None,
) -> List[Path]:
    """Render all 7 Part 2 electrochemistry, impedance & operando 2D figures into `gallery_dir`."""
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)

    def _run_hero(tmp_dir: Path) -> Path:
        ob.set_active_style("style_publication_minimal")
        panels = _build_hero_composite_panels()
        opju_path = ob.build_composite_opju(
            panels_rendered=panels,
            out_opju=tmp_dir / "demo_hero_composite_2x2.opju",
            title="demo_hero_composite_2x2",
            ncols=2,
            export_dir=None,
        )
        with ob.origin_session() as op:
            op.open(str(opju_path))
            gp_comp = op.find_graph()
            if gp_comp is None:
                raise RuntimeError("Master composite graph not found after opening OPJU.")
            ob.set_graph_page_inches(gp_comp, 14.35, 10.35)
            gl_b = gp_comp[1]
            ob.activate_layer(op, gp_comp, 2)
            gl_b.set_ylim(-0.35, 9.0)
            exported = ob.export_origin_publication_figures(
                op,
                gp_comp,
                tmp_dir,
                "demo_hero_composite_2x2",
                make_qa_preview=False,
            )
        return Path(exported["png"])

    def _make_spec_runner(spec_factory: Callable[[], cg.FigureSpec]) -> Callable[[Path], Path]:
        def _runner(tmp_dir: Path) -> Path:
            spec = spec_factory()
            res = ornd.render_figure_spec_origin(spec, out_dir=tmp_dir, export_images=True)
            return Path(res["primary_figures"]["png"])

        return _runner

    jobs: List[Tuple[str, int, Callable[[Path], Path]]] = [
        ("demo_hero_composite_2x2", 1800, _run_hero),
        ("demo_rate_galvanostatic", 1440, _make_spec_runner(_make_rate_galvanostatic_spec)),
        ("demo_dqdv_coupled", 1440, _make_spec_runner(_make_dqdv_coupled_spec)),
        ("demo_pulse_align", 1440, _make_spec_runner(_make_pulse_align_spec)),
        ("demo_ragone_loglog", 1440, _make_spec_runner(_make_ragone_loglog_spec)),
        ("demo_bode_dual_panel", 1440, _make_spec_runner(_make_bode_dual_panel_spec)),
        ("demo_operando_contour_side", 1800, _make_spec_runner(_make_operando_contour_side_spec)),
    ]

    filter_set = {s.removesuffix(".jpg") for s in only_names} if only_names else None
    outputs: List[Path] = []
    for out_name, long_edge, fn in jobs:
        if filter_set is not None and out_name not in filter_set:
            continue
        outputs.append(_render_single_job_with_retry(out_name, long_edge, gallery_dir, fn))
    return outputs


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render Part 2 synthetic electrochemistry gallery figures.")
    parser.add_argument("--only", nargs="*", default=None, help="Optional subset of figure stems to render.")
    args = parser.parse_args()
    generated = generate_part2(GALLERY_DIR, only_names=args.only)
    print(f"Successfully generated {len(generated)} Part 2 gallery figures.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
