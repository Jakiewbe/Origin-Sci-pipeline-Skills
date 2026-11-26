"""
gallery_part5_hard_and_noncartesian.py - Part 5 Hard Clinical, Analytical, Optical & Non-Cartesian Showcase Generator.

Renders 10 flagship cross-science & non-Cartesian publication figures (Clinical Survival, ML ROC,
FT-NMR Spectrum, Ultrafast Broken-Axis Kinetics, Dual-X Wavelength/Energy Optics, Ternary Phase Diagram,
Optical Polar Pattern, AI4Science Radar Benchmark, Multi-Track Ocean Profile, and 2D Vortex Quiver Field)
natively in headless OriginPro 2024 (`skip_origin=False`), downscaling exported 300 DPI PNGs via
`PIL.Image` (`LANCZOS`) to crisp `1440 x 1080 px` (`4:3`) RGB JPEGs (`quality=92, subsampling=0`).

100% deterministic synthetic data (`np.random.default_rng(2026)`), generic scientific labels, zero external files.
"""
from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "sci-origin-pipeline" / "scripts"
GALLERY_DIR = REPO_ROOT / "assets" / "gallery"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import chart_grammar as cg  # noqa: E402
import origin_renderer as ornd  # noqa: E402


def _standardized_normal(rng: np.random.Generator, n: int) -> np.ndarray:
    """Draw `n` deterministic Gaussian variates standardized to zero sample mean and unit sample SD."""
    raw = rng.normal(0.0, 1.0, size=n)
    centered = raw - float(np.mean(raw))
    sd = float(np.std(centered, ddof=1))
    return centered / (sd if sd > 1e-12 else 1.0)


