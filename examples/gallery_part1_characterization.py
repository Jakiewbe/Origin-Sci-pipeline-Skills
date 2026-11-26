"""
gallery_part1_characterization.py - Synthetic Characterization & Deconvolution Showcase (Part 1: 9 Figures).

Generates 9 publication-ready spectroscopy, diffraction, porosity, particle-size, EPR, and powder-compaction
figures via 100% headless OriginPro 2024 COM (`origin_builder.py`), using pure analytical mathematical curves
with zero external or confidential datasets.

Usage:
    python examples/gallery_part1_characterization.py
"""
from __future__ import annotations

import math
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "skills" / "sci-origin-pipeline" / "scripts"
GALLERY_DIR = REPO_ROOT / "assets" / "gallery"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fitting  # noqa: E402
import origin_builder as ob  # noqa: E402
import origin_theme as ot  # noqa: E402
import validator  # noqa: E402

SINGLE_LONG_EDGE_PX = 1440
GRID_LONG_EDGE_PX = 1800


@contextmanager
def _pre_export_hook(hook_fn: Optional[Callable[[Any, Any], None]]) -> Iterator[None]:
    """Run an optional native OriginPro overlay customization hook right before `flush_page_overlays`."""
    if hook_fn is None:
        yield
        return
    orig_export = ob.export_origin_publication_figures

    def _wrapped_export(
        op: Any,
        gp: Any,
        out_dir: str | Path,
        stem: str,
        width_in: float = 0.0,
        make_qa_preview: bool = True,
    ) -> Dict[str, str]:
        hook_fn(op, gp)
        return orig_export(op, gp, out_dir, stem, width_in=width_in, make_qa_preview=make_qa_preview)

    ob.export_origin_publication_figures = _wrapped_export  # type: ignore[assignment]
    try:
        yield
    finally:
        ob.export_origin_publication_figures = orig_export  # type: ignore[assignment]


def _downscale_png_to_gallery_jpg(png_path: Path, dst_jpg: Path, long_edge_px: int) -> Tuple[int, int]:
    """Downscale 300 DPI Origin-exported PNG via LANCZOS to RGB JPEG (`quality=90, subsampling=0`)."""
    dst_jpg.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as im:
        im_rgb = im.convert("RGB")
        w, h = im_rgb.size
        scale = float(long_edge_px) / float(max(w, h))
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        if (new_w, new_h) != (w, h):
            im_rgb = im_rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)
        im_rgb.save(dst_jpg, format="JPEG", quality=90, subsampling=0, optimize=True)
    return new_w, new_h


def _run_with_com_retry(
    job_name: str,
    render_once_fn: Callable[[Path], Path],
    dst_jpg: Path,
    long_edge_px: int,
) -> Path:
    """Execute a single-figure headless OriginPro COM job with 5-attempt lock-timeout retry."""
    for attempt in range(5):
        try:
            ob.set_active_style("style_publication_minimal")
            with tempfile.TemporaryDirectory(prefix=f"sciorigin_p1_{job_name}_") as tmp_s:
                tmp_dir = Path(tmp_s)
                png_path = render_once_fn(tmp_dir)
                if not png_path.exists() or png_path.stat().st_size == 0:
                    raise RuntimeError(f"Exported PNG missing or empty for {job_name}: {png_path}")
                w, h = _downscale_png_to_gallery_jpg(png_path, dst_jpg, long_edge_px)
                sz_kb = dst_jpg.stat().st_size / 1024.0
                print(f"  [OK] {dst_jpg.name}: {w}x{h} px ({sz_kb:.1f} KB)", flush=True)
                return dst_jpg
        except TimeoutError:
            if attempt == 4:
                raise
            print(f"  [LOCK WAIT] {job_name} attempt {attempt + 1}/5 timed out on COM mutex; retrying in 6s...", flush=True)
            time.sleep(6)
    raise RuntimeError(f"Unreachable retry exhaustion for {job_name}")


def _synthesise_shirley_step(x: np.ndarray, net_signal: np.ndarray, y_low_be: float, y_high_be: float) -> np.ndarray:
    """Analytical cumulative-area inelastic step background matching XPS photoelectron physics."""
    dx = np.gradient(x)
    pos = np.maximum(net_signal, 0.0)
    tot = max(float(np.sum(pos * dx)), 1e-12)
    cum = np.cumsum(pos * dx) / tot
    return y_low_be + (y_high_be - y_low_be) * cum


