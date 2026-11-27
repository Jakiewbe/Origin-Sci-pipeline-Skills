"""
gallery_part3_declarative.py - Part 3 Synthetic Declarative Grammar Showcase Generator for SciOrigin v8.0.

Renders 11 publication-grade figures (6 upgraded core demos + 5 brand-new declarative grammar modes)
natively in headless OriginPro 2024 (`skip_origin=False`), downscaling exported 300 DPI PNGs via
`PIL.Image` (`LANCZOS`) to crisp `1440 px` long-edge RGB JPEGs (`quality=90, subsampling=0`).

Zero external or private datasets required: 100% pure analytical/mathematical synthetic functions.
"""
from __future__ import annotations

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


def _make_synthetic_nyquist_spec(style_preset: str) -> cg.FigureSpec:
    """Analytical modified Randles + blocking/Warburg impedance spectra filling 4:3 `[0..1200, 0..900]` Ohm cleanly."""
    freqs = np.logspace(5.2, -1.64, 42)
    omega = 2.0 * np.pi * freqs
    params = [
        ("Sample 1", 18.0, 122.0, 2.2e-5, 145.0, 0.0155, "#2B6CB0"),
        ("Sample 2", 14.0, 86.0, 2.6e-5, 118.0, 0.0175, "#D84B5C"),
        ("Sample 3", 10.0, 56.0, 3.0e-5, 92.0, 0.0198, "#6579BE"),
    ]
    main_series: List[cg.SeriesSpec] = []
    inset_series: List[cg.SeriesSpec] = []
    for name, rs, rct, cdl, sigma_w, c_lim, color in params:
        z_faradaic = rct + sigma_w * (1.0 - 1j) / np.sqrt(omega)
        z_tot = rs + 1.0 / (1j * omega * cdl + 1.0 / z_faradaic) - 1j / (omega * c_lim)
        zr = np.round(z_tot.real, 3).tolist()
        nzi = np.round(-z_tot.imag, 3).tolist()
        main_series.append(
            cg.SeriesSpec(
                name=name, x=zr, y=nzi, color=color, line_style="solid", marker_style="circle_solid"
            )
        )
        inset_series.append(
            cg.SeriesSpec(
                name=name, x=zr, y=nzi, color=color, line_style="solid", marker_style="circle_solid"
            )
        )

    panel = cg.PanelSpec(
        panel_id="nyquist_main",
        equal_aspect=True,
        legend_style="corner_upper_right",
        x_axis=cg.AxisSpec(label="Z' (Ohm)", axis_kind="quantitative", limits=(0.0, 1200.0), major_step=300.0),
        y1_axis=cg.AxisSpec(label="-Z'' (Ohm)", axis_kind="quantitative", limits=(0.0, 900.0), major_step=300.0),
        layers=[cg.LayerSpec(layer_id="eis_curves", mark="line_scatter", series=main_series)],
        insets=[
            cg.InsetSpec(
                inset_id="hf_zoom",
                mode="zoom",
                bbox_pct=(51.0, 44.0, 42.0, 42.0),
                xlim=(0.0, 200.0),
                ylim=(0.0, 150.0),
                equal_aspect=True,
                show_zoom_box=True,
                zoom_box_color="#6579BE",
                x_axis=cg.AxisSpec(which="x", label="", axis_kind="inset", limits=(0.0, 200.0), major_step=100.0),
                y_axis=cg.AxisSpec(which="y1", label="", axis_kind="inset", limits=(0.0, 150.0), major_step=75.0),
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


def _make_synthetic_bar_grouped_spec() -> cg.FigureSpec:
    """Synthetic 5-group semantic vertical column chart with 1.5 pt dark borders, SD error bars, and bold top value labels."""
    cats = ["Group A", "Group B", "Group C", "Group D", "Group E"]
    bar_colors = ["#2B6CB0", "#3E86DE", "#6579BE", "#D84B5C", "#A02333"]
    cfg = {
        "title": "demo_bar_grouped_gradient",
        "mode": "bar_grouped_gradient",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "categories": cats,
        "x_label": "",
        "y_label": "Specific Activity (mA cm^{-2})",
        "y_limits": [0.0, 120.0],
        "show_value_labels": True,
        "value_format": "{:.1f}",
        "per_bar_semantic": True,
        "series": [
            {
                "name": "Specific Activity",
                "values": [34.6, 48.2, 63.5, 79.4, 92.8],
                "errors": [2.2, 2.7, 3.1, 3.5, 3.9],
                "bar_colors": bar_colors,
            }
        ],
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    spec.panels[0].y1_axis.major_step = 20.0
    return spec


def _make_synthetic_bar_stacked_abs_spec() -> cg.FigureSpec:
    """Synthetic 4-component absolute overpotential/loss decomposition stacked column chart across 5 conditions."""
    cats = ["Group A", "Group B", "Group C", "Group D", "Group E"]
    cfg = {
        "title": "demo_bar_stacked_abs",
        "mode": "bar_stacked",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "categories": cats,
        "x_label": "",
        "y_label": "Overpotential (mV)",
        "color_scheme": "sandwich_stack",
        "legend_style": "interior_top",
        "stacks": [
            {"name": "Ohmic Loss", "values": [64.0, 55.0, 46.0, 39.0, 33.0], "color": "#A8C4E8"},
            {"name": "Charge Transfer", "values": [118.0, 96.0, 76.0, 58.0, 45.0], "color": "#3E86DE"},
            {"name": "Surface Film", "values": [86.0, 72.0, 58.0, 44.0, 34.0], "color": "#D84B5C"},
            {"name": "Mass Diffusion", "values": [72.0, 59.0, 48.0, 37.0, 28.0], "color": "#A02333"},
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_synthetic_bar_stacked_100pct_spec() -> cg.FigureSpec:
    """Synthetic 0..100% normalized chemical species evolution sandwich-palette stacked column chart across 6 states."""
    states = [f"State {i}" for i in range(1, 7)]
    cfg = {
        "title": "demo_bar_stacked_100pct",
        "mode": "bar_stacked_100pct",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "categories": states,
        "x_label": "",
        "y_label": "Species Fraction (%)",
        "color_scheme": "sandwich_stack",
        "legend_style": "interior_top",
        "stacks": [
            {"name": "Species I", "values": [48.0, 40.0, 32.0, 25.0, 18.0, 13.0], "color": "#A8C4E8"},
            {"name": "Species II", "values": [28.0, 30.0, 30.0, 28.0, 25.0, 21.0], "color": "#3E86DE"},
            {"name": "Species III", "values": [16.0, 19.0, 24.0, 29.0, 34.0, 38.0], "color": "#D84B5C"},
            {"name": "Species IV", "values": [8.0, 11.0, 14.0, 18.0, 23.0, 28.0], "color": "#A02333"},
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_synthetic_xy_fit_band_spec() -> cg.FigureSpec:
    """Synthetic 2D scatter + linear regression fit curve + translucent 95% confidence band + italic equation & R^2."""
    x_vals = np.linspace(4.0, 48.0, 16)
    offsets = np.array(
        [3.6, -4.2, 4.5, -4.8, 2.9, -4.1, 4.9, -3.2, 3.8, -4.6, -2.4, -4.3, 2.7, -4.5, 4.1, -2.8],
        dtype=float,
    )
    y_vals = 2.12 * x_vals + 36.0 + offsets

    cfg = {
        "title": "demo_xy_fit_band",
        "mode": "xy_fit_and_band",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "x": np.round(x_vals, 2).tolist(),
        "y": np.round(y_vals, 2).tolist(),
        "x_label": "Ionic Conductivity (mS cm^{-1})",
        "y_label": "Reversible Capacity (mAh g^{-1})",
        "model": "linear",
        "ci_level": 0.95,
        "color": "#2B6CB0",
        "scatter_name": "Experimental",
        "fit_name": "Linear Fit (95% CI)",
        "marker_style": "circle_solid",
        "marker_size_pt": 7.5,
        "legend_style": "corner_upper_left",
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    eq_raw = str(spec.panels[0].meta.get("regression_equation", ""))
    if eq_raw and " * x" not in eq_raw:
        spec.panels[0].meta["regression_equation"] = eq_raw.replace("x", " * x")
    return spec


def _make_synthetic_matrix_heatmap_spec() -> cg.FigureSpec:
    """Synthetic 6x6 structure-property Pearson correlation matrix heatmap with diverging blue-white-red RIFF .pal."""
    labels = ["tau", "R_ct", "D_ion", "sigma_e", "Q_rev", "E_1/2"]
    # Positive-definite synthetic structure-property correlation matrix:
    # (tau, R_ct) impedance resistance block negatively correlated with transport/capacity (D_ion, sigma_e, Q_rev, E_1/2)
    corr = np.array(
        [
            [1.00, 0.86, -0.78, -0.69, -0.82, -0.58],
            [0.86, 1.00, -0.74, -0.84, -0.79, -0.66],
            [-0.78, -0.74, 1.00, 0.64, 0.85, 0.72],
            [-0.69, -0.84, 0.64, 1.00, 0.76, 0.68],
            [-0.82, -0.79, 0.85, 0.76, 1.00, 0.81],
            [-0.58, -0.66, 0.72, 0.68, 0.81, 1.00],
        ],
        dtype=float,
    )
    eigvals = np.linalg.eigvalsh(corr)
    if float(np.min(eigvals)) <= 0.0:
        raise ValueError(f"Synthetic correlation matrix must be positive definite; min eig={np.min(eigvals):.4f}")

    cfg = {
        "title": "demo_matrix_heatmap",
        "mode": "matrix_heatmap",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "color_scheme": "diverging_blue_white_red",
        "center_zero": True,
        "equal_aspect": True,
        "show_value_labels": True,
        "value_format": ".2f",
        "z_label": "Pearson r",
        "z_limits": [-1.0, 1.0],
        "x_labels": labels,
        "y_labels": labels,
        "matrix_z": corr.tolist(),
    }
    spec = cg.compile_config_to_figure_spec(cfg)
    # Use 14.5 pt cell callouts so 5-char negative correlation values (-0.84) fit inside 6x6 cells with crisp padding
    spec.theme = dict(spec.theme, callout_font_size=14.5)
    return spec


def build_part3_jobs() -> Dict[str, cg.FigureSpec]:
    """Return the ordered mapping of all 11 Part 3 gallery output stems to declarative `FigureSpec` objects."""
    return {
        "demo_dual_y_tnr": _make_synthetic_dual_y_spec("style_publication_minimal"),
        "demo_dual_y_arial": _make_synthetic_dual_y_spec("style_arial_clean"),
        "demo_nyquist_tnr": _make_synthetic_nyquist_spec("style_publication_minimal"),
        "demo_nyquist_arial": _make_synthetic_nyquist_spec("style_arial_clean"),
        "demo_drt_contour": _make_synthetic_contour_spec(),
        "demo_box_jitter": _make_synthetic_box_jitter_spec(),
        "demo_bar_grouped_gradient": _make_synthetic_bar_grouped_spec(),
        "demo_bar_stacked_abs": _make_synthetic_bar_stacked_abs_spec(),
        "demo_bar_stacked_100pct": _make_synthetic_bar_stacked_100pct_spec(),
        "demo_xy_fit_band": _make_synthetic_xy_fit_band_spec(),
        "demo_matrix_heatmap": _make_synthetic_matrix_heatmap_spec(),
    }


def _downscale_png_to_gallery_jpg(png_path: Path, dst_jpg: Path, long_edge_px: int = 1440) -> tuple[int, int]:
    """Downscale 300 DPI Origin PNG via LANCZOS to crisp RGB JPEG (`quality=90, subsampling=0`)."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as im:
        im_rgb = im.convert("RGB")
        w, h = im_rgb.size
        scale = float(long_edge_px) / float(max(w, h))
        target_wh = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
        im_out = im_rgb.resize(target_wh, Image.Resampling.LANCZOS)
        im_out.save(dst_jpg, format="JPEG", quality=90, subsampling=0, optimize=True)
    return target_wh


def _render_single_job_inprocess(out_name: str, gallery_dir: Path) -> Path:
    """Render one Part 3 figure in the current process (fresh OriginExt COM pointer when invoked via subprocess)."""
    jobs = build_part3_jobs()
    if out_name not in jobs:
        raise KeyError(f"Unknown Part 3 figure job: {out_name!r}")
    spec = jobs[out_name]
    spec.title = out_name
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"sciorigin_p3_{out_name}_") as fig_tmp_str:
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


def generate_part3(gallery_dir: Path = GALLERY_DIR, only_names: List[str] | None = None) -> List[Path]:
    """Render all 11 Part 3 declarative showcase figures natively in headless OriginPro 2024."""
    import subprocess

    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_part3_jobs()
    target_names = [k for k in jobs.keys() if (not only_names or k in set(only_names))]

    saved_paths: List[Path] = []
    script_path = str(Path(__file__).resolve())
    for out_name in target_names:
        print(f"[Part 3] Rendering native OriginPro showcase: {out_name} ...", flush=True)
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

    parser = argparse.ArgumentParser(description="Render Part 3 SciOrigin declarative showcase figures.")
    parser.add_argument("--single", type=str, default=None, help="Internal single-figure worker target.")
    parser.add_argument("--gallery-dir", type=Path, default=GALLERY_DIR, help="Output gallery directory.")
    parser.add_argument("names", nargs="*", help="Optional subset of figure stems to render.")
    cli_args = parser.parse_args()
    if cli_args.single:
        _render_single_job_inprocess(cli_args.single, cli_args.gallery_dir)
    else:
        generate_part3(cli_args.gallery_dir, only_names=(cli_args.names or None))