def _make_clinical_kaplan_meier_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    1. `demo_clinical_kaplan_meier` (`kaplan_meier_plot`, Arial + `okabe_ito`):
       2 clinical oncology cohorts (`Targeted Therapy`, `n=48` vs `Standard Care`, `n=48`, `0..36 months`)
       with step-horizontal survival curves, Greenwood 95% CI bands, censor ticks, `Log-rank p` & `HR`,
       and aligned bottom `Number at risk` table (`0, 6, 12, 18, 24, 30, 36` months).
    """
    n_arm = 48
    # Targeted Therapy: lower hazard (longer progression-free survival), administrative follow-up to 36 months
    u_tgt = np.clip(rng.uniform(0.03, 0.97, size=n_arm), 1e-4, 0.999)
    t_fail_tgt = 39.5 * np.power(-np.log(u_tgt), 1.0 / 1.26)
    t_cens_tgt = rng.uniform(15.0, 44.0, size=n_arm)
    t_cens_tgt[:14] = 36.0
    time_tgt = np.minimum(np.minimum(t_fail_tgt, t_cens_tgt), 36.0)
    evt_tgt = ((t_fail_tgt <= t_cens_tgt) & (t_fail_tgt <= 36.0)).astype(int)

    # Standard Care: higher hazard, clear separation (Log-rank p < 0.005) while avoiding early <15m drop below 0.38
    u_std = np.clip(rng.uniform(0.03, 0.97, size=n_arm), 1e-4, 0.999)
    t_fail_std = 20.5 * np.power(-np.log(u_std), 1.0 / 1.40)
    t_cens_std = rng.uniform(12.0, 40.0, size=n_arm)
    t_cens_std[:8] = 36.0
    time_std = np.minimum(np.minimum(t_fail_std, t_cens_std), 36.0)
    evt_std = ((t_fail_std <= t_cens_std) & (t_fail_std <= 36.0)).astype(int)

    cfg = {
        "title": "demo_clinical_kaplan_meier",
        "mode": "kaplan_meier_plot",
        "style_preset": "style_arial_clean",
        "color_scheme": "okabe_ito",
        "build_opju": False,
        "locale": "en",
        "x_label": "Time (months)",
        "y_label": "Survival Probability",
        "x_limits": [0.0, 36.0],
        "y_limits": [0.0, 1.18],
        "x_major_step": 6.0,
        "risk_times": [0.0, 6.0, 12.0, 18.0, 24.0, 30.0, 36.0],
        "show_ci": True,
        "show_censor": True,
        "show_risk_table": True,
        "groups": [
            {
                "name": "Targeted Therapy",
                "time": np.round(time_tgt, 2).tolist(),
                "event": evt_tgt.tolist(),
            },
            {
                "name": "Standard Care",
                "time": np.round(time_std, 2).tolist(),
                "event": evt_std.tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_ml_roc_curves_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    2. `demo_ml_roc_curves` (`roc_pr_curve`, `style_publication_minimal` TNR Bold 3pt):
       3 classification models (`Foundation Model`, `Graph Neural Net`, `Baseline RF`, `n_pos=140, n_neg=160`
       with `AUROC ~ 0.95, 0.88, 0.78`), dashed chance diagonal, `AUC` in legend, and open-circle Youden cutoff.
    """
    n_neg, n_pos = 160, 140
    y_true = ([0] * n_neg) + ([1] * n_pos)

    # Bi-normal separation delta_mu = sqrt(2) * Phi^-1(target_auc) -> ~0.95, ~0.88, ~0.78
    model_specs = [
        ("Foundation Model", 2.33, "#D84B5C"),
        ("Graph Neural Net", 1.66, "#2B6CB0"),
        ("Baseline RF", 1.09, "#2F855A"),
    ]
    models = []
    for name, delta_mu, col in model_specs:
        z_neg = _standardized_normal(rng, n_neg)
        z_pos = _standardized_normal(rng, n_pos) + delta_mu
        logits = np.concatenate([z_neg, z_pos])
        probs = 1.0 / (1.0 + np.exp(-logits))
        models.append(
            {
                "name": name,
                "color": col,
                "y_true": y_true,
                "y_score": np.round(probs, 5).tolist(),
            }
        )

    cfg = {
        "title": "demo_ml_roc_curves",
        "mode": "roc_pr_curve",
        "curve_kind": "roc",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "show_optimal_point": True,
        "legend_style": "corner_lower_right",
        "models": models,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _lorentzian(x: np.ndarray, x0: float, gamma: float, amp: float) -> np.ndarray:
    return amp * (gamma ** 2) / ((x - x0) ** 2 + gamma ** 2)


def _make_chem_nmr_spectrum_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    3. `demo_chem_nmr_spectrum` (`nmr_spectrum`, `style_publication_minimal` TNR Bold 3pt):
       Synthetic `1H NMR (400 MHz)` (`9.0 -> 0.0 ppm`, `invert=True`) of an aromatic ethyl ester:
       `Ar-H` multiplet at `~7.8 & 7.3 ppm` (`4H`), `-OCH2-` quartet at `~4.35 ppm` (`2H`),
       `-CH3` triplet at `~1.38 ppm` (`3H`), and `TMS` singlet at `0.00 ppm`, with elevated step-integrals.
    """
    ppm = np.linspace(9.2, -0.85, 3000)
    y = np.zeros_like(ppm)

    # Aromatic protons [4H]: ortho doublet (~7.82 ppm, 2H) + meta/para multiplet (~7.32 ppm, 2H)
    for shift, rel_i in [(7.845, 0.36), (7.805, 0.38)]:
        y += _lorentzian(ppm, shift, 0.0095, rel_i)
    for shift, rel_i in [(7.355, 0.18), (7.320, 0.37), (7.285, 0.19)]:
        y += _lorentzian(ppm, shift, 0.0095, rel_i)

    # Methylene quartet -OCH2- at ~4.35 ppm (1:3:3:1 Pascal quartet, [2H])
    j_q = 0.028
    for k_idx, weight in enumerate([1.0, 3.0, 3.0, 1.0]):
        shift = 4.35 + (1.5 - k_idx) * j_q
        y += _lorentzian(ppm, shift, 0.0082, 0.125 * weight)

    # Methyl triplet -CH3 at ~1.38 ppm (1:2:1 Pascal triplet, [3H], tallest peak normalized to 1.0)
    j_t = 0.028
    for k_idx, weight in enumerate([1.0, 2.0, 1.0]):
        shift = 1.38 + (1.0 - k_idx) * j_t
        y += _lorentzian(ppm, shift, 0.0082, 0.495 * weight)

    # Internal standard TMS singlet at 0.00 ppm
    y += _lorentzian(ppm, 0.00, 0.0065, 0.34)

    # Subtle realistic FT-NMR thermal baseline noise
    y += rng.normal(0.0, 0.0016, size=len(ppm))
    y = y - float(np.percentile(y, 5))
    y = y / float(np.max(y))

    cfg = {
        "title": "demo_chem_nmr_spectrum",
        "mode": "nmr_spectrum",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "x_label": "Chemical Shift \\g(d) (ppm)",
        "y_label": "Intensity (a.u.)",
        "invert_x": True,
        "x_limits": [-0.85, 9.2],
        "y_limits": [-0.05, 1.30],
        "legend_style": "corner_upper_left",
        "series": [
            {
                "name": "\\+(1)H NMR (400 MHz)",
                "color": "#111111",
                "integral_color": "#D84B5C",
                "x": np.round(ppm, 5).tolist(),
                "y": np.round(y, 5).tolist(),
                "integrals": [
                    {"ppm_range": [6.80, 8.12], "label": ""},
                    {"ppm_range": [3.80, 4.82], "label": ""},
                    {"ppm_range": [0.78, 1.84], "label": ""},
                ],
            }
        ],
        "guides": [
            {"kind": "text", "x": 6.92, "y": 0.89, "label": "4H", "color": "#D84B5C"},
            {"kind": "text", "x": 3.92, "y": 0.89, "label": "2H", "color": "#D84B5C"},
            {"kind": "text", "x": 0.88, "y": 0.89, "label": "3H", "color": "#D84B5C"},
            {"kind": "peak_tag", "x": 7.72, "y": 1.04, "label": "Ar-H (m)", "color": "#111111"},
            {"kind": "peak_tag", "x": 4.48, "y": 1.04, "label": "-OCH_2- (q)", "color": "#111111"},
            {"kind": "peak_tag", "x": 1.48, "y": 1.14, "label": "-CH_3 (t)", "color": "#111111"},
            {"kind": "peak_tag", "x": 0.00, "y": 0.48, "label": "TMS", "color": "#111111"},
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_physics_broken_x_ta_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    4. `demo_physics_broken_x_ta` (`broken_axis_plot`, `style_arial_clean`):
       Ultrafast transient absorption kinetics (`Time Delay (ps)` vs `-\\g(D)A (mOD)`) for `Pristine Film`
       vs `Passivated Film`, spanning `-2..18 ps` and `120..4800 ps` across an X-axis break (`20..100 ps`).
    """
    t_pre = np.array([-2.0, -1.2, -0.5, -0.1, 0.2, 0.5, 0.9, 1.5, 2.4, 3.6, 5.2, 7.2, 9.8, 12.6, 15.4, 18.0])
    t_post = np.array([120.0, 260.0, 520.0, 880.0, 1350.0, 1900.0, 2550.0, 3250.0, 4000.0, 4800.0])
    t_all = np.concatenate([t_pre, t_post])

    # Smooth instrument-response rise (erf-like logistic turn-on around t = 0 ps)
    irf_gate = 0.5 * (1.0 + np.tanh(t_all / 0.28))
    pos_t = np.maximum(t_all, 0.0)

    # Passivated Film: suppressed ultrafast trapping + long-lived carrier population
    y_pass = irf_gate * (7.2 * np.exp(-pos_t / 9.5) + 17.6 * np.exp(-pos_t / 3400.0))
    y_pass += rng.normal(0.0, 0.20, size=len(t_all))

    # Pristine Film: rapid hot-carrier/defect trapping + fast non-radiative decay
    y_pris = irf_gate * (14.4 * np.exp(-pos_t / 4.2) + 7.8 * np.exp(-pos_t / 920.0))
    y_pris += rng.normal(0.0, 0.20, size=len(t_all))

    cfg = {
        "title": "demo_physics_broken_x_ta",
        "mode": "broken_axis_plot",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "x_label": "Time Delay (ps)",
        "y_label": "-\\g(D)A (mOD)",
        "x_limits": [-2.5, 5000.0],
        "y_limits": [-1.5, 27.5],
        "x_breaks": [
            {
                "from": 20.0,
                "to": 100.0,
                "position_pct": 48.0,
                "inc_before": 5.0,
                "inc_after": 2000.0,
            }
        ],
        "legend_style": "corner_upper_right",
        "guides": [
            {"kind": "hline", "value": 0.0, "color": "#94A3B8", "line_style": "dashed"},
        ],
        "series": [
            {
                "name": "Passivated Film",
                "color": "#D84B5C",
                "marker_style": "circle_solid",
                "marker_size_pt": 5.8,
                "x": t_all.tolist(),
                "y": np.round(y_pass, 3).tolist(),
            },
            {
                "name": "Pristine Film",
                "color": "#2B6CB0",
                "marker_style": "circle_open",
                "marker_size_pt": 5.8,
                "x": t_all.tolist(),
                "y": np.round(y_pris, 3).tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_optics_uvvis_ev_topx_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    5. `demo_optics_uvvis_ev_topx` (`dual_x_optical_spectrum`, `style_publication_minimal` TNR Bold 3pt):
       Semiconductor / perovskite `Absorption` & `Photoluminescence (PL)` across bottom `Wavelength (nm)`
       (`380..820 nm`) with nonlinear formula-linked top X axis `Photon Energy (eV)` (`1239.84193/x`).
    """
    wl = np.linspace(380.0, 820.0, 441)
    ev = 1239.84193 / wl

    # Wide-bandgap perovskite (E_g ~ 2.35 eV, ~528 nm): continuum + sharp 1s excitonic peak + zero tail >570 nm
    eg_ev = 2.35
    step_edge = 1.0 / (1.0 + np.exp(-(ev - eg_ev) / 0.035))
    continuum = step_edge * (0.54 + 0.34 * np.clip((ev - eg_ev) / 0.95, 0.0, 1.2) ** 0.75)
    exciton = 0.23 * np.exp(-0.5 * ((wl - 518.0) / 9.5) ** 2)
    abs_spec = continuum + exciton + rng.normal(0.0, 0.0022, size=len(wl))
    abs_spec = np.clip(abs_spec - float(np.min(abs_spec[-120:])), 0.0, None)
    abs_spec = abs_spec / float(np.max(abs_spec))

    # Stokes-shifted narrow Photoluminescence (PL) peak centered at 534 nm (FWHM ~ 21 nm), leaving >570 nm open for legend
    pl_spec = np.exp(-0.5 * ((wl - 534.0) / 9.0) ** 2) + rng.normal(0.0, 0.0018, size=len(wl))
    pl_spec = np.clip(pl_spec, 0.0, None)
    pl_spec = pl_spec / float(np.max(pl_spec))

    cfg = {
        "title": "demo_optics_uvvis_ev_topx",
        "mode": "dual_x_optical_spectrum",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "x_label": "Wavelength (nm)",
        "y_label": "Normalized Intensity (a.u.)",
        "x_limits": [380.0, 820.0],
        "y_limits": [-0.04, 1.20],
        "linked_top_x": {
            "label": "Photon Energy (eV)",
            "formula": "1239.84193/x",
            "major_step": 0.5,
        },
        "legend_style": "corner_upper_right",
        "series": [
            {
                "name": "Absorption",
                "color": "#2B6CB0",
                "x": np.round(wl, 2).tolist(),
                "y": np.round(abs_spec, 4).tolist(),
            },
            {
                "name": "Photoluminescence (PL)",
                "color": "#D84B5C",
                "x": np.round(wl, 2).tolist(),
                "y": np.round(pl_spec, 4).tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_chem_ternary_phase_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    6. `demo_chem_ternary_phase` (`ternary_diagram`, `style_publication_minimal` TNR Bold 3pt):
       Ternary catalytic/alloy composition diagram (`Metal A (%)`, `Metal B (%)`, `Support C (%)`) showing
       `Single-Phase Solid Solution` (`circle`), `Phase-Separated` (`open_circle`), and `Phase Boundary`.
    """
    # Smooth binodal miscibility dome: C_bin(u) where u = A / (A + B) in [0.10, 0.90]
    u_grid = np.linspace(0.08, 0.92, 45)
    c_dome = 48.0 * np.maximum(0.0, 1.0 - ((u_grid - 0.50) / 0.42) ** 2) ** 0.85 + 2.0
    rem_dome = 100.0 - c_dome
    a_bound = u_grid * rem_dome
    b_bound = (1.0 - u_grid) * rem_dome

    # Single-Phase Solid Solution compositions (miscible region outside/above dome)
    sp_a, sp_b, sp_c = [], [], []
    u_sp = np.linspace(0.14, 0.86, 16) + rng.uniform(-0.02, 0.02, size=16)
    c_sp_offsets = rng.uniform(9.0, 34.0, size=16)
    for ui, dc in zip(u_sp, c_sp_offsets):
        c_b_here = 48.0 * max(0.0, 1.0 - ((float(ui) - 0.50) / 0.42) ** 2) ** 0.85 + 2.0
        ci = min(88.0, c_b_here + float(dc))
        rem = 100.0 - ci
        sp_a.append(round(float(ui) * rem, 2))
        sp_b.append(round((1.0 - float(ui)) * rem, 2))
        sp_c.append(round(ci, 2))

    # Phase-Separated compositions (inside two-phase immiscibility gap below dome)
    ps_a, ps_b, ps_c = [], [], []
    u_ps = np.linspace(0.22, 0.78, 14) + rng.uniform(-0.018, 0.018, size=14)
    frac_h = rng.uniform(0.18, 0.78, size=14)
    for ui, fh in zip(u_ps, frac_h):
        c_b_here = 48.0 * max(0.0, 1.0 - ((float(ui) - 0.50) / 0.42) ** 2) ** 0.85 + 2.0
        ci = max(5.0, float(fh) * (c_b_here - 5.0))
        rem = 100.0 - ci
        ps_a.append(round(float(ui) * rem, 2))
        ps_b.append(round((1.0 - float(ui)) * rem, 2))
        ps_c.append(round(ci, 2))

    cfg = {
        "title": "demo_chem_ternary_phase",
        "mode": "ternary_diagram",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "component_labels": ["Metal A (%)", "Metal B (%)", "Support C (%)"],
        "series": [
            {
                "name": "Single-Phase Solid Solution",
                "color": "#2B6CB0",
                "marker_style": "circle",
                "line_style": "none",
                "marker_size_pt": 7.2,
                "a": sp_a,
                "b": sp_b,
                "c": sp_c,
            },
            {
                "name": "Phase-Separated",
                "color": "#D84B5C",
                "marker_style": "open_circle",
                "line_style": "none",
                "marker_size_pt": 7.2,
                "a": ps_a,
                "b": ps_b,
                "c": ps_c,
            },
            {
                "name": "Phase Boundary",
                "color": "#111111",
                "marker_style": "none",
                "line_style": "solid",
                "a": np.round(a_bound, 3).tolist(),
                "b": np.round(b_bound, 3).tolist(),
                "c": np.round(c_dome, 3).tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_optics_polar_radiation_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    7. `demo_optics_polar_radiation` (`polar_radar_plot`, `subtype="polar"`, `style_arial_clean`):
       Optical polarization / dipole angular pattern (`0..360 deg`): `SHG Parallel` (`cos^4` two-lobe)
       vs `Quadrupole Mode` (`sin^2(2*theta)` four-lobe) in native Origin Polar coordinates.
    """
    _ = rng
    theta_deg = np.linspace(0.0, 360.0, 361)
    rad = np.deg2rad(theta_deg)
    r_shg = np.cos(rad) ** 4
    r_quad = 0.86 * (np.sin(2.0 * rad) ** 2)

    cfg = {
        "title": "demo_optics_polar_radiation",
        "mode": "polar_radar_plot",
        "subtype": "polar",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "y_label": "Normalized Intensity (a.u.)",
        "r_limits": [0.0, 1.05],
        "series": [
            {
                "name": "SHG Parallel",
                "color": "#D84B5C",
                "line_style": "solid",
                "marker_style": "none",
                "theta": np.round(theta_deg, 2).tolist(),
                "r": np.round(r_shg, 5).tolist(),
            },
            {
                "name": "Quadrupole Mode",
                "color": "#2B6CB0",
                "line_style": "solid",
                "marker_style": "none",
                "theta": np.round(theta_deg, 2).tolist(),
                "r": np.round(r_quad, 5).tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_ml_radar_benchmark_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    8. `demo_ml_radar_benchmark` (`polar_radar_plot`, `subtype="radar"`, Arial + `okabe_ito`):
       6-axis AI4Science foundation model benchmark (`Accuracy`, `OOD Gen.`, `Throughput`, `Calibration`,
       `Data Eff.`, `Symmetry`) comparing `Model A (Ours)` vs `Baseline B` vs `Baseline C`.
    """
    jitter = rng.uniform(-0.01, 0.01, size=(3, 6))
    cats = ["Accuracy", "OOD Gen.", "Throughput", "Calibration", "Data Eff.", "Symmetry"]
    m_a = np.round(np.clip(np.array([0.94, 0.89, 0.84, 0.91, 0.88, 0.95]) + jitter[0], 0.1, 0.98), 3)
    m_b = np.round(np.clip(np.array([0.81, 0.70, 0.89, 0.75, 0.68, 0.73]) + jitter[1], 0.1, 0.98), 3)
    m_c = np.round(np.clip(np.array([0.69, 0.56, 0.74, 0.63, 0.54, 0.51]) + jitter[2], 0.1, 0.98), 3)

    cfg = {
        "title": "demo_ml_radar_benchmark",
        "mode": "polar_radar_plot",
        "subtype": "radar",
        "style_preset": "style_arial_clean",
        "color_scheme": "okabe_ito",
        "build_opju": False,
        "locale": "en",
        "categories": cats,
        "r_limits": [0.0, 1.0],
        "fill_alpha": 0.18,
        "series": [
            {"name": "Model A (Ours)", "y": m_a.tolist()},
            {"name": "Baseline B", "y": m_b.tolist()},
            {"name": "Baseline C", "y": m_c.tolist()},
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_geo_multitrack_depth_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    9. `demo_geo_multitrack_depth` (`multi_track_profile`, `style_arial_clean`):
       3-track ocean/paleoclimate depth profile (`Depth (m)` `0 -> 200 m` inverted shared Y axis):
       Track 1 `Temp. (°C)`, Track 2 `Salinity (PSU)`, Track 3 `Dissolved O_2 (\\g(m)mol kg\\+(-1))`
       with a shaded `Thermocline` (`30..65 m`) cross-track horizon band.
    """
    depths = np.array([0.0, 10.0, 20.0, 30.0, 38.0, 47.0, 56.0, 65.0, 80.0, 100.0, 125.0, 150.0, 175.0, 200.0])

    # Realistic subtropical water-column CTD profile across mixed layer (0-30m), thermocline (30-65m), and deep layer
    sig_thermo = 1.0 / (1.0 + np.exp((depths - 47.5) / 8.5))
    temp_c = 10.2 + 15.4 * sig_thermo - 0.012 * np.maximum(depths - 65.0, 0.0) + rng.normal(0.0, 0.14, size=len(depths))
    sal_psu = 35.12 - 0.96 * sig_thermo + 0.0012 * np.maximum(depths - 65.0, 0.0) + rng.normal(0.0, 0.018, size=len(depths))
    # Subsurface oxygen maximum near base of euphotic mixed layer (~25-32m), then oxycline decay
    do_umol = (
        122.0
        + 96.0 * (1.0 / (1.0 + np.exp((depths - 58.0) / 14.0)))
        + 18.0 * np.exp(-0.5 * ((depths - 26.0) / 11.0) ** 2)
        + rng.normal(0.0, 1.8, size=len(depths))
    )

    cfg = {
        "title": "demo_geo_multitrack_depth",
        "mode": "multi_track_profile",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "depth_label": "Depth (m)",
        "depth_invert": True,
        "depth_limits": [0.0, 200.0],
        "horizons": [
            {
                "depth_start": 30.0,
                "depth_end": 65.0,
                "label": "Thermocline",
                "color": "#DCE8F5",
            }
        ],
        "tracks": [
            {
                "name": "Temperature",
                "x_label": "Temp. (°C)",
                "color": "#D84B5C",
                "x_limits": [7.5, 27.5],
                "x": np.round(temp_c, 2).tolist(),
                "depth": depths.tolist(),
            },
            {
                "name": "Salinity",
                "x_label": "Salinity (PSU)",
                "color": "#2B6CB0",
                "x_limits": [34.0, 35.4],
                "x": np.round(sal_psu, 3).tolist(),
                "depth": depths.tolist(),
            },
            {
                "name": "Dissolved O\\-(2)",
                "x_label": "Dissolved O_2 (\\g(m)mol kg\\+(-1))",
                "color": "#009E73",
                "x_limits": [60.0, 245.0],
                "x": np.round(do_umol, 1).tolist(),
                "depth": depths.tolist(),
            },
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _vortex_pair_velocity(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Evaluate a counter-rotating Lamb-Oseen vortex dipole on `[-2, 2] x [-2, 2]`."""
    rc2 = 0.56 ** 2
    vortices = [(-0.75, 0.0, +3.10), (+0.75, 0.0, -3.10)]
    u = np.zeros_like(x, dtype=float)
    v = np.zeros_like(y, dtype=float)
    for x0, y0, gamma in vortices:
        dx = x - x0
        dy = y - y0
        r2 = dx ** 2 + dy ** 2
        factor = (gamma / (2.0 * math.pi * np.maximum(r2, 1e-6))) * (1.0 - np.exp(-r2 / rc2))
        u += -factor * dy
        v += +factor * dx
    return u, v


def _make_physics_vector_quiver_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    10. `demo_physics_vector_quiver` (`vector_quiver_field`, TNR Bold 3pt + `color_scheme="viridis"`):
        2D counter-rotating vortex pair velocity field on `[-2, 2] x [-2, 2]` (`X (mm)`, `Y (mm)`):
        smooth `viridis` velocity-magnitude contour background + crisp 2D `VECTXYXY` arrows + colorbar `|v| (m s^-1)`.
    """
    _ = rng
    # High-resolution 49x49 scalar magnitude grid for smooth viridis pseudocolor background
    gx = np.linspace(-2.0, 2.0, 49)
    gy = np.linspace(-2.0, 2.0, 49)
    gxx, gyy = np.meshgrid(gx, gy)
    gu, gv = _vortex_pair_velocity(gxx, gyy)
    gmag = np.hypot(gu, gv)

    # Crisp 13x13 quiver grid inside [-1.72, 1.72] so arrow tips never clip the [-2, 2] frame
    qx_1d = np.linspace(-1.72, 1.72, 13)
    qy_1d = np.linspace(-1.72, 1.72, 13)
    qxx, qyy = np.meshgrid(qx_1d, qy_1d)
    qu, qv = _vortex_pair_velocity(qxx, qyy)

    cfg = {
        "title": "demo_physics_vector_quiver",
        "mode": "vector_quiver_field",
        "style_preset": "style_publication_minimal",
        "color_scheme": "viridis",
        "build_opju": False,
        "locale": "en",
        "x_label": "X (mm)",
        "y_label": "Y (mm)",
        "z_label": "|v| (m s\\+(-1))",
        "x_limits": [-2.0, 2.0],
        "y_limits": [-2.0, 2.0],
        "equal_aspect": True,
        "vector_color": "#FFFFFF",
        "matrix_x": np.round(gx, 4).tolist(),
        "matrix_y": np.round(gy, 4).tolist(),
        "matrix_z": np.round(gmag, 4).tolist(),
        "x": np.round(qxx.ravel(), 4).tolist(),
        "y": np.round(qyy.ravel(), 4).tolist(),
        "u": np.round(qu.ravel(), 4).tolist(),
        "v": np.round(qv.ravel(), 4).tolist(),
    }
    return cg.compile_config_to_figure_spec(cfg)


def build_part5_jobs() -> Dict[str, cg.FigureSpec]:
    """Return the ordered mapping of all 10 Part 5 hard & non-Cartesian gallery stems to `FigureSpec` objects."""
    rng = np.random.default_rng(2026)
    return {
        "demo_clinical_kaplan_meier": _make_clinical_kaplan_meier_spec(rng),
        "demo_ml_roc_curves": _make_ml_roc_curves_spec(rng),
        "demo_chem_nmr_spectrum": _make_chem_nmr_spectrum_spec(rng),
        "demo_physics_broken_x_ta": _make_physics_broken_x_ta_spec(rng),
        "demo_optics_uvvis_ev_topx": _make_optics_uvvis_ev_topx_spec(rng),
        "demo_chem_ternary_phase": _make_chem_ternary_phase_spec(rng),
        "demo_optics_polar_radiation": _make_optics_polar_radiation_spec(rng),
        "demo_ml_radar_benchmark": _make_ml_radar_benchmark_spec(rng),
        "demo_geo_multitrack_depth": _make_geo_multitrack_depth_spec(rng),
        "demo_physics_vector_quiver": _make_physics_vector_quiver_spec(rng),
    }


def _downscale_png_to_gallery_jpg(png_path: Path, dst_jpg: Path, long_edge_px: int = 1440) -> tuple[int, int]:
    """Downscale 300 DPI Origin PNG via LANCZOS to crisp `1440 x 1080` RGB JPEG (`quality=92, subsampling=0`)."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as im:
        im_rgb = im.convert("RGB")
        w, h = im_rgb.size
        scale = float(long_edge_px) / float(max(w, h))
        target_wh = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        im_out = im_rgb.resize(target_wh, Image.Resampling.LANCZOS)
        im_out.save(dst_jpg, format="JPEG", quality=92, subsampling=0, optimize=True)
    return target_wh


def _render_single_job_inprocess(out_name: str, gallery_dir: Path) -> Path:
    """Render one Part 5 figure in the current process (fresh OriginExt COM pointer when invoked via subprocess)."""
    jobs = build_part5_jobs()
    if out_name not in jobs:
        raise KeyError(f"Unknown Part 5 figure job: {out_name!r}")
    spec = jobs[out_name]
    spec.title = out_name
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"sciorigin_p5_{out_name}_") as fig_tmp_str:
        fig_tmp = Path(fig_tmp_str)
        res = None
        for attempt in range(5):
            try:
                res = ornd.render_figure_spec_origin(spec, fig_tmp, export_images=True)
                break
            except (TimeoutError, RuntimeError) as exc:
                if attempt == 4:
                    raise
                print(f"  [COM retry {attempt + 1}/5] {out_name}: {exc} -> sleeping 6s ...", flush=True)
                time.sleep(6)

        assert res is not None
        png_path = Path(res["primary_figures"]["png"])
        dst_jpg = gallery_dir / f"{out_name}.jpg"
        out_w, out_h = _downscale_png_to_gallery_jpg(png_path, dst_jpg, long_edge_px=1440)
        print(
            f"  -> Saved {dst_jpg.name} ({out_w}x{out_h} px, {dst_jpg.stat().st_size // 1024} KB)",
            flush=True,
        )
        return dst_jpg


def generate_part5(gallery_dir: Path = GALLERY_DIR, only_names: List[str] | None = None) -> List[Path]:
    """Render all 10 Part 5 hard & non-Cartesian showcase figures natively in headless OriginPro 2024."""
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_part5_jobs()
    target_names = [k for k in jobs.keys() if (not only_names or k in set(only_names))]

    saved_paths: List[Path] = []
    script_path = str(Path(__file__).resolve())
    for out_name in target_names:
        print(f"[Part 5] Rendering native OriginPro showcase: {out_name} ...", flush=True)
        dst_jpg = gallery_dir / f"{out_name}.jpg"
        for attempt in range(5):
            proc = subprocess.run(
                [sys.executable, script_path, "--single", out_name, "--gallery-dir", str(gallery_dir)],
                capture_output=True,
                text=True,
            )
            if proc.stdout:
                print(proc.stdout.rstrip(), flush=True)
            if proc.returncode == 0 and dst_jpg.exists() and dst_jpg.stat().st_size > 0:
                saved_paths.append(dst_jpg)
                break
            if attempt == 4:
                err_tail = (proc.stderr or proc.stdout or "").strip()[-1200:]
                raise RuntimeError(f"Failed to render {out_name} after 5 attempts:\n{err_tail}")
            print(f"  [Subprocess COM retry {attempt + 1}/5] {out_name} after 6s ...", flush=True)
            time.sleep(6)

    return saved_paths


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render Part 5 SciOrigin hard & non-Cartesian showcase figures.")
    parser.add_argument("--single", type=str, default=None, help="Internal single-figure worker target.")
    parser.add_argument("--gallery-dir", type=Path, default=GALLERY_DIR, help="Output gallery directory.")
    parser.add_argument("names", nargs="*", help="Optional subset of figure stems to render.")
    cli_args = parser.parse_args()
    if cli_args.single:
        _render_single_job_inprocess(cli_args.single, cli_args.gallery_dir)
    else:
        generate_part5(gallery_dir=cli_args.gallery_dir, only_names=cli_args.names or None)