# ---------------------------------------------------------------------------
# 1. demo_xps_deconv.jpg
# ---------------------------------------------------------------------------
def _render_xps_deconv(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202601)
    x = np.linspace(282.0, 296.0, 281)
    net_true = (
        fitting.pseudo_voigt_area(x, area=21500.0, center=284.80, fwhm=1.18, eta=0.25)
        + fitting.pseudo_voigt_area(x, area=8600.0, center=286.32, fwhm=1.30, eta=0.25)
        + fitting.pseudo_voigt_area(x, area=4900.0, center=287.82, fwhm=1.38, eta=0.25)
        + fitting.pseudo_voigt_area(x, area=3200.0, center=289.22, fwhm=1.46, eta=0.25)
    )
    bg_true = _synthesise_shirley_step(x, net_true, y_low_be=1350.0, y_high_be=3650.0)
    y_raw = bg_true + net_true + rng.normal(0.0, 145.0, size=len(x))

    c1s_preset: Dict[str, Any] = {
        "x_window": [282.0, 296.0],
        "invert_x": True,
        "x_label": "Binding Energy (eV)",
        "y_label": "Intensity (a.u.)",
        "baseline": "shirley",
        "subgroup_name": None,
        "components": [
            {
                "name": "C-C/C=C",
                "label": "C-C / C=C",
                "center": 284.80,
                "center_bounds": [284.50, 285.10],
                "fwhm": 1.20,
                "fwhm_bounds": [0.90, 1.65],
                "eta": 0.25,
                "color": "#3E86DE",
            },
            {
                "name": "C-O",
                "label": "C-O",
                "center": 286.30,
                "center_bounds": [285.95, 286.70],
                "fwhm": 1.32,
                "fwhm_bounds": [0.95, 1.80],
                "eta": 0.25,
                "color": "#6579BE",
            },
            {
                "name": "C=O",
                "label": "C=O",
                "center": 287.80,
                "center_bounds": [287.35, 288.25],
                "fwhm": 1.38,
                "fwhm_bounds": [1.00, 1.90],
                "eta": 0.25,
                "color": "#D84B5C",
            },
            {
                "name": "O-C=O",
                "label": "O-C=O",
                "center": 289.20,
                "center_bounds": [288.75, 289.70],
                "fwhm": 1.45,
                "fwhm_bounds": [1.05, 2.05],
                "eta": 0.25,
                "color": "#E8A3AF",
            },
        ],
    }
    fit_res = fitting.deconvolve_spectrum(x, y_raw, c1s_preset)

    def _xps_hook(_op: Any, gp: Any) -> None:
        legs = ob._PENDING_LEGENDS.get(gp.name, [])
        if legs and legs[0].get("entries"):
            e0 = legs[0]["entries"][0]
            legs[0]["entries"][0] = ("Exp. Data", e0[1], e0[2])

    figs_out: Dict[str, Dict[str, str]] = {}
    with _pre_export_hook(_xps_hook):
        ob.build_deconv_opju(
            {"C1s": fit_res},
            tmp_dir / "demo_xps_deconv.opju",
            sample_name="Sample A",
            export_dir=tmp_dir,
            stem_template="demo_xps_deconv",
            region_titles={"C1s": "Sample A  (XPS C 1s)"},
            exported_figures_out=figs_out,
        )
    return Path(figs_out["C1s"]["png"])


