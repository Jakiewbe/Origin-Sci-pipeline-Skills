from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from PIL import Image


DEFAULT_STYLE_PATH = Path(__file__).resolve().parents[1] / "presets" / "style_publication_minimal.json"


def load_style(style_path: Optional[str | Path] = None) -> Dict[str, Any]:
    if not style_path:
        p = DEFAULT_STYLE_PATH
    else:
        p = Path(style_path)
        if not p.exists():
            cand = DEFAULT_STYLE_PATH.parent / str(style_path)
            if cand.exists():
                p = cand
            else:
                cand_json = DEFAULT_STYLE_PATH.parent / f"{style_path}.json"
                if cand_json.exists():
                    p = cand_json
    return json.loads(p.read_text(encoding="utf-8"))


def apply_rcparams(style: Dict[str, Any]) -> None:
    bw = float(style.get("figure_box_linewidth", 1.8))
    cfg: Dict[str, Any] = {
        "font.family": "serif",
        "font.serif": [style.get("font_family", "Times New Roman"), "SimSun", "Microsoft YaHei", "DejaVu Serif"],
        "axes.unicode_minus": False,
        "mathtext.fontset": style.get("mathtext_fontset", "stix"),
        "axes.linewidth": bw,
        "xtick.direction": style.get("tick_direction", "in"),
        "ytick.direction": style.get("tick_direction", "in"),
        "xtick.top": bool(style.get("tick_top", False)),
        "ytick.right": bool(style.get("tick_right", False)),
        "xtick.major.size": float(style.get("major_tick_length", 5.5)),
        "ytick.major.size": float(style.get("major_tick_length", 5.5)),
        "xtick.minor.size": float(style.get("minor_tick_length", 3.0)),
        "ytick.minor.size": float(style.get("minor_tick_length", 3.0)),
        "xtick.major.width": float(style.get("tick_width", 1.5)),
        "ytick.major.width": float(style.get("tick_width", 1.5)),
        "xtick.minor.width": float(style.get("tick_width", 1.5)) * 0.8,
        "axes.labelsize": float(style.get("axis_label_size", 15)),
        "axes.labelweight": "bold",
        "xtick.labelsize": float(style.get("tick_label_size", 13)),
        "ytick.labelsize": float(style.get("tick_label_size", 13)),
    }
    if style.get("font_weight"):
        cfg["font.weight"] = str(style["font_weight"])
    plt.rcParams.update(cfg)


