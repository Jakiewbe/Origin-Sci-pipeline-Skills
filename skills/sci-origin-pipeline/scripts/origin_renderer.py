"""
origin_renderer.py - 100% Pure OriginPro 2024 Native Multi-Chart Rendering & Direct Export Engine.

Renders declarative `chart_grammar.FigureSpec` specifications directly inside headless OriginPro 2024
and exports publication-ready 600 DPI LZW `.tif`, 300 DPI `.png`, and `<=960 px` QA `.jpg` previews
via native `expGraph` (`tr.Margin:=2`), with zero dependency on `matplotlib` and zero `GraphObject` overlines.
"""
from __future__ import annotations

import math
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import chart_grammar as cg
import origin_builder as ob
import origin_theme as ot

# Re-export public Origin export & bar gradient helpers
export_origin_publication_figures = ob.export_origin_publication_figures
apply_origin_bar_gradient_and_label = ob.apply_origin_bar_gradient_and_label


def _sanitize_file_stem(name: str, default: str = "SciOrigin_Figure") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return cleaned or default


def _python_fmt_to_origin_fmt(fmt: Optional[str]) -> str:
    if not fmt:
        return ".2"
    s = str(fmt).strip()
    if s.startswith("."):
        return s
    m = re.search(r"\.(\d+)[fFgGeE]", s)
    if m:
        return f".{m.group(1)}"
    if "d" in s:
        return ".0"
    return ".2"


def _format_origin_guide_text(raw_text: str) -> str:
    """Convert scientific guide/span labels (`Delta V_0,app`, `ΔVslow`, `cm^-1`) into clean Origin rich text."""
    s = str(raw_text or "").strip()
    if not s:
        return ""
    s = s.replace("$", "").replace("\\mathrm", "")
    s = s.replace("\\Delta", "\\g(D)").replace("Δ", "\\g(D)")
    s = re.sub(r"\bDelta\s*", lambda _: "\\g(D)", s)
    s = s.replace("\\tau", "\\g(t)").replace("τ", "\\g(t)")
    s = s.replace("\\gamma", "\\g(g)").replace("γ", "\\g(g)")
    s = s.replace("\\theta", "\\g(q)").replace("θ", "\\g(q)")
    s = re.sub(r"\bOhm\b", lambda _: "\\g(W)", s)
    s = s.replace("pulse_end", "pulse,end")

    s = re.sub(r"\^\{([^}]+)\}", r"\\+(\1)", s)
    s = re.sub(r"\^(-?\d+)", r"\\+(\1)", s)
    s = re.sub(r"_\{([^}]+)\}", r"\\-(\1)", s)
    s = re.sub(
        r"\b([VEI])_(0,app|slow,app|0,pol|slow,pol|total,app|rec,app|before|instant|pulse,end|final)\b",
        r"\1\\-(\2)",
        s,
    )
    s = re.sub(r"\b([VE])(0,app|slow,app|0,pol|slow,pol)\b", r"\1\\-(\2)", s)
    s = re.sub(r"\b([A-Za-z0-9]+)_([A-Za-z0-9,+-]+)\b", r"\1\\-(\2)", s)
    s = re.sub(r"\{\s*([^}]*)\s*\}", r"\1", s)
    return s


def _line_style_code(style_name: str) -> int:
    s = str(style_name or "solid").strip().lower()
    if s in ("dashed", "dash", "--"):
        return 1
    if s in ("dotted", "dot", ":"):
        return 2
    if s in ("dashdot", "-."):
        return 3
    return 0


def _marker_cmd_and_interior(marker_style: str) -> Tuple[Optional[int], int]:
    """
    Map declarative marker names to `(shape_code, fill_mode)` (`shape_code`: `1=Sq, 2=Circle, 3=UpTri, 4=DownTri, 5=Diamond`;
    `fill_mode`: `1=Solid`, `2=Open`). Note: Origin's `Plot.symbol_interior` (`SetNumProp('symbol.interior')`) uses 0-based
    Origin C codes (`0=Solid ●`, `1=Open white-fill ○`), NOT LabTalk `-kf`'s 1-based codes.
    """
    m = str(marker_style or "none").strip().lower()
    if m in ("none", "", "false"):
        return None, 1
    if m in ("circle_open", "open_circle", "o_open"):
        return 2, 2
    if m in ("sphere_3d", "sphere", "ball", "3d", "circle_solid", "circle", "o"):
        return 2, 1
    if m in ("square", "s", "square_solid"):
        return 1, 1
    if m in ("square_open",):
        return 1, 2
    if m in ("triangle_up", "triangle", "^"):
        return 3, 1
    if m in ("triangle_down", "v"):
        return 4, 1
    if m in ("diamond", "d"):
        return 5, 1
    return 2, 1


def _apply_dp_gradient_and_label_raw(
    dp_obj: Any,
    c_prim: int,
    c_bottom: Optional[int] = None,
    *,
    shading_mode: int = 0,
    grad_lightness: int = 90,
    grad_dir: int = 0,
    gap: int = 24,
    border_color: int = -4,
    border_width: float = 1.4,
    label_color: Optional[int] = None,
    label_size: float = 22.0,
    label_fmt: str = ".2",
    has_yerr: bool = True,
    tnr_face_dword: int = 1852392883,
) -> None:
    bold_i = int(ob.get_active_spec()["bold_int"])
    tr = dp_obj.Theme
    fill = tr.Pattern.Fill
    fill.SetIntValue(int(c_prim), "FillColor")
    fill.SetIntValue(int(shading_mode), "ShadingMode")
    dp_obj.Theme = tr

    tr = dp_obj.Theme
    fill = tr.Pattern.Fill
    fill.SetIntValue(int(c_prim), "FillColor")
    fill.SetIntValue(int(shading_mode), "ShadingMode")
    fill.SetIntValue(int(grad_dir), "GradDirection")
    if shading_mode == 2 and c_bottom is not None:
        fill.SetIntValue(int(c_bottom), "GradColor")
    elif shading_mode == 1:
        fill.SetIntValue(int(grad_lightness), "GradLightness")

    if tr.Pattern.Border is not None:
        tr.Pattern.Border.SetIntValue(int(border_color), "Color")
        tr.Pattern.Border.SetDoubleValue(float(border_width), "Width")
    if tr.Spacing is not None:
        tr.Spacing.SetIntValue(int(gap), "Gap")

    if label_color is not None and tr.Label is not None:
        lbl = tr.Label
        lbl.SetIntValue(1, "Enable")
        lbl.SetIntValue(3, "PosColumn")
        lbl.SetDoubleValue(float(label_size), "Size")
        lbl.SetIntValue(bold_i, "Bold")
        lbl.SetIntValue(int(label_color), "Color")
        lbl.SetIntValue(0, "FrameType")
        lbl.SetIntValue(0, "WhiteOut")
        lbl.SetIntValue(1, "Form")
        lbl.SetStrValue(str(label_fmt), "FormatString")
        lbl.SetIntValue(20 if has_yerr else 10, "YOffset")
        if tnr_face_dword:
            lbl.SetIntValue(int(tnr_face_dword), "Face")

    dp_obj.Theme = tr


def _resolve_1d_equal_aspect_bounds_and_step(
    panel: cg.PanelSpec,
    xs: Sequence[float],
    ys: Sequence[float],
    target_ratio: float = 4.0 / 3.0,
) -> Tuple[Tuple[float, float], Tuple[float, float], Optional[float]]:
    """
    Resolve isometric `X_span : Y_span == target_ratio` (`4:3` on standard `6.40 x 4.80 in` frame) bounds
    and shared `major_step` for 1D `panel.equal_aspect=True` charts (EIS Nyquist).
    - Auto-infer (`limits is None`): `(0, 4*step)` x `(0, 3*step)` with shared `step`.
    - Explicit `4:3` limits (within 2%): preserve exact `limits` and `major_step`.
    - Legacy square `(0, L)` x `(0, L)` or non-`4:3` limits: adapt cleanly to `4:3` without clipping any data point.
    """
    x_lim_in = panel.x_axis.limits
    y_lim_in = panel.y1_axis.limits
    user_step = panel.x_axis.major_step or panel.y1_axis.major_step

    if x_lim_in is None and y_lim_in is None:
        if abs(target_ratio - (4.0 / 3.0)) <= 0.03:
            xb, yb, st = cg.compute_isometric_4_3_bounds(xs, ys)
            return xb, yb, (float(user_step) if (user_step and user_step > 0) else st)
        max_v = max(max(xs, default=1.0), max(ys, default=1.0)) * 1.10
        st = ob.compute_nice_linear_step(0.0, max_v, max_ticks=5) or 1.0
        top = math.ceil(max_v / st) * st
        return (0.0, top * target_ratio), (0.0, top), st

    if x_lim_in is not None:
        x0, x1 = float(min(x_lim_in)), float(max(x_lim_in))
    else:
        x0, x1 = 0.0, max(float(max(xs, default=1.0)) * 1.08, 1.0)
    if y_lim_in is not None:
        y0, y1 = float(min(y_lim_in)), float(max(y_lim_in))
    else:
        y0, y1 = 0.0, max(float(max(ys, default=1.0)) * 1.08, 1.0)

    dx = max(x1 - x0, 1e-9)
    dy = max(y1 - y0, 1e-9)
    if abs((dx / dy) - target_ratio) <= 0.02 * target_ratio:
        st_keep = float(user_step) if (user_step and user_step > 0) else ob.compute_nice_linear_step(x0, x1, max_ticks=5)
        return (x0, x1), (y0, y1), st_keep

    # Adapt legacy square or non-4:3 limits to exact `target_ratio` without clipping any data point
    max_all_x = float(max(xs)) if xs else x1
    max_all_y = float(max(ys)) if ys else y1
    if abs(target_ratio - (4.0 / 3.0)) <= 0.03 and abs(x0) < 1e-9 and abs(y0) < 1e-9:
        # Check if `(0, x1)` x `(0, 0.75 * x1)` fits all data cleanly without clipping
        if ys and max_all_x <= x1 and max_all_y <= 0.75 * x1 * 0.96 and (x1 / 4.0) in cg.ISO_4_3_STEPS:
            st = x1 / 4.0
            return (0.0, round(4.0 * st, 6)), (0.0, round(3.0 * st, 6)), st
        if (4.0 / 3.0) * y1 + 1e-9 >= x1 and (y1 / 3.0) in cg.ISO_4_3_STEPS:
            st = y1 / 3.0
            return (0.0, round(4.0 * st, 6)), (0.0, round(3.0 * st, 6)), st
        st = cg.pick_iso_4_3_step(x1, y1)
        return (0.0, round(4.0 * st, 6)), (0.0, round(3.0 * st, 6)), st

    if dx / dy < target_ratio:
        new_x1 = x0 + target_ratio * dy
        st = ob.compute_nice_linear_step(x0, new_x1, max_ticks=5)
        return (x0, new_x1), (y0, y1), st
    if ys and max_all_y <= y0 + (dx / target_ratio) * 0.98:
        new_y1 = y0 + (dx / target_ratio)
        st = ob.compute_nice_linear_step(x0, x1, max_ticks=5)
        return (x0, x1), (y0, new_y1), st
    new_x1 = x0 + target_ratio * dy
    st = ob.compute_nice_linear_step(x0, new_x1, max_ticks=5)
    return (x0, new_x1), (y0, y1), st


def _infer_panel_xy_bounds(
    panel: cg.PanelSpec,
    y_axis_filter: str = "y1",
    reserve_top_legend_space: bool = False,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    xs: List[float] = []
    ys: List[float] = []
    has_100_stack = False

    for ly in panel.layers:
        if ly.y_axis != y_axis_filter:
            continue
        if ly.mark == "bar_stacked_100pct":
            has_100_stack = True
            ys.extend([0.0, 100.0])
            n_c = len(ly.categories or (ly.series[0].y if ly.series and ly.series[0].y else []))
            if n_c > 0:
                xs.extend([0.4, float(n_c) + 0.6])
            continue
        if ly.mark == "bar_stacked":
            if ly.series and all(s.y for s in ly.series):
                n_pts = len(ly.series[0].y or [])
                totals = [sum((s.y or [0.0])[i] for s in ly.series) for i in range(n_pts)]
                ys.extend([0.0] + totals)
                xs.extend([0.4, float(n_pts) + 0.6])
            continue
        if ly.mark in ("stat_distribution", "stat_box_jitter"):
            n_g = len(ly.series)
            if n_g > 0:
                xs.extend([0.4, float(n_g) + 0.6])
            for s in ly.series:
                if s.y:
                    ys.extend([float(v) for v in s.y])
            continue
        if ly.mark in ("contour_pseudocolor", "matrix_heatmap") and ly.series:
            s0 = ly.series[0]
            if ly.mark == "matrix_heatmap" and s0.matrix_z is not None:
                z_arr_tmp = np.asarray(s0.matrix_z, dtype=float)
                if z_arr_tmp.ndim == 2:
                    xs.extend([0.5, float(z_arr_tmp.shape[1]) + 0.5])
                    ys.extend([0.5, float(z_arr_tmp.shape[0]) + 0.5])
                continue
            if s0.matrix_x:
                xs.extend([float(min(s0.matrix_x)), float(max(s0.matrix_x))])
            if s0.matrix_y:
                try:
                    ym = [float(v) for v in s0.matrix_y]
                    ys.extend([min(ym), max(ym)])
                except (TypeError, ValueError):
                    ys.extend([1.0, float(len(s0.matrix_y))])
            continue

        for s in ly.series:
            if s.y:
                ys.extend(s.y)
                if s.y_err:
                    ys.extend([yv + ev for yv, ev in zip(s.y, s.y_err)])
                    ys.extend([yv - ev for yv, ev in zip(s.y, s.y_err)])
                if s.y_high:
                    ys.extend(s.y_high)
                if s.y_low:
                    ys.extend(s.y_low)
            if s.x:
                num_x = [float(xv) for xv in s.x if isinstance(xv, (int, float)) and not isinstance(xv, bool)]
                if len(num_x) == len(s.x):
                    xs.extend(num_x)
                else:
                    xs.extend([0.4, float(len(s.x)) + 0.6])
            elif ly.categories:
                xs.extend([0.4, float(len(ly.categories)) + 0.6])

    has_2d_mat = any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers)
    has_stat_any = any(ly.mark in ("stat_distribution", "stat_box_jitter") for ly in panel.layers)
    if (
        panel.equal_aspect
        and not has_2d_mat
        and not has_stat_any
        and y_axis_filter == "y1"
        and panel.x_axis.scale != "log10"
        and panel.y1_axis.scale != "log10"
    ):
        eq_xb, eq_yb, _ = _resolve_1d_equal_aspect_bounds_and_step(panel, xs, ys)
        return eq_xb, eq_yb

    if panel.x_axis.limits is not None:
        x_bounds = (float(min(panel.x_axis.limits)), float(max(panel.x_axis.limits)))
    elif (panel.x_axis.axis_kind == "categorical" and panel.x_axis.categories) or has_stat_any:
        n_c = len(panel.x_axis.categories) if panel.x_axis.categories else max((len(ly.series) for ly in panel.layers), default=1)
        x_bounds = (0.4, float(max(1, n_c)) + 0.6)
    elif xs:
        x_lo, x_hi = min(xs), max(xs)
        if x_hi <= x_lo:
            x_hi = x_lo + 1.0
        x_sp = x_hi - x_lo
        if panel.x_axis.scale == "log10":
            pos_xs = [v for v in xs if v > 0]
            if pos_xs:
                lx0 = 10.0 ** math.floor(math.log10(min(pos_xs)) + 1e-9)
                lx1 = 10.0 ** math.ceil(math.log10(max(pos_xs)) - 1e-9)
                if min(pos_xs) <= 1.12 * lx0:
                    lx0 /= 10.0
                if max(pos_xs) >= 0.88 * lx1:
                    lx1 *= 10.0
                x_bounds = (lx0, max(lx0 * 10.0, lx1))
            else:
                x_bounds = (0.1, 10.0)
        elif not has_2d_mat and not panel.equal_aspect:
            x_pad_lo = 0.0 if (x_lo == 0.0 and x_hi > 0.0) else 0.05 * x_sp
            x_bounds = (x_lo - x_pad_lo, x_hi + 0.05 * x_sp)
        else:
            x_bounds = (x_lo, x_hi)
    else:
        x_bounds = (0.0, 1.0)

    target_ax = panel.y2_axis if (y_axis_filter == "y2" and panel.y2_axis is not None) else panel.y1_axis
    has_stat_y = any(ly.mark in ("stat_distribution", "stat_box_jitter") for ly in panel.layers if ly.y_axis == y_axis_filter)
    if target_ax.limits is not None and not reserve_top_legend_space:
        y_bounds = (float(min(target_ax.limits)), float(max(target_ax.limits)))
    elif has_100_stack:
        y_bounds = (0.0, 136.0 if reserve_top_legend_space else 100.0)
    elif ys:
        y_lo, y_hi = min(ys), max(ys)
        if y_hi <= y_lo:
            y_hi = y_lo + 1.0
        span = y_hi - y_lo
        if target_ax.scale == "log10":
            pos_ys = [v for v in ys if v > 0]
            if pos_ys:
                ly0 = 10.0 ** math.floor(math.log10(min(pos_ys) * 0.85))
                ly1 = 10.0 ** math.ceil(math.log10(max(pos_ys) * 1.18))
                y_bounds = (ly0, max(ly0 * 10.0, ly1))
            else:
                y_bounds = (0.1, 10.0)
        elif has_stat_y:
            y_bounds = (y_lo - 0.14 * span, y_hi + (0.36 if reserve_top_legend_space else 0.22) * span)
        elif reserve_top_legend_space and (y_lo >= 0.0 or panel.align_zero):
            y_bounds = (0.0, y_hi * 1.38)
        elif y_lo >= 0.0 and any("bar" in ly.mark for ly in panel.layers if ly.y_axis == y_axis_filter):
            has_lbl = any(
                (ly.show_value_labels or any(s.show_value_labels for s in ly.series))
                for ly in panel.layers
                if ly.y_axis == y_axis_filter
            )
            pad = 1.30 if has_lbl else 1.18
            y_bounds = (0.0, y_hi * pad)
        elif panel.align_zero and y_lo >= 0.0:
            raw_top = y_hi * 1.22
            step_snap = 10.0 if raw_top >= 25.0 else (5.0 if raw_top >= 10.0 else 1.0)
            y_bounds = (0.0, math.ceil(raw_top / step_snap) * step_snap)
        else:
            y_bounds = (y_lo - 0.07 * span, y_hi + (0.36 if reserve_top_legend_space else 0.22) * span)
    else:
        y_bounds = (0.0, 1.0)

    return x_bounds, y_bounds


def _resolve_clean_origin_template(panel_layers: Sequence[cg.LayerSpec]) -> Optional[str]:
    """Use `STACKCOLUMN` instead of `StackColP` when built-in clutter labels/ribbon links are disabled."""
    for ly in panel_layers:
        if ly.mark in ("bar_stacked", "bar_stacked_100pct"):
            if ly.mark == "bar_stacked_100pct" and (ly.show_value_labels or ly.show_ribbon_links):
                return "StackColP"
            return "STACKCOLUMN"
        if ly.mark in ("stat_distribution", "stat_box_jitter"):
            return None
        if ly.origin_template:
            return ly.origin_template
    return None