# ---------------------------------------------------------------------------
# 2. demo_model_sensitivity.jpg
# ---------------------------------------------------------------------------
def _render_model_sensitivity(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202602)
    x = np.linspace(682.0, 694.0, 241)
    # True 4-component overlapping multiplet spectrum:
    # Comp 1 (685.05 eV), Comp 2 (687.25 eV), Comp 3 dominant (688.68 eV), Comp 4 shoulder (689.85 eV)
    net_true = (
        fitting.pseudo_voigt_area(x, area=4600.0, center=685.05, fwhm=1.48, eta=0.30)
        + fitting.pseudo_voigt_area(x, area=6800.0, center=687.25, fwhm=1.52, eta=0.25)
        + fitting.pseudo_voigt_area(x, area=19800.0, center=688.68, fwhm=1.55, eta=0.25)
        + fitting.pseudo_voigt_area(x, area=6400.0, center=689.85, fwhm=1.62, eta=0.25)
    )
    bg_true = _synthesise_shirley_step(x, net_true, y_low_be=1100.0, y_high_be=2950.0)
    y_raw = bg_true + net_true + rng.normal(0.0, 115.0, size=len(x))

    models_cfg: List[Tuple[str, Dict[str, Any]]] = [
        (
            "Model M1 (Strict Window)",
            {
                "x_window": [682.0, 694.0],
                "invert_x": True,
                "x_label": "Binding Energy (eV)",
                "y_label": "Intensity (a.u.)",
                "baseline": "shirley",
                "components": [
                    {"name": "Peak 1", "label": "Peak 1", "center": 685.05, "center_bounds": [684.6, 685.5], "fwhm": 1.50, "fwhm_bounds": [1.05, 2.10], "eta": 0.30, "color": "#D84B5C"},
                    {"name": "Peak 2", "label": "Peak 2", "center": 686.80, "center_bounds": [686.2, 687.2], "fwhm": 1.55, "fwhm_bounds": [1.05, 2.15], "eta": 0.25, "color": "#E8A3AF"},
                    {"name": "Peak 3", "label": "Peak 3", "center": 687.90, "center_bounds": [687.4, 688.25], "fwhm": 1.60, "fwhm_bounds": [1.10, 2.25], "eta": 0.25, "color": "#3E86DE"},
                    {"name": "Peak 4", "label": "Peak 4", "center": 689.10, "center_bounds": [688.5, 690.2], "fwhm": 1.70, "fwhm_bounds": [1.10, 2.40], "eta": 0.25, "color": "#6579BE"},
                ],
            },
        ),
        (
            "Model M2 (Peak-Anchored)",
            {
                "x_window": [682.0, 694.0],
                "invert_x": True,
                "x_label": "Binding Energy (eV)",
                "y_label": "Intensity (a.u.)",
                "baseline": "shirley",
                "fwhm_reg_strength": 0.05,
                "max_fwhm_rel_spread": 0.18,
                "components": [
                    {"name": "Peak 1", "label": "Peak 1", "center": 685.05, "center_bounds": [684.6, 685.6], "fwhm": 1.48, "fwhm_bounds": [1.05, 2.05], "eta": 0.30, "color": "#D84B5C"},
                    {"name": "Peak 2", "label": "Peak 2", "center": 687.25, "center_bounds": [686.6, 687.8], "fwhm": 1.52, "fwhm_bounds": [1.10, 2.05], "eta": 0.25, "color": "#E8A3AF"},
                    {"name": "Peak 3", "label": "Peak 3", "center": 688.68, "center_bounds": [688.1, 689.1], "fwhm": 1.55, "fwhm_bounds": [1.10, 2.10], "eta": 0.25, "color": "#3E86DE"},
                    {"name": "Peak 4", "label": "Peak 4", "center": 689.85, "center_bounds": [689.2, 690.6], "fwhm": 1.62, "fwhm_bounds": [1.10, 2.25], "eta": 0.25, "color": "#6579BE"},
                ],
            },
        ),
        (
            "Model M3 (Shifted Split)",
            {
                "x_window": [682.0, 694.0],
                "invert_x": True,
                "x_label": "Binding Energy (eV)",
                "y_label": "Intensity (a.u.)",
                "baseline": "shirley",
                "fwhm_reg_strength": 0.04,
                "max_fwhm_rel_spread": 0.20,
                "components": [
                    {"name": "Peak 1", "label": "Peak 1", "center": 685.05, "center_bounds": [684.6, 685.6], "fwhm": 1.48, "fwhm_bounds": [1.05, 2.05], "eta": 0.30, "color": "#D84B5C"},
                    {"name": "Peak 2", "label": "Peak 2", "center": 687.55, "center_bounds": [686.8, 687.75], "fwhm": 1.50, "fwhm_bounds": [1.05, 2.05], "eta": 0.25, "color": "#E8A3AF"},
                    {"name": "Peak 3", "label": "Peak 3", "center": 688.25, "center_bounds": [687.85, 688.45], "fwhm": 1.48, "fwhm_bounds": [1.05, 1.95], "eta": 0.25, "color": "#3E86DE"},
                    {"name": "Peak 4", "label": "Peak 4", "center": 689.05, "center_bounds": [688.70, 689.55], "fwhm": 1.55, "fwhm_bounds": [1.05, 2.05], "eta": 0.25, "color": "#6579BE"},
                ],
            },
        ),
        (
            "Model M4 (3-Peak Underfit)",
            {
                "x_window": [682.0, 694.0],
                "invert_x": True,
                "x_label": "Binding Energy (eV)",
                "y_label": "Intensity (a.u.)",
                "baseline": "shirley",
                "fwhm_reg_strength": 0.05,
                "max_fwhm_rel_spread": 0.20,
                "components": [
                    {"name": "Peak 2", "label": "Peak 2", "center": 687.20, "center_bounds": [685.8, 687.8], "fwhm": 1.55, "fwhm_bounds": [1.10, 2.05], "eta": 0.25, "color": "#E8A3AF"},
                    {"name": "Peak 3", "label": "Peak 3", "center": 688.68, "center_bounds": [688.1, 689.1], "fwhm": 1.58, "fwhm_bounds": [1.10, 2.10], "eta": 0.25, "color": "#3E86DE"},
                    {"name": "Peak 4", "label": "Peak 4", "center": 689.85, "center_bounds": [689.2, 690.6], "fwhm": 1.65, "fwhm_bounds": [1.10, 2.25], "eta": 0.25, "color": "#6579BE"},
                ],
            },
        ),
    ]

    panel_items: List[Dict[str, Any]] = []
    badge_specs: List[Tuple[str, str, str]] = []
    for m_title, m_cfg in models_cfg:
        f_res = fitting.deconvolve_spectrum(x, y_raw, m_cfg)
        validator.audit_deconv_region(m_title, f_res, m_cfg)
        panel_items.append({"name": m_title, "fit": f_res})
        flags = f_res.get("audit_flags", [])
        cen_flags = [fl for fl in flags if fl.startswith("CEN_BOUND:")]
        nrmse_v = float(f_res["nrmse_pct"])
        if nrmse_v > 2.8:
            badge_line1 = "HIGH_NRMSE (Underfit)"
            badge_col = "#A02333"
        elif cen_flags:
            first_hit = cen_flags[0].split(":")[1].split(",")[0].split("(")[0]
            badge_line1 = f"CEN_BOUND ({first_hit})"
            badge_col = "#D84B5C"
        else:
            badge_line1 = "AUDIT PASS (Optimal)"
            badge_col = "#2B6CB0"
        badge_line2 = f"NRMSE = {nrmse_v:.2f}%"
        badge_specs.append((badge_line1, badge_line2, badge_col))

    def _grid_hook(op: Any, gp: Any) -> None:
        # Place shared legend cleanly across the top grid header (`above_frame_grid`)
        legs = ob._PENDING_LEGENDS.get(gp.name, [])
        if legs:
            legs[0]["pos_mode"] = "above_frame_grid"
            legs[0]["fallback_rect_pct"] = (11.02, 11.20, 80.52, 27.72)
            legs[0]["fontsize"] = 13.5

        # Expand top Y-headroom in each subplot and place compact audit badges cleanly above the peak envelope
        cell_w, cell_h = 44.0, 42.0
        for idx, (b_l1, b_l2, b_hex) in enumerate(badge_specs):
            res_i = panel_items[idx]["fit"]
            ymin_i = float(np.min(np.minimum(res_i["y_raw"], res_i["baseline"])))
            ymax_i = float(np.max(np.maximum(res_i["y_raw"], res_i["y_fit"])))
            yspan_i = max(ymax_i - ymin_i, 1e-6)
            ob.activate_layer(op, gp, idx + 1)
            gp[idx].set_ylim(ymin_i - 0.08 * yspan_i, ymax_i + 0.64 * yspan_i)

            r_i, c_i = idx // 2, idx % 2
            l_p = 7.5 + c_i * cell_w + cell_w * 0.08
            t_p = 7.5 + r_i * cell_h + cell_h * 0.11
            c_int = ot.hex_to_origin_rgb_int(b_hex)
            ink_sub = ot.hex_to_origin_rgb_int("#222222")
            ob.add_page_text_label(
                op, gp, gp[idx], idx + 1, f"AudBdgA_{idx+1}",
                b_l1, l_p + 1.8, t_p + 3.4,
                fontsize=11.2, color_int=c_int, pos_scatter=2, format_math=False,
            )
            ob.add_page_text_label(
                op, gp, gp[idx], idx + 1, f"AudBdgB_{idx+1}",
                b_l2, l_p + 1.8, t_p + 7.0,
                fontsize=10.8, color_int=ink_sub, pos_scatter=2, format_math=False,
            )

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_grid_hook):
        ob.build_deconv_grid_opju(
            panel_items,
            tmp_dir / "demo_model_sensitivity.opju",
            ncols=2,
            project_title="Model_Sensitivity",
            box_thickness=2.2,
            export_dir=tmp_dir,
            export_stem="demo_model_sensitivity",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 3. demo_raman_deconv.jpg
# ---------------------------------------------------------------------------
def _render_raman_deconv(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202603)
    x = np.linspace(1000.0, 1800.0, 321)
    net_true = (
        fitting.pseudo_voigt_area(x, area=26000.0, center=1190.0, fwhm=128.0, eta=0.0)
        + fitting.pseudo_voigt_area(x, area=158000.0, center=1348.0, fwhm=94.0, eta=0.75)
        + fitting.pseudo_voigt_area(x, area=44000.0, center=1505.0, fwhm=108.0, eta=0.0)
        + fitting.pseudo_voigt_area(x, area=108000.0, center=1590.0, fwhm=72.0, eta=0.65)
    )
    bg_true = 680.0 + 0.28 * (x - 1000.0)
    y_raw = bg_true + net_true + rng.normal(0.0, 26.0, size=len(x))

    raman_preset: Dict[str, Any] = {
        "x_window": [1000.0, 1800.0],
        "invert_x": False,
        "x_label": "Raman Shift (cm^-1)",
        "y_label": "Intensity (a.u.)",
        "baseline": "linear",
        "subgroup_name": None,
        "components": [
            {"name": "D*", "label": "D*", "center": 1190.0, "center_bounds": [1140.0, 1235.0], "fwhm": 128.0, "fwhm_bounds": [65.0, 220.0], "eta": 0.0, "color": "#C5DBF5"},
            {"name": "D", "label": "D", "center": 1348.0, "center_bounds": [1325.0, 1368.0], "fwhm": 94.0, "fwhm_bounds": [50.0, 165.0], "eta": 0.75, "color": "#D84B5C"},
            {"name": "D''", "label": "D''", "center": 1505.0, "center_bounds": [1470.0, 1538.0], "fwhm": 108.0, "fwhm_bounds": [55.0, 185.0], "eta": 0.0, "color": "#6579BE"},
            {"name": "G", "label": "G", "center": 1590.0, "center_bounds": [1572.0, 1608.0], "fwhm": 72.0, "fwhm_bounds": [40.0, 130.0], "eta": 0.65, "color": "#3E86DE"},
        ],
    }
    fit_res = fitting.deconvolve_spectrum(x, y_raw, raman_preset, laser_nm=532.0)
    id_ig = float(fit_res["extra_ratios"]["H_D_H_G_deconv"])
    ad_ag = float(fit_res["extra_ratios"]["A_D_A_G_area"])

    def _raman_hook(op: Any, gp: Any) -> None:
        legs = ob._PENDING_LEGENDS.get(gp.name, [])
        if legs and legs[0].get("entries"):
            e0 = legs[0]["entries"][0]
            legs[0]["entries"][0] = ("Exp. Data", e0[1], e0[2])

        spec = ob.get_active_spec()
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        l_p, t_p, _w_p, _h_p = ot.rect_in_to_page_pct(*box_in, pw, ph)
        ob.add_page_text_label(
            op, gp, gp[0], 1, "RamanRatioA",
            f"\\i(I)\\-(D) / \\i(I)\\-(G) = {id_ig:.2f}",
            l_p + 2.6, t_p + 27.6,
            fontsize=float(spec["callout_pt"]) * 0.94,
            color_int=ot.hex_to_origin_rgb_int("#A02333"),
            pos_scatter=2,
            format_math=False,
        )
        ob.add_page_text_label(
            op, gp, gp[0], 1, "RamanRatioB",
            f"\\i(A)\\-(D) / \\i(A)\\-(G) = {ad_ag:.2f}",
            l_p + 2.6, t_p + 33.4,
            fontsize=float(spec["callout_pt"]) * 0.90,
            color_int=ot.hex_to_origin_rgb_int("#2B6CB0"),
            pos_scatter=2,
            format_math=False,
        )

    figs_out: Dict[str, Dict[str, str]] = {}
    with _pre_export_hook(_raman_hook):
        ob.build_deconv_opju(
            {"FirstOrder": fit_res},
            tmp_dir / "demo_raman_deconv.opju",
            sample_name="Sample B",
            export_dir=tmp_dir,
            stem_template="demo_raman_deconv",
            region_titles={"FirstOrder": "Sample B  (532 nm)"},
            exported_figures_out=figs_out,
        )
    return Path(figs_out["FirstOrder"]["png"])


# ---------------------------------------------------------------------------
# 4. demo_xrd_waterfall.jpg
# ---------------------------------------------------------------------------
def _render_xrd_waterfall(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202604)
    x = np.linspace(10.0, 80.0, 1401)
    n_states = 5
    raw_curves: List[np.ndarray] = []
    for idx in range(n_states):
        p = idx / float(n_states - 1)  # 0.0 (State 1) -> 1.0 (State 5)
        # Layered precursor (001) attenuates & shifts slightly; host (002) develops turbostratic shoulder at ~23.6 deg;
        # cubic product (111), (200), (220) + minor secondary shoulder at 55.8 deg grow progressively
        y_bg = 75.0 * np.exp(-(x - 10.0) / 22.0) + 18.0
        pk_001 = (920.0 * (1.0 - 0.82 * p)) * np.exp(-0.5 * ((x - (14.25 - 0.35 * p)) / (0.62 + 0.18 * p)) ** 2)
        pk_sh24 = (260.0 * (p ** 1.1)) * np.exp(-0.5 * ((x - 23.6) / 1.25) ** 2)
        pk_002 = (460.0 + 340.0 * p) * np.exp(-0.5 * ((x - 26.35) / (0.85 - 0.18 * p)) ** 2)
        pk_111 = (1150.0 * (p ** 1.25)) * (0.38 ** 2 / ((x - 38.70) ** 2 + 0.38 ** 2))
        pk_200 = (980.0 * (p ** 1.25)) * (0.40 ** 2 / ((x - 45.00) ** 2 + 0.40 ** 2))
        pk_sh56 = (275.0 * (p ** 1.35)) * np.exp(-0.5 * ((x - 55.80) / 0.68) ** 2)
        pk_220 = (580.0 * (p ** 1.25)) * (0.46 ** 2 / ((x - 65.50) ** 2 + 0.46 ** 2))
        y = y_bg + pk_001 + pk_sh24 + pk_002 + pk_111 + pk_200 + pk_sh56 + pk_220 + rng.normal(0.0, 9.5, size=len(x))
        raw_curves.append(y)

    offset_step = 1120.0
    processed_curves: List[Dict[str, Any]] = []
    for idx, y_c in enumerate(raw_curves):
        y_norm = y_c - float(np.min(y_c))
        processed_curves.append(
            {
                "name": f"State {idx + 1}",
                "color": None,  # Uses sequential_blue_red palette automatically for 5 states
                "x": x,
                "y_raw": y_c,
                "y_offset": y_norm + idx * offset_step,
            }
        )

    markers = [
        {"pos": 14.2, "label": "(001)", "color": "#2B6CB0"},
        {"pos": 26.35, "label": "(002)", "color": "#3E86DE"},
        {"pos": 38.70, "label": "(111)", "color": "#D84B5C"},
        {"pos": 45.00, "label": "(200)", "color": "#A02333"},
        {"pos": 65.50, "label": "(220)", "color": "#6579BE"},
    ]

    # Compute exact top State-5 shoulder coordinates for clean shoulder peak annotations
    top_y = processed_curves[-1]["y_offset"]
    ymin_g = float(min(np.min(c["y_offset"]) for c in processed_curves))
    ymax_g = float(max(np.max(c["y_offset"]) for c in processed_curves))
    yspan_g = ymax_g - ymin_g
    y_lo = ymin_g - 0.06 * yspan_g
    y_hi = ymax_g + 1.24 * yspan_g
    y_sh24 = float(top_y[int(np.argmin(np.abs(x - 23.6)))]) + 0.075 * yspan_g
    y_sh56 = float(top_y[int(np.argmin(np.abs(x - 55.8)))]) + 0.075 * yspan_g

    def _xrd_hook(op: Any, gp: Any) -> None:
        sh_col = ot.hex_to_origin_rgb_int("#6579BE")
        ob.queue_overlay_data_text(
            op, gp, 1, 21.2, y_sh24, (10.0, 80.0), (y_lo, y_hi),
            rich_text="sh.", fontsize=16.5, color_int=sh_col, pos_scatter=0, format_math=False, no_repel=True,
        )
        ob.queue_overlay_data_text(
            op, gp, 1, 55.8, y_sh56, (10.0, 80.0), (y_lo, y_hi),
            rich_text="sh. (311)", fontsize=16.5, color_int=sh_col, pos_scatter=0, format_math=False, no_repel=True,
        )

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_xrd_hook):
        ob.build_waterfall_opju(
            processed_curves,
            tmp_dir / "demo_xrd_waterfall.opju",
            x_label="2\\theta (deg.)",
            y_label="Intensity (a.u.)",
            invert_x=False,
            project_title="Synthetic_XRD_Waterfall",
            markers=markers,
            export_dir=tmp_dir,
            export_stem="demo_xrd_waterfall",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 5. demo_ftir_waterfall.jpg
# ---------------------------------------------------------------------------
def _render_ftir_waterfall(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202605)
    x = np.linspace(600.0, 1800.0, 1201)
    n_states = 5
    raw_curves: List[np.ndarray] = []
    for idx in range(n_states):
        p = idx / float(n_states - 1)
        y_bg = 0.04 + 0.025 * ((x - 600.0) / 1200.0) ** 1.4
        b_co = (0.18 + 0.62 * p) * np.exp(-0.5 * ((x - 1718.0) / 22.0) ** 2)
        b_cc = (0.14 + 0.54 * p) * np.exp(-0.5 * ((x - 1585.0) / 26.0) ** 2)
        b_cov = (0.95 * (1.0 - 0.72 * p)) * (32.0 ** 2 / ((x - 1218.0) ** 2 + 32.0 ** 2))
        b_si = (0.32 + 0.42 * math.sin(math.pi * (0.18 + 0.72 * p))) * (34.0 ** 2 / ((x - (1105.0 - 12.0 * p)) ** 2 + 34.0 ** 2))
        b_oop = (0.15 + 0.52 * (p ** 1.2)) * np.exp(-0.5 * ((x - 748.0) / 18.0) ** 2)
        y = y_bg + b_co + b_cc + b_cov + b_si + b_oop + rng.normal(0.0, 0.006, size=len(x))
        raw_curves.append(y)

    offset_step = 0.92
    processed_curves: List[Dict[str, Any]] = []
    for idx, y_c in enumerate(raw_curves):
        y_norm = y_c - float(np.min(y_c))
        processed_curves.append(
            {
                "name": f"State {idx + 1}",
                "color": None,
                "x": x,
                "y_raw": y_c,
                "y_offset": y_norm + idx * offset_step,
            }
        )

    markers = [
        {"pos": 1718.0, "label": "C=O", "color": "#D84B5C"},
        {"pos": 1585.0, "label": "C=C", "color": "#2B6CB0"},
        {"pos": 1218.0, "label": "C-F (cov.)", "color": "#3E86DE"},
        {"pos": 1098.0, "label": "C-O / S.I.", "color": "#6579BE"},
        {"pos": 748.0, "label": "C-H bend", "color": "#A02333"},
    ]

    figs_out: Dict[str, str] = {}
    ob.build_waterfall_opju(
        processed_curves,
        tmp_dir / "demo_ftir_waterfall.opju",
        x_label="Wavenumber (cm^-1)",
        y_label="Absorbance (a.u.)",
        invert_x=True,
        project_title="Synthetic_FTIR_Waterfall",
        markers=markers,
        export_dir=tmp_dir,
        export_stem="demo_ftir_waterfall",
        exported_figures_out=figs_out,
    )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 6. demo_bet_porosity.jpg
# ---------------------------------------------------------------------------
def _render_bet_porosity(tmp_dir: Path) -> Path:
    # Type IV N2 isotherm with H2/H4 capillary condensation hysteresis loop
    # Kept cleanly beneath the (28%, 28%, 45%, 36%) BJH inset across P/P0 = 0.25..0.75
    ads_p = np.array(
        [
            0.005, 0.015, 0.03, 0.06, 0.10, 0.15, 0.20, 0.26, 0.32, 0.38,
            0.44, 0.50, 0.56, 0.62, 0.68, 0.74, 0.80, 0.85, 0.89, 0.92,
            0.95, 0.97, 0.985, 0.993,
        ],
        dtype=float,
    )
    langmuir_knee = 112.0 * (58.0 * ads_p) / (1.0 + 58.0 * ads_p)
    multilayer = 44.0 * ads_p
    condensation_ads = 62.0 / (1.0 + np.exp(-(ads_p - 0.76) / 0.055))
    macropore_tail = 105.0 * np.exp((ads_p - 0.993) / 0.032)
    ads_vol = langmuir_knee + multilayer + condensation_ads + macropore_tail

    des_p = np.array(
        [
            0.993, 0.980, 0.955, 0.920, 0.880, 0.830, 0.780, 0.720, 0.660,
            0.600, 0.540, 0.490, 0.455, 0.420, 0.360, 0.300, 0.220, 0.140, 0.070,
        ],
        dtype=float,
    )
    base_at_des = (
        112.0 * (58.0 * des_p) / (1.0 + 58.0 * des_p)
        + 44.0 * des_p
        + 62.0 / (1.0 + np.exp(-(des_p - 0.76) / 0.055))
        + 105.0 * np.exp((des_p - 0.993) / 0.032)
    )
    # Hysteresis loop opens smoothly above P/P0 = 0.45 and closes near P/P0 = 0.97
    hyst_open = 1.0 / (1.0 + np.exp(-(des_p - 0.485) / 0.022))
    hyst_close = 1.0 / (1.0 + np.exp((des_p - 0.925) / 0.030))
    des_vol = base_at_des + 36.0 * hyst_open * hyst_close

    d_nm = np.geomspace(1.4, 48.0, 40)
    dv = (
        0.068 * np.exp(-0.5 * (np.log(d_nm / 6.4) / 0.28) ** 2)
        + 0.019 * np.exp(-0.5 * (np.log(d_nm / 17.5) / 0.34) ** 2)
        + 0.002
    )
    cum_pv = np.cumsum(dv * np.gradient(d_nm))

    isotherm = {"ads_p_p0": ads_p, "ads_vol": ads_vol, "des_p_p0": des_p, "des_vol": des_vol}
    psd = {"diameter_nm": d_nm, "diff_vol": dv, "cum_pore_vol": cum_pv}

    def _bet_hook(op: Any, gp: Any) -> None:
        # Give generous vertical clearance between the BJH inset X-title ("Pore Width (nm)") and the hysteresis loop
        ob.activate_layer(op, gp, 1)
        gp[0].set_ylim(-18.0, 740.0)
        ob.activate_layer(op, gp, 2)
        gp[1].lt_exec("layer.unit=7; layer.left=28; layer.top=22; layer.width=45; layer.height=31;")

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_bet_hook):
        ob.build_bet_opju(
            isotherm,
            psd,
            tmp_dir / "demo_bet_porosity.opju",
            title="Sample_C_BET",
            bet_surface_area_m2_g=428.6,
            export_dir=tmp_dir,
            export_stem="demo_bet_porosity",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 7. demo_particle_size.jpg
# ---------------------------------------------------------------------------
def _render_particle_size(tmp_dir: Path) -> Path:
    size_um = np.geomspace(0.1, 200.0, 101)
    log_s = np.log(size_um)
    # Smooth bimodal log-normal volume density centered near ~12.5 um with minor fine shoulder
    pdf = 0.86 * np.exp(-0.5 * ((log_s - math.log(13.2)) / 0.56) ** 2) + 0.14 * np.exp(
        -0.5 * ((log_s - math.log(3.6)) / 0.42) ** 2
    )
    diff_vol_pct = (pdf / float(np.sum(pdf))) * 100.0 * 2.15  # Peak ~7.8%
    raw_cum = np.cumsum(pdf)
    cum_vol_pct = (raw_cum - raw_cum[0]) / (raw_cum[-1] - raw_cum[0]) * 100.0

    d10 = float(np.interp(10.0, cum_vol_pct, size_um))
    d50 = float(np.interp(50.0, cum_vol_pct, size_um))
    d90 = float(np.interp(90.0, cum_vol_pct, size_um))

    ps_data = {
        "size_um": size_um,
        "diff_vol_pct": diff_vol_pct,
        "cum_vol_pct": cum_vol_pct,
        "metrics": {"D10_um": d10, "D50_um": d50, "D90_um": d90},
    }

    def _ps_hook(op: Any, gp: Any) -> None:
        spec = ob.get_active_spec()
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        l_p, t_p, _w_p, _h_p = ot.rect_in_to_page_pct(*box_in, pw, ph)

        # Add vertical dashed drop-lines + circle anchors at (D10, 10%), (D50, 50%), (D90, 90%) on Layer 2
        gl2 = gp[1]
        ob.activate_layer(op, gp, 2)
        wb_d = op.new_book("w", lname="QuantileGuides")
        wks_d = wb_d[0]
        wks_d.cols = 8
        guide_col = ob._hex_to_origin_color(op, "#6579BE")
        pt_col = ob._hex_to_origin_color(op, "#A02333")
        sub_w = int(spec["sub_w_units"])
        for q_i, (d_val, pct_val) in enumerate([(d10, 10.0), (d50, 50.0), (d90, 90.0)]):
            wks_d.from_list(2 * q_i, [d_val, d_val], axis="X")
            wks_d.from_list(2 * q_i + 1, [0.0, pct_val], axis="Y")
            p_g = gl2.add_plot(wks_d, coly=2 * q_i + 1, colx=2 * q_i, type="l")
            p_g.color = guide_col
            p_idx = len(gl2.plot_list())
            gl2.lt_exec(f"range rgd = !{p_idx}; set rgd -d 2; set rgd -w {max(520, sub_w - 80)};")

        wks_d.from_list(6, [d10, d50, d90], axis="X")
        wks_d.from_list(7, [10.0, 50.0, 90.0], axis="Y")
        p_pts = gl2.add_plot(wks_d, coly=7, colx=6, type="s")
        p_pts.color = pt_col
        p_pts.symbol_size = float(spec["marker_size_pt"]) * 0.92
        pts_idx = len(gl2.plot_list())
        gl2.lt_exec(f"range rpt = !{pts_idx}; set rpt -k 2; set rpt -kf 1; label -r Legend;")

        # Clean D10 / D50 / D90 callout stack in the open upper-left decade (0.1..1.5 um)
        fs_c = float(spec["callout_pt"]) * 0.94
        c_ink = ot.hex_to_origin_rgb_int("#111111")
        c_acc = ot.hex_to_origin_rgb_int("#A02333")
        for idx_q, (lbl_q, val_q, col_q) in enumerate(
            [
                ("D\\-(10)", d10, c_ink),
                ("D\\-(50)", d50, c_acc),
                ("D\\-(90)", d90, c_ink),
            ]
        ):
            ob.add_page_text_label(
                op, gp, gp[0], 1, f"QuantLbl_{idx_q}",
                f"\\i({lbl_q[:1]}){lbl_q[1:]} = {val_q:.1f} \\g(m)m",
                l_p + 3.0, t_p + 20.4 + idx_q * 5.8,
                fontsize=fs_c, color_int=col_q, pos_scatter=2, format_math=False,
            )

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_ps_hook):
        ob.build_particle_size_opju(
            ps_data,
            tmp_dir / "demo_particle_size.opju",
            title="Sample_D_PSD",
            x_limits=(0.1, 200.0),
            export_dir=tmp_dir,
            export_stem="demo_particle_size",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 8. demo_epr_derivative.jpg
# ---------------------------------------------------------------------------
def _render_epr_derivative(tmp_dir: Path) -> Path:
    rng = np.random.default_rng(202608)
    b_field = np.linspace(3310.0, 3390.0, 801)
    b0 = 3350.00  # X-band resonance (~9.385 GHz) -> g = 2.0028
    dh_pp = 4.80  # Peak-to-peak linewidth in Gauss
    gamma = 0.5 * math.sqrt(3.0) * dh_pp
    # 1st-derivative Lorentzian absorption signal dI/dB
    di_db = -1000.0 * (2.0 * gamma * (b_field - b0)) / (((b_field - b0) ** 2 + gamma ** 2) ** 2)
    di_db = di_db / float(np.max(np.abs(di_db))) * 100.0 + rng.normal(0.0, 0.70, size=len(b_field))

    epr_metrics = fitting.analyze_epr_derivative(b_field, di_db)
    obs_dh_pp = float(epr_metrics["peak_to_peak_width"])

    def _epr_hook(op: Any, gp: Any) -> None:
        # Ensure Magnetic Field B increases left-to-right (3310 -> 3390 G) with symmetric 20 G ticks centered at 3350 G
        gl = gp[0]
        ob.activate_layer(op, gp, 1)
        gl.set_xlim(3310.0, 3390.0)
        gl.lt_exec("layer.x.inc=20;")

        # Set exact g = 2.0028 & Delta H_pp annotations in the queued overlay list
        txts = ob._PENDING_TEXT_ITEMS.get(gp.name, [])
        if len(txts) >= 1:
            txts[0]["text"] = "\\i(g) = 2.0028"
            txts[0]["format_math"] = False
        if len(txts) >= 2:
            txts[1]["text"] = f"\\g(D)\\i(H)\\-(pp) = {obs_dh_pp:.2f} G"
            txts[1]["format_math"] = False

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_epr_hook):
        ob.build_epr_opju(
            b_field,
            epr_metrics,
            tmp_dir / "demo_epr_derivative.opju",
            x_label="Magnetic Field, B (G)",
            title="Sample_E_EPR",
            export_dir=tmp_dir,
            export_stem="demo_epr_derivative",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# 9. demo_conductivity_pressure.jpg
# ---------------------------------------------------------------------------
def _render_conductivity_pressure(tmp_dir: Path) -> Path:
    pressure = np.array([5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60], dtype=float)
    # Percolation + interparticle contact saturation curve (S cm^-1) & Heckel compaction density (g cm^-3)
    conductivity = 0.032 + 4.35 * ((pressure / 60.0) ** 1.75) / (0.28 + 0.72 * ((pressure / 60.0) ** 1.75))
    density = 1.94 - (1.94 - 0.86) * np.exp(-0.046 * pressure)
    resistivity = 1.0 / conductivity

    cond_data = {
        "pressure_MPa": pressure,
        "conductivity": np.round(conductivity, 4),
        "density_g_cm3": np.round(density, 4),
        "resistivity": np.round(resistivity, 4),
        "conductivity_label": "Electrical Conductivity (S cm^-1)",
    }

    def _cond_hook(op: Any, gp: Any) -> None:
        # Use 10 MPa major ticks across 0..64 MPa so 24 pt tick labels have generous spacing
        ob.activate_layer(op, gp, 1)
        gp[0].set_xlim(0.0, 64.0)
        gp[0].lt_exec("layer.x.inc=10;")
        try:
            ob.activate_layer(op, gp, 2)
            gp[1].set_xlim(0.0, 64.0)
        except Exception:
            pass

    figs_out: Dict[str, str] = {}
    with _pre_export_hook(_cond_hook):
        ob.build_conductivity_opju(
            cond_data,
            tmp_dir / "demo_conductivity_pressure.opju",
            title="Sample_E_Conductivity",
            log_conductivity=True,
            export_dir=tmp_dir,
            export_stem="demo_conductivity_pressure",
            exported_figures_out=figs_out,
        )
    return Path(figs_out["png"])


# ---------------------------------------------------------------------------
# Public Entrypoint
# ---------------------------------------------------------------------------
def generate_part1(gallery_dir: Path = GALLERY_DIR, only_stems: Optional[List[str]] = None) -> List[Path]:
    """Render all 9 Part-1 characterization & deconvolution gallery JPEGs via headless OriginPro 2024."""
    out_dir = Path(gallery_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs: List[Tuple[str, Callable[[Path], Path], int]] = [
        ("demo_xps_deconv", _render_xps_deconv, SINGLE_LONG_EDGE_PX),
        ("demo_model_sensitivity", _render_model_sensitivity, GRID_LONG_EDGE_PX),
        ("demo_raman_deconv", _render_raman_deconv, SINGLE_LONG_EDGE_PX),
        ("demo_xrd_waterfall", _render_xrd_waterfall, SINGLE_LONG_EDGE_PX),
        ("demo_ftir_waterfall", _render_ftir_waterfall, SINGLE_LONG_EDGE_PX),
        ("demo_bet_porosity", _render_bet_porosity, SINGLE_LONG_EDGE_PX),
        ("demo_particle_size", _render_particle_size, SINGLE_LONG_EDGE_PX),
        ("demo_epr_derivative", _render_epr_derivative, SINGLE_LONG_EDGE_PX),
        ("demo_conductivity_pressure", _render_conductivity_pressure, SINGLE_LONG_EDGE_PX),
    ]
    if only_stems:
        wanted = set(only_stems)
        jobs = [jb for jb in jobs if jb[0] in wanted]

    generated: List[Path] = []
    print(f"Generating Part 1 Characterization Gallery ({len(jobs)} figures) -> {out_dir}", flush=True)
    for stem, fn, target_px in jobs:
        dst_jpg = out_dir / f"{stem}.jpg"
        generated.append(_run_with_com_retry(stem, fn, dst_jpg, target_px))
    return generated


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Render Part 1 Characterization Gallery in headless OriginPro.")
    ap.add_argument("--only", nargs="*", default=None, help="Optional subset of figure stems to render.")
    args = ap.parse_args()
    paths = generate_part1(GALLERY_DIR, only_stems=args.only)
    print(f"Completed Part 1: {len(paths)} JPEG figures written.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
