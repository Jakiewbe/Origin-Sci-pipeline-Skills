"""
generate_synthetic_gallery.py - 100% Synthetic Mathematical Demo Generator for SciOrigin v6.0.

Generates publication-ready showcase figures directly in headless OriginPro 2024 using pure
analytical functions (Randles-Warburg impedance, synthetic stacked fractions, 2D Gaussian relaxation
fields, and synthetic correlation matrices) — zero external data files required.

Usage:
    python examples/generate_synthetic_gallery.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "sci-origin-pipeline" / "scripts"
GALLERY_DIR = REPO_ROOT / "assets" / "gallery"

sys.path.insert(0, str(SCRIPTS_DIR))
import chart_grammar as cg  # noqa: E402
import origin_renderer as ornd  # noqa: E402


def _make_synthetic_nyquist_spec(style_preset: str) -> cg.FigureSpec:
    """Analytical Randles + finite-Warburg impedance spectra for Sample 1, Sample 2, Sample 3."""
    freqs = np.logspace(5.2, -1.6, 56)
    omega = 2.0 * np.pi * freqs
    params = [
        ("Sample 1", 22.0, 145.0, 1.8e-5, 210.0, "#2B6CB0"),
        ("Sample 2", 18.0, 92.0, 2.2e-5, 165.0, "#D84B5C"),
        ("Sample 3", 15.0, 58.0, 2.6e-5, 125.0, "#6579BE"),
    ]
    main_series: List[cg.SeriesSpec] = []
    inset_series: List[cg.SeriesSpec] = []
    for name, rs, rct, cdl, sigma_w, color in params:
        z_faradaic = rct + sigma_w * (1.0 - 1j) / np.sqrt(omega)
        z_tot = rs + 1.0 / (1j * omega * cdl + 1.0 / z_faradaic)
        zr = np.round(z_tot.real, 3).tolist()
        nzi = np.round(-z_tot.imag, 3).tolist()
        s_main = cg.SeriesSpec(
            name=name, x=zr, y=nzi, color=color, line_style="solid", marker_style="circle_solid"
        )
        s_ins = cg.SeriesSpec(
            name=name, x=zr, y=nzi, color=color, line_style="solid", marker_style="circle_solid"
        )
        main_series.append(s_main)
        inset_series.append(s_ins)

    panel = cg.PanelSpec(
        panel_id="nyquist_main",
        equal_aspect=True,
        legend_style="corner_upper_right",
        x_axis=cg.AxisSpec(label="Z' (Ohm)", axis_kind="quantitative", limits=(0.0, 1500.0), major_step=500.0),
        y1_axis=cg.AxisSpec(label="-Z'' (Ohm)", axis_kind="quantitative", limits=(0.0, 1500.0), major_step=500.0),
        layers=[cg.LayerSpec(layer_id="eis_curves", mark="line_scatter", series=main_series)],
        insets=[
            cg.InsetSpec(
                inset_id="hf_zoom",
                mode="zoom",
                bbox_pct=(45.0, 40.0, 46.0, 46.0),
                xlim=(0.0, 200.0),
                ylim=(0.0, 200.0),
                equal_aspect=True,
                show_zoom_box=True,
                zoom_box_color="#6579BE",
                layers=[cg.LayerSpec(layer_id="eis_hf", mark="line_scatter", series=inset_series)],
            )
        ],
    )
    return cg.FigureSpec(
        title=f"Synthetic_EIS_Nyquist_{style_preset}",
        mode="curve_with_inset",
        style_preset=style_preset,
        build_opju=False,
        panels=[panel],
    )


def _make_synthetic_dual_y_spec(style_preset: str) -> cg.FigureSpec:
    """Synthetic 6-sample 100% stacked phase composition + dual-Y quantitative metric."""
    cats = [f"Sample {i}" for i in range(1, 7)]
    p_alpha = [18.0, 22.0, 28.0, 35.0, 42.0, 48.0]
    p_beta = [52.0, 48.0, 44.0, 39.0, 34.0, 31.0]
    p_gamma = [30.0, 30.0, 28.0, 26.0, 24.0, 21.0]
    rate_ret = [42.0, 51.0, 63.0, 74.0, 83.0, 89.0]
    coul_eff = [78.0, 82.0, 86.0, 90.0, 93.0, 95.0]

    panel = cg.PanelSpec(
        panel_id="dual_main",
        align_zero=True,
        legend_style="interior_top",
        x_axis=cg.AxisSpec(label="", axis_kind="categorical", categories=cats),
        y1_axis=cg.AxisSpec(label="Phase Fraction (%)", axis_kind="dual_y_left", color="#111111"),
        y2_axis=cg.AxisSpec(label="Retention Index (%)", axis_kind="dual_y_right", color="#A02333"),
        layers=[
            cg.LayerSpec(
                layer_id="stack100",
                mark="bar_stacked_100pct",
                y_axis="y1",
                categories=cats,
                series=[
                    cg.SeriesSpec(name="Phase A", x=cats, y=p_alpha, color="#A8C4E8"),
                    cg.SeriesSpec(name="Phase B", x=cats, y=p_beta, color="#3E86DE"),
                    cg.SeriesSpec(name="Phase C", x=cats, y=p_gamma, color="#D84B5C"),
                ],
            ),
            cg.LayerSpec(
                layer_id="metric_lines",
                mark="line_scatter",
                y_axis="y2",
                categories=cats,
                series=[
                    cg.SeriesSpec(
                        name="Metric 1", x=cats, y=rate_ret, color="#A02333", marker_style="circle_solid"
                    ),
                    cg.SeriesSpec(
                        name="Metric 2", x=cats, y=coul_eff, color="#111111", marker_style="circle_open"
                    ),
                ],
            ),
        ],
    )
    return cg.FigureSpec(
        title=f"Synthetic_DualY_Combo_{style_preset}",
        mode="dual_y_combo",
        style_preset=style_preset,
        build_opju=False,
        panels=[panel],
    )


def _make_synthetic_contour_spec() -> cg.FigureSpec:
    """Analytical 2D Gaussian relaxation-time distribution field across 10 states."""
    log_tau = np.linspace(-5.0, 1.0, 120)
    n_states = 10
    states = [f"Sample {i}" for i in range(1, n_states + 1)]
    z_mat = np.zeros((n_states, len(log_tau)), dtype=float)
    for idx in range(n_states):
        prog = idx / float(n_states - 1)
        c1 = -3.4 + 0.55 * prog
        amp1 = 35.0 + 75.0 * prog
        c2 = -1.1 + 0.45 * prog
        amp2 = 55.0 + 135.0 * (prog ** 1.3)
        z_mat[idx, :] = amp1 * np.exp(-0.5 * ((log_tau - c1) / 0.36) ** 2) + amp2 * np.exp(
            -0.5 * ((log_tau - c2) / 0.44) ** 2
        )

    panel = cg.PanelSpec(
        panel_id="drt_2d",
        equal_aspect=True,
        x_axis=cg.AxisSpec(label="log_10(tau / s)", axis_kind="quantitative", limits=(-5.0, 1.0)),
        y1_axis=cg.AxisSpec(label="", axis_kind="categorical", categories=states),
        z_axis=cg.AxisSpec(label="gamma(tau) (Ohm)", axis_kind="quantitative", limits=(0.0, 200.0)),
        layers=[
            cg.LayerSpec(
                layer_id="field2d",
                mark="contour_pseudocolor",
                color_scheme="pseudocolor_zero_white",
                hide_contour_lines=True,
                series=[
                    cg.SeriesSpec(
                        name="SyntheticDRT",
                        matrix_x=log_tau.tolist(),
                        matrix_y=list(range(1, n_states + 1)),
                        matrix_z=np.round(z_mat, 3).tolist(),
                        meta={"state_labels": states},
                    )
                ],
            )
        ],
    )
    return cg.FigureSpec(
        title="Synthetic_DRT_Contour2D",
        mode="contour_pseudocolor_2d",
        style_preset="style_publication_minimal",
        build_opju=False,
        panels=[panel],
    )


def _make_synthetic_box_jitter_spec() -> cg.FigureSpec:
    """Deterministic synthetic 6-group replicate distribution."""
    rng = np.random.default_rng(42)
    centers = [0.92, 1.01, 1.12, 1.24, 1.18, 1.31]
    series_list: List[cg.SeriesSpec] = []
    cats = [f"Sample {i}" for i in range(1, 7)]
    for idx, mu in enumerate(centers):
        vals = np.round(mu + rng.normal(0.0, 0.045, size=7), 3).tolist()
        series_list.append(cg.SeriesSpec(name=cats[idx], y=vals, meta={"label": cats[idx]}))

    panel = cg.PanelSpec(
        panel_id="box_main",
        legend_style="none",
        x_axis=cg.AxisSpec(label="", axis_kind="categorical", categories=cats),
        y1_axis=cg.AxisSpec(label="Intensity Ratio (I_D / I_G)", axis_kind="quantitative"),
        layers=[cg.LayerSpec(layer_id="box_jit", mark="stat_distribution", series=series_list)],
    )
    return cg.FigureSpec(
        title="Synthetic_BoxJitter_Distribution",
        mode="stat_distribution",
        style_preset="style_publication_minimal",
        build_opju=False,
        panels=[panel],
    )


def main() -> int:
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    jobs: Dict[str, cg.FigureSpec] = {
        "demo_dual_y_tnr": _make_synthetic_dual_y_spec("style_publication_minimal"),
        "demo_dual_y_arial": _make_synthetic_dual_y_spec("style_arial_clean"),
        "demo_nyquist_tnr": _make_synthetic_nyquist_spec("style_publication_minimal"),
        "demo_nyquist_arial": _make_synthetic_nyquist_spec("style_arial_clean"),
        "demo_drt_contour": _make_synthetic_contour_spec(),
        "demo_box_jitter": _make_synthetic_box_jitter_spec(),
    }
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sciorigin_syn_") as tmp:
        tmp_p = Path(tmp)
        for out_name, spec in jobs.items():
            spec.title = out_name
            print(f"Rendering synthetic showcase: {out_name} ...", flush=True)
            res = ornd.render_figure_spec_origin(spec, tmp_p, export_images=True)
            qa_jpg = Path(res["primary_figures"]["qa_preview_jpg"])
            dst = GALLERY_DIR / f"{out_name}.jpg"
            shutil.copy2(qa_jpg, dst)
            print(f"  -> Saved {dst} ({dst.stat().st_size // 1024} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