def _pick_cleanest_legend_corner(
    panel: cg.PanelSpec,
    x_bounds: Tuple[float, float],
    y_bounds: Tuple[float, float],
) -> str:
    """Choose the interior corner (`corner_upper_left/right` or `corner_lower_left/right`) with lowest data/inset/guide occupancy."""
    style = (panel.legend_style or "").strip().lower()
    if "lower_left" in style or "bottom_left" in style:
        return "corner_lower_left"
    if "lower_right" in style or "bottom_right" in style:
        return "corner_lower_right"
    if "right" in style:
        return "corner_upper_right"
    if "upper_left" in style or "top_left" in style:
        return "corner_upper_left"

    if panel.equal_aspect:
        # Still score-based for equal_aspect (EIS Nyquist): high-frequency data clusters lower-right,
        # so remove the hard-coded early-exit and let data density scoring decide.
        pass

    x_lo, x_hi = min(x_bounds), max(x_bounds)
    y_lo, y_hi = min(y_bounds), max(y_bounds)
    x_sp = max(x_hi - x_lo, 1e-30)
    y_sp = max(y_hi - y_lo, 1e-30)
    inv_x = bool(panel.x_axis.invert)

    # Corners as (fx_min, fx_max, fy_min_from_bottom, fy_max_from_bottom)
    boxes = {
        "corner_upper_left": (0.0, 0.38, 0.72, 1.0),
        "corner_upper_right": (0.62, 1.0, 0.72, 1.0),
        "corner_lower_left": (0.0, 0.38, 0.0, 0.28),
        "corner_lower_right": (0.62, 1.0, 0.0, 0.28),
    }
    scores = {
        "corner_upper_left": 0.0,
        "corner_upper_right": 0.1,
        "corner_lower_left": 0.25,
        "corner_lower_right": 0.35,
    }

    for ins in panel.insets:
        il, it, iw, ih = ins.bbox_pct
        ix0, ix1 = il / 100.0, (il + iw) / 100.0
        iy1, iy0 = 1.0 - it / 100.0, 1.0 - (it + ih) / 100.0
        for cname, (bx0, bx1, by0, by1) in boxes.items():
            if min(ix1, bx1) > max(ix0, bx0) and min(iy1, by1) > max(iy0, by0):
                scores[cname] += 1000.0

    for ly in panel.layers:
        for s in ly.series:
            if not s.x or not s.y:
                continue
            step = max(1, len(s.y) // 120)
            for xv, yv in zip(s.x[::step], s.y[::step]):
                if not isinstance(xv, (int, float)) or not isinstance(yv, (int, float)):
                    continue
                fx = (x_hi - float(xv)) / x_sp if inv_x else (float(xv) - x_lo) / x_sp
                fy = (float(yv) - y_lo) / y_sp
                for cname, (bx0, bx1, by0, by1) in boxes.items():
                    if bx0 <= fx <= bx1 and by0 <= fy <= by1:
                        scores[cname] += 1.0

    for g in panel.guides:
        if g.kind == "hline" and g.value is not None:
            fy = (float(g.value) - y_lo) / y_sp
            for cname, (_bx0, _bx1, by0, by1) in boxes.items():
                if by0 <= fy <= by1:
                    scores[cname] += 6.0 if "right" in cname else 2.0

    return min(scores.keys(), key=lambda k: scores[k])


def _plot_layer_into_glayer(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    layer: cg.LayerSpec,
    panel: cg.PanelSpec,
    wb: Any,
    used_sheets: set[str],
    pal_tmp_dir: Path,
    *,
    categorical_linked_x: bool = False,
) -> List[Tuple[Any, ...]]:
    ob.activate_layer(op, gp, layer_num_1based)
    tnr_dword = ob.get_tnr_face_dword(op)
    leg_entries: List[Tuple[Any, ...]] = []
    sh_name = ob.unique_origin_short_name(layer.layer_id, used_sheets, default="Data")
    wks = wb[0] if len(used_sheets) == 1 else wb.add_sheet(sh_name)
    if len(used_sheets) == 1:
        wks.name = sh_name

    spec = ob.get_active_spec()
    bdr_lw = float(spec["bar_border_lw_pt"])
    sub_w_u = int(spec["sub_w_units"])
    comp_val_pt = ot.compensate_origin_layer_pt(
        float(spec["callout_pt"]),
        float(spec["box_rect_w_in"]),
        float(spec["box_rect_h_in"]),
        float(spec["page_rect_w_in"]),
        float(spec["page_rect_h_in"]),
    )

    # 1. Grouped Bars (Unified Pastel Solid Fill + Crisp Matching Deep Border)
    if layer.mark == "bar_grouped_gradient":
        K = len(layer.series)
        if K == 1:
            s0 = layer.series[0]
            y_vals = list(s0.y or [])
            N = len(y_vals)
            cats = list(layer.categories or [str(v) for v in (s0.x or [f"S{i+1}" for i in range(N)])])
            y_errs = list(s0.y_err) if s0.y_err is not None else None

            diag_cols: Dict[str, Any] = {"Category": cats}
            for i in range(N):
                diag_cols[f"Bar_{i+1}"] = [float(y_vals[i]) if r == i else np.nan for r in range(N)]
                diag_cols[f"Err_{i+1}"] = [
                    float(y_errs[i]) if (y_errs is not None and r == i) else np.nan for r in range(N)
                ]
            wks.from_df(pd.DataFrame(diag_cols))
            wks.set_label(0, panel.x_axis.label or "Category", "L")
            for i in range(N):
                wks.set_label(1 + 2 * i, str(cats[i]), "L")
                if s0.y_unit:
                    wks.set_label(1 + 2 * i, str(s0.y_unit), "U")
            wks.cols_axis("X" + "YE" * N)

            bar_cols = s0.meta.get("bar_colors") or ot.resolve_series_colors(
                N, scheme=("sequential_blue_red" if N > 6 else layer.color_scheme)
            )
            show_lbl = bool(s0.show_value_labels or layer.show_value_labels)
            lbl_fmt = _python_fmt_to_origin_fmt(s0.value_format)
            lbl_sz = comp_val_pt * (0.85 if N >= 8 else 1.0)
            err_ink = ot.hex_to_origin_rgb_int("#222222")

            def _opt_gap_single(n: int) -> int:
                if n <= 2:
                    return 50
                if n == 3:
                    return 38
                if n == 4:
                    return 28
                return 24

            opt_gap = _opt_gap_single(N)

            for i in range(N):
                has_err_i = bool(y_errs is not None and abs(float(y_errs[i])) > 0.0)
                before_cnt = len(gl.plot_list())
                p_i = gl.add_plot(
                    wks,
                    coly=1 + 2 * i,
                    colx=0,
                    colyerr=(2 + 2 * i if has_err_i else -1),
                    type="c",
                )
                after_cnt = len(gl.plot_list())
                bar_p_idx = before_cnt + 1
                if after_cnt >= before_cnt + 2:
                    gl.lt_exec(f"range re = !{after_cnt}; set re -w {sub_w_u}; set re -c {err_ink};")

                pb = ot.compute_pastel_fill_and_border(bar_cols[i % len(bar_cols)])
                c_fill = ot.hex_to_origin_rgb_int(pb["fill_hex"])
                c_bdr = ot.hex_to_origin_rgb_int(pb["border_hex"])
                c_lbl = ot.hex_to_origin_rgb_int(pb["label_hex"]) if show_lbl else None
                apply_origin_bar_gradient_and_label(
                    p_i,
                    c_fill,
                    None,
                    shading_mode=0,
                    gap=opt_gap,
                    border_color=c_bdr,
                    border_width=bdr_lw,
                    label_color=c_lbl,
                    label_size=lbl_sz,
                    label_fmt=lbl_fmt,
                    has_yerr=has_err_i,
                    gl=gl,
                    plot_idx_1based=bar_p_idx,
                    tnr_face_dword=tnr_dword,
                )
            return []

        s_first = layer.series[0]
        n_rows = len(s_first.y or [])
        cats = list(layer.categories or [str(v) for v in (s_first.x or [f"S{i+1}" for i in range(n_rows)])])
        grp_cols: Dict[str, Any] = {"Category": cats}
        axis_pattern = ["X"]
        col_labels: List[Tuple[int, str, Optional[str]]] = []
        cur_col = 1
        any_err = False
        for s in layer.series:
            grp_cols[s.name] = list(s.y or [])
            axis_pattern.append("Y")
            col_labels.append((cur_col, s.name, s.y_unit))
            cur_col += 1
            if s.y_err is not None and any(abs(v) > 0 for v in s.y_err):
                grp_cols[f"{s.name}_Err"] = list(s.y_err)
                axis_pattern.append("E")
                any_err = True
                cur_col += 1

        wks.from_df(pd.DataFrame(grp_cols))
        for c_idx, l_nm, u_nm in col_labels:
            wks.set_label(c_idx, l_nm, "L")
            if u_nm:
                wks.set_label(c_idx, u_nm, "U")
        wks.cols_axis("".join(axis_pattern))

        total_cols = len(axis_pattern)
        op.lt_exec(
            f"plotxy iy:={wks.lt_range(False)}!(1,2:{total_cols}) plot:=203 ogl:=[{gp.name}]{layer_num_1based}!;"
        )
        ob.activate_layer(op, gp, layer_num_1based)
        if not any_err:
            gl.group()

        s_colors = [ot.normalize_hex(s.color or "#3E86DE") for s in layer.series]
        pastel_fills = [ot.compute_pastel_fill_and_border(c)["fill_hex"] for c in s_colors]
        pal_file = pal_tmp_dir / f"{gp.name}_L{layer_num_1based}_grp.pal"
        ot.write_discrete_riff_pal(pal_file, pastel_fills)
        gl.set_str("plot1.colorlist", str(pal_file))
        gl.set_int("plot1.cmap.stretchpal", 0)
        gl.set_int("plot1.colorinc", 1)

        show_lbl = bool(layer.show_value_labels or any(s.show_value_labels for s in layer.series))
        lbl_fmt = _python_fmt_to_origin_fmt(s_first.value_format)
        lbl_col_int = ot.hex_to_origin_rgb_int("#222222") if show_lbl else None
        bdr_grp_int = ot.hex_to_origin_rgb_int("#2B3440")
        dp0 = gl.obj.DataPlots[0]

        K_grp = len(layer.series)
        grp_gap = 20 if K_grp >= 5 else (28 if K_grp == 4 else (38 if K_grp == 3 else 50))
        _apply_dp_gradient_and_label_raw(
            dp0,
            ot.hex_to_origin_rgb_int(pastel_fills[0]),
            shading_mode=0,
            gap=grp_gap,
            border_color=bdr_grp_int,
            border_width=bdr_lw,
            label_color=lbl_col_int,
            label_size=comp_val_pt * 0.85,
            label_fmt=lbl_fmt,
            has_yerr=any_err,
            tnr_face_dword=tnr_dword,
        )
        if K_grp >= 2:
            try:
                tr_dp0 = dp0.Theme
                if tr_dp0.Spacing is not None:
                    tr_dp0.Spacing.SetIntValue(-18, "Overlap")
                dp0.Theme = tr_dp0
            except Exception:
                pass

        n_plts = len(gl.plot_list())
        err_ink = ot.hex_to_origin_rgb_int("#111111")
        if any_err:
            p_cursor = 1
            for s_idx, s in enumerate(layer.series):
                b_col = ot.hex_to_origin_rgb_int(ot.compute_pastel_fill_and_border(s_colors[s_idx])["border_hex"])
                gl.lt_exec(f"range rb = !{p_cursor}; set rb -pbc {b_col}; set rb -pbw {bdr_lw};")
                leg_entries.append((p_cursor, s.name, s_colors[s_idx], "bar"))
                p_cursor += 1
                if s.y_err is not None and any(abs(v) > 0 for v in s.y_err) and p_cursor <= n_plts:
                    gl.lt_exec(f"range re = !{p_cursor}; set re -w {sub_w_u}; set re -c {err_ink};")
                    p_cursor += 1
        else:
            for k_i in range(1, K + 1):
                gl.lt_exec(f"range rb = !{k_i}; set rb -pbc {bdr_grp_int}; set rb -pbw {bdr_lw};")
                leg_entries.append((k_i, layer.series[k_i - 1].name, s_colors[k_i - 1], "bar"))
        return leg_entries

    # 2. Stacked Bars (`bar_stacked` / `bar_stacked_100pct` — Unified Pastel Fill + Crisp Solid Border)
    if layer.mark in ("bar_stacked", "bar_stacked_100pct"):
        K = len(layer.series)
        n_rows = len(layer.series[0].y or [])
        cats = list(layer.categories or [str(v) for v in (layer.series[0].x or [f"S{i+1}" for i in range(n_rows)])])
        st_cols: Dict[str, Any] = {"Category": cats}
        for s in layer.series:
            st_cols[s.name] = list(s.y or [])
        wks.from_df(pd.DataFrame(st_cols))
        wks.set_label(0, panel.x_axis.label or "Category", "L")
        for idx, s in enumerate(layer.series, start=1):
            wks.set_label(idx, s.name, "L")
            if s.y_unit:
                wks.set_label(idx, s.y_unit, "U")
        wks.cols_axis("X" + "Y" * K)

        op.lt_exec(
            f"plotxy iy:={wks.lt_range(False)}!(1,2:{1 + K}) plot:=213 ogl:=[{gp.name}]{layer_num_1based}!;"
        )
        ob.activate_layer(op, gp, layer_num_1based)

        st_colors = [ot.normalize_hex(s.color or "#3E86DE") for s in layer.series]
        st_pastels = [ot.compute_pastel_fill_and_border(c)["fill_hex"] for c in st_colors]
        pal_file = pal_tmp_dir / f"{gp.name}_L{layer_num_1based}_stack.pal"
        ot.write_discrete_riff_pal(pal_file, st_pastels)
        gl.set_str("plot1.colorlist", str(pal_file))
        gl.set_int("plot1.cmap.stretchpal", 0)
        gl.set_int("plot1.colorinc", 1)

        div_int = ot.hex_to_origin_rgb_int("#2B3440")
        div_w = bdr_lw
        for k_i in range(1, K + 1):
            gl.lt_exec(f"range rr = !{k_i}; set rr -pbc {div_int}; set rr -pbw {div_w};")
            leg_entries.append((k_i, layer.series[k_i - 1].name, st_colors[k_i - 1], "bar"))

        try:
            dp0 = gl.obj.DataPlots[0]
            tr = dp0.Theme
            if tr.Pattern.Border is not None:
                tr.Pattern.Border.SetIntValue(div_int, "Color")
                tr.Pattern.Border.SetDoubleValue(div_w, "Width")
            if tr.Spacing is not None:
                tr.Spacing.SetIntValue(26, "Gap")
            if not layer.show_value_labels and tr.Label is not None:
                tr.Label.SetIntValue(0, "Enable")
            dp0.Theme = tr
        except Exception:
            pass

        return leg_entries

    # 3. Statistical Box + Whisker + Jitter Distribution (`stat_distribution` / `stat_box_jitter`)
    if layer.mark in ("stat_distribution", "stat_box_jitter"):
        K = len(layer.series)
        wks.cols = max(1, K)
        for idx, s in enumerate(layer.series):
            grp_lbl = str(s.meta.get("label") or s.name)
            wks.from_list(idx, list(s.y or []), lname=grp_lbl, axis="Y")
        wks.cols_axis("Y" * max(1, K))

        fallback_pal = ot.resolve_series_colors(max(1, K), scheme="paired_semantic")
        distinct_in = {ot.normalize_hex(s.color) for s in layer.series if s.color}
        use_fb_pal = K > 1 and len(distinct_in) <= 1

        hw = 0.24 if K <= 6 else 0.19
        cw = 0.52 * hw
        geom_cols: List[Tuple[str, str, List[float]]] = []
        group_geom_meta: List[Dict[str, Any]] = []

        for g_idx, s in enumerate(layer.series):
            grp_lbl = str(s.meta.get("label") or s.name)
            raw_c = (
                fallback_pal[g_idx % len(fallback_pal)]
                if use_fb_pal
                else (s.color or fallback_pal[g_idx % len(fallback_pal)])
            )
            c_hex = ot.normalize_hex(raw_c)
            vals = np.asarray(
                [float(v) for v in (s.y or []) if v is not None and np.isfinite(float(v))],
                dtype=float,
            )
            if vals.size == 0:
                continue
            q25, med, q75 = [float(v) for v in np.percentile(vals, [25.0, 50.0, 75.0])]
            iqr = max(q75 - q25, 0.0)
            if vals.size >= 3 and iqr > 1e-12:
                lo_in = vals[vals >= q25 - 1.5 * iqr]
                hi_in = vals[vals <= q75 + 1.5 * iqr]
                w_lo = float(np.min(lo_in)) if lo_in.size else float(np.min(vals))
                w_hi = float(np.max(hi_in)) if hi_in.size else float(np.max(vals))
            else:
                w_lo, w_hi = float(np.min(vals)), float(np.max(vals))
            if abs(q75 - q25) < 1e-9:
                eps_b = max(1e-4, 0.015 * max(abs(med), 1.0))
                q25, q75 = med - eps_b, med + eps_b

            x_c = float(g_idx + 1)
            base_col = len(geom_cols)
            # 0,1,2: Box fill X, Upper(Q75), Lower(Q25)
            geom_cols.append(("X", f"G{g_idx+1}_BX", [x_c - hw, x_c + hw]))
            geom_cols.append(("Y", f"G{g_idx+1}_Q75", [q75, q75]))
            geom_cols.append(("Y", f"G{g_idx+1}_Q25", [q25, q25]))
            # 3,4: Closed 4-sided box outline
            geom_cols.append(("X", f"G{g_idx+1}_OutX", [x_c - hw, x_c + hw, x_c + hw, x_c - hw, x_c - hw]))
            geom_cols.append(("Y", f"G{g_idx+1}_OutY", [q25, q25, q75, q75, q25]))
            # 5,6: Median line
            geom_cols.append(("X", f"G{g_idx+1}_MedX", [x_c - hw, x_c + hw]))
            geom_cols.append(("Y", f"G{g_idx+1}_MedY", [med, med]))
            # 7..14: Whisker stems & T-caps
            geom_cols.append(("X", f"G{g_idx+1}_WLoX", [x_c, x_c]))
            geom_cols.append(("Y", f"G{g_idx+1}_WLoY", [q25, w_lo]))
            geom_cols.append(("X", f"G{g_idx+1}_CLoX", [x_c - cw, x_c + cw]))
            geom_cols.append(("Y", f"G{g_idx+1}_CLoY", [w_lo, w_lo]))
            geom_cols.append(("X", f"G{g_idx+1}_WHiX", [x_c, x_c]))
            geom_cols.append(("Y", f"G{g_idx+1}_WHiY", [q75, w_hi]))
            geom_cols.append(("X", f"G{g_idx+1}_CHiX", [x_c - cw, x_c + cw]))
            geom_cols.append(("Y", f"G{g_idx+1}_CHiY", [w_hi, w_hi]))
            # 15,16: Deterministic symmetric jittered replicate points
            n_v = int(vals.size)
            order = np.argsort(vals, kind="mergesort")
            vals_sorted = vals[order]
            if n_v == 1:
                jit_x = [x_c]
            else:
                max_j = min(0.125, 0.54 * hw)
                jit_x = [
                    x_c + max_j * math.sin(2.39996323 * (rank_i + 1) + 0.65 * g_idx)
                    for rank_i in range(n_v)
                ]
            geom_cols.append(("X", f"G{g_idx+1}_PtX", jit_x))
            geom_cols.append(("Y", f"G{g_idx+1}_PtY", [float(v) for v in vals_sorted]))

            group_geom_meta.append(
                {
                    "base": base_col,
                    "label": grp_lbl,
                    "color_hex": c_hex,
                    "has_lo_w": (q25 - w_lo) > 1e-9,
                    "has_hi_w": (w_hi - q75) > 1e-9,
                }
            )

        bx_sh = ob.unique_origin_short_name(f"BoxGeomL{layer_num_1based}", used_sheets, default="BoxGeom")
        wks_bx = wb.add_sheet(bx_sh)
        wks_bx.cols = max(2, len(geom_cols))
        for c_i, (ax_r, c_nm, c_vs) in enumerate(geom_cols):
            wks_bx.from_list(c_i, c_vs, lname=c_nm, axis=ax_r)
        wks_bx.cols_axis("".join(cs[0] for cs in geom_cols))

        ob.activate_layer(op, gp, layer_num_1based)
        bx_out_w = int(round(max(650.0, bdr_lw * 550.0)))
        bx_med_w = int(spec["curve_w_units"])
        bx_wh_w = int(spec["sub_w_units"])
        bx_mk_sz = float(spec["marker_size_pt"])
        for gm in group_geom_meta:
            b0 = int(gm["base"])
            c_hex = str(gm["color_hex"])
            pb_bx = ot.compute_pastel_fill_and_border(c_hex)
            c_oc = ob._hex_to_origin_color(op, pb_bx["border_hex"])
            pastel_oc = ob._hex_to_origin_color(op, pb_bx["fill_hex"])

            p_up = gl.add_plot(wks_bx, coly=b0 + 1, colx=b0, type="l")
            up_idx = len(gl.plot_list())
            p_lo = gl.add_plot(wks_bx, coly=b0 + 2, colx=b0, type="l")
            lo_idx = len(gl.plot_list())
            p_up.color = pastel_oc
            p_lo.color = pastel_oc
            p_up.set_fill_area(above=pastel_oc, type=9, below=pastel_oc)
            p_up.transparency = 14
            p_lo.transparency = 100
            gl.lt_exec(f"range rup = !{up_idx}; set rup -w 40; range rlo = !{lo_idx}; set rlo -w 40;")

            p_out = gl.add_plot(wks_bx, coly=b0 + 4, colx=b0 + 3, type="l")
            out_idx = len(gl.plot_list())
            p_out.color = c_oc
            gl.lt_exec(f"range rout = !{out_idx}; set rout -w {bx_out_w};")

            p_med = gl.add_plot(wks_bx, coly=b0 + 6, colx=b0 + 5, type="l")
            med_idx = len(gl.plot_list())
            p_med.color = c_oc
            gl.lt_exec(f"range rmed = !{med_idx}; set rmed -w {bx_med_w};")

            w_pairs = [(b0 + 9, b0 + 10)]
            if gm["has_lo_w"]:
                w_pairs.insert(0, (b0 + 7, b0 + 8))
            w_pairs.append((b0 + 13, b0 + 14))
            if gm["has_hi_w"]:
                w_pairs.insert(-1, (b0 + 11, b0 + 12))
            for cx_w, cy_w in w_pairs:
                p_w = gl.add_plot(wks_bx, coly=cy_w, colx=cx_w, type="l")
                w_idx = len(gl.plot_list())
                p_w.color = c_oc
                gl.lt_exec(f"range rw = !{w_idx}; set rw -w {bx_wh_w};")

            # Jittered replicate pure 2D solid circles (`symbol_kind=2, symbol_interior=0`)
            p_pt = gl.add_plot(wks_bx, coly=b0 + 16, colx=b0 + 15, type="s")
            p_pt.color = c_oc
            p_pt.symbol_size = bx_mk_sz
            p_pt.symbol_kind = 2
            p_pt.symbol_interior = 0

            leg_entries.append((out_idx, str(gm["label"]), pb_bx["border_hex"], "bar"))

        gl.lt_exec("label -r Legend;")
        return leg_entries

    # 4. Line / Scatter / Shaded Band / Waterfall (`line_scatter`, `waterfall`, `deconv_envelope`)
    col_specs: List[Tuple[str, str, List[Any]]] = []
    series_col_map: List[Dict[str, Optional[int]]] = []

    for s in layer.series:
        yv = list(s.y or [])
        n_pts = len(yv)
        if categorical_linked_x:
            xv: List[Any] = [float(i + 1) for i in range(n_pts)]
        elif s.x is not None and len(s.x) == n_pts:
            if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in s.x):
                xv = [float(v) for v in s.x]
            else:
                xv = [str(v) for v in s.x]
        elif layer.categories and len(layer.categories) == n_pts:
            xv = list(layer.categories)
        else:
            xv = [float(i + 1) for i in range(n_pts)]

        c_map: Dict[str, Optional[int]] = {"x": len(col_specs), "y": None, "err": None, "up": None, "lo": None}
        col_specs.append(("X", f"{s.name}_X", xv))
        c_map["y"] = len(col_specs)
        col_specs.append(("Y", s.name, yv))

        if s.y_err is not None and len(s.y_err) == n_pts and any(abs(v) > 0 for v in s.y_err):
            c_map["err"] = len(col_specs)
            col_specs.append(("E", f"{s.name}_Err", list(s.y_err)))
        if s.y_low is not None and s.y_high is not None and len(s.y_low) == n_pts and len(s.y_high) == n_pts:
            c_map["up"] = len(col_specs)
            col_specs.append(("Y", f"{s.name}_Upper", list(s.y_high)))
            c_map["lo"] = len(col_specs)
            col_specs.append(("Y", f"{s.name}_Lower", list(s.y_low)))

        series_col_map.append(c_map)

    wks.cols = len(col_specs)
    for c_i, (ax_role, c_lname, c_vals) in enumerate(col_specs):
        wks.from_list(c_i, c_vals, lname=c_lname, axis=ax_role)
    wks.cols_axis("".join(cs[0] for cs in col_specs))

    err_ink = ot.hex_to_origin_rgb_int("#111111")
    for s, c_map in zip(layer.series, series_col_map):
        c_hex = ot.normalize_hex(s.color or "#3E86DE")
        c_color = ob._hex_to_origin_color(op, c_hex)
        col_x = int(c_map["x"])  # type: ignore[arg-type]
        col_y = int(c_map["y"])  # type: ignore[arg-type]

        if c_map["up"] is not None and c_map["lo"] is not None:
            pb_band = ot.compute_pastel_fill_and_border(c_hex)
            band_oc = ob._hex_to_origin_color(op, pb_band["fill_hex"])
            p_up = gl.add_plot(wks, coly=int(c_map["up"]), colx=col_x, type="l")
            up_idx = len(gl.plot_list())
            p_lo = gl.add_plot(wks, coly=int(c_map["lo"]), colx=col_x, type="l")
            lo_idx = len(gl.plot_list())
            p_up.color = band_oc
            p_lo.color = band_oc
            p_up.set_fill_area(above=band_oc, type=9, below=band_oc)
            p_up.transparency = 22
            p_lo.transparency = 100
            gl.lt_exec(f"range rup = !{up_idx}; set rup -w 50; range rlo = !{lo_idx}; set rlo -w 50;")

        m_shape, m_int = _marker_cmd_and_interior(s.marker_style)
        has_line = str(s.line_style or "solid").strip().lower() not in ("none", "", "false")
        has_marker = m_shape is not None

        if has_line and has_marker:
            p_type: Any = "y"
        elif has_marker:
            p_type = "s"
        else:
            p_type = "l"

        before_cnt = len(gl.plot_list())
        p_main = gl.add_plot(
            wks,
            coly=col_y,
            colx=col_x,
            colyerr=(int(c_map["err"]) if c_map["err"] is not None else -1),
            type=p_type,
        )
        after_cnt = len(gl.plot_list())
        main_idx = before_cnt + 1
        p_main.color = c_color

        raw_lw = float(s.line_width_pt or spec["curve_lw_pt"])
        if abs(raw_lw - 2.8) < 0.25 or abs(raw_lw - 3.0) < 0.15:
            w_units = int(spec["curve_w_units"])
        else:
            w_units = max(250, int(round(raw_lw * 500.0)))
        d_code = _line_style_code(s.line_style)
        cmd_parts: List[str] = []
        if has_line:
            cmd_parts.append(f"set rm -w {w_units}; set rm -d {d_code};")
        if has_marker and m_shape == 20:
            cmd_parts.append("set rm -k 20;")
        if c_map["up"] is None and s.fill_alpha is not None and s.fill_alpha > 0 and has_line:
            p_main.set_fill_area(above=c_color, type=1, below=c_color)
            p_main.transparency = int(round((1.0 - float(s.fill_alpha)) * 100.0))

        if cmd_parts:
            gl.lt_exec(f"range rm = !{main_idx}; " + " ".join(cmd_parts))

        if has_marker and m_shape is not None and m_shape != 20:
            p_main.symbol_size = float(s.marker_size_pt or spec["marker_size_pt"])
            # Python symbol_kind matches LabTalk shape code (1=sq, 2=circle, 3=up-tri, 4=down-tri, 5=diamond)
            p_main.symbol_kind = int(m_shape)
            # Python symbol_interior: 0 = Solid filled, 1 = Open white-filled (m_int is 1 for solid, 2 for open)
            p_main.symbol_interior = 1 if int(m_int) == 2 else 0

        if after_cnt >= before_cnt + 2:
            gl.lt_exec(f"range re = !{after_cnt}; set re -w {sub_w_u}; set re -c {err_ink};")

        if has_line and has_marker:
            sw_kind = "open_circle" if m_int == 2 else "line_sphere"
        elif has_marker:
            sw_kind = "scatter"
        elif d_code == 1:
            sw_kind = "line_dashed"
        else:
            sw_kind = "line"

        leg_entries.append((main_idx, s.name, c_hex, sw_kind))

    return leg_entries