def _configure_axis_ticks(
    ax: plt.Axes,
    style: Dict[str, Any],
    *,
    has_y_ticks: bool = True,
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    if not style.get("show_minor_ticks", True):
        ax.xaxis.set_minor_locator(ticker.NullLocator())
        ax.yaxis.set_minor_locator(ticker.NullLocator())
        ax.tick_params(axis="x", top=bool(style.get("tick_top", False)), bottom=True)
        if has_y_ticks:
            ax.tick_params(axis="y", right=bool(style.get("tick_right", False)), left=True)
        else:
            ax.set_yticks([])
        return

    if not log_x:
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    if has_y_ticks:
        if not log_y:
            ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    else:
        ax.set_yticks([])


def save_publication_figure(
    fig: plt.Figure,
    out_stem: str | Path,
    style: Dict[str, Any],
) -> Dict[str, str]:
    """Save 300dpi PNG + 600dpi lossless LZW TIFF + lightweight <=960px JPEG QA preview."""
    stem = Path(out_stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    qa_dir = stem.parent / "_qa_previews"
    qa_dir.mkdir(parents=True, exist_ok=True)

    exp_cfg = style.get("export", {})
    png_dpi = int(exp_cfg.get("png_dpi", 300))
    tif_dpi = int(exp_cfg.get("tif_dpi", 600))
    max_px = int(exp_cfg.get("qa_preview_max_px", 960))
    jpg_q = int(exp_cfg.get("qa_preview_jpeg_quality", 82))

    png_path = stem.with_suffix(".png")
    tif_path = stem.with_suffix(".tif")
    qa_path = qa_dir / f"{stem.name}_preview.jpg"

    fig.savefig(png_path, dpi=png_dpi, bbox_inches="tight", facecolor="white")
    tmp_png_600 = qa_dir / f"__tmp600_{stem.name}.png"
    fig.savefig(tmp_png_600, dpi=tif_dpi, bbox_inches="tight", facecolor="white")
    with Image.open(tmp_png_600) as im600:
        im_rgb = im600.convert("RGB")
        im_rgb.save(tif_path, format="TIFF", compression="tiff_lzw", dpi=(tif_dpi, tif_dpi))
        im_prev = im_rgb.copy()
        im_prev.thumbnail((max_px, max_px))
        im_prev.save(qa_path, format="JPEG", quality=jpg_q)
    try:
        tmp_png_600.unlink()
    except OSError:
        pass
    plt.close(fig)

    return {
        "png": str(png_path),
        "tif": str(tif_path),
        "qa_preview_jpg": str(qa_path),
    }


def _bold_ticks(ax: plt.Axes) -> None:
    for lbl in list(ax.get_xticklabels()) + list(ax.get_yticklabels()):
        lbl.set_fontweight("bold")


def _draw_deconv_on_ax(
    ax: plt.Axes,
    fit_result: Dict[str, Any],
    left_title: str,
    right_title: str,
    style: Dict[str, Any],
    show_legend: bool = True,
    compact_panel: bool = False,
) -> None:
    dc = style["deconv_colors"]
    x = fit_result["x"]
    y_raw = fit_result["y_raw"]
    bg = fit_result["baseline"]
    y_fit = fit_result["y_fit"]
    comps = fit_result["components"]
    curves_bg = fit_result["comp_curves_with_bg"]

    ax.plot(x, bg, color=dc["baseline"], lw=1.05, zorder=2)

    palette = dc["components"]
    alpha = float(dc.get("fill_alpha", 0.56))
    for i, (m, c_bg) in enumerate(zip(comps, curves_bg)):
        col = m.get("color") or palette[i % len(palette)]
        ax.fill_between(x, bg, c_bg, color=col, alpha=alpha, lw=0.85, edgecolor=col, zorder=3 + i * 0.1)

    step = max(1, len(x) // (65 if compact_panel else 85))
    ax.scatter(
        x[::step],
        y_raw[::step],
        s=12 if compact_panel else 18,
        color=dc["raw_scatter"],
        alpha=0.86,
        label="Raw",
        zorder=8,
    )
    ax.plot(x, y_fit, color=dc["envelope_fit"], lw=1.8 if compact_panel else 2.1, label="Fitting", zorder=9)

    ymin = float(np.min(np.minimum(y_raw, bg)))
    ymax = float(np.max(np.maximum(y_raw, y_fit)))
    yrange = max(ymax - ymin, 1e-6)
    has_flags = bool(fit_result.get("audit_flags"))
    ax.set_ylim(ymin - (0.14 if has_flags else 0.06) * yrange, ymax + 0.26 * yrange)

    invert_x = bool(fit_result.get("invert_x", False))
    if invert_x:
        ax.set_xlim(float(np.max(x)), float(np.min(x)))
    else:
        ax.set_xlim(float(np.min(x)), float(np.max(x)))

    ax.set_xlabel(fit_result.get("x_label", "Binding Energy (eV)"))
    ax.set_ylabel(fit_result.get("y_label", "Intensity (a.u.)"))
    _configure_axis_ticks(ax, style, has_y_ticks=False)
    _bold_ticks(ax)

    title_fs = 11.8 if compact_panel else 14.0
    if left_title:
        ax.text(0.04, 0.94, left_title, transform=ax.transAxes, fontsize=title_fs, fontweight="bold", va="top", ha="left")
    if right_title:
        ax.text(0.96, 0.94, right_title, transform=ax.transAxes, fontsize=title_fs, fontweight="bold", va="top", ha="right")

    ratios = fit_result.get("extra_ratios", {})
    if "I_D_I_G_raw_net" in ratios and "A_D_A_G_area" in ratios:
        r_y = 0.94 if not right_title else 0.83
        ax.text(
            0.96,
            r_y,
            f"$I_\\mathrm{{D}}/I_\\mathrm{{G}}$ = {ratios['I_D_I_G_raw_net']:.2f}\n"
            f"$A_\\mathrm{{D}}/A_\\mathrm{{G}}$ = {ratios['A_D_A_G_area']:.2f}",
            transform=ax.transAxes,
            fontsize=10.5 if compact_panel else 11.5,
            fontweight="bold",
            color="#2E5B88",
            va="top",
            ha="right",
        )

    if show_legend:
        leg = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.02, 0.85),
            frameon=False,
            prop={"weight": "bold", "size": 10.5 if compact_panel else 12.5},
        )
        for txt in leg.get_texts():
            txt.set_fontweight("bold")

    audit_flags = fit_result.get("audit_flags") or []
    if audit_flags:
        badge_txt = " | ".join(audit_flags[:2])
        ax.text(
            0.97,
            0.035,
            badge_txt,
            transform=ax.transAxes,
            fontsize=8.2 if compact_panel else 9.0,
            fontweight="bold",
            color="#9B2C2C",
            ha="right",
            va="bottom",
            bbox=dict(boxstyle="round,pad=0.18", fc="#FFF5F5", ec="#E2A3A3", alpha=0.88),
            zorder=14,
        )

    _place_smart_callouts(ax, x, bg, y_fit, comps, curves_bg, ymin, ymax, yrange, invert_x, style, compact_panel=compact_panel)


def plot_deconvolution(
    fit_result: Dict[str, Any],
    out_stem: str | Path,
    region_title: str = "C 1s",
    sample_title: str = "Sample",
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render single-panel publication XPS/Raman deconvoluted spectrum."""
    st = style or load_style()
    apply_rcparams(st)
    fig, ax = plt.subplots(figsize=(6.4, 4.9))
    _draw_deconv_on_ax(ax, fit_result, region_title, sample_title, st, show_legend=True, compact_panel=False)
    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_deconv_grid(
    panel_items: List[Dict[str, Any]],
    out_stem: str | Path,
    ncols: int = 3,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render multi-panel (a)-(f) deconvolution composite grid for cohort comparisons."""
    st = style or load_style()
    apply_rcparams(st)
    n_panels = len(panel_items)
    ncols = max(1, min(ncols, n_panels))
    nrows = math.ceil(n_panels / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(5.2 * ncols, 4.3 * nrows), squeeze=False)
    flat_axes = axes.flatten()

    for idx, p_item in enumerate(panel_items):
        ax = flat_axes[idx]
        letter = chr(ord("a") + idx)
        p_title = f"({letter}) {p_item['name']}"
        _draw_deconv_on_ax(
            ax,
            p_item["fit"],
            left_title=p_title,
            right_title="",
            style=st,
            show_legend=(idx == 0),
            compact_panel=True,
        )

    for extra_idx in range(n_panels, len(flat_axes)):
        flat_axes[extra_idx].axis("off")

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def _place_smart_callouts(
    ax: plt.Axes,
    x: np.ndarray,
    bg: np.ndarray,
    y_fit: np.ndarray,
    comps: List[Dict[str, Any]],
    curves_bg: List[np.ndarray],
    ymin: float,
    ymax: float,
    yrange: float,
    invert_x: bool,
    style: Dict[str, Any],
    compact_panel: bool = False,
) -> None:
    x_span = float(np.max(x) - np.min(x))
    visual_items = []
    for m, c_bg in zip(comps, curves_bg):
        if m["area_pct"] < 1.2:
            continue
        idx = int(np.argmin(np.abs(x - m["center"])))
        vis_x = (float(np.max(x)) - m["center"]) / x_span if invert_x else (m["center"] - float(np.min(x))) / x_span
        visual_items.append((vis_x, idx, m, c_bg))

    visual_items.sort(key=lambda t: t[0])
    placed_boxes: List[Tuple[float, float]] = []

    for rank, (vis_x, idx, m, c_bg) in enumerate(visual_items):
        peak_x = float(x[idx])
        peak_top_y = float(c_bg[idx])
        rel_h = (peak_top_y - float(bg[idx])) / yrange
        anchor_y = float(bg[idx]) + 0.82 * (peak_top_y - float(bg[idx]))

        step_vis = 0.13 if rel_h > 0.55 else 0.07
        cand_vis_options = [
            float(np.clip(vis_x + step_vis, 0.10, 0.90)),
            float(np.clip(vis_x - step_vis, 0.10, 0.90)),
            float(np.clip(vis_x, 0.10, 0.90)),
        ]
        best_cand = None
        best_cost = float("inf")
        for cvx in cand_vis_options:
            lx = (float(np.max(x)) - cvx * x_span) if invert_x else (float(np.min(x)) + cvx * x_span)
            w_mask = np.abs(x - lx) <= 0.065 * x_span
            env_top = float(np.max(y_fit[w_mask])) if np.any(w_mask) else float(np.interp(lx, x, y_fit))
            env_norm = (env_top - ymin) / yrange
            req_norm_y = max(env_norm + 0.07, (anchor_y - ymin) / yrange + 0.04) + 0.05 * (rank % 2)
            req_norm_y = float(np.clip(req_norm_y, 0.20, 1.06))
            cost = env_norm * 0.6 + abs(cvx - vis_x) * 1.2
            if cvx < 0.34 and req_norm_y > 0.68:
                cost += 2.2
            if cvx > 0.70 and req_norm_y > 0.74:
                cost += 1.8
            for px, py in placed_boxes:
                if abs(cvx - px) < 0.18 and abs(req_norm_y - py) < 0.12:
                    cost += 1.5
            if cost < best_cost:
                best_cost = cost
                best_cand = (cvx, req_norm_y)

        cand_vis_x, cand_norm_y = best_cand if best_cand is not None else (vis_x, 0.85)

        for _ in range(8):
            collision = False
            for px, py in placed_boxes:
                if abs(cand_vis_x - px) < 0.17 and abs(cand_norm_y - py) < 0.115:
                    collision = True
                    cand_norm_y = min(1.08, py + 0.125)
            if not collision:
                break

        placed_boxes.append((cand_vis_x, cand_norm_y))
        label_x = (float(np.max(x)) - cand_vis_x * x_span) if invert_x else (float(np.min(x)) + cand_vis_x * x_span)
        label_y = ymin + cand_norm_y * yrange

        fs = float(style.get("callout_font_size", 11.2)) - (1.2 if compact_panel else 0.0)
        ax.annotate(
            m["label"],
            xy=(peak_x, anchor_y),
            xytext=(label_x, label_y),
            ha="center",
            va="bottom",
            fontsize=fs,
            fontweight="bold",
            color=m["color"],
            bbox=dict(boxstyle="round,pad=0.06", fc="white", ec="none", alpha=0.72),
            arrowprops=dict(
                arrowstyle="-|>",
                color=m["color"],
                lw=1.2 if compact_panel else 1.35,
                shrinkA=1,
                shrinkB=2,
                mutation_scale=9 if compact_panel else 10,
            ),
            zorder=12,
        )


def plot_stacked_bar(
    sample_labels: List[str],
    comp_labels: List[str],
    comp_colors: List[str],
    pct_matrix: np.ndarray,
    out_stem: str | Path,
    y_label: str = "Area Fraction (%)",
    x_label: str = "Sample",
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render 0-100% stacked composition bar chart (n_samples x n_components)."""
    st = style or load_style()
    apply_rcparams(st)

    fig_w = max(6.8, min(14.0, 0.78 * len(sample_labels) + 1.6))
    fig, ax = plt.subplots(figsize=(fig_w, 5.0))
    x_pos = np.arange(len(sample_labels))
    bottoms = np.zeros(len(sample_labels), dtype=float)

    for c_i in range(pct_matrix.shape[1]):
        vals = pct_matrix[:, c_i]
        ax.bar(
            x_pos,
            vals,
            width=0.56,
            bottom=bottoms,
            color=comp_colors[c_i % len(comp_colors)],
            edgecolor="#222222",
            linewidth=0.9,
            label=comp_labels[c_i],
            zorder=3,
        )
        bottoms += vals

    ax.set_xticks(x_pos)
    ax.set_xticklabels(sample_labels, rotation=15 if max((len(s) for s in sample_labels), default=0) > 6 else 0)
    ax.set_ylim(0.0, 108.0)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    _bold_ticks(ax)

    ncol_leg = min(3, max(2, len(comp_labels)))
    leg = ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=ncol_leg,
        frameon=False,
        prop={"weight": "bold", "size": 10.8},
    )
    for txt in leg.get_texts():
        txt.set_fontweight("bold")

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def _normalize_with_exclusions(
    x: np.ndarray,
    y: np.ndarray,
    normalize_each: bool,
    norm_exclude_windows: Optional[List[List[float]]] = None,
    clip_top_factor: Optional[float] = None,
) -> np.ndarray:
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


def plot_waterfall(
    series_list: List[Dict[str, Any]],
    out_stem: str | Path,
    x_label: str,
    y_label: str = "Intensity (a.u.)",
    invert_x: bool = False,
    x_window: Optional[Tuple[float, float]] = None,
    markers: Optional[List[Dict[str, Any]]] = None,
    normalize_each: bool = True,
    offset_step: float = 1.18,
    norm_exclude_windows: Optional[List[List[float]]] = None,
    clip_top_factor: Optional[float] = None,
    style: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    """Render stacked waterfall multi-sample comparison (with optional substrate-peak exclusion normalization)."""
    st = style or load_style()
    apply_rcparams(st)
    pal = st["series_palette"]
    curve_lw = float(st.get("curve_linewidth", 1.85))
    guide_lw = float(st.get("guide_linewidth", 1.1))
    guide_alpha = float(st.get("guide_alpha", 0.82))
    guide_ls_raw = st.get("guide_linestyle", "--")
    if isinstance(guide_ls_raw, list) and len(guide_ls_raw) == 2 and isinstance(guide_ls_raw[1], list):
        guide_ls: Any = (guide_ls_raw[0], tuple(guide_ls_raw[1]))
    else:
        guide_ls = guide_ls_raw
    use_corner_legend = st.get("legend_style") == "corner_upper_left"
    minimal_mode = bool(st.get("minimal_axes", False))

    fig_h = max(5.6, min(11.0, 0.72 * len(series_list) + 1.2))
    fig, ax = plt.subplots(figsize=(6.8, fig_h))
    processed_curves: List[Dict[str, Any]] = []

    all_xmin, all_xmax = [], []
    top_y_max = 0.0

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

        col = item.get("color") or pal[idx % len(pal)]
        ax.plot(x, y_off, color=col, lw=curve_lw, label=item["name"], zorder=4 + idx)

        if not use_corner_legend:
            n_pts = len(x)
            seg_slice = slice(0, max(6, int(0.26 * n_pts))) if invert_x else slice(min(n_pts - 6, int(0.72 * n_pts)), n_pts)
            x_seg = x[seg_slice]
            y_seg = y_off[seg_slice]
            win_w = max(3, len(y_seg) // 5)
            best_pos = 0
            best_score = float("inf")
            for s_i in range(0, max(1, len(y_seg) - win_w)):
                sub = y_seg[s_i : s_i + win_w]
                score = float(np.max(sub) - np.min(sub)) + 0.35 * float(np.mean(sub) - idx * step_val)
                if score < best_score:
                    best_score = score
                    best_pos = s_i + win_w // 2
            ax.text(
                float(x_seg[best_pos]),
                float(y_seg[best_pos]) + 0.14 * step_val,
                item["name"],
                color=col,
                fontsize=11.0,
                fontweight="bold",
                ha="center",
                va="bottom",
                bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="none", alpha=0.72),
                zorder=10,
            )

        all_xmin.append(float(np.min(x)))
        all_xmax.append(float(np.max(x)))
        top_y_max = max(top_y_max, float(np.max(y_off)))
        processed_curves.append(
            {
                "name": item["name"],
                "color": col,
                "x": x,
                "y_raw": y,
                "y_offset": y_off,
            }
        )

    xmin_g, xmax_g = min(all_xmin), max(all_xmax)
    if invert_x:
        ax.set_xlim(xmax_g, xmin_g)
    else:
        ax.set_xlim(xmin_g, xmax_g)

    has_floating_top_marker = bool(markers and any("y_frac" not in mk for mk in markers))
    top_pad_mult = 0.96 if (has_floating_top_marker or not minimal_mode) else 0.32
    ax.set_ylim(-0.14 * offset_step, top_y_max + top_pad_mult * offset_step)

    if markers:
        annot_fs = float(st.get("title_annot_size", 20.0)) if minimal_mode else 9.8
        for m_idx, mk in enumerate(markers):
            pos = float(mk["pos"])
            if xmin_g <= pos <= xmax_g:
                mk_col = mk.get("color", "#6E6E6E")
                mk_dx = float(mk.get("dx", 0.0))
                ax.axvline(pos, color=mk_col, ls=guide_ls, lw=guide_lw, alpha=guide_alpha, zorder=2)
                if "y_frac" in mk:
                    y_annot = top_y_max * float(mk["y_frac"])
                    va_annot = "center"
                else:
                    y_annot = top_y_max + (0.18 + 0.32 * (m_idx % 2)) * offset_step
                    va_annot = "bottom"
                txt_kwargs: Dict[str, Any] = {
                    "fontsize": annot_fs,
                    "fontweight": "bold",
                    "color": mk.get("text_color", mk.get("color", "#333333")),
                    "ha": "center",
                    "va": va_annot,
                    "zorder": 12,
                }
                if not minimal_mode:
                    txt_kwargs["bbox"] = dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.82)
                ax.text(pos + mk_dx, y_annot, mk["label"], **txt_kwargs)

    if use_corner_legend and series_list:
        leg = ax.legend(
            loc="upper left",
            bbox_to_anchor=(0.012, 0.985),
            frameon=False,
            handlelength=1.5,
            handletextpad=0.45,
            borderaxespad=0.2,
            prop={"weight": "bold", "size": float(st.get("callout_font_size", 18.5))},
        )
        for txt in leg.get_texts():
            txt.set_fontweight("bold")

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    _configure_axis_ticks(ax, st, has_y_ticks=False)
    _bold_ticks(ax)

    fig.tight_layout()
    paths = save_publication_figure(fig, out_stem, st)
    return paths, processed_curves


def plot_nyquist(
    eis_series: List[Dict[str, Any]],
    out_stem: str | Path,
    add_hf_inset: bool = True,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render isometric 1:1 Ohm/inch EIS Nyquist plot inside a standard 4:3 frame (`X_span : Y_span = 4 : 3`)."""
    st = style or load_style()
    apply_rcparams(st)
    pal = st["series_palette"]

    fig, ax = plt.subplots(figsize=(6.8, 5.1))

    max_zr = 0.0
    max_nzi = 0.0
    hf_zr = 0.0
    hf_nzi = 0.0
    for idx, item in enumerate(eis_series):
        zr = np.asarray(item["z_real"], dtype=float)
        nzi = np.asarray(item["neg_z_imag"], dtype=float)
        col = item.get("color") or pal[idx % len(pal)]
        ax.plot(
            zr,
            nzi,
            marker="o",
            ms=5.0,
            mfc=col,
            mec=col,
            mew=1.2,
            lw=1.6,
            color=col,
            label=item["name"],
            zorder=5 + idx,
        )
        max_zr = max(max_zr, float(np.max(zr)))
        max_nzi = max(max_nzi, float(np.max(nzi)))
        n_hf = max(6, len(zr) // 3)
        hf_zr = max(hf_zr, float(np.max(zr[:n_hf])))
        hf_nzi = max(hf_nzi, float(np.max(nzi[:n_hf])))

    if max_nzi > 2.2 * max(max_zr, 1.0):
        req_y = min(max_nzi * 1.08, max(900.0, max_zr * 1.45))
        req_x = max(max_zr * 1.08, 1.0)
    else:
        req_x = max(max_zr * 1.08, 1.0)
        req_y = max(max_nzi * 1.08, 1.0)
    need_step = max(req_x / 4.0, req_y / 3.0, 1e-6)
    step = float(math.ceil(need_step / 5000.0) * 5000.0)
    for cand in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 3.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0, 250.0, 300.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0, 5000.0):
        if cand + 1e-9 >= need_step:
            step = float(cand)
            break
    xlim_top = 4.0 * step
    ylim_top = 3.0 * step

    ax.set_xlim(0.0, xlim_top)
    ax.set_ylim(0.0, ylim_top)
    ax.set_aspect("equal", adjustable="box")
    ax.xaxis.set_major_locator(ticker.MultipleLocator(step))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(step))

    ax.set_xlabel("$Z'$ ($\\Omega$)")
    ax.set_ylabel("$-Z''$ ($\\Omega$)")
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    _bold_ticks(ax)

    leg = ax.legend(loc="upper right", frameon=False, prop={"weight": "bold", "size": 11.5})
    for txt in leg.get_texts():
        txt.set_fontweight("bold")

    if add_hf_inset and 0 < max(hf_zr, hf_nzi) < 0.42 * xlim_top:
        ax_in = ax.inset_axes([0.51, 0.14, 0.42, 0.42])
        for idx, item in enumerate(eis_series):
            zr = np.asarray(item["z_real"], dtype=float)
            nzi = np.asarray(item["neg_z_imag"], dtype=float)
            col = item.get("color") or pal[idx % len(pal)]
            ax_in.plot(zr, nzi, marker="o", ms=3.6, mfc=col, mec=col, lw=1.2, color=col)
        in_u = max((hf_zr * 1.15) / 4.0, (hf_nzi * 1.15) / 3.0, 0.5)
        ax_in.set_xlim(0.0, 4.0 * in_u)
        ax_in.set_ylim(0.0, 3.0 * in_u)
        ax_in.set_aspect("equal", adjustable="box")
        ax_in.tick_params(labelsize=9.5, direction="out")
        for sp in ax_in.spines.values():
            sp.set_linewidth(1.2)
        _bold_ticks(ax_in)

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_bet_dual(
    isotherm: Dict[str, Any],
    psd: Dict[str, Any],
    out_stem: str | Path,
    bet_surface_area_m2_g: Optional[float] = None,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render two-panel BET characterization: (a) N2 Adsorption-Desorption Isotherm + (b) Pore Size Distribution."""
    st = style or load_style()
    apply_rcparams(st)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.7))

    col_iso = "#1F4E79"
    ax1.plot(
        isotherm["ads_p_p0"],
        isotherm["ads_vol"],
        marker="o",
        ms=5.2,
        mfc=col_iso,
        mec=col_iso,
        lw=1.8,
        color=col_iso,
        label="Adsorption",
    )
    ax1.plot(
        isotherm["des_p_p0"],
        isotherm["des_vol"],
        marker="o",
        ms=5.2,
        mfc="white",
        mec="#C0392B",
        mew=1.5,
        lw=1.8,
        color="#C0392B",
        label="Desorption",
    )
    ax1.set_xlim(-0.02, 1.03)
    ax1.set_xlabel("Relative Pressure ($P/P_0$)")
    ax1.set_ylabel("Quantity Adsorbed ($\\mathrm{cm^3\\ g^{-1}}$ STP)")
    ax1.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax1.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax1.text(0.04, 0.94, "(a)", transform=ax1.transAxes, fontsize=13.5, fontweight="bold", va="top")
    if bet_surface_area_m2_g is not None:
        ax1.text(
            0.06,
            0.66,
            f"$S_\\mathrm{{BET}}$ = {bet_surface_area_m2_g:.1f} $\\mathrm{{m^2\\ g^{{-1}}}}$",
            transform=ax1.transAxes,
            fontsize=11.5,
            fontweight="bold",
            color="#1F4E79",
        )
    leg1 = ax1.legend(loc="upper left", bbox_to_anchor=(0.04, 0.87), frameon=False, prop={"weight": "bold", "size": 11.5})
    for t in leg1.get_texts():
        t.set_fontweight("bold")
    _bold_ticks(ax1)

    col_psd = "#2E8B57"
    d_nm = psd["diameter_nm"]
    dv = psd["diff_vol"]
    ax2.plot(d_nm, dv, marker="s", ms=4.8, mfc=col_psd, mec=col_psd, lw=1.8, color=col_psd)
    ax2.fill_between(d_nm, 0.0, dv, color=col_psd, alpha=0.22)
    ax2.set_xlabel("Pore Diameter (nm)")
    ax2.set_ylabel(psd["y_label"])
    ax2.set_ylim(0.0, float(np.max(dv)) * 1.18)
    ax2.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax2.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax2.text(0.04, 0.94, "(b)", transform=ax2.transAxes, fontsize=13.5, fontweight="bold", va="top")
    _bold_ticks(ax2)

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_particle_size_log(
    ps_data: Dict[str, Any],
    out_stem: str | Path,
    sample_title: str = "Sample 1",
    x_limits: Tuple[float, float] = (0.5, 200.0),
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render Mastersizer Log10-X Dual-Y (Differential Vol% + Cumulative Vol%) particle size distribution."""
    st = style or load_style()
    apply_rcparams(st)

    fig, ax1 = plt.subplots(figsize=(6.5, 4.9))
    ax2 = ax1.twinx()

    sz = ps_data["size_um"]
    diff_v = ps_data["diff_vol_pct"]
    cum_v = ps_data["cum_vol_pct"]

    c1 = "#1F4E79"
    c2 = "#C0392B"

    ax1.set_xscale("log")
    ax1.plot(sz, diff_v, color=c1, lw=2.1, label="Differential Volume (%)")
    ax1.fill_between(sz, 0.0, diff_v, color="#4A8DB7", alpha=0.35)
    ax2.plot(sz, cum_v, color=c2, lw=2.0, ls="--", label="Cumulative Volume (%)")

    ax1.set_xlim(x_limits[0], x_limits[1])
    ax1.set_ylim(0.0, float(np.max(diff_v)) * 1.24)
    ax2.set_ylim(0.0, 108.0)

    ax1.set_xlabel("Particle Size ($\\mu$m)")
    ax1.set_ylabel("Volume Density (%)", color=c1)
    ax2.set_ylabel("Cumulative Volume (%)", color=c2)
    ax1.tick_params(axis="x", pad=5)
    ax1.tick_params(axis="y", colors=c1, pad=4)
    ax2.tick_params(axis="y", colors=c2, direction="in", pad=5)

    meta = ps_data.get("metrics", {})
    if "D50_um" in meta:
        info_txt = (
            f"$D_{{10}}$ = {meta.get('D10_um', 0):.2f} $\\mu$m\n"
            f"$D_{{50}}$ = {meta.get('D50_um', 0):.2f} $\\mu$m\n"
            f"$D_{{90}}$ = {meta.get('D90_um', 0):.2f} $\\mu$m"
        )
        ax1.text(
            0.05,
            0.93,
            f"{sample_title}\n{info_txt}",
            transform=ax1.transAxes,
            fontsize=11.2,
            fontweight="bold",
            va="top",
            ha="left",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#CCCCCC", alpha=0.9),
        )

    _bold_ticks(ax1)
    _bold_ticks(ax2)
    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_epr_derivative(
    x: np.ndarray,
    epr_metrics: Dict[str, Any],
    out_stem: str | Path,
    x_label: str = "$g$-factor",
    sample_title: str = "Sample 1",
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render first-derivative EPR spectrum with zero-crossing g-factor marker."""
    st = style or load_style()
    apply_rcparams(st)

    y_corr = epr_metrics["y_corrected"]
    g0 = epr_metrics["center_zero_crossing"]

    fig, ax = plt.subplots(figsize=(6.2, 4.7))
    ax.axhline(0.0, color="#888888", lw=1.0, ls=":", zorder=2)
    ax.axvline(g0, color="#C0392B", lw=1.2, ls="--", zorder=3)
    ax.plot(x, y_corr, color="#1F4E79", lw=2.0, zorder=5)

    span_y = max(float(np.max(np.abs(y_corr))), 1e-9)
    ax.set_ylim(-1.22 * span_y, 1.26 * span_y)
    # Invert g-axis if x is g-factor (standard EPR magnetic field increases left-to-right => g decreases left-to-right)
    if "g" in x_label.lower():
        ax.set_xlim(float(np.max(x)), float(np.min(x)))
        lbl_str = f"$g$ = {g0:.4f}"
    else:
        ax.set_xlim(float(np.min(x)), float(np.max(x)))
        lbl_str = f"$B_0$ = {g0:.1f} G"

    ax.text(0.05, 0.93, sample_title, transform=ax.transAxes, fontsize=13.5, fontweight="bold", va="top")
    ax.text(
        0.95,
        0.93,
        lbl_str,
        transform=ax.transAxes,
        fontsize=12.5,
        fontweight="bold",
        color="#C0392B",
        va="top",
        ha="right",
    )
    ax.set_xlabel(x_label)
    ax.set_ylabel("EPR Intensity (a.u.)")
    ax.set_yticks([])
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    _bold_ticks(ax)

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_conductivity_pressure(
    cond_data: Dict[str, Any],
    out_stem: str | Path,
    sample_title: str = "Sample 1",
    log_conductivity: bool = True,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render Powder Conductivity & Compact Density vs Pressure Dual-Y curve."""
    st = style or load_style()
    apply_rcparams(st)

    fig, ax1 = plt.subplots(figsize=(6.4, 4.8))
    pr = cond_data["pressure_MPa"]
    cond = cond_data["conductivity"]
    dens = cond_data["density_g_cm3"]

    c1 = "#1F4E79"
    c2 = "#2E8B57"

    if log_conductivity and np.all(cond > 0):
        ax1.set_yscale("log")
    ax1.plot(pr, cond, marker="o", ms=6.0, mfc=c1, mec=c1, lw=2.0, color=c1, label="Conductivity")
    ax1.set_xlabel("Compaction Pressure (MPa)")
    ax1.set_ylabel(cond_data["conductivity_label"], color=c1)
    ax1.tick_params(axis="y", colors=c1)
    ax1.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))

    if np.isfinite(dens).sum() >= 3:
        ax2 = ax1.twinx()
        ax2.plot(pr, dens, marker="s", ms=5.5, mfc="white", mec=c2, mew=1.5, lw=1.8, ls="--", color=c2, label="Compact Density")
        ax2.set_ylabel("Compact Density ($\\mathrm{g\\ cm^{-3}}$)", color=c2)
        ax2.tick_params(axis="y", colors=c2, direction="in")
        _bold_ticks(ax2)

    ax1.text(0.05, 0.93, sample_title, transform=ax1.transAxes, fontsize=13.0, fontweight="bold", va="top")
    _bold_ticks(ax1)

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_xy_multi_series(
    series_list: List[Dict[str, Any]],
    out_stem: str | Path,
    x_label: str,
    y_label: str,
    log_x: bool = False,
    log_y: bool = False,
    invert_x: bool = False,
    show_markers: bool = True,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render publication multi-series XY curves (Galvanostatic Rate, Short-Pulse XYXY, Ragone, GITT D_Li+)."""
    st = style or load_style()
    apply_rcparams(st)
    pal = st["series_palette"]
    mks = ["o", "s", "^", "D", "v", "P"]

    fig, ax = plt.subplots(figsize=(6.4, 4.9))
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")

    xmin_all, xmax_all = [], []
    for idx, s in enumerate(series_list):
        x = np.asarray(s["x"], dtype=float)
        y = np.asarray(s["y"], dtype=float)
        col = s.get("color") or pal[idx % len(pal)]
        mk = mks[idx % len(mks)] if (show_markers and len(x) <= 80) else None
        ax.plot(
            x,
            y,
            color=col,
            lw=2.0,
            marker=mk,
            ms=5.2 if mk else 0,
            mfc="white" if idx % 2 == 1 else col,
            mec=col,
            mew=1.4,
            label=s["name"],
        )
        xmin_all.append(float(np.min(x)))
        xmax_all.append(float(np.max(x)))

    if invert_x:
        ax.set_xlim(max(xmax_all), min(xmin_all))

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    if not log_x:
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    if not log_y:
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    _bold_ticks(ax)

    if len(series_list) > 1 or series_list[0].get("name"):
        leg = ax.legend(loc="best", frameon=False, prop={"weight": "bold", "size": 11.5})
        for t in leg.get_texts():
            t.set_fontweight("bold")

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_composite_figure(
    panels_rendered: List[Dict[str, Any]],
    out_stem: str | Path,
    ncols: int = 2,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Render a journal-grade Multi-Modal Paper Composite Figure ((a)-(d) / (a)-(f)),
    combining heterogeneous modalities (XPS/Raman deconvolutions, XRD/FTIR waterfalls,
    1:1 EIS Nyquist with HF inset, EPR derivative, or Neware rate discharge curves).
    """
    st = style or load_style()
    apply_rcparams(st)
    pal = st["series_palette"]

    n_panels = len(panels_rendered)
    ncols = max(1, min(ncols, n_panels))
    nrows = math.ceil(n_panels / ncols)

    fig, axes = plt.subplots(nrows, ncols, figsize=(6.1 * ncols, 4.9 * nrows), squeeze=False)
    flat_axes = axes.flatten()

    for idx, p in enumerate(panels_rendered):
        ax = flat_axes[idx]
        letter = chr(ord("a") + idx)
        p_label = f"({letter}) {p.get('panel_title', '')}".strip()
        ptype = p["panel_type"]

        if ptype == "deconvolve":
            _draw_deconv_on_ax(
                ax,
                p["fit_result"],
                left_title=p_label,
                right_title=p.get("right_title", ""),
                style=st,
                show_legend=True,
                compact_panel=True,
            )

        elif ptype == "waterfall":
            proc = p["processed_curves"]
            invert_x = bool(p.get("invert_x", False))
            offset_step = float(p.get("offset_step", 1.18))
            top_y_max = 0.0
            xmin_l, xmax_l = [], []
            for s_i, c_item in enumerate(proc):
                xv, y_off = c_item["x"], c_item["y_offset"]
                col = c_item["color"]
                ax.plot(xv, y_off, color=col, lw=1.65, zorder=4 + s_i)
                n_pts = len(xv)
                seg_slice = slice(0, max(6, int(0.26 * n_pts))) if invert_x else slice(min(n_pts - 6, int(0.72 * n_pts)), n_pts)
                x_seg, y_seg = xv[seg_slice], y_off[seg_slice]
                win_w = max(3, len(y_seg) // 5)
                best_pos, best_sc = 0, float("inf")
                for k_i in range(0, max(1, len(y_seg) - win_w)):
                    sub = y_seg[k_i : k_i + win_w]
                    sc = float(np.max(sub) - np.min(sub)) + 0.35 * float(np.mean(sub) - s_i * offset_step)
                    if sc < best_sc:
                        best_sc, best_pos = sc, k_i + win_w // 2
                ax.text(
                    float(x_seg[best_pos]),
                    float(y_seg[best_pos]) + 0.13 * offset_step,
                    c_item["name"],
                    color=col,
                    fontsize=9.8,
                    fontweight="bold",
                    ha="center",
                    va="bottom",
                    bbox=dict(boxstyle="round,pad=0.06", fc="white", ec="none", alpha=0.72),
                    zorder=10,
                )
                xmin_l.append(float(np.min(xv)))
                xmax_l.append(float(np.max(xv)))
                top_y_max = max(top_y_max, float(np.max(y_off)))

            xmin_g, xmax_g = min(xmin_l), max(xmax_l)
            ax.set_xlim(xmax_g, xmin_g) if invert_x else ax.set_xlim(xmin_g, xmax_g)
            ax.set_ylim(-0.14 * offset_step, top_y_max + 1.05 * offset_step)
            for m_i, mk in enumerate(p.get("markers", [])):
                pos = float(mk["pos"])
                if xmin_g <= pos <= xmax_g:
                    ax.axvline(pos, color="#6E6E6E", ls="--", lw=1.0, alpha=0.82, zorder=2)
                    ax.text(
                        pos,
                        top_y_max + (0.16 + 0.30 * (m_i % 2)) * offset_step,
                        mk["label"],
                        fontsize=8.8,
                        fontweight="bold",
                        color="#333333",
                        ha="center",
                        va="bottom",
                        bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="none", alpha=0.8),
                    )
            ax.text(0.03, 0.96, p_label, transform=ax.transAxes, fontsize=11.8, fontweight="bold", va="top", ha="left")
            ax.set_xlabel(p.get("x_label", "X"))
            ax.set_ylabel(p.get("y_label", "Intensity (a.u.)"))
            ax.set_yticks([])
            ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
            _bold_ticks(ax)

        elif ptype == "nyquist":
            eis_series = p["eis_series"]
            mks = ["o", "s", "^", "D"]
            max_span, hf_max = 0.0, 0.0
            for s_i, item in enumerate(eis_series):
                zr, nzi = item["z_real"], item["neg_z_imag"]
                col = item.get("color") or pal[s_i % len(pal)]
                mk = mks[s_i % len(mks)]
                ax.plot(zr, nzi, marker=mk, ms=4.5, mfc="white" if s_i % 2 == 1 else col, mec=col, lw=1.5, color=col, label=item["name"])
                max_span = max(max_span, float(np.max(zr)), float(np.max(nzi)))
                n_hf = max(6, len(zr) // 3)
                hf_max = max(hf_max, float(np.max(zr[:n_hf])), float(np.max(nzi[:n_hf])))
            lim = max_span * 1.16
            ax.set_xlim(0.0, lim)
            ax.set_ylim(0.0, lim)
            ax.set_aspect("equal", adjustable="box")
            ax.set_xlabel("$Z'$ ($\\Omega$)")
            ax.set_ylabel("$-Z''$ ($\\Omega$)")
            ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
            ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
            ax.text(0.04, 0.95, p_label, transform=ax.transAxes, fontsize=11.8, fontweight="bold", va="top")
            leg = ax.legend(loc="lower right", frameon=False, prop={"weight": "bold", "size": 10.2})
            for t in leg.get_texts():
                t.set_fontweight("bold")
            if p.get("add_hf_inset", True) and 0 < hf_max < 0.38 * lim:
                ax_in = ax.inset_axes([0.52, 0.50, 0.43, 0.43])
                for s_i, item in enumerate(eis_series):
                    col = item.get("color") or pal[s_i % len(pal)]
                    ax_in.plot(item["z_real"], item["neg_z_imag"], marker=mks[s_i % len(mks)], ms=3.2, mfc="white" if s_i % 2 == 1 else col, mec=col, lw=1.1, color=col)
                in_lim = hf_max * 1.15
                ax_in.set_xlim(0.0, in_lim)
                ax_in.set_ylim(0.0, in_lim)
                ax_in.set_aspect("equal", adjustable="box")
                ax_in.tick_params(labelsize=8.5, direction="in")
                _bold_ticks(ax_in)
            _bold_ticks(ax)

        elif ptype == "xy_series":
            series_list = p["series_list"]
            if p.get("log_x"):
                ax.set_xscale("log")
            if p.get("log_y"):
                ax.set_yscale("log")
            for s_i, s in enumerate(series_list):
                col = s.get("color") or pal[s_i % len(pal)]
                ax.plot(s["x"], s["y"], color=col, lw=1.9, label=s["name"])
            if p.get("invert_x"):
                xmin_all = min(float(np.min(s["x"])) for s in series_list)
                xmax_all = max(float(np.max(s["x"])) for s in series_list)
                ax.set_xlim(xmax_all, xmin_all)
            if p.get("y_limits"):
                ax.set_ylim(p["y_limits"][0], p["y_limits"][1])
            ax.set_xlabel(p.get("x_label", "X"))
            ax.set_ylabel(p.get("y_label", "Y"))
            if not p.get("log_x"):
                ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
            if not p.get("log_y"):
                ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
            ax.text(0.08, 0.95, p_label, transform=ax.transAxes, fontsize=11.8, fontweight="bold", va="top")
            leg = ax.legend(loc=p.get("legend_loc", "upper right"), frameon=False, prop={"weight": "bold", "size": 10.2})
            for t in leg.get_texts():
                t.set_fontweight("bold")
            _bold_ticks(ax)

    for extra_i in range(n_panels, len(flat_axes)):
        flat_axes[extra_i].axis("off")

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)


def plot_raw_spectrum(
    x: np.ndarray,
    y: np.ndarray,
    out_stem: str | Path,
    region_title: str = "Raw Spectrum",
    sample_title: str = "Sample",
    x_label: str = "Binding Energy (eV)",
    y_label: str = "Intensity (Counts / s)",
    invert_x: bool = True,
    snr: Optional[float] = None,
    peak_x: Optional[float] = None,
    style: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Render clean raw spectrum preview (for unfamiliar material systems or unmodeled regions prior to fitting)."""
    st = style or load_style()
    apply_rcparams(st)

    fig, ax = plt.subplots(figsize=(6.4, 4.7))
    col = st["series_palette"][0]
    ax.plot(x, y, color=col, lw=1.9, label="Raw Signal", zorder=4)
    k = max(1, min(6, len(y) // 8))
    y_bg = np.linspace(float(np.mean(y[:k])), float(np.mean(y[-k:])), len(x))
    ax.plot(x, y_bg, color="#666666", lw=1.05, ls="--", label="Endpoint Guide", zorder=3)

    if peak_x is None and len(x) > 0:
        peak_x = float(x[int(np.argmax(y - y_bg))])
    if peak_x is not None:
        pk_idx = int(np.argmin(np.abs(x - peak_x)))
        ax.axvline(peak_x, color="#C0392B", lw=1.1, ls=":", alpha=0.85, zorder=2)
        ax.scatter([peak_x], [float(y[pk_idx])], color="#C0392B", s=34, zorder=6)

    ymin, ymax = float(np.min(y)), float(np.max(y))
    yrange = max(ymax - ymin, 1e-6)
    ax.set_ylim(ymin - 0.16 * yrange, ymax + 0.22 * yrange)
    ax.set_xlim(float(np.max(x)), float(np.min(x))) if invert_x else ax.set_xlim(float(np.min(x)), float(np.max(x)))

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    _configure_axis_ticks(ax, st, has_y_ticks=False)
    _bold_ticks(ax)

    ax.text(0.04, 0.94, f"{region_title} (Raw Preview)", transform=ax.transAxes, fontsize=13.0, fontweight="bold", va="top")
    ax.text(0.96, 0.94, sample_title, transform=ax.transAxes, fontsize=13.0, fontweight="bold", va="top", ha="right")
    info_lines = []
    if peak_x is not None:
        info_lines.append(f"Max Peak: {peak_x:.2f}")
    if snr is not None:
        info_lines.append(f"Est. SNR: {snr:.1f}" + (" (Trace < 3.5)" if snr < 3.5 else ""))
    info_lines.append("Unfitted Raw Preview")
    ax.text(
        0.96,
        0.05,
        "\n".join(info_lines),
        transform=ax.transAxes,
        fontsize=9.5,
        fontweight="bold",
        color="#2E5B88" if (snr is None or snr >= 3.5) else "#9B2C2C",
        va="bottom",
        ha="right",
        bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#CCCCCC", alpha=0.88),
        zorder=10,
    )
    leg = ax.legend(loc="upper left", bbox_to_anchor=(0.03, 0.85), frameon=False, prop={"weight": "bold", "size": 11.0})
    for txt in leg.get_texts():
        txt.set_fontweight("bold")

    fig.tight_layout()
    return save_publication_figure(fig, out_stem, st)
