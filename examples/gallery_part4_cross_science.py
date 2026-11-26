"""
gallery_part4_cross_science.py - Part 4 Cross-Discipline Scientific Showcase Generator for SciOrigin.

Renders 6 flagship cross-science publication figures (Biomedicine, Single-Cell Omics, Transcriptomics,
Pharmacology, Computational Catalysis, and Machine Learning) natively in headless OriginPro 2024
(`skip_origin=False`), downscaling exported 300 DPI PNGs via `PIL.Image` (`LANCZOS`) to crisp
`1440 x 1080 px` (`4:3`) RGB JPEGs (`quality=92, subsampling=0`).

100% deterministic synthetic data (`np.random.default_rng(2026)`), generic scientific labels, zero external files.
"""
from __future__ import annotations

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


def _make_bio_bar_dot_sig_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    1. `demo_bio_bar_dot_sig` (`stat_bar_dot_sig`, TNR Bold preset):
       4 treatment groups (`Control`, `Low Dose`, `High Dose`, `Combo`, `n=8` biological replicates each)
       showing mean±SD bars + individual replicate dots + One-way ANOVA / Tukey HSD `sig_bracket` stars (`*`, `**`, `***`).
    """
    means_and_sds = [
        ("Control", 1.00, 0.21),
        ("Low Dose", 1.34, 0.22),
        ("High Dose", 1.43, 0.22),
        ("Combo", 1.53, 0.22),
    ]
    groups: Dict[str, List[float]] = {}
    for name, mu, sd in means_and_sds:
        z = _standardized_normal(rng, 8)
        vals = np.round(mu + sd * z, 3).tolist()
        groups[name] = vals

    cfg = {
        "title": "demo_bio_bar_dot_sig",
        "mode": "stat_bar_dot_sig",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "x_label": "Treatment Group",
        "y_label": "Relative Expression (fold)",
        "error_bar": "SD",
        "color_scheme": "paired_semantic",
        "hide_ns": True,
        "max_brackets": 4,
        "groups": groups,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_bio_violin_okabe_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    2. `demo_bio_violin_okabe` (`stat_violin_raincloud`, Arial Regular preset + `color_scheme="okabe_ito"`):
       5 cell populations (`Cluster 1..5`, `n=45` each) native Origin Violin + quartile box + significance brackets.
    """
    cluster_params = [
        ("Cluster 1", 4.90, 0.78),
        ("Cluster 2", 5.85, 0.82),
        ("Cluster 3", 5.35, 0.80),
        ("Cluster 4", 7.35, 0.86),
        ("Cluster 5", 6.45, 0.84),
    ]
    groups: Dict[str, List[float]] = {}
    for cname, mu, sd in cluster_params:
        z = _standardized_normal(rng, 45)
        vals = mu + sd * z
        groups[cname] = np.round(vals, 3).tolist()

    cfg = {
        "title": "demo_bio_violin_okabe",
        "mode": "stat_violin_raincloud",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "color_scheme": "okabe_ito",
        "x_label": "Cell Population",
        "y_label": "Module Expression Score (a.u.)",
        "show_stats": True,
        "hide_ns": True,
        "max_brackets": 3,
        "groups": groups,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_omics_volcano_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    3. `demo_omics_volcano` (`volcano_plot`, Arial Regular preset):
       1,200 synthetic transcripts (`log2 Fold Change` vs `-log10(FDR)`), `Down` (`#2B6CB0`) / `NS` (`#B8C2CC`) /
       `Up` (`#D84B5C`), `±1.0` & `p=0.01` dashed thresholds, and 6 non-overlapping top gene callouts (`Gene A1..F6`).
    """
    n_bg = 1194
    fc_bg = np.concatenate(
        [
            rng.normal(0.0, 0.66, size=860),
            rng.normal(-1.60, 0.52, size=167),
            rng.normal(1.62, 0.54, size=167),
        ]
    )
    fc_bg = np.clip(fc_bg, -3.6, 3.6)
    nlp_bg = 0.46 * (np.abs(fc_bg) ** 1.42) + rng.gamma(shape=1.28, scale=0.52, size=n_bg)
    nlp_bg = np.clip(nlp_bg, 0.04, 4.35)
    bg_genes = [f"Transcript_{i + 1:04d}" for i in range(n_bg)]

    # 6 well-separated flagship hits above the bulk cloud (3 Down on outer-left wing, 3 Up on outer-right wing)
    top_hits = [
        ("Gene A1", -3.75, 9.45),
        ("Gene B2", -3.35, 7.55),
        ("Gene C3", -3.05, 5.75),
        ("Gene D4", 3.80, 9.65),
        ("Gene E5", 3.40, 7.80),
        ("Gene F6", 3.10, 5.95),
    ]

    all_genes = bg_genes + [h[0] for h in top_hits]
    all_fc = np.round(np.concatenate([fc_bg, [h[1] for h in top_hits]]), 4)
    all_nlp = np.concatenate([nlp_bg, [h[2] for h in top_hits]])
    all_fdr = np.power(10.0, -all_nlp)

    cfg = {
        "title": "demo_omics_volcano",
        "mode": "volcano_plot",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "x_label": "log_2 Fold Change",
        "y_label": "-log_10(FDR)",
        "fc_cutoff": 1.0,
        "p_cutoff": 0.01,
        "top_n_labels": 6,
        "highlight_genes": ["Gene A1", "Gene B2", "Gene C3", "Gene D4", "Gene E5", "Gene F6"],
        "down_color": "#2B6CB0",
        "ns_color": "#B8C2CC",
        "up_color": "#D84B5C",
        "x_limits": [-4.8, 4.8],
        "genes": all_genes,
        "log2fc": all_fc.tolist(),
        "fdr": all_fdr.tolist(),
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_pharma_ic50_4pl_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    4. `demo_pharma_ic50_4pl` (`dose_response_4pl`, TNR Bold preset):
       2 inhibitors (`Compound 1` `IC50 ~ 18 nM` vs `Compound 2` `IC50 ~ 240 nM`) across 8 log-spaced
       concentrations (`0.1..10000 nM`, `Cell Viability (%)`), 4PL sigmoid curves + 95% CI bands + `50%` `IC50` drop-lines.
    """
    concs = np.geomspace(0.1, 10000.0, 8)
    compounds = [
        ("Compound 1", 4.2, 99.6, 18.0, 1.08, "#D84B5C"),
        ("Compound 2", 5.0, 99.8, 240.0, 1.05, "#2B6CB0"),
    ]
    series_list = []
    for name, bottom, top, ic50_true, hill, color in compounds:
        mean_curve = bottom + (top - bottom) / (1.0 + np.power(concs / ic50_true, hill))
        # Simulate n=3 independent assay wells per concentration for realistic mean ± SD & 4PL 95% CI band
        reps = mean_curve[:, None] + rng.normal(0.0, 1.65, size=(len(concs), 3))
        reps = np.clip(reps, 0.5, 103.5)
        y_mean = np.round(np.mean(reps, axis=1), 2).tolist()
        y_sd = np.round(np.std(reps, axis=1, ddof=1), 2).tolist()
        series_list.append(
            {
                "name": name,
                "color": color,
                "x": np.round(concs, 4).tolist(),
                "y": y_mean,
                "y_err": y_sd,
            }
        )

    cfg = {
        "title": "demo_pharma_ic50_4pl",
        "mode": "dose_response_4pl",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "x_label": "Concentration (nM)",
        "y_label": "Cell Viability (%)",
        "error_bar": "SD",
        "ci_level": 0.95,
        "show_ic50_guides": True,
        "series": series_list,
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_chem_free_energy_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    5. `demo_chem_free_energy` (`free_energy_diagram`, TNR Bold preset):
       2 electrocatalysts (`Catalyst 1` vs `Catalyst 2`) 5-step OER free-energy step profile
       (`*`, `*OH`, `*O`, `*OOH`, `O_2`, `Free Energy \\g(D)\\i(G) (eV)`) with thick plateaus & dashed connectors.
    """
    # Small deterministic DFT zero-point energy perturbation around canonical 4e- OER pathway (sum fixed at 4.92 eV)
    jitter = rng.uniform(-0.02, 0.02, size=3)
    cat1_steps = [
        0.00,
        round(1.08 + float(jitter[0]), 2),
        round(2.40 + float(jitter[1]), 2),
        round(3.68 + float(jitter[2]), 2),
        4.92,
    ]
    cat2_steps = [
        0.00,
        round(0.84 - float(jitter[0]), 2),
        round(2.58 + float(jitter[1]), 2),
        round(3.96 - float(jitter[2]), 2),
        4.92,
    ]

    cfg = {
        "title": "demo_chem_free_energy",
        "mode": "free_energy_diagram",
        "style_preset": "style_publication_minimal",
        "build_opju": False,
        "locale": "en",
        "x_label": "Reaction Coordinate",
        "y_label": "Free Energy \\g(D)\\i(G) (eV)",
        "step_labels": ["*", "*OH", "*O", "*OOH", "O_2"],
        "legend_style": "corner_upper_left",
        "pathways": [
            {"name": "Catalyst 1", "color": "#2B6CB0", "steps": cat1_steps},
            {"name": "Catalyst 2", "color": "#D84B5C", "steps": cat2_steps},
        ],
    }
    return cg.compile_config_to_figure_spec(cfg)


def _make_ml_forest_ablation_spec(rng: np.random.Generator) -> cg.FigureSpec:
    """
    6. `demo_ml_forest_ablation` (`forest_ablation_plot`, Arial Regular preset):
       6 model variants (`Full Model` baseline & `Ablation 1..5`, `\\g(D)AUROC` with 95% CI horizontal bars
       + vertical `0.0` dashed reference line).
    """
    # Deterministic 5-fold CV bootstrap half-widths from rng(2026)
    base_specs = [
        ("Full Model", 0.000, 0.006, "#2B6CB0"),
        ("Ablation 1", -0.018, 0.009, "#3E86DE"),
        ("Ablation 2", -0.035, 0.011, "#6579BE"),
        ("Ablation 3", -0.053, 0.012, "#D84B5C"),
        ("Ablation 4", -0.072, 0.014, "#C53A4B"),
        ("Ablation 5", -0.094, 0.016, "#A02333"),
    ]
    items = []
    for idx, (nm, est_base, hw_base, col) in enumerate(base_specs):
        est = 0.000 if idx == 0 else round(est_base + float(rng.uniform(-0.002, 0.002)), 3)
        hw = round(hw_base + float(rng.uniform(0.000, 0.002)), 3)
        items.append(
            {
                "name": nm,
                "estimate": est,
                "ci_low": round(est - hw, 3),
                "ci_high": round(est + hw, 3),
                "color": col,
            }
        )

    cfg = {
        "title": "demo_ml_forest_ablation",
        "mode": "forest_ablation_plot",
        "style_preset": "style_arial_clean",
        "build_opju": False,
        "locale": "en",
        "x_label": "\\g(D)AUROC (95% CI)",
        "y_label": "",
        "null_value": 0.0,
        "value_format": "{:+.3f}",
        "show_ci_text": True,
        "items": items,
    }
    return cg.compile_config_to_figure_spec(cfg)


def build_part4_jobs() -> Dict[str, cg.FigureSpec]:
    """Return the ordered mapping of all 6 Part 4 cross-science gallery stems to `FigureSpec` objects."""
    rng = np.random.default_rng(2026)
    return {
        "demo_bio_bar_dot_sig": _make_bio_bar_dot_sig_spec(rng),
        "demo_bio_violin_okabe": _make_bio_violin_okabe_spec(rng),
        "demo_omics_volcano": _make_omics_volcano_spec(rng),
        "demo_pharma_ic50_4pl": _make_pharma_ic50_4pl_spec(rng),
        "demo_chem_free_energy": _make_chem_free_energy_spec(rng),
        "demo_ml_forest_ablation": _make_ml_forest_ablation_spec(rng),
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
    """Render one Part 4 figure in the current process (fresh OriginExt COM pointer when invoked via subprocess)."""
    jobs = build_part4_jobs()
    if out_name not in jobs:
        raise KeyError(f"Unknown Part 4 figure job: {out_name!r}")
    spec = jobs[out_name]
    spec.title = out_name
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"sciorigin_p4_{out_name}_") as fig_tmp_str:
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


def generate_part4(gallery_dir: Path = GALLERY_DIR, only_names: List[str] | None = None) -> List[Path]:
    """Render all 6 Part 4 cross-science showcase figures natively in headless OriginPro 2024."""
    gallery_dir = Path(gallery_dir).resolve()
    gallery_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_part4_jobs()
    target_names = [k for k in jobs.keys() if (not only_names or k in set(only_names))]

    saved_paths: List[Path] = []
    script_path = str(Path(__file__).resolve())
    for out_name in target_names:
        print(f"[Part 4] Rendering native OriginPro cross-science showcase: {out_name} ...", flush=True)
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

    parser = argparse.ArgumentParser(description="Render Part 4 SciOrigin cross-science showcase figures.")
    parser.add_argument("--single", type=str, default=None, help="Internal single-figure worker target.")
    parser.add_argument("--gallery-dir", type=Path, default=GALLERY_DIR, help="Output gallery directory.")
    parser.add_argument("names", nargs="*", help="Optional subset of figure stems to render.")
    cli_args = parser.parse_args()
    if cli_args.single:
        _render_single_job_inprocess(cli_args.single, cli_args.gallery_dir)
    else:
        generate_part4(gallery_dir=cli_args.gallery_dir, only_names=cli_args.names or None)