def _render_guides_into_glayer(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    guides: Sequence[cg.GuideSpec],
    wb: Any,
    used_sheets: set[str],
    x_bounds: Tuple[float, float],
    y_bounds: Tuple[float, float],
    *,
    invert_x: bool = False,
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    if not guides:
        return

    ob.activate_layer(op, gp, layer_num_1based)
    x_lo, x_hi = min(x_bounds), max(x_bounds)
    y_lo, y_hi = min(y_bounds), max(y_bounds)
    x_span = max(x_hi - x_lo, 1e-6)
    y_span = max(y_hi - y_lo, 1e-6)

    seg_cols: List[Tuple[str, List[float], str, List[float], str, int, int]] = []
    # (data_x, data_y, rich_lbl, c_int, fs, pos_scatter, dx_pct, dy_top_pct, no_repel)
    callouts: List[Tuple[float, float, str, int, float, int, float, float, bool]] = []

    spec = ob.get_active_spec()
    sub_w = int(spec["sub_w_units"])
    base_callout_fs = float(spec["callout_pt"])

    all_hline_ys = sorted(
        [float(g.value) for g in guides if g.kind == "hline" and g.value is not None],
        reverse=True,
    )
    all_vline_xs = sorted(
        [float(g.value) for g in guides if g.kind == "vline" and g.value is not None]
    )

    for idx, g in enumerate(guides):
        c_hex = g.color or "#3E86DE"
        c_int = ot.hex_to_origin_rgb_int(c_hex)
        w_units = sub_w
        d_code = _line_style_code(g.line_style)
        fs = min(base_callout_fs, float(g.font_size_pt or base_callout_fs))
        rich_lbl = _format_origin_guide_text(g.label)

        if g.kind == "vline" and g.value is not None:
            xv = float(g.value)
            seg_cols.append((f"GX{idx+1}", [xv, xv], f"GY{idx+1}", [y_lo, y_hi], c_hex, w_units, d_code))
            if rich_lbl:
                pos_sc = 1 if g.label_side == "left" else 2
                dx_p = -0.9 if pos_sc == 1 else 0.9
                ly = y_lo + float(g.shoulder_y_frac or 0.80) * y_span
                callouts.append((xv, ly, rich_lbl, c_int, fs, pos_sc, dx_p, 0.0, False))

        elif g.kind == "hline" and g.value is not None:
            yv = float(g.value)
            seg_cols.append((f"GX{idx+1}", [x_lo, x_hi], f"GY{idx+1}", [yv, yv], c_hex, w_units, d_code))
            if rich_lbl:
                has_close_upper = any(0.001 * y_span < (yu - yv) < 0.14 * y_span for yu in all_hline_ys)
                dy_hl = 4.6 if has_close_upper else -5.0
                lx = x_lo + (0.04 if invert_x else 0.97) * x_span
                callouts.append((lx, yv, rich_lbl, c_int, min(fs, 20.0), 1, -0.6, dy_hl, False))

        elif g.kind == "span_v" and g.start is not None and g.end is not None:
            xp = float(g.anchor_pos if g.anchor_pos is not None else (g.x if g.x is not None else (x_lo + 0.35 * x_span)))
            ys0, ys1 = float(min(g.start, g.end)), float(max(g.start, g.end))
            cap_dx = 0.014 * x_span
            arr_dy = min(0.022 * y_span, 0.22 * max(ys1 - ys0, 1e-6))
            arr_dx = 0.009 * x_span
            seg_cols.append((f"SVX{idx+1}a", [xp, xp], f"SVY{idx+1}a", [ys0, ys1], c_hex, w_units, 0))
            seg_cols.append((f"SVX{idx+1}b", [xp - cap_dx, xp + cap_dx], f"SVY{idx+1}b", [ys0, ys0], c_hex, w_units, 0))
            seg_cols.append((f"SVX{idx+1}c", [xp - cap_dx, xp + cap_dx], f"SVY{idx+1}c", [ys1, ys1], c_hex, w_units, 0))
            seg_cols.append(
                (f"SVX{idx+1}d", [xp - arr_dx, xp, xp + arr_dx], f"SVY{idx+1}d", [ys0 + arr_dy, ys0, ys0 + arr_dy], c_hex, w_units, 0)
            )
            seg_cols.append(
                (f"SVX{idx+1}e", [xp - arr_dx, xp, xp + arr_dx], f"SVY{idx+1}e", [ys1 - arr_dy, ys1, ys1 - arr_dy], c_hex, w_units, 0)
            )
            if rich_lbl:
                fs_sp = min(fs, 19.0)
                x_rel = (x_hi - xp) / x_span if invert_x else (xp - x_lo) / x_span
                if (ys1 - ys0) < 0.18 * y_span:
                    lowest_ref = min([ys0] + all_hline_ys) if all_hline_ys else ys0
                    ly = max(y_lo + 0.11 * y_span, lowest_ref - 0.14 * y_span)
                    seg_cols.append(
                        (f"SVX{idx+1}ld", [xp, xp], f"SVY{idx+1}ld", [ys0 - 0.012 * y_span, ly + 0.042 * y_span], c_hex, max(500, sub_w - 150), 2)
                    )
                    callouts.append((xp, ly, rich_lbl, c_int, fs_sp, 0, 0.0, 0.0, False))
                elif g.label_side == "left" or x_rel >= 0.42:
                    ly = 0.5 * (ys0 + ys1)
                    callouts.append((xp, ly, rich_lbl, c_int, fs_sp, 1, -1.2, 0.0, False))
                elif " = " in rich_lbl and x_rel < 0.35:
                    # Stack narrow two-line equation (`\Delta V_{0,app}` / `= 1.269 V`) inside pulse trough
                    lhs_sp, rhs_sp = rich_lbl.split(" = ", 1)
                    ly = 0.5 * (ys0 + ys1)
                    callouts.append((xp, ly, lhs_sp.strip(), c_int, fs_sp, 2, 0.85, -2.5, True))
                    callouts.append((xp, ly, f"= {rhs_sp.strip()}", c_int, fs_sp, 2, 0.85, +2.5, True))
                else:
                    ly = 0.5 * (ys0 + ys1)
                    callouts.append((xp, ly, rich_lbl, c_int, fs_sp, 2, 0.85, 0.0, False))

        elif g.kind == "span_h" and g.start is not None and g.end is not None:
            yp = float(g.anchor_pos if g.anchor_pos is not None else (g.y if g.y is not None else (y_lo + 0.5 * y_span)))
            xs0, xs1 = float(min(g.start, g.end)), float(max(g.start, g.end))
            cap_dy = 0.018 * y_span
            seg_cols.append((f"SHX{idx+1}a", [xs0, xs1], f"SHY{idx+1}a", [yp, yp], c_hex, w_units, 0))
            seg_cols.append((f"SHX{idx+1}b", [xs0, xs0], f"SHY{idx+1}b", [yp - cap_dy, yp + cap_dy], c_hex, w_units, 0))
            seg_cols.append((f"SHX{idx+1}c", [xs1, xs1], f"SHY{idx+1}c", [yp - cap_dy, yp + cap_dy], c_hex, w_units, 0))
            if rich_lbl:
                callouts.append((0.5 * (xs0 + xs1), yp, rich_lbl, c_int, fs, 0, 0.0, -2.5, False))

        elif g.kind == "trend_arrow" and g.x is not None and g.y is not None and g.x_end is not None and g.y_end is not None:
            x0, y0, x1, y1 = float(g.x), float(g.y), float(g.x_end), float(g.y_end)
            seg_cols.append((f"TAX{idx+1}", [x0, x1], f"TAY{idx+1}", [y0, y1], c_hex, w_units, d_code))
            if rich_lbl:
                callouts.append((0.5 * (x0 + x1), 0.5 * (y0 + y1), rich_lbl, c_int, fs, 0, 0.0, -2.4, False))

        elif g.kind in ("peak_tag", "text") and rich_lbl:
            tx = float(g.x if g.x is not None else (g.value if g.value is not None else x_lo + 0.5 * x_span))
            ty = float(g.y if g.y is not None else (y_lo + float(g.shoulder_y_frac or 0.77) * y_span))
            callouts.append((tx, ty, rich_lbl, c_int, fs, 0, 0.0, 0.0, False))

    if seg_cols:
        g_sh_name = ob.unique_origin_short_name(f"GuidesL{layer_num_1based}", used_sheets, default="Guides")
        wks_g = wb.add_sheet(g_sh_name)
        wks_g.cols = len(seg_cols) * 2
        wks_g.cols_axis("XY" * len(seg_cols))
        ob.activate_layer(op, gp, layer_num_1based)
        for s_i, (xn, xv_l, yn, yv_l, chx, wu, dc) in enumerate(seg_cols):
            wks_g.from_list(2 * s_i, xv_l, lname=xn, axis="X")
            wks_g.from_list(2 * s_i + 1, yv_l, lname=yn, axis="Y")
            p_g = gl.add_plot(wks_g, coly=2 * s_i + 1, colx=2 * s_i, type="l")
            p_g.color = ob._hex_to_origin_color(op, chx)
            p_idx = len(gl.plot_list())
            gl.lt_exec(f"range rg = !{p_idx}; set rg -w {wu}; set rg -d {dc};")
        gl.lt_exec("label -r Legend;")

    for tx, ty, r_lbl, c_int, fs, pos_sc, dx_p, dy_p, no_rep in callouts:
        ob.queue_overlay_data_text(
            op,
            gp,
            layer_num_1based,
            tx,
            ty,
            x_bounds,
            y_bounds,
            rich_text=r_lbl,
            fontsize=fs,
            color_int=c_int,
            invert_x=invert_x,
            log_x=log_x,
            log_y=log_y,
            pos_scatter=pos_sc,
            dx_pct=dx_p,
            dy_top_pct=dy_p,
            format_math=False,
            no_repel=no_rep,
        )


def _extract_panel_categories(panel: cg.PanelSpec) -> List[str]:
    if panel.x_axis.categories:
        return [str(c) for c in panel.x_axis.categories]
    for ly in panel.layers:
        if ly.categories:
            return [str(c) for c in ly.categories]
        if ly.mark in ("stat_distribution", "stat_box_jitter") and ly.series:
            return [str(s.meta.get("label") or s.name) for s in ly.series]
        if ly.series and ly.series[0].x and all(isinstance(v, str) for v in ly.series[0].x):
            return [str(v) for v in ly.series[0].x]
    return []


def _apply_single_axis_layer_style(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    panel: cg.PanelSpec,
    *,
    rect_pct: Optional[Tuple[float, float, float, float]] = None,
    rect_in: Optional[Tuple[float, float, float, float]] = None,
    axis_title_pt: Optional[float] = None,
    tick_label_pt: Optional[float] = None,
    hide_y_override: bool = False,
    reserve_top_legend_space: bool = False,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    spec = ob.get_active_spec()
    ob.activate_layer(op, gp, layer_num_1based)

    tgt_wh = ob._PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
    pw_in, ph_in = tgt_wh

    has_2d_mat = any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers)
    if rect_in is not None:
        li, ti, wi, hi = rect_in
        gl.lt_exec(f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi};")
        lw_in, lh_in = float(wi), float(hi)
    elif rect_pct is not None and not (has_2d_mat and panel.equal_aspect):
        l_p, t_p, w_p, h_p = rect_pct
        gl.lt_exec(f"layer.unit=1; layer.left={l_p}; layer.top={t_p}; layer.width={w_p}; layer.height={h_p};")
        lw_in, lh_in = pw_in * (float(w_p) / 100.0), ph_in * (float(h_p) / 100.0)
    else:
        lw_in = float(spec["box_sq_side_in"] if has_2d_mat else spec["box_rect_w_in"])
        lh_in = float(spec["box_sq_side_in"] if has_2d_mat else spec["box_rect_h_in"])

    raw_bt = float(panel.box_linewidth_pt or spec["box_lw_pt"])
    bt = float(spec["box_lw_pt"]) if abs(raw_bt - 3.0) < 0.05 else raw_bt
    ax_pt_use = float(spec["axis_title_pt"] if axis_title_pt is None else axis_title_pt)
    tk_pt_use = float(spec["tick_label_pt"] if tick_label_pt is None else tick_label_pt)
    comp_tick_pt = ot.compensate_origin_layer_pt(tk_pt_use, lw_in, lh_in, pw_in, ph_in)
    bold_i = int(spec["bold_int"])

    x_ax = panel.x_axis
    y_ax = panel.y1_axis
    ink_int = ot.hex_to_origin_rgb_int(y_ax.color or "#111111")
    f_id = ob.get_font_id(op)
    font_clause = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""

    x_is_log = x_ax.scale == "log10"
    y_is_log = y_ax.scale == "log10"
    x_type = 2 if x_is_log else 1
    y_type = 2 if y_is_log else 1

    has_2d_mat = any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers)
    has_stat = any(ly.mark in ("stat_distribution", "stat_box_jitter") for ly in panel.layers)
    is_cat_x = ((x_ax.axis_kind == "categorical") or has_stat) and not has_2d_mat
    x_ticks = 0 if is_cat_x else (5 if x_is_log else 1)
    if y_ax.axis_kind == "intensity_arbitrary" or hide_y_override:
        y_ticks = 0
        y_labels = 0
    else:
        y_ticks = 5 if y_is_log else 1
        y_labels = 1

    gl.lt_exec(
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.type={x_type}; layer.y.type={y_type}; "
        f"layer.x.showAxes=3; layer.y.showAxes=3; "
        f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
        f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
        f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
        f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
        f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
        f"layer.x.ticks={x_ticks}; "
        f"layer.y.ticks={y_ticks}; layer.y.showLabels={y_labels}; "
        f"layer.x2.ticks=0; layer.y2.ticks=0; "
        f"{font_clause}"
        f"layer.x.label.pt={comp_tick_pt}; layer.y.label.pt={comp_tick_pt}; "
        f"layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i};"
    )
    if x_is_log:
        gl.lt_exec("layer.x.ticks=5; layer.x.minorTicks=8; layer.x.label.numFormat=2;")
    if y_is_log and y_labels:
        gl.lt_exec("layer.y.ticks=5; layer.y.minorTicks=8; layer.y.label.numFormat=2;")

    gl.rescale()
    x_bounds, y_bounds = _infer_panel_xy_bounds(
        panel, y_axis_filter="y1", reserve_top_legend_space=reserve_top_legend_space
    )
    cats = _extract_panel_categories(panel) if is_cat_x else []

    is_1d_eq = panel.equal_aspect and not has_2d_mat and not is_cat_x and not x_is_log and not y_is_log
    eq_step_resolved: Optional[float] = None
    if is_1d_eq:
        xs_eq = [
            float(xv)
            for ly in panel.layers
            if ly.y_axis == "y1"
            for s in ly.series
            for xv in (s.x or [])
            if isinstance(xv, (int, float)) and not isinstance(xv, bool)
        ]
        ys_eq = [float(yv) for ly in panel.layers if ly.y_axis == "y1" for s in ly.series for yv in (s.y or [])]
        tgt_ratio = lw_in / max(lh_in, 1e-6)
        x_bounds, y_bounds, eq_step_resolved = _resolve_1d_equal_aspect_bounds_and_step(
            panel, xs_eq, ys_eq, target_ratio=tgt_ratio
        )
        x_from, x_to = (x_bounds[1], x_bounds[0]) if x_ax.invert else (x_bounds[0], x_bounds[1])
        gl.set_xlim(x_from, x_to)
        gl.set_ylim(y_bounds[0], y_bounds[1])
        gl.lt_exec(f"layer.x.from={x_from}; layer.x.to={x_to}; layer.y.from={y_bounds[0]}; layer.y.to={y_bounds[1]};")
        if eq_step_resolved is not None and eq_step_resolved > 0:
            gl.lt_exec(f"layer.x.inc={eq_step_resolved}; layer.y.inc={eq_step_resolved};")
    else:
        if x_ax.limits is not None:
            x0, x1 = float(x_ax.limits[0]), float(x_ax.limits[1])
            if x_ax.invert and x0 < x1:
                gl.set_xlim(x1, x0)
            else:
                gl.set_xlim(x0, x1)
            x_bounds = (min(x0, x1), max(x0, x1))
        elif is_cat_x and cats:
            x_bounds = (0.4, float(len(cats)) + 0.6)
            gl.set_xlim(x_bounds[0], x_bounds[1])
            gl.lt_exec(f"layer.x.from={x_bounds[0]}; layer.x.to={x_bounds[1]}; layer.x.inc=1;")
        elif x_ax.invert:
            gl.set_xlim(x_bounds[1], x_bounds[0])
        else:
            gl.set_xlim(x_bounds[0], x_bounds[1])

        if y_ax.limits is not None and not reserve_top_legend_space:
            gl.set_ylim(float(y_ax.limits[0]), float(y_ax.limits[1]))
            y_bounds = (float(min(y_ax.limits)), float(max(y_ax.limits)))
        else:
            gl.set_ylim(y_bounds[0], y_bounds[1])

        max_auto_tks = 5 if panel.equal_aspect else 6
        if x_ax.major_step is not None and x_ax.major_step > 0:
            gl.lt_exec(f"layer.x.inc={float(x_ax.major_step)};")
        elif not is_cat_x and not x_is_log and not has_2d_mat:
            auto_xs = ob.compute_nice_linear_step(x_bounds[0], x_bounds[1], max_ticks=max_auto_tks)
            if auto_xs:
                gl.lt_exec(f"layer.x.inc={auto_xs};")

        if y_ax.major_step is not None and y_ax.major_step > 0:
            gl.lt_exec(f"layer.y.inc={float(y_ax.major_step)};")
        elif y_labels and not y_is_log and not has_2d_mat:
            auto_ys = ob.compute_nice_linear_step(y_bounds[0], y_bounds[1], max_ticks=max_auto_tks)
            if auto_ys:
                gl.lt_exec(f"layer.y.inc={auto_ys};")

    if is_cat_x and cats:
        ob.render_categorical_x_labels_clean(
            op,
            gp,
            gl,
            layer_num_1based,
            cats,
            xlim_lo=x_bounds[0],
            xlim_hi=x_bounds[1],
            tick_label_pt=tk_pt_use,
            color_int=ink_int,
            show_outward_ticks=False,
        )

    ob.style_origin_native_axis_title(
        gl, "XB", x_ax.label, fontsize=ax_pt_use, color_int=ink_int, op=op, gp=gp, layer_num_1based=layer_num_1based
    )
    ob.style_origin_native_axis_title(
        gl,
        "YL",
        "" if hide_y_override else y_ax.label,
        fontsize=ax_pt_use,
        color_int=ink_int,
        op=op,
        gp=gp,
        layer_num_1based=layer_num_1based,
    )
    ob.sanitize_layer_frames_and_grids(
        gl, remove_default_legend=True, op=op, gp=gp, layer_num_1based=layer_num_1based
    )
    return x_bounds, y_bounds


def _resolve_inset_bbox_pct(ins: cg.InsetSpec, panel: cg.PanelSpec) -> Tuple[float, float, float, float]:
    l_p, t_p, w_p, h_p = [float(v) for v in ins.bbox_pct]
    show_ins_titles = ins.mode in ("subchart", "subpanel")
    if panel.equal_aspect or ins.equal_aspect:
        if show_ins_titles:
            l_p = max(l_p, 48.0)
            t_p = min(t_p, 34.0)
            side_p = min(w_p, h_p, 42.0)
            w_p, h_p = side_p, side_p
        else:
            # Inside a 6.40 x 4.80 in (4:3) parent frame, equal % width & height (42% x 42%)
            # yields exact 4:3 physical dimensions (2.688 x 2.016 in) in the lower-right quadrant!
            l_p = max(l_p, 51.0)
            t_p = max(43.0, min(t_p, 46.0))
            side_p = min(w_p, h_p, 42.0)
            w_p, h_p = side_p, side_p
    return l_p, t_p, w_p, h_p


def _resolve_inset_xy_bounds(
    ins: cg.InsetSpec,
    panel: cg.PanelSpec,
    par_w_in: float,
    par_h_in: float,
) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    """
    Resolve inset `(xlim, ylim)` so when `ins.equal_aspect=True`, `ins_x_span / ins_y_span` matches
    the physical inch aspect ratio of the inset (`4:3` inside standard `6.40 x 4.80 in` frame),
    expanding whichever axis is tighter so zero data points are clipped.
    """
    if ins.xlim is None or ins.ylim is None:
        return (
            (float(ins.xlim[0]), float(ins.xlim[1])) if ins.xlim is not None else None,
            (float(ins.ylim[0]), float(ins.ylim[1])) if ins.ylim is not None else None,
        )
    ix0, ix1 = float(ins.xlim[0]), float(ins.xlim[1])
    iy0, iy1 = float(ins.ylim[0]), float(ins.ylim[1])
    if not ins.equal_aspect:
        return (ix0, ix1), (iy0, iy1)

    _lp, _tp, w_p, h_p = _resolve_inset_bbox_pct(ins, panel)
    ins_w_in = max(par_w_in * (w_p / 100.0), 1e-6)
    ins_h_in = max(par_h_in * (h_p / 100.0), 1e-6)
    target_ratio = ins_w_in / ins_h_in
    dx = abs(ix1 - ix0)
    dy = abs(iy1 - iy0)
    if dx <= 1e-12 or dy <= 1e-12 or abs((dx / dy) - target_ratio) <= 0.02 * target_ratio:
        return (ix0, ix1), (iy0, iy1)

    if abs(ix0) < 1e-9 and abs(iy0) < 1e-9 and ix1 > 0 and iy1 > 0 and abs(target_ratio - (4.0 / 3.0)) <= 0.03:
        u_raw = max(ix1 / 4.0, iy1 / 3.0)
        if u_raw >= 25.0:
            u = math.ceil((u_raw - 1e-9) / 5.0) * 5.0
        elif u_raw >= 5.0:
            u = math.ceil((u_raw - 1e-9) / 1.0) * 1.0
        else:
            u = round(u_raw, 6)
        return (0.0, round(4.0 * u, 6)), (0.0, round(3.0 * u, 6))

    if dx / dy < target_ratio:
        new_dx = target_ratio * dy
        return (ix0, ix0 + (new_dx if ix1 >= ix0 else -new_dx)), (iy0, iy1)
    new_dy = dx / target_ratio
    return (ix0, ix1), (iy0, iy0 + (new_dy if iy1 >= iy0 else -new_dy))


def _render_insets_for_panel(
    op: Any,
    gp: Any,
    gl_main: Any,
    main_layer_num_1based: int,
    panel: cg.PanelSpec,
    wb: Any,
    used_sheets: set[str],
    pal_tmp_dir: Path,
    main_x_bounds: Tuple[float, float],
    main_y_bounds: Tuple[float, float],
) -> None:
    if not panel.insets:
        return

    spec = ob.get_active_spec()
    f_id = ob.get_font_id(op)
    bold_i = int(spec["bold_int"])
    sub_w = int(spec["sub_w_units"])
    font_clause = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""
    mx_span = max(abs(main_x_bounds[1] - main_x_bounds[0]), 1e-6)
    my_span = max(abs(main_y_bounds[1] - main_y_bounds[0]), 1e-6)
    tgt_wh = ob._PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
    pw_in, ph_in = tgt_wh
    par_w_in = float(spec["box_rect_w_in"])
    par_h_in = float(spec["box_rect_h_in"])

    for ins_idx, ins in enumerate(panel.insets, start=1):
        ix_lim_res, iy_lim_res = _resolve_inset_xy_bounds(ins, panel, par_w_in, par_h_in)
        if ins.show_zoom_box and ix_lim_res is not None and iy_lim_res is not None:
            ob.activate_layer(op, gp, main_layer_num_1based)
            zx0, zx1 = float(ix_lim_res[0]), float(ix_lim_res[1])
            zy0, zy1 = float(iy_lim_res[0]), float(iy_lim_res[1])
            zx0_vis = max(zx0, main_x_bounds[0] + 0.008 * mx_span) if abs(zx0 - main_x_bounds[0]) < 0.01 * mx_span else zx0
            zy0_vis = max(zy0, main_y_bounds[0] + 0.008 * my_span) if abs(zy0 - main_y_bounds[0]) < 0.01 * my_span else zy0
            zb_sh = ob.unique_origin_short_name(f"ZoomBox{ins_idx}", used_sheets, default="ZBox")
            wks_zb = wb.add_sheet(zb_sh)
            wks_zb.cols = 2
            wks_zb.from_list(0, [zx0_vis, zx1, zx1, zx0_vis, zx0_vis], lname="ZBox_X", axis="X")
            wks_zb.from_list(1, [zy0_vis, zy0_vis, zy1, zy1, zy0_vis], lname="ZBox_Y", axis="Y")
            p_zb = gl_main.add_plot(wks_zb, coly=1, colx=0, type="l")
            p_zb.color = ob._hex_to_origin_color(op, ins.zoom_box_color or "#6579BE")
            zb_p_idx = len(gl_main.plot_list())
            gl_main.lt_exec(f"range rzb = !{zb_p_idx}; set rzb -d 1; set rzb -w {sub_w}; label -r Legend;")

        gl_in = gp.add_layer(6)
        ins_lay_num = main_layer_num_1based + ins_idx
        ob.activate_layer(op, gp, ins_lay_num)
        gl_in.lt_exec("layer.fsize=1;")

        ix_bg0 = float(ix_lim_res[0]) if ix_lim_res is not None else 0.0
        ix_bg1 = float(ix_lim_res[1]) if ix_lim_res is not None else 1.0
        iy_bg0 = float(iy_lim_res[0]) if iy_lim_res is not None else 0.0
        iy_bg1 = float(iy_lim_res[1]) if iy_lim_res is not None else 1.0
        bg_sh = ob.unique_origin_short_name(f"InsBG{ins_idx}", used_sheets, default="IBG")
        wks_ibg = wb.add_sheet(bg_sh)
        wks_ibg.cols = 3
        wks_ibg.from_list(0, [ix_bg0, ix_bg1], axis="X")
        wks_ibg.from_list(1, [iy_bg1, iy_bg1], axis="Y")
        wks_ibg.from_list(2, [iy_bg0, iy_bg0], axis="Y")
        bg_oc = ob._hex_to_origin_color(op, ins.background_color or "#FFFFFF")
        p_ibu = gl_in.add_plot(wks_ibg, coly=1, colx=0, type="l")
        p_ibl = gl_in.add_plot(wks_ibg, coly=2, colx=0, type="l")
        p_ibu.color = bg_oc
        p_ibl.color = bg_oc
        p_ibu.set_fill_area(above=bg_oc, type=9, below=bg_oc)
        p_ibu.transparency = 0
        p_ibl.transparency = 100
        gl_in.lt_exec("range rbu = !1; set rbu -w 0; range rbl = !2; set rbl -w 0;")

        l_p, t_p, w_p, h_p = _resolve_inset_bbox_pct(ins, panel)
        ins_w_in = par_w_in * (w_p / 100.0)
        ins_h_in = par_h_in * (h_p / 100.0)
        ins_scale = ot.compute_origin_layer_scale(ins_w_in, ins_h_in, pw_in, ph_in)
        ins_target_lw = round((float(spec["curve_lw_pt"]) * 0.72) / ins_scale, 2)
        ins_target_mk = round(4.8 / ins_scale, 1)

        for sub_ly in ins.layers:
            saved_styles = [(sub_s, sub_s.line_width_pt, sub_s.marker_size_pt) for sub_s in sub_ly.series]
            for sub_s, _, _ in saved_styles:
                sub_s.line_width_pt = ins_target_lw
                sub_s.marker_size_pt = ins_target_mk
            try:
                _plot_layer_into_glayer(
                    op, gp, gl_in, ins_lay_num, sub_ly, panel, wb, used_sheets, pal_tmp_dir
                )
            finally:
                for sub_s, orig_lw, orig_mk in saved_styles:
                    sub_s.line_width_pt = orig_lw
                    sub_s.marker_size_pt = orig_mk

        ob.activate_layer(op, gp, ins_lay_num)
        gl_in.rescale()
        if ix_lim_res is not None:
            gl_in.set_xlim(float(ix_lim_res[0]), float(ix_lim_res[1]))
        if iy_lim_res is not None:
            gl_in.set_ylim(float(iy_lim_res[0]), float(iy_lim_res[1]))

        white_int = ot.hex_to_origin_rgb_int(ins.background_color or "#FFFFFF")
        ink_int = ot.hex_to_origin_rgb_int("#111111")
        ins_bt = float(spec["inset_box_lw_pt"])
        ins_comp_pt = ot.compensate_origin_layer_pt(float(spec["inset_tick_pt"]), ins_w_in, ins_h_in, pw_in, ph_in)
        x_log = 1 if ins.x_axis.scale == "log10" else 0
        y_log = 1 if ins.y_axis.scale == "log10" else 0
        ins_xt = 5 if x_log else 1
        ins_yt = 5 if y_log else 1

        gl_in.lt_exec(
            f"layer.fsize=1; "
            f"layer.unit=7; layer.left={l_p}; layer.top={t_p}; layer.width={w_p}; layer.height={h_p}; "
            f"layer.color={white_int}; "
            f"layer.x.grid.show=0; layer.y.grid.show=0; "
            f"layer.x.type={2 if x_log else 1}; layer.y.type={2 if y_log else 1}; "
            f"layer.x.showAxes=3; layer.y.showAxes=3; "
            f"layer.x.thickness={ins_bt}; layer.y.thickness={ins_bt}; "
            f"layer.x2.thickness={ins_bt}; layer.y2.thickness={ins_bt}; "
            f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
            f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
            f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
            f"layer.x.ticks={ins_xt}; layer.y.ticks={ins_yt}; "
            f"layer.x2.ticks=0; layer.y2.ticks=0; "
            f"layer.x.maxTicks=4; layer.y.maxTicks=4; "
            f"{font_clause}"
            f"layer.x.label.pt={ins_comp_pt}; layer.y.label.pt={ins_comp_pt}; "
            f"layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
            f"XB.show=0; YL.show=0; label -r Legend;"
        )
        if x_log:
            gl_in.lt_exec("layer.x.minorTicks=8; layer.x.label.numFormat=2;")
        if y_log:
            gl_in.lt_exec("layer.y.minorTicks=8; layer.y.label.numFormat=2;")
        elif ix_lim_res is not None and iy_lim_res is not None and not x_log:
            gl_in.lt_exec(
                f"layer.x.from={ix_lim_res[0]}; layer.x.to={ix_lim_res[1]}; "
                f"layer.y.from={iy_lim_res[0]}; layer.y.to={iy_lim_res[1]};"
            )
            inc_x = (
                float(ins.x_axis.major_step)
                if (ins.x_axis.major_step is not None and ins.x_axis.major_step > 0)
                else ob.compute_nice_linear_step(float(ix_lim_res[0]), float(ix_lim_res[1]), max_ticks=4)
            )
            inc_y = (
                float(ins.y_axis.major_step)
                if (ins.y_axis.major_step is not None and ins.y_axis.major_step > 0)
                else ob.compute_nice_linear_step(float(iy_lim_res[0]), float(iy_lim_res[1]), max_ticks=4)
            )
            if inc_x and inc_x > 0:
                gl_in.lt_exec(f"layer.x.inc={inc_x};")
            if inc_y and inc_y > 0:
                gl_in.lt_exec(f"layer.y.inc={inc_y};")

        show_ins_titles = ins.mode in ("subchart", "subpanel")
        ob.style_origin_native_axis_title(
            gl_in,
            "XB",
            (ins.x_axis.label or "") if show_ins_titles else "",
            fontsize=15.5,
            color_int=ink_int,
            op=op,
            gp=gp,
            layer_num_1based=ins_lay_num,
        )
        ob.style_origin_native_axis_title(
            gl_in,
            "YL",
            (ins.y_axis.label or "") if show_ins_titles else "",
            fontsize=15.5,
            color_int=ink_int,
            op=op,
            gp=gp,
            layer_num_1based=ins_lay_num,
        )

        if ins.guides:
            ix_b = ix_lim_res if ix_lim_res is not None else (0.0, 1.0)
            iy_b = iy_lim_res if iy_lim_res is not None else (0.0, 1.0)
            _render_guides_into_glayer(
                op, gp, gl_in, ins_lay_num, ins.guides, wb, used_sheets, ix_b, iy_b
            )


def _render_dual_y_panel_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    assert panel.y2_axis is not None
    spec = ob.get_active_spec()
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    li, ti, wi, hi = (
        float(spec["box_rect_left_in"]),
        float(spec["box_rect_top_in"]),
        float(spec["box_rect_w_in"]),
        float(spec["box_rect_h_in"]),
    )
    rect_pct = ot.rect_in_to_page_pct(li, ti, wi, hi, pw, ph)
    comp_tk_pt = ot.compensate_origin_layer_pt(float(spec["tick_label_pt"]), wi, hi, pw, ph)
    ax_title_pt = float(spec["axis_title_pt"])
    bold_i = int(spec["bold_int"])

    wb = op.new_book("w", lname=f"{page_lname}_Book")
    used_sheets: set[str] = set()
    f_id = ob.get_font_id(op)
    font_clause = (
        f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; layer.y2.label.font={f_id}; "
        if f_id > 0
        else ""
    )

    y1_layers = [ly for ly in panel.layers if ly.y_axis == "y1"]
    y2_layers = [ly for ly in panel.layers if ly.y_axis == "y2"]
    y1_has_bar = any("bar" in ly.mark for ly in y1_layers)
    y2_has_bar = any("bar" in ly.mark for ly in y2_layers)

    if y2_has_bar and not y1_has_bar:
        bot_side, top_side = "y2", "y1"
        bot_layers, top_layers = y2_layers, y1_layers
    else:
        bot_side, top_side = "y1", "y2"
        bot_layers, top_layers = y1_layers, y2_layers

    bot_template = _resolve_clean_origin_template(bot_layers)
    gp = op.new_graph(lname=page_lname, template=bot_template) if bot_template else op.new_graph(lname=page_lname)
    ob.set_graph_page_inches(gp, pw, ph)

    gl_bot = gp[0]
    bot_leg: List[Tuple[Any, ...]] = []
    for ly in bot_layers:
        bot_leg.extend(_plot_layer_into_glayer(op, gp, gl_bot, 1, ly, panel, wb, used_sheets, pal_tmp_dir))

    gl_top = gp.add_layer(2)
    is_cat_x = panel.x_axis.axis_kind == "categorical" or y1_has_bar or y2_has_bar
    top_leg: List[Tuple[Any, ...]] = []
    for ly in top_layers:
        top_leg.extend(
            _plot_layer_into_glayer(
                op,
                gp,
                gl_top,
                2,
                ly,
                panel,
                wb,
                used_sheets,
                pal_tmp_dir,
                categorical_linked_x=(is_cat_x and "bar" not in ly.mark),
            )
        )

    raw_bt = float(panel.box_linewidth_pt or spec["box_lw_pt"])
    bt = float(spec["box_lw_pt"]) if abs(raw_bt - 3.0) < 0.05 else raw_bt
    c_left_hex = panel.y1_axis.color or "#111111"
    c_right_hex = panel.y2_axis.color or "#A02333"
    c_left_int = ot.hex_to_origin_rgb_int(c_left_hex)
    c_right_int = ot.hex_to_origin_rgb_int(c_right_hex)
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    x_ticks = 0 if is_cat_x else 1
    x_log = 1 if panel.x_axis.scale == "log10" else 0

    ob.activate_layer(op, gp, 1)
    gl_bot.rescale()
    ob.activate_layer(op, gp, 2)
    gl_top.rescale()

    has_leg_any = (panel.legend_style != "none") and bool(bot_leg or top_leg)
    has_100_any_panel = any(ly.mark == "bar_stacked_100pct" for ly in panel.layers)
    top_100_pad_panel = 154.0 if (has_leg_any and bot_leg and top_leg) else (138.0 if has_leg_any else 100.0)
    x_b1, y1_bounds = _infer_panel_xy_bounds(panel, "y1", reserve_top_legend_space=has_leg_any)
    x_b2, y2_bounds = _infer_panel_xy_bounds(panel, "y2", reserve_top_legend_space=has_leg_any)

    cats = _extract_panel_categories(panel)
    n_cats = len(cats)
    if n_cats == 0:
        for ly in panel.layers:
            if ly.series and ly.series[0].y:
                n_cats = len(ly.series[0].y)
                break
    x_lo_use = float(panel.x_axis.limits[0]) if panel.x_axis.limits is not None else (0.4 if is_cat_x else x_b1[0])
    x_hi_use = float(panel.x_axis.limits[1]) if panel.x_axis.limits is not None else ((float(n_cats) + 0.6) if is_cat_x else x_b1[1])

    def _style_dual_half(gl_target: Any, lay_num: int, side: str, is_bottom_layer: bool) -> None:
        nonlocal y1_bounds, y2_bounds
        ob.activate_layer(op, gp, lay_num)
        ax_spec = panel.y1_axis if side == "y1" else panel.y2_axis
        assert ax_spec is not None
        c_y = c_left_int if side == "y1" else c_right_int
        c_y_hex = c_left_hex if side == "y1" else c_right_hex
        y_show_ax = 1 if side == "y1" else 2
        y_show_lbl = 1 if side == "y1" else 2
        y_log = 1 if ax_spec.scale == "log10" else 0
        y_lim_use = y1_bounds if side == "y1" else y2_bounds
        side_layers = y1_layers if side == "y1" else y2_layers

        if is_bottom_layer:
            x_clause = (
                f"layer.x.type={2 if x_log else 1}; layer.x.showAxes=3; "
                f"layer.x.thickness={bt}; layer.x2.thickness={bt}; "
                f"layer.x.color={ink_int}; layer.x2.color={ink_int}; "
                f"layer.x.label.color={ink_int}; "
                f"layer.x.ticks={x_ticks}; layer.x.showMinorTicks={x_log}; layer.x2.ticks=0; "
                f"layer.x.label.pt={comp_tk_pt}; layer.x.label.bold={bold_i};"
            )
        else:
            x_clause = (
                f"layer.x.type={2 if x_log else 1}; layer.x.link=1; "
                f"layer.x.showAxes=0; layer.x.showLabels=0; layer.x.ticks=0; layer.x2.ticks=0;"
            )

        gl_target.lt_exec(
            f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi}; "
            f"layer.x.grid.show=0; layer.y.grid.show=0; "
            f"{font_clause}"
            f"{x_clause} "
            f"layer.y.type={2 if y_log else 1}; "
            f"layer.y.showAxes={y_show_ax}; layer.y.showLabels={y_show_lbl}; "
            f"layer.y.thickness={bt}; layer.y2.thickness={bt}; "
            f"layer.y.ticks=1; layer.y2.ticks=1; "
            f"layer.y.showMinorTicks={y_log}; layer.y2.showMinorTicks={y_log}; "
            f"layer.y.color={c_y}; layer.y2.color={c_y}; "
            f"layer.y.label.color={c_y}; layer.y2.label.color={c_y}; "
            f"layer.y.label.pt={comp_tk_pt}; layer.y2.label.pt={comp_tk_pt}; "
            f"layer.y.label.bold={bold_i}; layer.y2.label.bold={bold_i};"
        )

        gl_target.set_xlim(x_lo_use, x_hi_use)
        if is_cat_x and n_cats > 0:
            gl_target.lt_exec(f"layer.x.from={x_lo_use}; layer.x.to={x_hi_use}; layer.x.inc=1;")

        if any(ly.mark == "bar_stacked_100pct" for ly in side_layers):
            ob.apply_clamped_0_100_y_ticks(
                op,
                gp,
                gl_target,
                lay_num,
                wb,
                used_sheets,
                x_lo_use,
                x_hi_use,
                ylim_top=top_100_pad_panel,
                max_tick_val=100.0,
                step_val=20.0,
                side=("left" if side == "y1" else "right"),
                color_hex=c_y_hex,
                tick_pt=float(spec["tick_label_pt"]),
            )
            if side == "y1":
                y1_bounds = (0.0, top_100_pad_panel)
            else:
                y2_bounds = (0.0, top_100_pad_panel)
        elif has_100_any_panel and has_leg_any and not y_log and float(y_lim_use[0]) >= 0.0:
            raw_data_ys = [float(v) for ly in side_layers for s in ly.series for v in (s.y or [])]
            raw_max_v = max(raw_data_ys) if raw_data_ys else float(y_lim_use[1])
            step_c2 = ob.compute_nice_linear_step(0.0, max(raw_max_v * 1.06, 1.0), max_ticks=6) or 10.0
            nice_max_c2 = max(step_c2, math.ceil((raw_max_v * 1.04) / step_c2) * step_c2)
            scaled_top_c2 = nice_max_c2 * (top_100_pad_panel / 100.0)
            ob.apply_clamped_0_100_y_ticks(
                op,
                gp,
                gl_target,
                lay_num,
                wb,
                used_sheets,
                x_lo_use,
                x_hi_use,
                ylim_top=scaled_top_c2,
                max_tick_val=nice_max_c2,
                step_val=step_c2,
                side=("left" if side == "y1" else "right"),
                color_hex=c_y_hex,
                tick_pt=float(spec["tick_label_pt"]),
            )
            if side == "y1":
                y1_bounds = (0.0, scaled_top_c2)
            else:
                y2_bounds = (0.0, scaled_top_c2)
        else:
            gl_target.set_ylim(float(y_lim_use[0]), float(y_lim_use[1]))

        if is_bottom_layer:
            if is_cat_x and cats:
                ob.render_categorical_x_labels_clean(
                    op,
                    gp,
                    gl_target,
                    lay_num,
                    cats,
                    xlim_lo=x_lo_use,
                    xlim_hi=x_hi_use,
                    tick_label_pt=float(spec["tick_label_pt"]),
                    color_int=ink_int,
                    show_outward_ticks=False,
                )
            ob.style_origin_native_axis_title(
                gl_target,
                "XB",
                panel.x_axis.label,
                fontsize=ax_title_pt,
                color_int=ink_int,
                op=op,
                gp=gp,
                layer_num_1based=lay_num,
            )

        if side == "y1":
            ob.style_origin_native_axis_title(
                gl_target, "YL", ax_spec.label, fontsize=ax_title_pt, color_int=c_y, op=op, gp=gp, layer_num_1based=lay_num
            )
        else:
            ob.style_origin_native_axis_title(
                gl_target, "YR", ax_spec.label, fontsize=ax_title_pt, color_int=c_y, op=op, gp=gp, layer_num_1based=lay_num
            )

        ob.sanitize_layer_frames_and_grids(gl_target, remove_default_legend=True, op=op, gp=gp, layer_num_1based=lay_num)

    _style_dual_half(gl_bot, 1, bot_side, is_bottom_layer=True)
    _style_dual_half(gl_top, 2, top_side, is_bottom_layer=False)

    if panel.guides:
        g_y1 = [g for g in panel.guides if g.axis == "y1"]
        g_y2 = [g for g in panel.guides if g.axis == "y2"]
        if g_y1:
            gl_for_y1, lnum_y1 = (gl_bot, 1) if bot_side == "y1" else (gl_top, 2)
            _render_guides_into_glayer(op, gp, gl_for_y1, lnum_y1, g_y1, wb, used_sheets, x_b1, y1_bounds)
        if g_y2:
            gl_for_y2, lnum_y2 = (gl_bot, 1) if bot_side == "y2" else (gl_top, 2)
            _render_guides_into_glayer(op, gp, gl_for_y2, lnum_y2, g_y2, wb, used_sheets, x_b2, y2_bounds)

    ob.activate_layer(op, gp, 1)
    gl_bot.lt_exec("label -r Legend;")
    ob.activate_layer(op, gp, 2)
    gl_top.lt_exec("label -r Legend;")
    if has_leg_any:
        leg_fs = 19.5 if max(len(bot_leg), len(top_leg)) >= 4 else float(spec["legend_pt"])
        if bot_leg and top_leg:
            ob.configure_custom_legend(
                gl_bot, bot_leg, fontsize=leg_fs, horizontal=True, pos_mode="interior_top",
                layer_rect_pct=rect_pct, op=op, gp=gp, layer_num_1based=1
            )
            ob.configure_custom_legend(
                gl_top, top_leg, fontsize=leg_fs, horizontal=True, pos_mode="interior_top_row2",
                layer_rect_pct=rect_pct, op=op, gp=gp, layer_num_1based=2
            )
        else:
            comb_leg = list(bot_leg) + list(top_leg)
            ob.configure_custom_legend(
                gl_bot, comb_leg, fontsize=leg_fs, horizontal=True, pos_mode="interior_top",
                layer_rect_pct=rect_pct, op=op, gp=gp, layer_num_1based=1
            )

    return gp


def _hide_spectrum_native_titles_in_tree(node: Any, depth: int = 0) -> None:
    """Walk `SPECTRUM1.Theme` safely via `firstChild`/`nextSibling` to hide built-in `颜色刻度标题`."""
    if node is None or depth > 5:
        return
    ch = getattr(node, "firstChild", None)
    while ch is not None:
        nm = getattr(ch, "Name", "")
        if nm == "Titles":
            sub = getattr(ch, "firstChild", None)
            while sub is not None:
                snm = getattr(sub, "Name", "")
                try:
                    sub.SetIntValue(0, "Show")
                except Exception:
                    pass
                if snm == "All":
                    try:
                        sub.SetStrValue("", "Text")
                    except Exception:
                        pass
                sub = getattr(sub, "nextSibling", None)
        elif nm not in ("ColorListValues", "BorderColorListValues", "FillColorListValues", "FillColor2ListValues"):
            _hide_spectrum_native_titles_in_tree(ch, depth + 1)
        ch = getattr(ch, "nextSibling", None)


def _upsample_2d_linear(z_np: np.ndarray, target_min_ny: int = 240, target_min_nx: int = 240) -> np.ndarray:
    """Linearly interpolate sparse 2D matrices along Y/X so `MATRIX_IMAGE` (`type=220`) renders silky-smooth continuous gradients with zero contour lines."""
    ny, nx = z_np.shape
    out = z_np.astype(float)
    if ny >= 2 and ny < target_min_ny:
        y_old = np.linspace(0.0, 1.0, ny)
        y_new = np.linspace(0.0, 1.0, target_min_ny)
        out_y = np.empty((target_min_ny, nx), dtype=float)
        for j in range(nx):
            out_y[:, j] = np.interp(y_new, y_old, out[:, j])
        out = out_y
    cur_ny, cur_nx = out.shape
    if cur_nx >= 2 and cur_nx < target_min_nx:
        x_old = np.linspace(0.0, 1.0, cur_nx)
        x_new = np.linspace(0.0, 1.0, target_min_nx)
        out_x = np.empty((cur_ny, target_min_nx), dtype=float)
        for i in range(cur_ny):
            out_x[i, :] = np.interp(x_new, x_old, out[i, :])
        out = out_x
    return out


def _render_contour_2d_page(
    op: Any,
    fig_spec: cg.FigureSpec,
    contour_panel: cg.PanelSpec,
    side_panel: Optional[cg.PanelSpec],
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    _ = fig_spec
    contour_layer = next(ly for ly in contour_panel.layers if ly.mark in ("contour_pseudocolor", "matrix_heatmap"))
    mat_s = contour_layer.series[0]
    if mat_s.matrix_z is None:
        raise ValueError(f"Contour panel '{contour_panel.panel_id}' has no populated `matrix_z` array.")

    z_np = np.asarray(mat_s.matrix_z, dtype=float)
    ny, nx = z_np.shape
    x_arr = (
        np.asarray(mat_s.matrix_x, dtype=float)
        if mat_s.matrix_x is not None
        else np.arange(1, nx + 1, dtype=float)
    )
    if mat_s.matrix_y is not None:
        try:
            y_arr = np.asarray([float(v) for v in mat_s.matrix_y], dtype=float)
        except (TypeError, ValueError):
            y_arr = np.arange(1, ny + 1, dtype=float)
    else:
        y_arr = np.arange(1, ny + 1, dtype=float)

    is_heatmap = contour_layer.mark == "matrix_heatmap"
    x1, x2 = float(x_arr[0]), float(x_arr[-1])
    y1, y2 = float(y_arr[0]), float(y_arr[-1])

    state_labels = (
        mat_s.meta.get("state_labels")
        or mat_s.meta.get("matrix_y_labels")
        or contour_panel.y1_axis.categories
    )
    x_mat_labels = mat_s.meta.get("matrix_x_labels") or contour_panel.x_axis.categories
    has_y_lbls = bool(state_labels and len(state_labels) == ny and np.allclose(y_arr, np.arange(1, ny + 1, dtype=float)))
    has_x_lbls = bool(is_heatmap and x_mat_labels and len(x_mat_labels) == nx)

    z_ax = contour_panel.z_axis
    if z_ax is not None and z_ax.limits is not None:
        z_lo, z_hi = float(z_ax.limits[0]), float(z_ax.limits[1])
    elif is_heatmap and mat_s.meta.get("center_zero") and float(np.min(z_np)) >= -1.05 and float(np.max(z_np)) <= 1.05:
        z_lo, z_hi = -1.0, 1.0
    else:
        z_lo, z_hi = float(np.min(z_np)), float(np.max(z_np))
        if not is_heatmap and z_lo >= 0.0:
            p96 = float(np.percentile(z_np, 96.0))
            if p96 > 0.0 and z_hi > 2.8 * p96:
                raw_cap = 1.25 * p96
                step_z = 50.0 if raw_cap >= 150.0 else (10.0 if raw_cap >= 30.0 else 1.0)
                z_hi = math.ceil(raw_cap / step_z) * step_z
                z_lo = 0.0
    if z_hi <= z_lo:
        z_hi = z_lo + 1.0

    mb = op.new_book("m", lname=f"{page_lname}_Matrix")
    ms = mb[0]
    ms.name = ob.sanitize_origin_short_name(mat_s.name, "Field2D")

    if not is_heatmap:
        # Store exact raw unclipped matrix in companion sheet for Source Data inspectability
        ms_raw = mb.add_sheet("RawField")
        ms_raw.from_np(z_np)
        ms_raw.xymap = (x1, x2, y1, y2)
        z_clipped = np.clip(z_np, z_lo, z_hi)
        if has_y_lbls and ny >= 2:
            # Pad half-band top (`0.5`) and bottom (`ny + 0.5`) so first/last state clouds sit centered in full bands
            y_map_lo, y_map_hi = 0.5, float(ny) + 0.5
            y_knots = np.concatenate(([0.5], np.arange(1, ny + 1, dtype=float), [float(ny) + 0.5]))
            z_knots = np.vstack([z_clipped[0:1, :], z_clipped, z_clipped[-1:, :]])
            y_dense = np.linspace(0.5, float(ny) + 0.5, 260)
            z_up_y = np.empty((260, nx), dtype=float)
            for j_col in range(nx):
                z_up_y[:, j_col] = np.interp(y_dense, y_knots, z_knots[:, j_col])
            z_render = _upsample_2d_linear(z_up_y, target_min_ny=260, target_min_nx=max(260, nx))
        else:
            y_map_lo, y_map_hi = y1, y2
            z_render = (
                _upsample_2d_linear(z_clipped, target_min_ny=260, target_min_nx=max(260, nx))
                if contour_layer.hide_contour_lines
                else z_clipped
            )
        ms.from_np(z_render)
        ms.xymap = (x1, x2, y_map_lo, y_map_hi)
        tpl_name = "CONTOUR"
        plot_code = 226
    else:
        y_map_lo, y_map_hi = y1, y2
        ms_raw = mb.add_sheet("RawMatrix")
        ms_raw.from_np(z_np)
        ms_raw.xymap = (x1, x2, y1, y2)
        ms.from_np(np.round(z_np, 2))
        ms.xymap = (x1, x2, y1, y2)
        tpl_name = "Heat_Map_With_Labels"
        plot_code = 105

    # Suppress default Chinese placeholder "颜色刻度标题" on SPECTRUM1 via non-breaking space LongName on MatrixObject(0)
    try:
        ms.obj.MatrixObjects(0).SetLongName("\xa0")
    except Exception:
        pass

    gp = op.new_graph(lname=page_lname, template=tpl_name)
    ob.activate_layer(op, gp, 1)
    gl_c = gp[0]
    p_c = gl_c.add_mplot(ms, 0, type=plot_code)

    # matrix_heatmap: white cell dividers (0.8 pt) + disable built-in SimSun cell labels (`set rhm -Z 0`)
    if is_heatmap:
        white_int = ot.hex_to_origin_rgb_int("#FFFFFF")
        try:
            tr_hm = p_c.obj.Theme
            if tr_hm is not None:
                if tr_hm.DataPlot is not None:
                    tr_hm.DataPlot.SetDoubleValue(0.8, "MeshLineWidth")
                    tr_hm.DataPlot.SetIntValue(white_int, "MeshLineColor")
                if getattr(tr_hm, "Pattern", None) is not None and tr_hm.Pattern.Border is not None:
                    tr_hm.Pattern.Border.SetDoubleValue(0.8, "Width")
                    tr_hm.Pattern.Border.SetIntValue(white_int, "Color")
                if getattr(tr_hm, "Label", None) is not None:
                    tr_hm.Label.SetIntValue(0, "Enable")
                p_c.obj.Theme = tr_hm
        except Exception:
            pass
        gl_c.lt_exec("range rhm = !1; set rhm -Z 0;")

    # Set clean major tick levels * 16 minors BEFORE assigning RIFF .pal
    z_span = z_hi - z_lo
    n_maj_lvls = 5 if (is_heatmap and abs(z_lo + z_hi) < 1e-6) else 6
    maj_levels = [0.0 if abs(float(v)) < 1e-6 else float(v) for v in np.linspace(z_lo, z_hi, n_maj_lvls)]
    try:
        zd = p_c.zlevels
        zd["minors"] = 16
        lvls_adj = list(maj_levels)
        lvls_adj[0] = z_lo - 1e-5 * z_span
        lvls_adj[-1] = z_hi + 1e-5 * z_span
        zd["levels"] = lvls_adj
        p_c.zlevels = zd
    except Exception:
        pass

    if contour_layer.palette_colors:
        stops = list(contour_layer.palette_colors)
    elif is_heatmap and ("diverging" in contour_layer.color_scheme or z_lo < -1e-6):
        stops = list(ot.DIVERGING_BLUE_WHITE_RED_STOPS)
    else:
        stops = list(ot.PSEUDOCOLOR_ZERO_WHITE_STOPS)
    pal_file = pal_tmp_dir / f"{gp.name}_2d.pal"
    ot.write_continuous_riff_pal(pal_file, stops, n_colors=256)
    p_c.colormap = str(pal_file)
    try:
        tr_cm = p_c.obj.Theme
        if tr_cm.ColorMap is not None:
            if not is_heatmap and contour_layer.hide_contour_lines:
                tr_cm.ColorMap.SetIntValue(0, "MajorLines")
                tr_cm.ColorMap.SetIntValue(0, "MinorLines")
                tr_cm.ColorMap.SetIntValue(1, "ColorFillControl")
            if tr_cm.ColorMap.Details is not None:
                tr_cm.ColorMap.Details.SetIntValue(ot.hex_to_origin_rgb_int(stops[0]), "BelowColor")
                tr_cm.ColorMap.Details.SetIntValue(ot.hex_to_origin_rgb_int(stops[-1]), "AboveColor")
        p_c.obj.Theme = tr_cm
    except Exception:
        pass

    spec = ob.get_active_spec()
    wb_aux = op.new_book("w", lname=f"{page_lname}_Aux")
    used_sheets: set[str] = set()
    has_long_state_y = bool(state_labels and max((len(str(s)) for s in state_labels), default=0) >= 4)
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    white_txt_int = ot.hex_to_origin_rgb_int("#FFFFFF")

    if side_panel is None:
        # Exact unified `10.40 x 7.80 in` (`3120 x 2339 px`) 4:3 page canvas with `4.80 x 4.80 in` 1:1 square box
        page_w, page_h = float(spec["page_sq_w_in"]), float(spec["page_sq_h_in"])
        sq_side = float(spec["box_sq_side_in"])
        sq_top = float(spec["box_sq_top_in"])
        # Shift 4.80 in square 0.40 in left (to 2.40 in) so [square + 0.24 gap + 0.24 colorbar + ~0.55 labels] centers optically on 10.40 in page
        sq_left = max(2.15, float(spec["box_sq_left_in"]) - 0.40)
        sq_box_in = (sq_left, sq_top, sq_side, sq_side)
        ob.set_graph_page_inches(gp, page_w, page_h)
        _apply_single_axis_layer_style(
            op,
            gp,
            gl_c,
            1,
            contour_panel,
            rect_in=sq_box_in,
            axis_title_pt=float(spec["axis_title_pt"]),
            tick_label_pt=float(spec["tick_label_pt"]),
        )
        ob.activate_layer(op, gp, 1)
        gl_c.lt_exec(f"layer.unit=2; layer.left={sq_left}; layer.top={sq_top}; layer.width={sq_side}; layer.height={sq_side};")
        if is_heatmap:
            gl_c.set_xlim(x1 - 0.5, x2 + 0.5)
            gl_c.set_ylim(y2 + 0.5, y1 - 0.5)
            gl_c.lt_exec(
                f"layer.x.from={x1 - 0.5}; layer.x.to={x2 + 0.5}; layer.x.inc=1; layer.x.ticks=0; "
                f"layer.y.from={y2 + 0.5}; layer.y.to={y1 - 0.5}; layer.y.inc=1; layer.y.ticks=0;"
            )
        elif has_y_lbls:
            gl_c.set_xlim(x2 if contour_panel.x_axis.invert else x1, x1 if contour_panel.x_axis.invert else x2)
            gl_c.set_ylim(y_map_hi, y_map_lo)
            gl_c.lt_exec(f"layer.y.from={y_map_hi}; layer.y.to={y_map_lo}; layer.y.inc=1; layer.y.ticks=1;")
        else:
            gl_c.set_xlim(x2 if contour_panel.x_axis.invert else x1, x1 if contour_panel.x_axis.invert else x2)
            gl_c.set_ylim(y1, y2)
        gl_c.lt_exec("label -r Legend;")
        c_rect_pct = ot.rect_in_to_page_pct(*sq_box_in, page_w, page_h)
        y_lbl_rect_pct = c_rect_pct
        cb_box_in: Optional[Tuple[float, float, float, float]] = (sq_left + sq_side + 0.24, sq_top, 0.24, sq_side)
        spec_x_pct, spec_top_pct, bar_w_pct, spec_h_pct = ot.rect_in_to_page_pct(*cb_box_in, page_w, page_h)
    else:
        page_w, page_h = 11.4, 6.9
        ob.set_graph_page_inches(gp, page_w, page_h)
        side_on_left = side_panel.col <= contour_panel.col
        if side_on_left:
            s_rect = (15.5 if has_long_state_y else 11.5, 10.5, 20.0, 68.0)
            c_rect = (38.5 if has_long_state_y else 35.0, 10.5, 41.0, 68.0)
            spec_x_pct = 82.0
        else:
            c_rect = (17.5 if has_long_state_y else 12.5, 10.5, 42.0, 68.0)
            s_rect = (62.0, 10.5, 19.0, 68.0)
            spec_x_pct = 83.5
        spec_top_pct = 10.5
        spec_h_pct = 68.0
        bar_w_pct = 2.4
        cb_box_in = None

        _apply_single_axis_layer_style(
            op,
            gp,
            gl_c,
            1,
            contour_panel,
            rect_pct=c_rect,
            axis_title_pt=22.0,
            tick_label_pt=18.0,
            hide_y_override=side_on_left,
        )
        if is_heatmap:
            gl_c.set_xlim(x1 - 0.5, x2 + 0.5)
            gl_c.set_ylim(y2 + 0.5, y1 - 0.5)
            gl_c.lt_exec(
                f"layer.x.from={x1 - 0.5}; layer.x.to={x2 + 0.5}; layer.x.inc=1; "
                f"layer.y.from={y2 + 0.5}; layer.y.to={y1 - 0.5}; layer.y.inc=1;"
            )
        elif has_y_lbls:
            gl_c.set_xlim(x2 if contour_panel.x_axis.invert else x1, x1 if contour_panel.x_axis.invert else x2)
            gl_c.set_ylim(y_map_hi, y_map_lo)
            gl_c.lt_exec(f"layer.y.from={y_map_hi}; layer.y.to={y_map_lo}; layer.y.inc=1;")
        else:
            gl_c.set_xlim(x2 if contour_panel.x_axis.invert else x1, x1 if contour_panel.x_axis.invert else x2)
            gl_c.set_ylim(y1, y2)
        gl_c.lt_exec("label -r Legend;")

        gl_side = gp.add_layer(0)
        for s_ly in side_panel.layers:
            _plot_layer_into_glayer(op, gp, gl_side, 2, s_ly, side_panel, wb_aux, used_sheets, pal_tmp_dir)
        _apply_single_axis_layer_style(
            op,
            gp,
            gl_side,
            2,
            side_panel,
            rect_pct=s_rect,
            axis_title_pt=22.0,
            tick_label_pt=18.0,
            hide_y_override=(not side_on_left),
        )
        if has_y_lbls:
            gl_side.set_ylim(y_map_hi, y_map_lo)
            gl_side.lt_exec(f"layer.y.from={y_map_hi}; layer.y.to={y_map_lo}; layer.y.inc=1;")
        else:
            gl_side.set_ylim(y1, y2)
        ob.activate_layer(op, gp, 2)
        gl_side.lt_exec("label -r Legend;")

        c_rect_pct = c_rect
        y_lbl_rect_pct = s_rect if side_on_left else c_rect
        left_r, right_r = (s_rect, c_rect) if side_on_left else (c_rect, s_rect)
        ob.add_page_text_label(
            op, gp, gl_c, 1, "TagA", "a", max(2.0, left_r[0] - 4.2), max(2.5, left_r[1] - 4.8), fontsize=23.0, pos_scatter=0, format_math=False
        )
        ob.add_page_text_label(
            op, gp, gl_c, 1, "TagB", "b", max(2.0, right_r[0] - 2.8), max(2.5, right_r[1] - 4.8), fontsize=23.0, pos_scatter=0, format_math=False
        )

    # Render categorical Y/X labels in active preset font (`Times New Roman Bold` or `Arial Regular`)
    if has_y_lbls and state_labels:
        st_sh = ob.unique_origin_short_name("StateTicks", used_sheets, default="States")
        wks_st = wb_aux[0] if len(used_sheets) == 1 else wb_aux.add_sheet(st_sh)
        if len(used_sheets) == 1:
            wks_st.name = st_sh
        wks_st.cols = 2 if has_x_lbls else 1
        wks_st.from_list(0, [str(s) for s in state_labels], lname="StateY")
        if side_panel is not None and side_panel.col <= contour_panel.col:
            ob.activate_layer(op, gp, 2)
            gl_side.lt_exec("layer.y.showLabels=0;")
            ob.register_custom_y_label_layer(gp, 2, extra_gap=(3.2 if has_long_state_y else 1.2))
        else:
            ob.activate_layer(op, gp, 1)
            gl_c.lt_exec("layer.y.showLabels=0;")
            ob.register_custom_y_label_layer(gp, 1, extra_gap=(3.2 if has_long_state_y else 1.2))
        yl_fs = 19.5 if ny >= 11 else (20.5 if ny >= 8 else float(spec["tick_label_pt"]))
        for i_r, s_lbl in enumerate(state_labels):
            ry_pct = y_lbl_rect_pct[1] + ((i_r + 0.5) / float(ny)) * y_lbl_rect_pct[3]
            ob.add_page_text_label(
                op,
                gp,
                gl_c,
                1,
                f"CatY_{i_r+1}",
                str(s_lbl),
                y_lbl_rect_pct[0] - (0.11 / page_w) * 100.0,
                ry_pct,
                fontsize=yl_fs,
                color_int=ink_int,
                pos_scatter=1,
                format_math=False,
            )

    if has_x_lbls and x_mat_labels:
        ob.activate_layer(op, gp, 1)
        gl_c.lt_exec("layer.x.showLabels=0; layer.x.ticks=0;")
        upi_hm = ob._origin_units_per_inch(spec)
        rot_deg = 45 if max((len(str(s)) for s in x_mat_labels), default=0) >= 4 else 0
        rot_rad = math.radians(rot_deg)
        xl_fs = 18.0 if nx >= 9 else (19.5 if nx >= 8 else float(spec["tick_label_pt"]))
        char_h_hm = xl_fs / 78.0
        bot_edge_pct = c_rect_pct[1] + c_rect_pct[3]
        for j_c, x_lbl in enumerate(x_mat_labels):
            s_txt = str(x_lbl)
            col_cx_pct = c_rect_pct[0] + ((j_c + 0.5) / float(nx)) * c_rect_pct[2]
            if rot_deg > 0:
                em_hm = sum(
                    0.28
                    if ch in " .,'|!"
                    else (
                        0.34
                        if ch in "iltf()-/"
                        else (0.65 if (ch.isupper() or ch.isdigit() or ch in "%+*=#") else 0.50)
                    )
                    for ch in s_txt
                )
                lbl_len_in = max(0.28, (em_hm + 0.08) * xl_fs / upi_hm)
                dx_tip_pct = ((0.50 * lbl_len_in * math.cos(rot_rad)) / page_w) * 100.0
                dy_tip_pct = ((0.18 + 0.50 * lbl_len_in * math.sin(rot_rad) + 0.45 * char_h_hm * math.cos(rot_rad)) / page_h) * 100.0
                cx_pct = col_cx_pct - dx_tip_pct + 0.32
                cy_pct = bot_edge_pct + dy_tip_pct
            else:
                cx_pct = col_cx_pct
                cy_pct = bot_edge_pct + 3.8
            ob.add_page_text_label(
                op,
                gp,
                gl_c,
                1,
                f"CatX_{j_c+1}",
                s_txt,
                cx_pct,
                cy_pct,
                fontsize=xl_fs,
                color_int=ink_int,
                rotate=rot_deg,
                pos_scatter=0,
                format_math=False,
            )

    # Render heatmap cell values cleanly fitted inside each square cell
    if is_heatmap and (contour_layer.show_value_labels or mat_s.show_value_labels):
        cell_fs = 12.5 if max(nx, ny) >= 9 else (15.0 if max(nx, ny) >= 7 else float(spec["callout_pt"]))
        v_fmt = mat_s.value_format or "{:.2f}"
        for i_r in range(ny):
            ry_pct = c_rect_pct[1] + ((i_r + 0.5) / float(ny)) * c_rect_pct[3]
            for j_c in range(nx):
                val = float(z_np[i_r, j_c])
                if not np.isfinite(val):
                    continue
                cx_pct = c_rect_pct[0] + ((j_c + 0.5) / float(nx)) * c_rect_pct[2]
                try:
                    v_str = v_fmt.format(val)
                except Exception:
                    v_str = f"{val:.2f}"
                norm_mag = abs(val) / max(abs(z_lo), abs(z_hi), 1e-6) if z_lo < 0 else (val - z_lo) / max(z_span, 1e-6)
                c_cell_txt = white_txt_int if norm_mag >= 0.62 else ink_int
                ob.add_page_text_label(
                    op,
                    gp,
                    gl_c,
                    1,
                    f"HM_{i_r}_{j_c}",
                    v_str,
                    cx_pct,
                    ry_pct,
                    fontsize=cell_fs,
                    color_int=c_cell_txt,
                    pos_scatter=0,
                    format_math=False,
                )

    # Destroy legacy SPECTRUM1 and build flush 64-band RGB-interpolated GLayer ColorBar!
    ob.activate_layer(op, gp, 1)
    gl_c.lt_exec("label -r SPECTRUM1; label -r ColorScale;")
    for go in list(gl_c.obj.GraphObjects):
        if getattr(go, "Name", "").upper() in ("SPECTRUM1", "COLORSCALE"):
            try:
                go.Destroy()
            except Exception:
                pass

    n_bands = 64
    stop_hexes = [ot.normalize_hex(c) for c in stops]
    stop_pos = np.linspace(0.0, 1.0, len(stop_hexes))
    stop_r = np.array([int(h[1:3], 16) for h in stop_hexes], dtype=float)
    stop_g = np.array([int(h[3:5], 16) for h in stop_hexes], dtype=float)
    stop_b = np.array([int(h[5:7], 16) for h in stop_hexes], dtype=float)
    band_mids = (np.arange(n_bands, dtype=float) + 0.5) / float(n_bands)
    band_hexes = [
        f"#{int(round(rv)):02X}{int(round(gv)):02X}{int(round(bv)):02X}"
        for rv, gv, bv in zip(
            np.interp(band_mids, stop_pos, stop_r),
            np.interp(band_mids, stop_pos, stop_g),
            np.interp(band_mids, stop_pos, stop_b),
        )
    ]

    cb_sh = ob.unique_origin_short_name("ColorBar64", used_sheets, default="CBar")
    wks_cb = wb_aux.add_sheet(cb_sh)
    wks_cb.cols = 1 + 2 * n_bands
    wks_cb.from_list(0, [0.0, 1.0], lname="CB_X", axis="X")
    z_edges = np.linspace(z_lo, z_hi, n_bands + 1, dtype=float)
    dz_overlap = 0.004 * z_span
    for b_i in range(n_bands):
        y_bot_b = float(z_edges[b_i])
        y_top_b = float(min(z_hi, z_edges[b_i + 1] + (dz_overlap if b_i < n_bands - 1 else 0.0)))
        wks_cb.from_list(1 + 2 * b_i, [y_top_b, y_top_b], axis="Y")
        wks_cb.from_list(2 + 2 * b_i, [y_bot_b, y_bot_b], axis="Y")

    gl_cbar = gp.add_layer(0)
    cbar_lay_num = int(gp.obj.Layers.Count)
    ob.activate_layer(op, gp, cbar_lay_num)
    for b_i, b_hex in enumerate(band_hexes):
        b_oc = ob._hex_to_origin_color(op, b_hex)
        p_bu = gl_cbar.add_plot(wks_cb, coly=1 + 2 * b_i, colx=0, type="l")
        p_bl = gl_cbar.add_plot(wks_cb, coly=2 + 2 * b_i, colx=0, type="l")
        p_bu.color = b_oc
        p_bl.color = b_oc
        p_bu.set_fill_area(above=b_oc, type=9, below=b_oc)
        p_bu.transparency = 0
        p_bl.transparency = 100
        u_idx = 2 * b_i + 1
        l_idx = 2 * b_i + 2
        gl_cbar.lt_exec(f"range rbu = !{u_idx}; set rbu -w 40; range rbl = !{l_idx}; set rbl -w 0;")

    cb_bt = float(spec["inset_box_lw_pt"])
    z_inc_cb = z_span / max(1, len(maj_levels) - 1)
    cb_pos_cmd = (
        f"layer.unit=2; layer.left={cb_box_in[0]}; layer.top={cb_box_in[1]}; layer.width={cb_box_in[2]}; layer.height={cb_box_in[3]}; "
        if cb_box_in is not None
        else f"layer.unit=1; layer.left={spec_x_pct}; layer.top={spec_top_pct}; layer.width={bar_w_pct}; layer.height={spec_h_pct}; "
    )
    gl_cbar.lt_exec(
        f"{cb_pos_cmd}"
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.showAxes=3; layer.y.showAxes=3; "
        f"layer.x.thickness={cb_bt}; layer.y.thickness={cb_bt}; layer.x2.thickness={cb_bt}; layer.y2.thickness={cb_bt}; "
        f"layer.x.color={ink_int}; layer.y.color={ink_int}; layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
        f"layer.x.ticks=0; layer.x2.ticks=0; layer.x.showLabels=0; "
        f"layer.y.ticks=0; layer.y2.ticks=1; layer.y.showLabels=0; layer.y2.showLabels=0; "
        f"XB.show=0; YL.show=0; YR.show=0; XT.show=0; label -r Legend; label -r SPECTRUM1; label -r ColorScale;"
    )
    gl_cbar.set_xlim(0.0, 1.0)
    gl_cbar.set_ylim(z_lo, z_hi)
    gl_cbar.lt_exec(
        f"layer.x.from=0; layer.x.to=1; layer.y.from={z_lo}; layer.y.to={z_hi}; layer.y.inc={z_inc_cb}; "
        f"label -r SPECTRUM1; label -r ColorScale; label -r Legend;"
    )
    for go_cb in list(gl_cbar.obj.GraphObjects):
        if getattr(go_cb, "Name", "").upper() in ("SPECTRUM1", "COLORSCALE", "LEGEND"):
            try:
                go_cb.Destroy()
            except Exception:
                pass

    # Render clean major tick labels alongside gl_cbar
    for idx_lv, lv in enumerate(maj_levels):
        frac_top = (z_hi - lv) / max(z_span, 1e-9)
        ly_pct = spec_top_pct + frac_top * spec_h_pct
        if abs(lv - round(lv)) < 1e-4 and z_span >= 10.0:
            lv_str = f"{int(round(lv))}"
        elif abs(lv * 10.0 - round(lv * 10.0)) < 1e-3:
            lv_str = f"{lv:.1f}"
        else:
            lv_str = f"{lv:.2f}"
        ob.add_page_text_label(
            op,
            gp,
            gl_c,
            1,
            f"ZBarTick_{idx_lv}",
            lv_str,
            spec_x_pct + bar_w_pct + (0.09 / page_w) * 100.0,
            ly_pct,
            fontsize=20.0,
            color_int=ink_int,
            pos_scatter=2,
            format_math=False,
        )

    if z_ax and z_ax.label:
        z_raw = z_ax.label
    elif is_heatmap:
        z_raw = "Pearson \\i(r)" if z_lo < 0 else ""
    else:
        z_raw = "Intensity (a.u.)"
    if z_raw:
        z_rich = _format_origin_guide_text(z_raw).replace("Pearson r", "Pearson \\i(r)")
        z_title_x_pct = min(95.5, spec_x_pct + bar_w_pct + (1.06 / page_w) * 100.0)
        ob.add_page_text_label(
            op,
            gp,
            gl_c,
            1,
            "ZBarTitle",
            z_rich,
            z_title_x_pct,
            spec_top_pct + 0.5 * spec_h_pct,
            fontsize=25.0,
            rotate=90,
            pos_scatter=0,
            format_math=True,
        )

    if contour_panel.guides:
        _render_guides_into_glayer(
            op,
            gp,
            gl_c,
            1,
            contour_panel.guides,
            wb_aux,
            used_sheets,
            (min(x1, x2), max(x1, x2)),
            (min(y1, y2), max(y1, y2)),
            invert_x=contour_panel.x_axis.invert,
        )

    return gp


def _render_single_panel_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    if panel.y2_axis is not None and any(ly.y_axis == "y2" for ly in panel.layers):
        return _render_dual_y_panel_page(op, panel, page_lname, pal_tmp_dir)

    if any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers):
        dummy_fig = cg.FigureSpec(title=page_lname, mode="contour_pseudocolor_2d", panels=[panel])
        return _render_contour_2d_page(op, dummy_fig, panel, None, page_lname, pal_tmp_dir)

    spec = ob.get_active_spec()
    tpl = _resolve_clean_origin_template(panel.layers)
    gp = op.new_graph(lname=page_lname, template=tpl) if tpl else op.new_graph(lname=page_lname)

    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    box_in = (
        float(spec["box_rect_left_in"]),
        float(spec["box_rect_top_in"]),
        float(spec["box_rect_w_in"]),
        float(spec["box_rect_h_in"]),
    )
    ob.set_graph_page_inches(gp, pw, ph)
    rect_for_leg = ot.rect_in_to_page_pct(*box_in, pw, ph)

    wb = op.new_book("w", lname=f"{page_lname}_Book")
    used_sheets: set[str] = set()
    gl = gp[0]

    all_leg: List[Tuple[Any, ...]] = []
    for ly in panel.layers:
        all_leg.extend(_plot_layer_into_glayer(op, gp, gl, 1, ly, panel, wb, used_sheets, pal_tmp_dir))

    has_stacked_100 = any(ly.mark == "bar_stacked_100pct" for ly in panel.layers if ly.y_axis == "y1")
    has_stacked = any(ly.mark in ("bar_stacked", "bar_stacked_100pct") for ly in panel.layers)
    has_stat = any(ly.mark in ("stat_distribution", "stat_box_jitter") for ly in panel.layers)
    has_dense_guides = sum(1 for g in panel.guides if g.kind in ("hline", "span_v")) >= 3
    n_leg = len(all_leg)
    want_leg = (panel.legend_style != "none") and bool(all_leg)
    use_interior_top_leg = (
        (has_stacked or (has_stat and n_leg <= 7) or (has_dense_guides and n_leg <= 4 and not panel.insets))
        and want_leg
    )

    x_bounds, y_bounds = _apply_single_axis_layer_style(
        op,
        gp,
        gl,
        1,
        panel,
        rect_pct=rect_for_leg,
        rect_in=box_in,
        axis_title_pt=float(spec["axis_title_pt"]),
        tick_label_pt=float(spec["tick_label_pt"]),
        reserve_top_legend_space=(use_interior_top_leg and not panel.equal_aspect),
    )

    if has_stacked_100:
        top_100 = 138.0 if want_leg else 100.0
        ob.apply_clamped_0_100_y_ticks(
            op,
            gp,
            gl,
            1,
            wb,
            used_sheets,
            x_bounds[0],
            x_bounds[1],
            ylim_top=top_100,
            max_tick_val=100.0,
            step_val=20.0,
            tick_pt=float(spec["tick_label_pt"]),
        )
        y_bounds = (0.0, top_100)

    if panel.guides:
        _render_guides_into_glayer(
            op,
            gp,
            gl,
            1,
            panel.guides,
            wb,
            used_sheets,
            x_bounds,
            y_bounds,
            invert_x=panel.x_axis.invert,
            log_x=(panel.x_axis.scale == "log10"),
            log_y=(panel.y1_axis.scale == "log10"),
        )

    if panel.insets:
        _render_insets_for_panel(op, gp, gl, 1, panel, wb, used_sheets, pal_tmp_dir, x_bounds, y_bounds)
        if panel.equal_aspect and panel.insets:
            _draw_zoom_connectors(op, gp, gl, 1, panel, panel.insets, x_bounds, y_bounds, wb, used_sheets)

    # Configure main layer custom legend STRICTLY INSIDE plot box!
    if not want_leg:
        ob.activate_layer(op, gp, 1)
        gl.lt_exec("label -r Legend;")
    elif use_interior_top_leg:
        ob.configure_custom_legend(
            gl,
            all_leg,
            fontsize=(20.0 if n_leg >= 5 else float(spec["legend_pt"])),
            horizontal=True,
            pos_mode="interior_top",
            layer_rect_pct=rect_for_leg,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
    else:
        pos_m = _pick_cleanest_legend_corner(panel, x_bounds, y_bounds)
        ob.configure_custom_legend(
            gl,
            all_leg,
            fontsize=(19.5 if n_leg >= 6 else float(spec["legend_pt"])),
            pos_mode=pos_m,
            layer_rect_pct=rect_for_leg,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )

    return gp


def _compute_grid_cell_rect_pct(
    panel: cg.PanelSpec,
    nrows: int,
    ncols: int,
    width_ratios: Sequence[float],
    height_ratios: Sequence[float],
) -> Tuple[float, float, float, float]:
    tot_w = sum(width_ratios) or float(ncols)
    tot_h = sum(height_ratios) or float(nrows)
    usable_w = 90.0
    usable_h = 88.0
    margin_l = 6.0
    margin_t = 6.0

    col_starts = [margin_l]
    for r in width_ratios:
        col_starts.append(col_starts[-1] + usable_w * (float(r) / tot_w))
    row_starts = [margin_t]
    for r in height_ratios:
        row_starts.append(row_starts[-1] + usable_h * (float(r) / tot_h))

    c0, c1 = panel.col, min(ncols, panel.col + panel.col_span)
    r0, r1 = panel.row, min(nrows, panel.row + panel.row_span)
    cell_l = col_starts[c0]
    cell_w = col_starts[c1] - cell_l
    cell_t = row_starts[r0]
    cell_h = row_starts[r1] - cell_t

    has_y2 = panel.y2_axis is not None and any(ly.y_axis == "y2" for ly in panel.layers)
    pad_l = cell_w * 0.17
    pad_r = cell_w * (0.16 if has_y2 else 0.06)
    pad_t = cell_h * 0.14
    pad_b = cell_h * 0.18
    return (cell_l + pad_l, cell_t + pad_t, max(10.0, cell_w - pad_l - pad_r), max(10.0, cell_h - pad_t - pad_b))


def _render_multi_panel_composite_page(
    op: Any,
    fig_spec: cg.FigureSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    nr, nc = fig_spec.nrows, fig_spec.ncols
    gp = op.new_graph(lname=page_lname)
    page_w = max(8.6, 5.8 * nc)
    page_h = max(5.6, 4.8 * nr)
    ob.set_graph_page_inches(gp, page_w, page_h)

    wb = op.new_book("w", lname=f"{page_lname}_GridBook")
    used_sheets: set[str] = set()
    lay_counter = 0

    for p_idx, panel in enumerate(fig_spec.panels):
        rect = _compute_grid_cell_rect_pct(panel, nr, nc, fig_spec.width_ratios, fig_spec.height_ratios)
        gl_p = gp[0] if lay_counter == 0 else gp.add_layer(0)
        lay_counter += 1
        cur_lay_num = lay_counter
        ob.activate_layer(op, gp, cur_lay_num)

        leg_p: List[Tuple[Any, ...]] = []
        y1_layers = [ly for ly in panel.layers if ly.y_axis == "y1"] or panel.layers
        for ly in y1_layers:
            if ly.mark in ("contour_pseudocolor", "matrix_heatmap"):
                mat_s = ly.series[0]
                z_np = np.asarray(mat_s.matrix_z, dtype=float)
                mb = op.new_book("m", lname=f"{page_lname}_{panel.panel_id}_M")
                ms = mb[0]
                z_use = _upsample_2d_linear(z_np) if (ly.hide_contour_lines and ly.mark != "matrix_heatmap") else z_np
                ms.from_np(z_use)
                xa = mat_s.matrix_x or [1.0, float(z_np.shape[1])]
                ya = (
                    [float(v) for v in mat_s.matrix_y]
                    if mat_s.matrix_y and all(isinstance(v, (int, float)) for v in mat_s.matrix_y)
                    else [1.0, float(z_np.shape[0])]
                )
                ms.xymap = (float(xa[0]), float(xa[-1]), float(ya[0]), float(ya[-1]))
                ob.activate_layer(op, gp, cur_lay_num)
                pcode = 105 if ly.mark == "matrix_heatmap" else (220 if ly.hide_contour_lines else 226)
                pc = gl_p.add_mplot(ms, 0, type=pcode)
                pal_f = pal_tmp_dir / f"{gp.name}_p{p_idx}.pal"
                ot.write_continuous_riff_pal(pal_f, ly.palette_colors or ot.PSEUDOCOLOR_ZERO_WHITE_STOPS)
                pc.colormap = str(pal_f)
            else:
                leg_p.extend(_plot_layer_into_glayer(op, gp, gl_p, cur_lay_num, ly, panel, wb, used_sheets, pal_tmp_dir))

        x_b, y_b = _apply_single_axis_layer_style(
            op, gp, gl_p, cur_lay_num, panel, rect_pct=rect, axis_title_pt=17.5, tick_label_pt=14.0
        )
        if panel.guides:
            _render_guides_into_glayer(
                op,
                gp,
                gl_p,
                cur_lay_num,
                panel.guides,
                wb,
                used_sheets,
                x_b,
                y_b,
                invert_x=panel.x_axis.invert,
                log_x=(panel.x_axis.scale == "log10"),
                log_y=(panel.y1_axis.scale == "log10"),
            )

        has_st = any(ly.mark in ("bar_stacked", "bar_stacked_100pct") for ly in y1_layers)
        if panel.legend_style == "none" or not leg_p:
            ob.activate_layer(op, gp, cur_lay_num)
            gl_p.lt_exec("label -r Legend;")
        else:
            pos_m = "above_frame" if has_st else _pick_cleanest_legend_corner(panel, x_b, y_b)
            ob.configure_custom_legend(
                gl_p,
                leg_p,
                fontsize=12.5,
                horizontal=has_st,
                pos_mode=pos_m,
                layer_rect_pct=rect,
                op=op,
                gp=gp,
                layer_num_1based=cur_lay_num,
            )

        tag_raw = panel.tag or chr(ord("a") + p_idx)
        tag_txt = tag_raw if tag_raw.startswith("(") else f"({tag_raw})"
        ob.add_page_text_label(
            op,
            gp,
            gl_p,
            cur_lay_num,
            f"GridTag{p_idx+1}",
            tag_txt,
            max(1.5, rect[0] - 5.0),
            max(1.8, rect[1] - 3.8),
            fontsize=19.0,
            pos_scatter=0,
            format_math=False,
        )

    return gp


# ---------------------------------------------------------------------------
# 17_EIS Zoom-Box Connector Guide Lines
# ---------------------------------------------------------------------------


def _draw_zoom_connectors(
    op: Any,
    gp: Any,
    gl_main: Any,
    main_layer_num_1based: int,
    panel: cg.PanelSpec,
    insets: Sequence[cg.InsetSpec],
    main_x_bounds: Tuple[float, float],
    main_y_bounds: Tuple[float, float],
    wb: Any,
    used_sheets: set,
) -> None:
    """Draw 2 light dotted tangent connector lines from the Zoom Box right corners to the inset left corners."""
    if not insets:
        return
    ob.activate_layer(op, gp, main_layer_num_1based)
    x_lo, x_hi = min(main_x_bounds), max(main_x_bounds)
    y_lo, y_hi = min(main_y_bounds), max(main_y_bounds)
    x_span = max(x_hi - x_lo, 1e-6)
    y_span = max(y_hi - y_lo, 1e-6)

    spec = ob.get_active_spec()
    par_w_in = float(spec["box_rect_w_in"])
    par_h_in = float(spec["box_rect_h_in"])

    for ins in insets:
        ix_lim_res, iy_lim_res = _resolve_inset_xy_bounds(ins, panel, par_w_in, par_h_in)
        if ix_lim_res is None or iy_lim_res is None:
            continue
        zx0, zx1 = float(min(ix_lim_res)), float(max(ix_lim_res))
        zy0, zy1 = float(min(iy_lim_res)), float(max(iy_lim_res))
        il, it, iw, ih = _resolve_inset_bbox_pct(ins, panel)

        def _pct_to_data_x(p: float) -> float:
            return x_lo + (p / 100.0) * x_span

        def _pct_to_data_y_from_top(p: float) -> float:
            return y_hi - (p / 100.0) * y_span

        ins_x0 = _pct_to_data_x(il)
        ins_y1 = _pct_to_data_y_from_top(it)
        ins_y0 = _pct_to_data_y_from_top(it + ih)

        pairs = [
            (zx1, zy1, ins_x0, ins_y1),  # top-right of zoom box → exact top-left corner of inset
            (zx1, zy0, ins_x0, ins_y0),  # bottom-right of zoom box → exact bottom-left corner of inset
        ]

        con_sh = ob.unique_origin_short_name("ZoomCon", used_sheets, default="ZCon")
        wks_con = wb.add_sheet(con_sh)
        wks_con.cols = len(pairs) * 2
        wks_con.cols_axis("XY" * len(pairs))
        for ci, (xa, ya, xb, yb) in enumerate(pairs):
            wks_con.from_list(2 * ci, [xa, xb], lname=f"ConX{ci+1}", axis="X")
            wks_con.from_list(2 * ci + 1, [ya, yb], lname=f"ConY{ci+1}", axis="Y")
            p_con = gl_main.add_plot(wks_con, coly=2 * ci + 1, colx=2 * ci, type="l")
            p_con.color = ob._hex_to_origin_color(op, "#8C96A6")
            con_idx = len(gl_main.plot_list())
            gl_main.lt_exec(f"range rcon = !{con_idx}; set rcon -d 2; set rcon -w 650; label -r Legend;")


# ---------------------------------------------------------------------------
# 20. xy_fit_and_band — XY Scatter + Fit Line + Confidence Band
# ---------------------------------------------------------------------------


def _render_xy_fit_and_band_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    """
    Mode 20: `xy_fit_and_band`
    Exact Family A 4:3 (`9.20 x 6.90 in`, `6.00 x 4.50 in` box) + pastel 95% CI band + 2D `-k 2` circles + in-box legend & equation.
    """
    spec = ob.get_active_spec()
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    box_in = (
        float(spec["box_rect_left_in"]),
        float(spec["box_rect_top_in"]),
        float(spec["box_rect_w_in"]),
        float(spec["box_rect_h_in"]),
    )
    rect_use = ot.rect_in_to_page_pct(*box_in, pw, ph)

    gp = op.new_graph(lname=page_lname)
    ob.set_graph_page_inches(gp, pw, ph)

    wb = op.new_book("w", lname=f"{page_lname}_Book")
    used_sheets: set[str] = set()
    gl = gp[0]

    eq_text = str(panel.meta.get("regression_equation") or panel.meta.get("equation_str") or "").strip()
    r2_val = panel.meta.get("r_squared", panel.meta.get("r2", ""))

    for ly in panel.layers:
        for s in ly.series:
            is_no_line = str(s.line_style or "solid").strip().lower() in ("none", "", "false")
            if is_no_line and str(s.marker_style or "none").strip().lower() in ("none", "", "false"):
                s.marker_style = "circle_solid"
                s.marker_size_pt = float(spec["marker_size_pt"])
            if s.name == "scatter":
                s.name = "Experimental"
            elif s.name == "fit_band":
                s.name = "Fit (95% CI)"
            if s.y_low is not None and s.y_high is not None:
                s.line_width_pt = float(spec["curve_lw_pt"])
            if not eq_text and s.meta.get("equation_str"):
                eq_text = str(s.meta["equation_str"]).strip()
            if r2_val == "" and s.meta.get("r2") is not None:
                r2_val = s.meta["r2"]

    all_leg: List[Tuple[Any, ...]] = []
    for ly in panel.layers:
        all_leg.extend(_plot_layer_into_glayer(op, gp, gl, 1, ly, panel, wb, used_sheets, pal_tmp_dir))

    x_bounds, y_bounds = _apply_single_axis_layer_style(
        op,
        gp,
        gl,
        1,
        panel,
        rect_pct=rect_use,
        rect_in=box_in,
        axis_title_pt=float(spec["axis_title_pt"]),
        tick_label_pt=float(spec["tick_label_pt"]),
        reserve_top_legend_space=True,
    )

    if panel.guides:
        _render_guides_into_glayer(
            op, gp, gl, 1, panel.guides, wb, used_sheets, x_bounds, y_bounds,
            invert_x=panel.x_axis.invert,
            log_x=(panel.x_axis.scale == "log10"),
            log_y=(panel.y1_axis.scale == "log10"),
        )

    leg_corner = _pick_cleanest_legend_corner(panel, x_bounds, y_bounds)
    if panel.legend_style != "none" and all_leg:
        ob.configure_custom_legend(
            gl, all_leg, fontsize=float(spec["legend_pt"]), horizontal=False, pos_mode=leg_corner,
            layer_rect_pct=rect_use, op=op, gp=gp, layer_num_1based=1,
        )
    else:
        ob.activate_layer(op, gp, 1)
        gl.lt_exec("label -r Legend;")

    if eq_text or r2_val != "":
        eq_clean = eq_text.replace("R²", "\\i(R)\\+(2)").replace("×", "\\g(\\xD7)")
        eq_clean = re.sub(r"\s*\*\s*(?=[xX]\b)", " ", eq_clean)
        eq_clean = re.sub(r"\s*\*\s*", lambda _: " \\g(\\xD7) ", eq_clean)
        eq_clean = re.sub(r"\^\{([^}]+)\}", lambda m: f"\\+({m.group(1)})", eq_clean)
        eq_clean = re.sub(r"\^(-?\d+(?:\.\d+)?)", lambda m: f"\\+({m.group(1)})", eq_clean)
        eq_clean = re.sub(r"\by\b", lambda _: "\\i(y)", eq_clean)
        eq_clean = re.sub(r"\bx\b", lambda _: "\\i(x)", eq_clean)
        r2_str = f"{float(r2_val):.4f}" if isinstance(r2_val, (int, float)) else str(r2_val)
        if eq_clean and ("R\\+(2)" in eq_clean or "R^2" in eq_clean):
            full_ann = eq_clean
        elif eq_clean and r2_str:
            full_ann = f"{eq_clean},  \\i(R)\\+(2) = {r2_str}"
        else:
            full_ann = eq_clean or f"\\i(R)\\+(2) = {r2_str}"

        l_p, t_p, w_p, h_p = rect_use
        eq_fs = min(float(spec["callout_pt"]), 20.5 if len(full_ann) >= 28 else float(spec["callout_pt"]))
        # Place equation cleanly below the 2-item in-box legend if in upper corner, or above if in lower corner
        n_leg_rows = len(all_leg) if (panel.legend_style != "none" and all_leg) else 0
        row_h_pct = max(5.4, float(spec["legend_pt"]) * 0.265)
        if leg_corner == "corner_upper_right":
            eq_x, eq_y, eq_align = l_p + w_p - 2.4, t_p + 5.2 + n_leg_rows * row_h_pct + 1.4, 1
        elif leg_corner == "corner_lower_right":
            eq_x, eq_y, eq_align = l_p + w_p - 2.4, max(t_p + 5.2, t_p + h_p - max(0, n_leg_rows) * row_h_pct - 6.6), 1
        elif leg_corner == "corner_lower_left":
            eq_x, eq_y, eq_align = l_p + 2.8, max(t_p + 5.2, t_p + h_p - max(0, n_leg_rows) * row_h_pct - 6.6), 2
        else:
            eq_x, eq_y, eq_align = l_p + 2.8, t_p + 5.2 + n_leg_rows * row_h_pct + 1.4, 2
        ob.add_page_text_label(
            op, gp, gl, 1, "FitEqBox", full_ann, eq_x, eq_y,
            fontsize=eq_fs, pos_scatter=eq_align, format_math=False,
        )

    return gp


# ---------------------------------------------------------------------------
# 21. bode_dual_panel — EIS Bode (|Z| over -Phase), top/bottom dual Layer
# ---------------------------------------------------------------------------


def _render_bode_dual_panel_page(
    op: Any,
    fig_spec: cg.FigureSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    """
    Mode 21: `bode_dual_panel`
    Exact Family A outer envelope (`9.20 x 6.90 in` canvas; Upper `(1.65, 0.58, 6.00, 2.10) in`,
    Lower `(1.65, 2.98, 6.00, 2.10) in` -> outer top `0.58 in` & bottom `5.08 in` match all single panels to 0 px!).
    """
    spec = ob.get_active_spec()
    page_w, page_h = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    li = float(spec["box_rect_left_in"])
    wi = float(spec["box_rect_w_in"])
    top1_in = float(spec["bode_top_in"])
    sub_h_in = float(spec["bode_sub_h_in"])
    gap_in = float(spec["bode_gap_in"])
    top2_in = round(top1_in + sub_h_in + gap_in, 4)

    r_top = ot.rect_in_to_page_pct(li, top1_in, wi, sub_h_in, page_w, page_h)
    r_bot = ot.rect_in_to_page_pct(li, top2_in, wi, sub_h_in, page_w, page_h)
    comp_bode_tk = ot.compensate_origin_layer_pt(float(spec["tick_label_pt"]), wi, sub_h_in, page_w, page_h)

    gp = op.new_graph(lname=page_lname)
    ob.set_graph_page_inches(gp, page_w, page_h)

    wb = op.new_book("w", lname=f"{page_lname}_Book")
    used_sheets: set[str] = set()
    f_id = ob.get_font_id(op)
    bold_i = int(spec["bold_int"])
    font_clause = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""
    ink_int = ot.hex_to_origin_rgb_int("#111111")

    panels = fig_spec.panels
    p_top = panels[0]
    p_bot = panels[1] if len(panels) > 1 else panels[0]

    freq_vals: List[float] = []
    zmag_vals: List[float] = []
    phase_vals: List[float] = []
    for pnl_i, pnl in enumerate((p_top, p_bot)):
        for ly in pnl.layers:
            for s in ly.series:
                s.marker_style = "circle_solid"
                s.marker_size_pt = 6.0
                s.line_width_pt = float(spec["curve_lw_pt"])
                if s.x:
                    freq_vals.extend([float(v) for v in s.x if isinstance(v, (int, float)) and float(v) > 0])
                if s.y:
                    if pnl_i == 0:
                        zmag_vals.extend([float(v) for v in s.y if isinstance(v, (int, float)) and float(v) > 0])
                    else:
                        phase_vals.extend([float(v) for v in s.y if isinstance(v, (int, float))])

    if freq_vals and max(freq_vals) > min(freq_vals):
        f_lo = 10.0 ** math.floor(math.log10(min(freq_vals)) + 1e-9)
        f_hi = 10.0 ** math.ceil(math.log10(max(freq_vals)) - 1e-9)
        if max(freq_vals) >= 0.88 * f_hi:
            f_hi *= 10.0
        if f_hi <= f_lo:
            f_hi = f_lo * 10.0
    else:
        f_lo, f_hi = 1e-2, 1e6

    # --- Upper Layer: |Z| ---
    gl_top = gp[0]
    top_leg: List[Tuple[Any, ...]] = []
    for ly in p_top.layers:
        top_leg.extend(_plot_layer_into_glayer(op, gp, gl_top, 1, ly, p_top, wb, used_sheets, pal_tmp_dir))

    bt = float(spec["box_lw_pt"])
    y_is_log_top = p_top.y1_axis.scale == "log10"

    ob.activate_layer(op, gp, 1)
    gl_top.lt_exec(
        f"layer.unit=2; layer.left={li}; layer.top={top1_in}; layer.width={wi}; layer.height={sub_h_in}; "
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.type=2; layer.y.type={2 if y_is_log_top else 1}; "
        f"layer.x.showAxes=3; layer.y.showAxes=3; "
        f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
        f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
        f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
        f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
        f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
        f"layer.x.ticks=5; layer.x2.ticks=0; "
        f"layer.y.ticks={5 if y_is_log_top else 1}; layer.y2.ticks=0; "
        f"{font_clause}"
        f"layer.x.label.pt={comp_bode_tk}; layer.y.label.pt={comp_bode_tk}; "
        f"layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
        f"layer.x.showLabels=0;"
    )
    gl_top.rescale()
    fx0 = float(p_top.x_axis.limits[0]) if p_top.x_axis.limits else f_lo
    fx1 = float(p_top.x_axis.limits[1]) if p_top.x_axis.limits else f_hi
    n_dec_fx = round(math.log10(max(fx1 / max(fx0, 1e-30), 10.0)))
    x_inc_bode = 2 if n_dec_fx >= 6 else 1
    gl_top.set_xlim(fx0, fx1)
    gl_top.lt_exec(f"layer.x.from={fx0}; layer.x.to={fx1}; layer.x.inc={x_inc_bode}; layer.x.ticks=5; layer.x.minorTicks=8;")
    if p_top.y1_axis.limits is not None:
        gl_top.set_ylim(float(p_top.y1_axis.limits[0]), float(p_top.y1_axis.limits[1]))
    elif y_is_log_top and zmag_vals:
        z0 = 10.0 ** math.floor(math.log10(min(zmag_vals) * 0.85))
        # Extra decade headroom at top so in-box horizontal legend sits cleanly inside upper box!
        z1 = 10.0 ** math.ceil(math.log10(max(zmag_vals) * 4.5))
        if z1 <= z0:
            z1 = z0 * 10.0
        n_dec_z = round(math.log10(max(z1 / max(z0, 1e-12), 10.0)))
        inc_z = 2 if n_dec_z >= 4 else 1
        gl_top.set_ylim(z0, z1)
        gl_top.lt_exec(
            f"layer.y.from={z0}; layer.y.to={z1}; layer.y.inc={inc_z}; layer.y.ticks=5; layer.y.minorTicks=8; "
            f"layer.y.label.numFormat=2;"
        )

    top_yl_lbl = (p_top.y1_axis.label or "|\\i(Z)| (\\g(W))").replace("Ω", "\\g(W)").replace("|Z|", "|\\i(Z)|")
    ob.style_origin_native_axis_title(gl_top, "XB", "", fontsize=25.0, color_int=ink_int, op=op, gp=gp, layer_num_1based=1)
    ob.style_origin_native_axis_title(gl_top, "YL", top_yl_lbl, fontsize=25.0, color_int=ink_int, op=op, gp=gp, layer_num_1based=1)
    ob.sanitize_layer_frames_and_grids(gl_top, remove_default_legend=True, op=op, gp=gp, layer_num_1based=1)

    # --- Lower Layer: -Phase ---
    gl_bot = gp.add_layer(0)
    bot_leg: List[Tuple[Any, ...]] = []
    for ly in p_bot.layers:
        bot_leg.extend(_plot_layer_into_glayer(op, gp, gl_bot, 2, ly, p_bot, wb, used_sheets, pal_tmp_dir))

    y_is_log_bot = p_bot.y1_axis.scale == "log10"

    ob.activate_layer(op, gp, 2)
    gl_bot.lt_exec(
        f"layer.unit=2; layer.left={li}; layer.top={top2_in}; layer.width={wi}; layer.height={sub_h_in}; "
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.type=2; layer.y.type={2 if y_is_log_bot else 1}; "
        f"layer.x.showAxes=3; layer.y.showAxes=3; "
        f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
        f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
        f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
        f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
        f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
        f"layer.x.ticks=5; layer.x2.ticks=0; "
        f"layer.y.ticks={5 if y_is_log_bot else 1}; layer.y2.ticks=0; "
        f"{font_clause}"
        f"layer.x.label.pt={comp_bode_tk}; layer.y.label.pt={comp_bode_tk}; "
        f"layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
        f"layer.x.label.numFormat=2;"
    )
    gl_bot.rescale()
    bx0 = float(p_bot.x_axis.limits[0]) if p_bot.x_axis.limits else fx0
    bx1 = float(p_bot.x_axis.limits[1]) if p_bot.x_axis.limits else fx1
    n_dec_bx = round(math.log10(max(bx1 / max(bx0, 1e-30), 10.0)))
    bx_inc_bode = 2 if n_dec_bx >= 6 else 1
    gl_bot.set_xlim(bx0, bx1)
    gl_bot.lt_exec(
        f"layer.x.from={bx0}; layer.x.to={bx1}; layer.x.inc={bx_inc_bode}; layer.x.ticks=5; layer.x.minorTicks=8; "
        f"layer.x.label.numFormat=2;"
    )
    if p_bot.y1_axis.limits is not None:
        gl_bot.set_ylim(float(p_bot.y1_axis.limits[0]), float(p_bot.y1_axis.limits[1]))
    elif not y_is_log_bot and phase_vals:
        ph_min = min(0.0, math.floor(min(phase_vals) / 10.0) * 10.0)
        ph_max = max(15.0, math.ceil((max(phase_vals) * 1.18) / 15.0) * 15.0)
        gl_bot.set_ylim(ph_min, ph_max)
        gl_bot.lt_exec(f"layer.y.from={ph_min}; layer.y.to={ph_max}; layer.y.maxTicks=4;")

    x_label = p_bot.x_axis.origin_rich_label or p_bot.x_axis.label or "Frequency (Hz)"
    ob.style_origin_native_axis_title(
        gl_bot, "XB", x_label, fontsize=float(spec["axis_title_pt"]), color_int=ink_int, op=op, gp=gp, layer_num_1based=2
    )
    ob.style_origin_native_axis_title(
        gl_bot, "YL", p_bot.y1_axis.label or "-Phase (deg.)", fontsize=25.0, color_int=ink_int, op=op, gp=gp, layer_num_1based=2
    )
    ob.sanitize_layer_frames_and_grids(gl_bot, remove_default_legend=True, op=op, gp=gp, layer_num_1based=2)

    # Shared legend: horizontal, centered INSIDE top headroom of upper frame!
    all_leg = top_leg or bot_leg
    if all_leg:
        ob.configure_custom_legend(
            gl_top, all_leg, fontsize=(20.0 if len(all_leg) >= 3 else float(spec["legend_pt"])), horizontal=True,
            pos_mode="interior_top", layer_rect_pct=r_top,
            op=op, gp=gp, layer_num_1based=1,
        )

    return gp


def render_figure_spec_origin(
    fig_spec: cg.FigureSpec | Dict[str, Any],
    out_dir: str | Path,
    out_opju: Optional[str | Path] = None,
    export_images: bool = True,
) -> Dict[str, Any]:
    """
    Render a validated `FigureSpec` natively in OriginPro 2024:
    - Saves full editable `.opju` project (`out_opju` when `fig_spec.build_opju` is True)
    - Exports 600 DPI lossless LZW `.tif` + 300 DPI `.png` + `<=960 px` `_qa_previews/*_preview.jpg`
      via `export_origin_publication_figures` strictly AFTER all styling/Theme/Overlay commits finish.
    """
    spec = fig_spec if isinstance(fig_spec, cg.FigureSpec) else cg.FigureSpec.from_dict(fig_spec)
    ob.set_active_style(spec.theme if spec.theme else spec.style_preset)
    out_p = Path(out_dir).resolve()
    out_p.mkdir(parents=True, exist_ok=True)

    stem = _sanitize_file_stem(spec.title, default=f"SciOrigin_{spec.mode}")
    opju_target = Path(out_opju).resolve() if out_opju is not None else (out_p / f"{stem}.opju")

    panel_figures: Dict[str, Dict[str, str]] = {}
    all_exported_files: List[str] = []
    graph_names: List[str] = []

    is_bode_dual = (
        spec.mode == "bode_dual_panel"
        or (len(spec.panels) == 2 and any(p.meta.get("bode_panel") for p in spec.panels))
    )
    is_xy_fit_band = (
        spec.mode == "xy_fit_and_band"
        or (
            len(spec.panels) == 1
            and any(ly.mark == "line_band" or ly.layer_id == "xy_fit_main" for ly in spec.panels[0].layers)
        )
    )

    with tempfile.TemporaryDirectory(prefix="sciorigin_pal_") as tmp_dir_str:
        pal_tmp_dir = Path(tmp_dir_str)
        with ob.origin_session() as op:
            root_pe = op.pe.cd()

            if (
                spec.mode == "contour_pseudocolor_2d"
                and len(spec.panels) == 2
                and any(
                    any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in p.layers)
                    for p in spec.panels
                )
            ):
                p_contour = next(
                    p for p in spec.panels if any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in p.layers)
                )
                p_side = next(p for p in spec.panels if p.panel_id != p_contour.panel_id)
                gp_main = _render_contour_2d_page(op, spec, p_contour, p_side, stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures: Dict[str, str] = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem)
                    all_exported_files.extend(primary_figures.values())

            elif is_xy_fit_band and len(spec.panels) >= 1:
                gp_main = _render_xy_fit_and_band_page(op, spec.panels[0], stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem)
                    all_exported_files.extend(primary_figures.values())

            elif is_bode_dual and len(spec.panels) >= 2:
                gp_main = _render_bode_dual_panel_page(op, spec, stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem)
                    all_exported_files.extend(primary_figures.values())

            elif len(spec.panels) == 1:
                gp_main = _render_single_panel_page(op, spec.panels[0], stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem)
                    all_exported_files.extend(primary_figures.values())

            else:
                standalone_pages: List[Tuple[str, str, Any]] = []
                for idx, pnl in enumerate(spec.panels):
                    op.pe.cd(root_pe)
                    letter = pnl.tag or chr(ord("a") + idx)
                    safe_pid = ob.sanitize_origin_short_name(pnl.panel_id, f"P{idx+1}", max_len=16)
                    sub_f = op.pe.mkdir(f"Panel_{letter}_{safe_pid}", True)
                    op.pe.cd(sub_f)
                    gp_sub = _render_single_panel_page(op, pnl, f"{stem}_{pnl.panel_id}", pal_tmp_dir)
                    graph_names.append(gp_sub.name)
                    sub_stem = (
                        f"{stem}_QV"
                        if (spec.subtype == "galvanostatic_dqdv" and idx == 0)
                        else (
                            f"{stem}_dQdV"
                            if (spec.subtype == "galvanostatic_dqdv" and idx == 1)
                            else f"{stem}_{pnl.panel_id}"
                        )
                    )
                    standalone_pages.append((pnl.panel_id, sub_stem, gp_sub))

                op.pe.cd(root_pe)
                gp_main = _render_multi_panel_composite_page(op, spec, stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem)
                    all_exported_files.extend(primary_figures.values())
                    for pid, sub_stem, gp_sub in standalone_pages:
                        p_figs = export_origin_publication_figures(op, gp_sub, out_p, sub_stem)
                        panel_figures[pid] = p_figs
                        all_exported_files.extend(p_figs.values())

            op.pe.cd(root_pe)
            saved_opju = ob._safe_save_opju(op, opju_target) if spec.build_opju else None

    return {
        "opju": saved_opju,
        "primary_figures": primary_figures,
        "panel_figures": panel_figures,
        "all_exported_files": all_exported_files,
        "graph_pages": graph_names,
    }
