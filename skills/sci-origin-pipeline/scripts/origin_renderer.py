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

# Re-export bar gradient helper & wrap publication export with vector PDF support
apply_origin_bar_gradient_and_label = ob.apply_origin_bar_gradient_and_label


def export_origin_publication_figures(
    op: Any,
    gp: Any,
    out_dir: str | Path,
    stem: str,
    width_in: float = 0.0,
    make_qa_preview: bool = True,
    export_pdf: bool = False,
) -> Dict[str, str]:
    """
    Export 600 DPI lossless LZW `.tif`, 300 DPI `.png`, `<=960 px` `_qa_previews/*_preview.jpg`,
    and optional native vector `.pdf` (`export_pdf=True`) via OriginPro `expGraph` (`tr.Margin:=2`).
    """
    res = ob.export_origin_publication_figures(
        op,
        gp,
        out_dir,
        stem,
        width_in=width_in,
        make_qa_preview=make_qa_preview,
    )
    if export_pdf:
        out_p = Path(out_dir).resolve()
        out_p.mkdir(parents=True, exist_ok=True)
        tgt_wh = ob._PAGE_TARGET_INCHES.get(gp.name)
        if tgt_wh is not None:
            gp.obj.Units = 0
            gp.obj.Width = float(tgt_wh[0])
            gp.obj.Height = float(tgt_wh[1])
        op.lt_exec(f'win -a "{gp.name}";')
        size_clause = f"tr1.Unit:=0 tr1.Width:={float(width_in)} " if (width_in and float(width_in) > 0.0) else ""
        pdf_p = out_p / f"{stem}.pdf"
        op.po.LT_set_str("__LASTEXP", "")
        op.lt_exec(
            f'expGraph type:=pdf filename:="{stem}" path:="{out_p}" overwrite:=replace '
            f"tr.Margin:=2 {size_clause}-sw;"
        )
        pdf_str = op.po.LT_get_str("__LASTEXP") or str(pdf_p)
        pdf_cand = Path(pdf_str)
        if not pdf_cand.exists() or pdf_cand.stat().st_size == 0:
            op.lt_exec(
                f'expGraph type:=pdf filename:="{pdf_p.name}" path:="{out_p}" overwrite:=1 tr.margin:=2;'
            )
            pdf_cand = pdf_p
        if not pdf_cand.exists() or pdf_cand.stat().st_size == 0:
            if pdf_p.exists() and pdf_p.stat().st_size > 0:
                pdf_cand = pdf_p
            else:
                raise RuntimeError(f"Origin expGraph failed to export vector PDF for '{gp.name}' -> {pdf_p}")
        res["pdf"] = str(pdf_cand.resolve())
    return res


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
    s = s.replace("\\delta", "\\g(d)").replace("δ", "\\g(d)")
    s = s.replace("\\lambda", "\\g(l)").replace("λ", "\\g(l)")
    s = s.replace("\\mu", "\\g(m)").replace("μ", "\\g(m)")
    s = s.replace("\\ddagger", "‡").replace("\\ddag", "‡")
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
    has_forest_ci = False
    forest_has_text = False

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
        if ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box"):
            n_g = len(ly.series)
            if n_g > 0:
                xs.extend([0.4, float(n_g) + 0.6])
            for s in ly.series:
                if s.y:
                    v_arr = [float(v) for v in s.y if v is not None and math.isfinite(float(v))]
                    if v_arr:
                        ys.extend(v_arr)
                        if ly.mark == "violin_box" and len(v_arr) >= 2:
                            sd_v = float(np.std(v_arr, ddof=1))
                            ys.extend([min(v_arr) - 0.35 * sd_v, max(v_arr) + 0.35 * sd_v])
            continue
        if ly.mark == "bar_dot_error":
            n_g = len(ly.categories) if ly.categories else len(ly.series)
            if n_g > 0:
                xs.extend([0.4, float(n_g) + 0.6])
            ys.append(0.0)
            for s in ly.series:
                if s.y:
                    ys.extend([float(v) for v in s.y])
                    if s.y_err:
                        ys.extend([float(yv) + float(ev) for yv, ev in zip(s.y, s.y_err)])
                        ys.extend([float(yv) - float(ev) for yv, ev in zip(s.y, s.y_err)])
                raw_pts = s.meta.get("raw_points")
                if isinstance(raw_pts, (list, tuple)):
                    for rp in raw_pts:
                        if isinstance(rp, (int, float)):
                            ys.append(float(rp))
                        elif isinstance(rp, (list, tuple)):
                            ys.extend([float(vv) for vv in rp if isinstance(vv, (int, float))])
            continue
        if ly.mark == "forest_ci":
            has_forest_ci = True
            for s in ly.series:
                if ly.show_value_labels or s.show_value_labels:
                    forest_has_text = True
                if s.x:
                    xs.extend([float(xv) for xv in s.x if isinstance(xv, (int, float))])
                for ci_k in ("ci_low", "ci_high"):
                    ci_seq = s.meta.get(ci_k)
                    if isinstance(ci_seq, (list, tuple)):
                        xs.extend([float(cv) for cv in ci_seq if isinstance(cv, (int, float))])
                k_items = len(s.y or s.x or ly.categories or [])
                if k_items > 0:
                    ys.extend([0.4, float(k_items) + 0.6])
            for g in panel.guides:
                if g.kind == "vline" and g.value is not None:
                    xs.append(float(g.value))
            continue
        if ly.mark == "energy_step":
            n_m = len(ly.categories) if ly.categories else max((len(s.y or []) for s in ly.series), default=2)
            hw_e = float(ly.style_overrides.get("plateau_half_width", 0.28))
            xs.extend([1.0 - hw_e - 0.25, float(n_m) + hw_e + 0.25])
            for s in ly.series:
                if s.y:
                    ys.extend([float(v) for v in s.y])
                for seg_key in ("connector_segments", "ts_segments"):
                    for _sx_p, sy_p in (s.meta.get(seg_key) or []):
                        ys.extend([float(vv) for vv in sy_p if isinstance(vv, (int, float))])
            continue
        if ly.mark == "km_step":
            for s in ly.series:
                if s.x:
                    xs.extend([float(xv) for xv in s.x if isinstance(xv, (int, float))])
                if s.y:
                    ys.extend([float(yv) for yv in s.y if isinstance(yv, (int, float))])
                if s.y_low:
                    ys.extend([float(yv) for yv in s.y_low if isinstance(yv, (int, float))])
                if s.y_high:
                    ys.extend([float(yv) for yv in s.y_high if isinstance(yv, (int, float))])
            ar_tbl = panel.meta.get("at_risk_table")
            if isinstance(ar_tbl, dict) and ar_tbl.get("times"):
                xs.extend([float(tv) for tv in ar_tbl["times"] if isinstance(tv, (int, float))])
            continue
        if ly.mark == "vector_quiver":
            for s in ly.series:
                xv_q = [float(v) for v in (s.x or []) if isinstance(v, (int, float))]
                yv_q = [float(v) for v in (s.y or []) if isinstance(v, (int, float))]
                xs.extend(xv_q)
                ys.extend(yv_q)
                xe_q = s.meta.get("x_end")
                ye_q = s.meta.get("y_end")
                if isinstance(xe_q, (list, tuple)) and isinstance(ye_q, (list, tuple)):
                    xs.extend([float(v) for v in xe_q if isinstance(v, (int, float))])
                    ys.extend([float(v) for v in ye_q if isinstance(v, (int, float))])
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

    # Include slope_triangle guide vertices in xs/ys so reference triangles never clip
    for g in panel.guides:
        if g.kind == "slope_triangle" and g.axis == y_axis_filter and g.x is not None and g.y is not None:
            gx1 = float(g.x)
            gx2 = float(g.x2 if g.x2 is not None else (g.x_end if g.x_end is not None else gx1))
            gy1 = float(g.y)
            xs.extend([gx1, gx2])
            ys.append(gy1)
            if g.y_end is not None:
                ys.append(float(g.y_end))
            elif g.value is not None:
                m_sl = float(g.value)
                is_lx = panel.x_axis.scale == "log10"
                is_ly = (panel.y2_axis.scale == "log10") if (y_axis_filter == "y2" and panel.y2_axis) else (panel.y1_axis.scale == "log10")
                try:
                    if is_lx and is_ly and gx1 > 0 and gx2 > 0 and gy1 > 0:
                        ys.append(gy1 * ((gx2 / gx1) ** m_sl))
                    elif (not is_lx) and is_ly and gy1 > 0:
                        ys.append(10.0 ** (math.log10(gy1) + m_sl * (gx2 - gx1)))
                    elif is_lx and (not is_ly) and gx1 > 0 and gx2 > 0:
                        ys.append(gy1 + m_sl * (math.log10(gx2) - math.log10(gx1)))
                    else:
                        ys.append(gy1 + m_sl * (gx2 - gx1))
                except Exception:
                    pass

    # Include significance bracket heights + >=12% headroom guard in ys
    sig_bracket_ys = [
        float(g.value)
        for g in panel.guides
        if g.kind == "sig_bracket" and g.axis == y_axis_filter and g.value is not None
    ]
    if sig_bracket_ys:
        max_sig_y = max(sig_bracket_ys)
        min_base_y = min(ys) if ys else 0.0
        base_span = max(max_sig_y - min(0.0, min_base_y), (max(ys) - min_base_y) if ys else 1.0, 1e-6)
        ys.append(max_sig_y + 0.14 * base_span)

    has_2d_mat = any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers)
    has_stat_any = any(ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box") for ly in panel.layers)
    if (
        panel.equal_aspect
        and not has_2d_mat
        and not has_stat_any
        and not has_forest_ci
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
                min_px, max_px = min(pos_xs), max(pos_xs)
                lx0 = 10.0 ** math.floor(math.log10(min_px) + 1e-9)
                lx1 = 10.0 ** math.ceil(math.log10(max_px) - 1e-9)
                n_dec = round(math.log10(max(lx1 / max(lx0, 1e-30), 10.0)))
                if n_dec >= 4:
                    lo_use = lx0 * 0.55 if min_px <= 1.15 * lx0 else lx0
                    hi_use = lx1 * 1.85 if max_px >= 0.85 * lx1 else lx1
                    x_bounds = (lo_use, max(lo_use * 10.0, hi_use))
                else:
                    if min_px <= 1.12 * lx0:
                        lx0 /= 10.0
                    if max_px >= 0.88 * lx1:
                        lx1 *= 10.0
                    x_bounds = (lx0, max(lx0 * 10.0, lx1))
            else:
                x_bounds = (0.1, 10.0)
        elif has_forest_ci:
            max_ci_len = 18
            for ly_f in panel.layers:
                if ly_f.mark == "forest_ci" and ly_f.series:
                    fc_l = ly_f.series[0].meta.get("formatted_ci") or []
                    if fc_l:
                        max_ci_len = max((len(str(t)) for t in fc_l), default=18)
            r_pad_frac = max(1.26, min(1.62, 0.074 * max_ci_len)) if forest_has_text else 0.10
            x_bounds = (x_lo - 0.10 * x_sp, x_hi + r_pad_frac * x_sp)
        elif not has_2d_mat and not panel.equal_aspect:
            x_pad_lo = 0.0 if (x_lo == 0.0 and x_hi > 0.0) else 0.05 * x_sp
            x_lo_cand = x_lo - x_pad_lo
            linked_top_cfg = getattr(panel.x_axis, "linked_top", None)
            if isinstance(linked_top_cfg, dict) and "/" in str(linked_top_cfg.get("formula", "")) and x_lo > 0.0:
                x_lo_cand = max(x_lo * 0.94, x_lo_cand, 1e-6)
            x_bounds = (x_lo_cand, x_hi + 0.05 * x_sp)
        else:
            x_bounds = (x_lo, x_hi)
    else:
        x_bounds = (0.0, 1.0)

    target_ax = panel.y2_axis if (y_axis_filter == "y2" and panel.y2_axis is not None) else panel.y1_axis
    has_stat_y = any(ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box") for ly in panel.layers if ly.y_axis == y_axis_filter)
    has_km_y = any(ly.mark == "km_step" for ly in panel.layers if ly.y_axis == y_axis_filter)
    if target_ax.limits is not None and not reserve_top_legend_space:
        y_bounds = (float(min(target_ax.limits)), float(max(target_ax.limits)))
    elif has_km_y:
        y_top_km = 105.0 if (ys and max(ys) > 1.5) else 1.05
        y_bounds = (0.0, y_top_km)
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
            y_bounds = (y_lo - 0.10 * span, y_hi + (0.28 if reserve_top_legend_space else 0.14) * span)
        elif reserve_top_legend_space and (y_lo >= 0.0 or panel.align_zero):
            y_bounds = (0.0, y_hi * 1.32)
        elif y_lo >= 0.0 and any("bar" in ly.mark for ly in panel.layers if ly.y_axis == y_axis_filter):
            has_lbl = any(
                (ly.show_value_labels or any(s.show_value_labels for s in ly.series))
                for ly in panel.layers
                if ly.y_axis == y_axis_filter
            )
            pad = 1.30 if has_lbl else (1.08 if sig_bracket_ys else 1.18)
            y_bounds = (0.0, y_hi * pad)
        elif panel.align_zero and y_lo >= 0.0:
            raw_top = y_hi * 1.22
            step_snap = 10.0 if raw_top >= 25.0 else (5.0 if raw_top >= 10.0 else 1.0)
            y_bounds = (0.0, math.ceil(raw_top / step_snap) * step_snap)
        else:
            y_bounds = (y_lo - 0.07 * span, y_hi + (0.32 if reserve_top_legend_space else 0.18) * span)
    else:
        y_bounds = (0.0, 1.0)

    # Hard post-guard: ensure highest sig_bracket + star always has >=15% headroom (or >=26% with interior top legend)
    if sig_bracket_ys and target_ax.limits is None and target_ax.scale != "log10":
        max_sig_y = max(sig_bracket_ys)
        cur_span = max(max_sig_y - y_bounds[0], y_bounds[1] - y_bounds[0], 1e-6)
        req_top = max_sig_y + (0.26 if reserve_top_legend_space else 0.15) * cur_span
        if y_bounds[1] < req_top:
            y_bounds = (y_bounds[0], req_top)

    return x_bounds, y_bounds


def _resolve_clean_origin_template(panel_layers: Sequence[cg.LayerSpec]) -> Optional[str]:
    """Use `STACKCOLUMN` instead of `StackColP` when built-in clutter labels/ribbon links are disabled."""
    for ly in panel_layers:
        if ly.mark in ("bar_stacked", "bar_stacked_100pct"):
            if ly.mark == "bar_stacked_100pct" and (ly.show_value_labels or ly.show_ribbon_links):
                return "StackColP"
            return "STACKCOLUMN"
        if ly.mark == "violin_box":
            return "ViolinBox"
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
    explicit_corner: Optional[str] = None
    if "lower_left" in style or "bottom_left" in style:
        explicit_corner = "corner_lower_left"
    elif "lower_right" in style or "bottom_right" in style:
        explicit_corner = "corner_lower_right"
    elif "right" in style:
        explicit_corner = "corner_upper_right"
    elif "upper_left" in style or "top_left" in style:
        explicit_corner = "corner_upper_left"

    x_lo, x_hi = min(x_bounds), max(x_bounds)
    y_lo, y_hi = min(y_bounds), max(y_bounds)
    inv_x = bool(panel.x_axis.invert)
    inv_y = bool(panel.y1_axis.invert)
    is_log_x = panel.x_axis.scale == "log10"
    is_log_y = panel.y1_axis.scale == "log10"

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
                fx = ob._map_data_to_frac(float(xv), x_lo, x_hi, inv_x, is_log_x)
                fy_raw = ob._map_data_to_frac(float(yv), y_lo, y_hi, False, is_log_y)
                fy = (1.0 - fy_raw) if inv_y else fy_raw
                for cname, (bx0, bx1, by0, by1) in boxes.items():
                    if bx0 <= fx <= bx1 and by0 <= fy <= by1:
                        scores[cname] += 1.0

    for g in panel.guides:
        if g.kind == "hline" and g.value is not None:
            fy_raw = ob._map_data_to_frac(float(g.value), y_lo, y_hi, False, is_log_y)
            fy = (1.0 - fy_raw) if inv_y else fy_raw
            for cname, (_bx0, _bx1, by0, by1) in boxes.items():
                if by0 <= fy <= by1:
                    scores[cname] += 6.0 if "right" in cname else 2.0

    best_corner = min(scores.keys(), key=lambda k: scores[k])
    if explicit_corner is not None:
        # Honor explicit corner unless it is heavily collided (>= 5 hits) while another corner is nearly empty (< 1.0)
        if scores[explicit_corner] >= 5.0 and scores[best_corner] < 1.0:
            return best_corner
        return explicit_corner
    return best_corner


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

    # 3b. Bar + Individual Replicate Dots + Error Bars (`bar_dot_error`)
    if layer.mark == "bar_dot_error":
        grp_records: List[Dict[str, Any]] = []
        if len(layer.series) == 1 and len(layer.series[0].y or []) > 1:
            s0 = layer.series[0]
            y_vs = list(s0.y or [])
            N_b = len(y_vs)
            cats_b = list(layer.categories or [str(v) for v in (s0.x or [f"G{i+1}" for i in range(N_b)])])
            errs_b = list(s0.y_err) if s0.y_err is not None else [0.0] * N_b
            raw_seq = s0.meta.get("raw_points") or []
            pal_b = layer.palette_colors or ot.resolve_series_colors(N_b, scheme=layer.color_scheme)
            for i in range(N_b):
                rp_i = raw_seq[i] if (i < len(raw_seq) and isinstance(raw_seq[i], (list, tuple))) else []
                grp_records.append(
                    {
                        "name": str(cats_b[i]),
                        "mean": float(y_vs[i]),
                        "err": float(errs_b[i]) if i < len(errs_b) else 0.0,
                        "color": ot.normalize_hex(pal_b[i % len(pal_b)]),
                        "raw_points": [float(v) for v in rp_i if isinstance(v, (int, float))],
                        "y_unit": s0.y_unit,
                        "value_format": s0.value_format,
                    }
                )
        else:
            N_b = len(layer.series)
            pal_b = layer.palette_colors or ot.resolve_series_colors(max(1, N_b), scheme=layer.color_scheme)
            for i, s in enumerate(layer.series):
                yv0 = float(s.y[0]) if s.y else 0.0
                ev0 = float(s.y_err[0]) if s.y_err else 0.0
                rp_i = s.meta.get("raw_points") or []
                grp_records.append(
                    {
                        "name": str(s.name or (layer.categories[i] if layer.categories and i < len(layer.categories) else f"G{i+1}")),
                        "mean": yv0,
                        "err": ev0,
                        "color": ot.normalize_hex(s.color or pal_b[i % len(pal_b)]),
                        "raw_points": [float(v) for v in rp_i if isinstance(v, (int, float))],
                        "y_unit": s.y_unit,
                        "value_format": s.value_format,
                    }
                )

        N_g = len(grp_records)
        cats_bd = [g["name"] for g in grp_records]
        diag_bd: Dict[str, Any] = {"Category": cats_bd}
        for i, gr in enumerate(grp_records):
            diag_bd[f"Bar_{i+1}"] = [gr["mean"] if r == i else np.nan for r in range(N_g)]
            diag_bd[f"Err_{i+1}"] = [gr["err"] if r == i else np.nan for r in range(N_g)]
        wks.from_df(pd.DataFrame(diag_bd))
        wks.set_label(0, panel.x_axis.label or "Group", "L")
        for i, gr in enumerate(grp_records):
            wks.set_label(1 + 2 * i, gr["name"], "L")
            if gr["y_unit"]:
                wks.set_label(1 + 2 * i, str(gr["y_unit"]), "U")
        wks.cols_axis("X" + "YE" * N_g)

        has_any_dots = any(bool(gr["raw_points"]) for gr in grp_records)
        has_sig_brk = any(g.kind == "sig_bracket" for g in panel.guides)
        # Never show bar-top numeric labels when replicate dots or significance brackets are overlaid!
        allow_bar_lbl = bool(layer.show_value_labels) and not has_any_dots and not has_sig_brk
        opt_gap_bd = 50 if N_g <= 2 else (38 if N_g == 3 else (28 if N_g == 4 else 24))
        err_ink = ot.hex_to_origin_rgb_int("#222222")

        for i, gr in enumerate(grp_records):
            has_err_i = abs(gr["err"]) > 0.0
            before_cnt = len(gl.plot_list())
            p_bar = gl.add_plot(
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

            pb = ot.compute_pastel_fill_and_border(gr["color"])
            c_fill = ot.hex_to_origin_rgb_int(pb["fill_hex"])
            c_bdr = ot.hex_to_origin_rgb_int(pb["border_hex"])
            c_lbl = ot.hex_to_origin_rgb_int(pb["label_hex"]) if allow_bar_lbl else None
            apply_origin_bar_gradient_and_label(
                p_bar,
                c_fill,
                None,
                shading_mode=0,
                gap=opt_gap_bd,
                border_color=c_bdr,
                border_width=bdr_lw,
                label_color=c_lbl,
                label_size=comp_val_pt,
                label_fmt=_python_fmt_to_origin_fmt(gr["value_format"]),
                has_yerr=has_err_i,
                gl=gl,
                plot_idx_1based=bar_p_idx,
                tnr_face_dword=tnr_dword,
            )

        if has_any_dots:
            dot_sh = ob.unique_origin_short_name(f"RepDotsL{layer_num_1based}", used_sheets, default="RepDots")
            wks_dt = wb.add_sheet(dot_sh)
            dot_cols: List[Tuple[str, str, List[float]]] = []
            dot_meta: List[Tuple[int, str]] = []
            jit_w = min(0.13, float(layer.style_overrides.get("jitter_width", 0.13)))
            for i, gr in enumerate(grp_records):
                rpts = gr["raw_points"]
                if not rpts:
                    continue
                vals_s = sorted(float(v) for v in rpts)
                n_v = len(vals_s)
                xc = float(i + 1)
                if n_v == 1:
                    jx = [xc]
                else:
                    # Symmetric deterministic golden-angle offsets within ±jit_w (shifted slightly off x=xc center stem)
                    jx = [
                        xc + jit_w * math.sin(2.39996323 * (rk + 1) + 0.72 * i + 0.35)
                        for rk in range(n_v)
                    ]
                b_col = len(dot_cols)
                dot_cols.append(("X", f"D{i+1}_X", jx))
                dot_cols.append(("Y", f"D{i+1}_Y", vals_s))
                dot_meta.append((b_col, gr["color"]))

            if dot_cols:
                wks_dt.cols = len(dot_cols)
                for ci, (ax_r, c_nm, c_vs) in enumerate(dot_cols):
                    wks_dt.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
                wks_dt.cols_axis("".join(c[0] for c in dot_cols))
                ob.activate_layer(op, gp, layer_num_1based)
                dot_sz = max(5.8, float(spec["marker_size_pt"]) * 0.88)
                for b_col, c_hex in dot_meta:
                    pb_d = ot.compute_pastel_fill_and_border(c_hex)
                    bdr_oc = ob._hex_to_origin_color(op, pb_d["border_hex"])
                    p_d = gl.add_plot(wks_dt, coly=b_col + 1, colx=b_col, type="s")
                    p_d.color = bdr_oc
                    p_d.symbol_size = dot_sz
                    p_d.symbol_kind = 2
                    p_d.symbol_interior = 1  # White-filled 2D circle with crisp group-colored border

        gl.lt_exec("label -r Legend;")
        return []

    # 3c. Native OriginPro 2024 Violin + Quartile Box Distribution (`violin_box`)
    if layer.mark == "violin_box":
        K = len(layer.series)
        wks.cols = max(1, K)
        for idx, s in enumerate(layer.series):
            grp_lbl = str(s.meta.get("label") or s.name)
            wks.from_list(idx, [float(v) for v in (s.y or []) if v is not None], lname=grp_lbl, axis="Y")
        wks.cols_axis("Y" * max(1, K))

        dr = op.make_DataRange()
        for idx in range(K):
            dr.Add("Y", wks.obj, 0, idx, -1, idx)
        ob.activate_layer(op, gp, layer_num_1based)
        gl.add_plot(dr, type=206)
        gl.group(False)
        gl.rescale()

        fb_pal = ot.resolve_series_colors(max(1, K), scheme=(layer.color_scheme or "okabe_ito"))
        distinct_v = {ot.normalize_hex(s.color) for s in layer.series if s.color}
        use_fb_v = K > 1 and len(distinct_v) <= 1
        w_int = ot.hex_to_origin_rgb_int("#FFFFFF")

        for i, s in enumerate(layer.series):
            c_hex = fb_pal[i % len(fb_pal)] if use_fb_v else ot.normalize_hex(s.color or fb_pal[i % len(fb_pal)])
            pb = ot.compute_pastel_fill_and_border(c_hex)
            fi = ot.hex_to_origin_rgb_int(pb["fill_hex"])
            bi = ot.hex_to_origin_rgb_int(pb["border_hex"])
            gl.lt_exec(
                f"range rv = !{i + 1}; "
                f"set rv -pf 1; set rv -pfb {w_int}; set rv -pbc {bi}; set rv -pbw {bdr_lw}; "
                f"set rv -p2f 1; set rv -p2fb {fi}; set rv -p2fc {fi}; set rv -p2bc {bi}; set rv -p2bw {bdr_lw}; "
                f"set rv -c {bi};"
            )
            grp_lbl = str(s.meta.get("label") or s.name)
            leg_entries.append((i + 1, grp_lbl, pb["border_hex"], "bar"))

        gl.lt_exec("label -r Legend;")
        return leg_entries

    # 3d. Horizontal Forest / Ablation Plot (`forest_ci`)
    if layer.mark == "forest_ci" and layer.series:
        s0 = layer.series[0]
        ests = [float(v) for v in (s0.x or [])]
        K_f = len(ests)
        y_pos = [float(v) for v in (s0.y or [float(i + 1) for i in range(K_f)])]
        ci_lo = [float(v) for v in (s0.meta.get("ci_low") or ests)]
        ci_hi = [float(v) for v in (s0.meta.get("ci_high") or ests)]
        it_cols = list(s0.meta.get("item_colors") or layer.palette_colors or ot.resolve_series_colors(max(1, K_f), scheme=layer.color_scheme))

        f_cols: List[Tuple[str, str, List[float]]] = []
        f_meta: List[Tuple[int, str]] = []
        cap_dy = 0.10
        for i in range(K_f):
            yi = y_pos[i]
            est_i = ests[i]
            lo_i = ci_lo[i] if i < len(ci_lo) else est_i
            hi_i = ci_hi[i] if i < len(ci_hi) else est_i
            c_hex = ot.normalize_hex(it_cols[i % len(it_cols)])
            b0 = len(f_cols)
            # 0,1: horizontal CI bar; 2,3: left end-cap; 4,5: right end-cap; 6,7: center point estimate
            f_cols.append(("X", f"F{i+1}_BarX", [lo_i, hi_i]))
            f_cols.append(("Y", f"F{i+1}_BarY", [yi, yi]))
            f_cols.append(("X", f"F{i+1}_CLoX", [lo_i, lo_i]))
            f_cols.append(("Y", f"F{i+1}_CLoY", [yi - cap_dy, yi + cap_dy]))
            f_cols.append(("X", f"F{i+1}_CHiX", [hi_i, hi_i]))
            f_cols.append(("Y", f"F{i+1}_CHiY", [yi - cap_dy, yi + cap_dy]))
            f_cols.append(("X", f"F{i+1}_PtX", [est_i]))
            f_cols.append(("Y", f"F{i+1}_PtY", [yi]))
            f_meta.append((b0, c_hex))

        wks.cols = max(2, len(f_cols))
        for ci, (ax_r, c_nm, c_vs) in enumerate(f_cols):
            wks.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
        wks.cols_axis("".join(c[0] for c in f_cols))

        ob.activate_layer(op, gp, layer_num_1based)
        cw_u = int(spec["curve_w_units"])
        mk_sz_f = float(s0.marker_size_pt or spec["marker_size_pt"]) * 1.15
        for b0, c_hex in f_meta:
            c_oc = ob._hex_to_origin_color(op, c_hex)
            p_bar = gl.add_plot(wks, coly=b0 + 1, colx=b0, type="l")
            p_bar.color = c_oc
            gl.lt_exec(f"range rf = !{len(gl.plot_list())}; set rf -w {cw_u};")

            for cx_c, cy_c in ((b0 + 2, b0 + 3), (b0 + 4, b0 + 5)):
                p_cap = gl.add_plot(wks, coly=cy_c, colx=cx_c, type="l")
                p_cap.color = c_oc
                gl.lt_exec(f"range rc = !{len(gl.plot_list())}; set rc -w {sub_w_u};")

            p_pt = gl.add_plot(wks, coly=b0 + 7, colx=b0 + 6, type="s")
            p_pt.color = c_oc
            p_pt.symbol_kind = 2
            p_pt.symbol_interior = 0
            p_pt.symbol_size = mk_sz_f

        gl.lt_exec("label -r Legend;")
        return []

    # 3e. Reaction Free-Energy Step Profile (`energy_step`) + Optional `TS‡` Spline Saddle Barriers
    if layer.mark == "energy_step" and layer.series:
        hw_e = float(layer.style_overrides.get("plateau_half_width", 0.28))
        cw_plat = int(round(1.35 * float(spec["curve_w_units"])))
        cw_conn = max(750, int(spec["sub_w_units"]))
        e_cols: List[Tuple[str, str, List[float]]] = []
        # (name, c_hex, conn_cols_idx_with_is_spline, plat_cols_idx, skip_leg)
        pw_draw_plan: List[Tuple[str, str, List[Tuple[int, int, bool]], List[Tuple[int, int]], bool]] = []

        fb_pw = ot.resolve_series_colors(max(1, len(layer.series)), scheme=layer.color_scheme)
        for p_i, s in enumerate(layer.series):
            c_hex = ot.normalize_hex(s.color or fb_pw[p_i % len(fb_pw)])
            skip_leg_s = bool(s.meta.get("skip_legend", False))
            if str(s.meta.get("line_connect", "")).strip().lower() in ("spline", "bspline") and not s.meta.get("plateau_segments"):
                sx_sp = [float(v) for v in (s.x or [])]
                sy_sp = [float(v) for v in (s.y or [])]
                if len(sx_sp) >= 2 and len(sx_sp) == len(sy_sp):
                    cx_i = len(e_cols)
                    e_cols.append(("X", f"TS{p_i+1}_X", sx_sp))
                    e_cols.append(("Y", f"TS{p_i+1}_Y", sy_sp))
                    pw_draw_plan.append((s.name, c_hex, [(cx_i, cx_i + 1, True)], [], True))
                continue

            steps_v = [float(v) for v in (s.y or s.meta.get("steps") or [])]
            if len(steps_v) < 2:
                continue
            hw_s = float(s.meta.get("plateau_half_width", hw_e))
            plat_segs = s.meta.get("plateau_segments") or [
                ([float(k + 1) - hw_s, float(k + 1) + hw_s], [g_v, g_v]) for k, g_v in enumerate(steps_v)
            ]
            conn_segs = s.meta.get("connector_segments") or [
                ([float(k + 1) + hw_s, float(k + 2) - hw_s], [steps_v[k], steps_v[k + 1]])
                for k in range(len(steps_v) - 1)
            ]
            ts_segs = s.meta.get("ts_segments") or []
            plat_cols_idx: List[Tuple[int, int]] = []
            conn_cols_idx: List[Tuple[int, int, bool]] = []
            for k_s, (sx_pair, sy_pair) in enumerate(conn_segs):
                sx_l = [float(v) for v in sx_pair]
                sy_l = [float(v) for v in sy_pair]
                is_sp_seg = len(sx_l) >= 3
                cx_i = len(e_cols)
                e_cols.append(("X", f"PW{p_i+1}_CX{k_s+1}", sx_l))
                e_cols.append(("Y", f"PW{p_i+1}_CY{k_s+1}", sy_l))
                conn_cols_idx.append((cx_i, cx_i + 1, is_sp_seg))
            for k_t, (tsx_pair, tsy_pair) in enumerate(ts_segs):
                cx_i = len(e_cols)
                e_cols.append(("X", f"PW{p_i+1}_TSX{k_t+1}", [float(v) for v in tsx_pair]))
                e_cols.append(("Y", f"PW{p_i+1}_TSY{k_t+1}", [float(v) for v in tsy_pair]))
                conn_cols_idx.append((cx_i, cx_i + 1, True))
            for k_p, (px_pair, py_pair) in enumerate(plat_segs):
                px_i = len(e_cols)
                e_cols.append(("X", f"PW{p_i+1}_PX{k_p+1}", [float(px_pair[0]), float(px_pair[1])]))
                e_cols.append(("Y", f"PW{p_i+1}_PY{k_p+1}", [float(py_pair[0]), float(py_pair[1])]))
                plat_cols_idx.append((px_i, px_i + 1))
            pw_draw_plan.append((s.name, c_hex, conn_cols_idx, plat_cols_idx, skip_leg_s))

        wks.cols = max(2, len(e_cols))
        for ci, (ax_r, c_nm, c_vs) in enumerate(e_cols):
            wks.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
        wks.cols_axis("".join(c[0] for c in e_cols))

        ob.activate_layer(op, gp, layer_num_1based)
        # Draw dashed connectors & TS spline saddles first so thick horizontal plateaus sit cleanly on top of joints!
        for _nm, c_hex, conn_list, _plat_list, _sk_l in pw_draw_plan:
            c_oc = ob._hex_to_origin_color(op, c_hex)
            for cx_i, cy_i, is_sp_seg in conn_list:
                p_c = gl.add_plot(wks, coly=cy_i, colx=cx_i, type="l")
                p_c.color = c_oc
                cur_c_idx = len(gl.plot_list())
                if is_sp_seg:
                    gl.lt_exec(f"range rcn = !{cur_c_idx}; set rcn -l 9; set rcn -w {cw_conn}; set rcn -d 0;")
                else:
                    gl.lt_exec(f"range rcn = !{cur_c_idx}; set rcn -w {cw_conn}; set rcn -d 1;")

        for nm, c_hex, _conn_list, plat_list, sk_l in pw_draw_plan:
            if not plat_list:
                continue
            c_oc = ob._hex_to_origin_color(op, c_hex)
            first_plat_plot_idx: Optional[int] = None
            for px_i, py_i in plat_list:
                p_p = gl.add_plot(wks, coly=py_i, colx=px_i, type="l")
                p_p.color = c_oc
                cur_p_idx = len(gl.plot_list())
                if first_plat_plot_idx is None:
                    first_plat_plot_idx = cur_p_idx
                gl.lt_exec(f"range rpl = !{cur_p_idx}; set rpl -w {cw_plat}; set rpl -d 0;")
            if first_plat_plot_idx is not None and not sk_l:
                leg_entries.append((first_plat_plot_idx, nm, c_hex, "line"))

        gl.lt_exec("label -r Legend;")
        return leg_entries

    # 3f. Kaplan-Meier Survival Step Curve + Greenwood 95% CI + Vertical Censor Ticks (`km_step`)
    if layer.mark == "km_step" and layer.series:
        km_cols: List[Tuple[str, str, List[float]]] = []
        km_plan: List[Dict[str, Any]] = []
        fb_km = ot.resolve_series_colors(max(1, len(layer.series)), scheme=layer.color_scheme)

        for a_i, s in enumerate(layer.series):
            xv_k = [float(v) for v in (s.x or [])]
            yv_k = [float(v) for v in (s.y or [])]
            if not xv_k or len(xv_k) != len(yv_k):
                continue
            c_hex = ot.normalize_hex(s.color or fb_km[a_i % len(fb_km)])
            plan_it: Dict[str, Any] = {
                "name": s.name,
                "c_hex": c_hex,
                "line_style": s.line_style,
                "line_width_pt": s.line_width_pt,
                "skip_legend": bool(s.meta.get("skip_legend", False)),
                "col_x": len(km_cols),
                "col_y": len(km_cols) + 1,
                "col_lo": None,
                "col_hi": None,
                "col_cx": None,
                "col_cy": None,
            }
            km_cols.append(("X", f"Arm{a_i+1}_Time", xv_k))
            km_cols.append(("Y", s.name, yv_k))
            if s.y_low is not None and s.y_high is not None and len(s.y_low) == len(xv_k) and len(s.y_high) == len(xv_k):
                plan_it["col_lo"] = len(km_cols)
                km_cols.append(("Y", f"Arm{a_i+1}_CILow", [float(v) for v in s.y_low]))
                plan_it["col_hi"] = len(km_cols)
                km_cols.append(("Y", f"Arm{a_i+1}_CIHigh", [float(v) for v in s.y_high]))
            cx_raw = s.meta.get("censored_x") if s.meta.get("censored_x") is not None else s.meta.get("censored_time")
            cy_raw = s.meta.get("censored_y") if s.meta.get("censored_y") is not None else s.meta.get("censored_surv")
            if cx_raw and cy_raw and len(cx_raw) == len(cy_raw):
                plan_it["col_cx"] = len(km_cols)
                km_cols.append(("X", f"Arm{a_i+1}_CensT", [float(v) for v in cx_raw]))
                plan_it["col_cy"] = len(km_cols)
                km_cols.append(("Y", f"Arm{a_i+1}_CensS", [float(v) for v in cy_raw]))
            km_plan.append(plan_it)

        wks.cols = max(2, len(km_cols))
        for ci, (ax_r, c_nm, c_vs) in enumerate(km_cols):
            wks.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
        wks.cols_axis("".join(c[0] for c in km_cols))

        ob.activate_layer(op, gp, layer_num_1based)
        cw_main = int(spec["curve_w_units"])
        cens_sz = 8.5 if float(spec["page_rect_w_in"]) >= 6.0 else max(3.8, float(spec["marker_size_pt"]) * 1.15)

        # Pass 1: Step-Horz shaded 95% CI bands (`set rr -l 11`, `type=9`, `transparency=78`)
        for pit in km_plan:
            if pit["col_lo"] is not None and pit["col_hi"] is not None:
                c_oc = ob._hex_to_origin_color(op, pit["c_hex"])
                p_lo = gl.add_plot(wks, coly=int(pit["col_lo"]), colx=int(pit["col_x"]), type=200)
                lo_idx = len(gl.plot_list())
                p_hi = gl.add_plot(wks, coly=int(pit["col_hi"]), colx=int(pit["col_x"]), type=200)
                hi_idx = len(gl.plot_list())
                p_lo.color = c_oc
                p_hi.color = c_oc
                p_lo.set_fill_area(above=c_oc, type=9, below=c_oc)
                p_lo.transparency = 78
                p_hi.transparency = 100
                gl.lt_exec(
                    f"range rlo = !{lo_idx}; set rlo -l 11; set rlo -w 50; "
                    f"range rhi = !{hi_idx}; set rhi -l 11; set rhi -w 50;"
                )

        # Pass 2: Main survival Step-Horz curves + crisp `-k 10` vertical bar (`|`) censor ticks
        for pit in km_plan:
            c_oc = ob._hex_to_origin_color(op, pit["c_hex"])
            p_m = gl.add_plot(wks, coly=int(pit["col_y"]), colx=int(pit["col_x"]), type=200)
            m_idx = len(gl.plot_list())
            p_m.color = c_oc
            d_c = _line_style_code(pit["line_style"])
            gl.lt_exec(f"range rm = !{m_idx}; set rm -l 11; set rm -w {cw_main}; set rm -d {d_c};")
            if pit["col_cx"] is not None and pit["col_cy"] is not None:
                p_cs = gl.add_plot(wks, coly=int(pit["col_cy"]), colx=int(pit["col_cx"]), type=201)
                cs_idx = len(gl.plot_list())
                p_cs.color = c_oc
                cw_cens = int(max(600, cw_main * 0.65))
                gl.lt_exec(f"range rc = !{cs_idx}; set rc -k 10; set rc -z {cens_sz}; set rc -w {cw_cens};")
            if not pit["skip_legend"]:
                leg_entries.append((m_idx, pit["name"], pit["c_hex"], "line_dashed" if d_c == 1 else "line"))

        gl.lt_exec("label -r Legend;")
        return leg_entries

    # 3g. 2D Vector / Quiver Field (`vector_quiver`: NaN-separated 2-col native vector shafts + 26° V-arrowheads)
    if layer.mark == "vector_quiver" and layer.series:
        has_bg_contour = any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers)
        box_w_q = float(spec["box_sq_side_in"] if (has_bg_contour or panel.equal_aspect) else spec["box_rect_w_in"])
        box_h_q = float(spec["box_sq_side_in"] if (has_bg_contour or panel.equal_aspect) else spec["box_rect_h_in"])
        cos26 = math.cos(math.radians(26.0))
        sin26 = math.sin(math.radians(26.0))

        for v_i, s in enumerate(layer.series):
            xv_q = [float(v) for v in (s.x or [])]
            yv_q = [float(v) for v in (s.y or [])]
            if not xv_q or len(xv_q) != len(yv_q):
                continue
            xe_raw = s.meta.get("x_end")
            ye_raw = s.meta.get("y_end")
            if xe_raw is not None and ye_raw is not None and len(xe_raw) == len(xv_q) and len(ye_raw) == len(yv_q):
                x2_q = [float(v) for v in xe_raw]
                y2_q = [float(v) for v in ye_raw]
            else:
                u_q = [float(v) for v in (s.meta.get("u") or [0.0] * len(xv_q))]
                v_q = [float(v) for v in (s.meta.get("v") or [0.0] * len(yv_q))]
                ux = sorted(set(round(v, 8) for v in xv_q))
                uy = sorted(set(round(v, 8) for v in yv_q))
                dx_g = min((ux[k + 1] - ux[k] for k in range(len(ux) - 1)), default=max(max(xv_q) - min(xv_q), 1.0) / 10.0)
                dy_g = min((uy[k + 1] - uy[k] for k in range(len(uy) - 1)), default=max(max(yv_q) - min(yv_q), 1.0) / 10.0)
                mags = [math.hypot(uu, vv) for uu, vv in zip(u_q, v_q)]
                p95_m = float(np.percentile(mags, 95.0)) if mags else 1.0
                v_scale = float(s.meta.get("arrow_scale") or (0.78 * min(dx_g, dy_g) / max(p95_m, 1e-9)))
                x2_q = [xx + v_scale * uu for xx, uu in zip(xv_q, u_q)]
                y2_q = [yy + v_scale * vv for yy, vv in zip(yv_q, v_q)]

            x_sp_q = (
                abs(float(panel.x_axis.limits[1]) - float(panel.x_axis.limits[0]))
                if panel.x_axis.limits is not None
                else max(max(xv_q + x2_q) - min(xv_q + x2_q), 1e-6)
            )
            y_sp_q = (
                abs(float(panel.y1_axis.limits[1]) - float(panel.y1_axis.limits[0]))
                if panel.y1_axis.limits is not None
                else max(max(yv_q + y2_q) - min(yv_q + y2_q), 1e-6)
            )
            x_sp_q = max(x_sp_q, 1e-6)
            y_sp_q = max(y_sp_q, 1e-6)

            nan_v = float("nan")
            seg_x: List[float] = []
            seg_y: List[float] = []
            w_scale_ref = box_w_q / 4.80
            for x1_i, y1_i, x2_i, y2_i in zip(xv_q, yv_q, x2_q, y2_q):
                ux_in = ((x2_i - x1_i) / x_sp_q) * box_w_q
                uy_in = ((y2_i - y1_i) / y_sp_q) * box_h_q
                len_in = math.hypot(ux_in, uy_in)
                if len_in <= 1e-7:
                    continue
                ex, ey = ux_in / len_in, uy_in / len_in
                wing_in = min(0.105 * w_scale_ref, max(0.024 * w_scale_ref, 0.30 * len_in))
                bx_in, by_in = -ex, -ey
                lx_in = wing_in * (bx_in * cos26 - by_in * sin26)
                ly_in = wing_in * (bx_in * sin26 + by_in * cos26)
                rx_in = wing_in * (bx_in * cos26 + by_in * sin26)
                ry_in = wing_in * (-bx_in * sin26 + by_in * cos26)
                xh_l = x2_i + (lx_in / max(box_w_q, 1e-6)) * x_sp_q
                yh_l = y2_i + (ly_in / max(box_h_q, 1e-6)) * y_sp_q
                xh_r = x2_i + (rx_in / max(box_w_q, 1e-6)) * x_sp_q
                yh_r = y2_i + (ry_in / max(box_h_q, 1e-6)) * y_sp_q
                seg_x.extend([x1_i, x2_i, xh_l, nan_v, x2_i, xh_r, nan_v])
                seg_y.extend([y1_i, y2_i, yh_l, nan_v, y2_i, yh_r, nan_v])

            if not seg_x:
                continue
            if v_i == 0:
                wks_v = wks
            else:
                vq_sh = ob.unique_origin_short_name(f"Vec{v_i+1}", used_sheets, default="Vec")
                wks_v = wb.add_sheet(vq_sh)
            wks_v.cols = 2
            wks_v.from_list(0, seg_x, lname="Vec_X", axis="X")
            wks_v.from_list(1, seg_y, lname=s.name or "Vec_Y", axis="Y")
            wks_v.cols_axis("XY")

            ob.activate_layer(op, gp, layer_num_1based)
            vec_hex = ot.normalize_hex(s.color or ("#111111" if has_bg_contour else "#1E293B"))
            vec_int = ot.hex_to_origin_rgb_int(vec_hex)
            vec_w = max(480, int(round(0.88 * float(spec["sub_w_units"]))))
            p_vq = gl.add_plot(wks_v, coly=1, colx=0, type="l")
            p_vq.color = ob._hex_to_origin_color(op, vec_hex)
            vq_idx = len(gl.plot_list())
            gl.lt_exec(f"range rv = !{vq_idx}; set rv -c {vec_int}; set rv -w {vec_w}; set rv -d 0; label -r Legend;")
            if not s.meta.get("skip_legend") and not has_bg_contour and len(layer.series) > 1:
                leg_entries.append((vq_idx, s.name, vec_hex, "line"))
        return leg_entries

    # 4. Line / Scatter / Step-Line / Shaded Band / Waterfall (`line_scatter`, `scatter`, `step_line`, `waterfall`, `deconv_envelope`)
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

        line_conn = str(s.meta.get("line_connect") or s.meta.get("connect") or "").strip().lower()
        is_step_mark = layer.mark == "step_line" or line_conn in ("step", "step_horz")
        is_spline_conn = line_conn in ("spline", "bspline")

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
            step_band_cmd = "set rup -l 11; set rlo -l 11; " if is_step_mark else ""
            gl.lt_exec(f"range rup = !{up_idx}; range rlo = !{lo_idx}; {step_band_cmd}set rup -w 50; set rlo -w 50;")

        m_shape, m_int = _marker_cmd_and_interior(s.marker_style)
        is_scatter_mark = layer.mark == "scatter"
        has_line = (not is_scatter_mark) and (
            is_step_mark or is_spline_conn or str(s.line_style or "solid").strip().lower() not in ("none", "", "false")
        )
        if is_scatter_mark and m_shape is None:
            m_shape, m_int = 2, 1
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
            if is_step_mark:
                cmd_parts.append("set rm -l 11;")
            elif is_spline_conn:
                cmd_parts.append("set rm -l 9;")
            cmd_parts.append(f"set rm -w {w_units}; set rm -d {d_code};")
        if has_marker and m_shape == 20:
            cmd_parts.append("set rm -k 20;")
        if c_map["up"] is None and s.fill_alpha is not None and s.fill_alpha > 0 and has_line:
            p_main.set_fill_area(above=c_color, type=1, below=c_color)
            p_main.transparency = int(round((1.0 - float(s.fill_alpha)) * 100.0))

        # High-density scatter transparency (`volcano_plot` or >=150 points without connecting line)
        n_data_pts = len(s.y or [])
        is_dense_scatter = (not has_line) and has_marker and (n_data_pts >= 150 or s.meta.get("alpha_pct") is not None)
        if is_dense_scatter:
            alpha_t = int(s.meta.get("alpha_pct", 35))
            p_main.transparency = alpha_t
            cmd_parts.append(f"set rm -t {alpha_t};")

        if cmd_parts:
            gl.lt_exec(f"range rm = !{main_idx}; " + " ".join(cmd_parts))

        if has_marker and m_shape is not None and m_shape != 20:
            if is_dense_scatter and s.marker_size_pt is None:
                eff_mk_sz = 4.8 if "ns" in str(s.name).lower() else 6.5
            else:
                eff_mk_sz = float(s.marker_size_pt or spec["marker_size_pt"])
            p_main.symbol_size = eff_mk_sz
            # Python symbol_kind matches LabTalk shape code (1=sq, 2=circle, 3=up-tri, 4=down-tri, 5=diamond)
            p_main.symbol_kind = int(m_shape)
            # Python symbol_interior: 0 = Solid filled, 1 = Open white-filled (m_int is 1 for solid, 2 for open)
            p_main.symbol_interior = 1 if int(m_int) == 2 else 0

        if after_cnt >= before_cnt + 2:
            gl.lt_exec(f"range re = !{after_cnt}; set re -w {sub_w_u}; set re -c {err_ink};")

        if has_line and has_marker:
            sw_kind = "open_circle" if m_int == 2 else "line_sphere"
        elif has_marker:
            sw_kind = "scatter_open" if m_int == 2 else "scatter"
        elif d_code == 1:
            sw_kind = "line_dashed"
        else:
            sw_kind = "line"

        if not s.meta.get("skip_legend"):
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
    rect_pct: Optional[Tuple[float, float, float, float]] = None,
    invert_x: bool = False,
    invert_y: bool = False,
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

    if rect_pct is not None:
        l_p, t_p, w_p, h_p = rect_pct
    else:
        l_p, t_p, w_p, h_p = ob._query_layer_rect_page_pct(op, gp, layer_num_1based, {})[:4]

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
    ic50_drop_xs = [
        float(g.value)
        for g in guides
        if g.kind == "vline" and g.value is not None and g.meta.get("guide_role") == "ic50_drop"
    ]

    for idx, g in enumerate(guides):
        c_hex = g.color or "#3E86DE"
        c_int = ot.hex_to_origin_rgb_int(c_hex)
        w_units = sub_w
        d_code = _line_style_code(g.line_style)
        fs = min(base_callout_fs, float(g.font_size_pt or base_callout_fs))
        rich_lbl = _format_origin_guide_text(g.label)
        g_role = str(g.meta.get("guide_role", ""))

        if g.kind == "sig_bracket" and g.value is not None and g.x is not None and (g.x2 is not None or g.x_end is not None):
            x1 = float(g.x)
            x2 = float(g.x2 if g.x2 is not None else g.x_end)
            y_bar = float(g.value)
            drop = float(g.tip_drop) if (g.tip_drop is not None and float(g.tip_drop) > 0.0) else (0.026 * y_span)
            brk_hex = g.color or "#111111"
            brk_int = ot.hex_to_origin_rgb_int(brk_hex)
            seg_cols.append(
                (
                    f"SBX{idx+1}",
                    [x1, x1, x2, x2],
                    f"SBY{idx+1}",
                    [y_bar - drop, y_bar, y_bar, y_bar - drop],
                    brk_hex,
                    sub_w,
                    0,
                )
            )
            raw_star = str(g.label or "").strip()
            if raw_star:
                xm = 0.5 * (x1 + x2)
                xf_m = ob._map_data_to_frac(xm, x_lo, x_hi, invert_x, log_x)
                yf_raw = ob._map_data_to_frac(y_bar, y_lo, y_hi, False, log_y)
                yf_b = (1.0 - yf_raw) if invert_y else yf_raw
                xp_star = l_p + xf_m * w_p
                is_star_only = all(ch == "*" for ch in raw_star)
                dy_star_pct = -0.95 if is_star_only else -1.85
                yp_star = max(t_p + 1.8, t_p + (1.0 - yf_b) * h_p + dy_star_pct)
                star_fs = min(float(spec.get("annotation_pt", spec.get("callout_pt", 22.0))), 19.5 if is_star_only else 18.0)
                ob.add_page_text_label(
                    op,
                    gp,
                    gl,
                    layer_num_1based,
                    f"SigBrk_{idx+1}",
                    raw_star,
                    xp_star,
                    yp_star,
                    fontsize=star_fs,
                    color_int=brk_int,
                    pos_scatter=0,
                    format_math=False,
                )

        elif g.kind == "vline" and g.value is not None:
            xv = float(g.value)
            if g_role == "ic50_drop":
                ref_y_top = float(g.meta.get("ref_y", g.meta.get("mid_y", 50.0)))
                seg_cols.append((f"GX{idx+1}", [xv, xv], f"GY{idx+1}", [y_lo, min(y_hi, ref_y_top)], c_hex, w_units, d_code))
            else:
                seg_cols.append((f"GX{idx+1}", [xv, xv], f"GY{idx+1}", [y_lo, y_hi], c_hex, w_units, d_code))
                if rich_lbl:
                    pos_sc = 1 if g.label_side == "left" else 2
                    dx_p = -0.9 if pos_sc == 1 else 0.9
                    ly = y_lo + float(g.shoulder_y_frac or 0.80) * y_span
                    callouts.append((xv, ly, rich_lbl, c_int, fs, pos_sc, dx_p, 0.0, False))

        elif g.kind == "hline" and g.value is not None:
            yv = float(g.value)
            if g_role == "ic50_mid_response" and ic50_drop_xs:
                x_end_h = max(ic50_drop_xs) if not invert_x else min(ic50_drop_xs)
                x_start_h = x_hi if invert_x else x_lo
                seg_cols.append((f"GX{idx+1}", [x_start_h, x_end_h], f"GY{idx+1}", [yv, yv], c_hex, w_units, d_code))
            else:
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

        elif g.kind == "slope_triangle" and g.x is not None and g.y is not None and (g.x2 is not None or g.x_end is not None):
            x1_t = float(g.x)
            x2_t = float(g.x2 if g.x2 is not None else g.x_end)
            y1_t = float(g.y)
            if g.y_end is not None:
                y2_t = float(g.y_end)
            else:
                m_sl = float(g.value if g.value is not None else 1.0)
                if log_x and log_y and x1_t > 0 and x2_t > 0 and y1_t > 0:
                    y2_t = y1_t * ((x2_t / x1_t) ** m_sl)
                elif (not log_x) and log_y and y1_t > 0:
                    y2_t = 10.0 ** (math.log10(y1_t) + m_sl * (x2_t - x1_t))
                elif log_x and (not log_y) and x1_t > 0 and x2_t > 0:
                    y2_t = y1_t + m_sl * (math.log10(x2_t) - math.log10(x1_t))
                else:
                    y2_t = y1_t + m_sl * (x2_t - x1_t)
            tri_hex = g.color or "#334155"
            tri_int = ot.hex_to_origin_rgb_int(tri_hex)
            seg_cols.append(
                (
                    f"STX{idx+1}",
                    [x1_t, x2_t, x2_t, x1_t],
                    f"STY{idx+1}",
                    [y1_t, y1_t, y2_t, y1_t],
                    tri_hex,
                    w_units,
                    0,
                )
            )
            if rich_lbl:
                xm_t = math.sqrt(x1_t * x2_t) if (log_x and x1_t > 0 and x2_t > 0) else 0.5 * (x1_t + x2_t)
                ym_t = math.sqrt(y1_t * y2_t) if (log_y and y1_t > 0 and y2_t > 0) else 0.5 * (y1_t + y2_t)
                xf_b = ob._map_data_to_frac(x2_t, x_lo, x_hi, invert_x, log_x)
                xf_m = ob._map_data_to_frac(xm_t, x_lo, x_hi, invert_x, log_x)
                yf_b_raw = ob._map_data_to_frac(y1_t, y_lo, y_hi, False, log_y)
                yf_m_raw = ob._map_data_to_frac(ym_t, y_lo, y_hi, False, log_y)
                yf_b = (1.0 - yf_b_raw) if invert_y else yf_b_raw
                yf_m = (1.0 - yf_m_raw) if invert_y else yf_m_raw
                pos_sc_t = 1 if xf_b >= xf_m else 2
                dx_t = -0.95 if pos_sc_t == 1 else 0.95
                dy_t = -2.1 if yf_b <= yf_m else 2.1
                callouts.append((xm_t, ym_t, rich_lbl, tri_int, min(fs, 19.5), pos_sc_t, dx_t, dy_t, True))

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


def _render_point_callouts_into_glayer(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    point_callouts: Sequence[Dict[str, Any]],
    wb: Any,
    used_sheets: set[str],
    x_bounds: Tuple[float, float],
    y_bounds: Tuple[float, float],
    rect_pct: Tuple[float, float, float, float],
    *,
    invert_x: bool = False,
    log_x: bool = False,
    log_y: bool = False,
    top_reserved_pct: float = 0.0,
) -> None:
    """
    Render non-overlapping leader segments + borderless (`FrameType=0`) gene/protein labels inside the plot frame.
    """
    if not point_callouts:
        return

    spec = ob.get_active_spec()
    pw_in, _ph_in = ob._PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
    upi = ob._origin_units_per_inch(spec)
    fs_lbl = min(float(spec["callout_pt"]), 18.5)
    ldr_w = max(520, int(round(float(spec["sub_w_units"]) * 0.80)))
    l_p, t_p, w_p, h_p = rect_pct
    x_lo, x_hi = min(x_bounds), max(x_bounds)
    y_lo, y_hi = min(y_bounds), max(y_bounds)

    def _pct_to_data_x(xp: float) -> float:
        fx = max(0.01, min(0.99, (xp - l_p) / max(w_p, 1e-6)))
        a, b = (x_hi, x_lo) if invert_x else (x_lo, x_hi)
        if log_x and a > 0 and b > 0:
            return 10.0 ** (math.log10(a) + fx * (math.log10(b) - math.log10(a)))
        return a + fx * (b - a)

    def _pct_to_data_y(yp_top: float) -> float:
        fy = max(0.01, min(0.99, 1.0 - (yp_top - t_p) / max(h_p, 1e-6)))
        if log_y and y_lo > 0 and y_hi > 0:
            return 10.0 ** (math.log10(y_lo) + fy * (math.log10(y_hi) - math.log10(y_lo)))
        return y_lo + fy * (y_hi - y_lo)

    y_min_safe = t_p + max(4.2, top_reserved_pct)
    y_max_safe = t_p + h_p - 5.2

    # Detect vertical guide thresholds (e.g. ±fc_cutoff in volcano_plot) so callout labels stay cleanly inside their wing when possible
    neg_cut_xf = 0.46
    pos_cut_xf = 0.54
    items_left: List[Dict[str, Any]] = []
    items_right: List[Dict[str, Any]] = []
    for c_idx, pc in enumerate(point_callouts):
        if not isinstance(pc, dict) or pc.get("x") is None or pc.get("y") is None:
            continue
        lbl = str(pc.get("label", "")).strip()
        if not lbl:
            continue
        xv, yv = float(pc["x"]), float(pc["y"])
        xf = ob._map_data_to_frac(xv, x_lo, x_hi, invert_x, log_x)
        yf = ob._map_data_to_frac(yv, y_lo, y_hi, False, log_y)
        px = l_p + xf * w_p
        py = t_p + (1.0 - yf) * h_p
        txt_w_pct = max(5.0, ((0.52 * len(lbl) + 0.30) * fs_lbl / (pw_in * upi)) * 100.0)

        if xf < 0.5:
            # Prefer placing right of outer-left points while staying left of vertical threshold if it fits; else outer-left
            wing_right_lim = l_p + (0.34 if x_lo < -1.5 < x_hi else neg_cut_xf) * w_p
            can_go_left = (px - 3.0 - txt_w_pct) >= (l_p + 1.6)
            can_fit_wing_inward = (px + 2.8 + txt_w_pct) <= wing_right_lim
            if can_fit_wing_inward and (not can_go_left or xf < 0.22):
                ax = px + 2.8
                pos_sc = 2
            elif can_go_left:
                ax = px - 2.8
                pos_sc = 1
            else:
                ax = min(l_p + 0.45 * w_p - txt_w_pct, max(l_p + 1.8, px + 2.6))
                pos_sc = 2
            ay = max(y_min_safe, min(y_max_safe, py - 2.0))
            items_left.append(
                {
                    "idx": c_idx,
                    "lbl": lbl,
                    "color": str(pc.get("color") or "#222222"),
                    "px": px,
                    "py": py,
                    "ax": ax,
                    "ay": ay,
                    "pos_sc": pos_sc,
                    "w": txt_w_pct,
                }
            )
        else:
            wing_left_lim = l_p + (0.66 if x_lo < 1.5 < x_hi else pos_cut_xf) * w_p
            can_go_right = (px + 3.0 + txt_w_pct) <= (l_p + w_p - 1.6)
            can_fit_wing_inward = (px - 2.8 - txt_w_pct) >= wing_left_lim
            if can_fit_wing_inward and (not can_go_right or xf > 0.78):
                ax = px - 2.8
                pos_sc = 1
            elif can_go_right:
                ax = px + 2.8
                pos_sc = 2
            else:
                ax = max(l_p + 0.55 * w_p + txt_w_pct, min(l_p + w_p - 1.8, px - 2.6))
                pos_sc = 1
            ay = max(y_min_safe, min(y_max_safe, py - 2.0))
            items_right.append(
                {
                    "idx": c_idx,
                    "lbl": lbl,
                    "color": str(pc.get("color") or "#222222"),
                    "px": px,
                    "py": py,
                    "ax": ax,
                    "ay": ay,
                    "pos_sc": pos_sc,
                    "w": txt_w_pct,
                }
            )

    min_dy = 5.1
    for grp in (items_left, items_right):
        grp.sort(key=lambda d: d["ay"])
        for _it in range(20):
            moved = False
            for i in range(len(grp) - 1):
                a, b = grp[i], grp[i + 1]
                # Check horizontal overlap of label boxes before forcing vertical push
                ax0 = a["ax"] if a["pos_sc"] == 2 else (a["ax"] - a["w"])
                ax1 = a["ax"] + a["w"] if a["pos_sc"] == 2 else a["ax"]
                bx0 = b["ax"] if b["pos_sc"] == 2 else (b["ax"] - b["w"])
                bx1 = b["ax"] + b["w"] if b["pos_sc"] == 2 else b["ax"]
                if min(ax1, bx1) + 1.8 > max(ax0, bx0) and (b["ay"] - a["ay"]) < min_dy:
                    push = 0.52 * (min_dy - (b["ay"] - a["ay"]))
                    a["ay"] = max(y_min_safe, a["ay"] - push)
                    b["ay"] = min(y_max_safe, b["ay"] + push)
                    if (b["ay"] - a["ay"]) < min_dy * 0.92:
                        if a["ay"] <= y_min_safe + 0.2:
                            b["ay"] = min(y_max_safe, a["ay"] + min_dy)
                        else:
                            a["ay"] = max(y_min_safe, b["ay"] - min_dy)
                    moved = True
            if not moved:
                break

    resolved_all = items_left + items_right
    if not resolved_all:
        return

    ldr_sh = ob.unique_origin_short_name(f"CalloutL{layer_num_1based}", used_sheets, default="Callouts")
    wks_ldr = wb.add_sheet(ldr_sh)
    wks_ldr.cols = 2 * len(resolved_all)
    wks_ldr.cols_axis("XY" * len(resolved_all))
    ob.activate_layer(op, gp, layer_num_1based)

    ldr_ink_oc = ob._hex_to_origin_color(op, "#3B4252")
    ink_lbl_int = ot.hex_to_origin_rgb_int("#111111")

    for k_i, it in enumerate(resolved_all):
        dx_v = it["ax"] - it["px"]
        dy_v = it["ay"] - it["py"]
        dist_pct = math.hypot(dx_v, dy_v)
        # Trim 0.45% at point rim and 0.35% before text edge so leader segment never touches circle center or glyphs
        t0 = min(0.32, 0.48 / max(dist_pct, 1e-3))
        t1 = max(0.68, 1.0 - 0.38 / max(dist_pct, 1e-3))
        sx_p = it["px"] + t0 * dx_v
        sy_p = it["py"] + t0 * dy_v
        ex_p = it["px"] + t1 * dx_v
        ey_p = it["py"] + t1 * dy_v

        wks_ldr.from_list(2 * k_i, [_pct_to_data_x(sx_p), _pct_to_data_x(ex_p)], lname=f"LX{k_i+1}", axis="X")
        wks_ldr.from_list(2 * k_i + 1, [_pct_to_data_y(sy_p), _pct_to_data_y(ey_p)], lname=f"LY{k_i+1}", axis="Y")
        p_ldr = gl.add_plot(wks_ldr, coly=2 * k_i + 1, colx=2 * k_i, type="l")
        p_ldr.color = ldr_ink_oc
        gl.lt_exec(f"range rld = !{len(gl.plot_list())}; set rld -w {ldr_w}; set rld -d 0;")

        ob.add_page_text_label(
            op,
            gp,
            gl,
            layer_num_1based,
            f"PtCall_{k_i+1}",
            it["lbl"],
            it["ax"],
            it["ay"],
            fontsize=fs_lbl,
            color_int=ink_lbl_int,
            pos_scatter=it["pos_sc"],
            format_math=False,
        )

    gl.lt_exec("label -r Legend;")


def _format_cat_label_chem_subscripts(raw_c: str) -> str:
    """Convert explicit `O_2` / `H_2O` / `CO_2` subscript tokens in reaction step labels to Origin `\\-(...)`."""
    s = str(raw_c or "").strip()
    if "_" not in s and "^" not in s:
        return s
    s = s.replace("$", "")
    s = re.sub(r"_\{([^{}]+)\}", r"\\-(\1)", s)
    s = re.sub(r"([A-Za-z0-9)])_(\d+)", r"\1\\-(\2)", s)
    s = re.sub(r"\^\{([^{}]+)\}", r"\\+(\1)", s)
    return s


def _extract_panel_categories(panel: cg.PanelSpec) -> List[str]:
    has_energy = any(ly.mark == "energy_step" for ly in panel.layers)
    fmt_fn = _format_cat_label_chem_subscripts if has_energy else str
    if panel.x_axis.categories:
        return [fmt_fn(str(c)) for c in panel.x_axis.categories]
    for ly in panel.layers:
        if ly.categories and ly.mark != "forest_ci":
            return [fmt_fn(str(c)) for c in ly.categories]
        if ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box", "bar_dot_error") and ly.series:
            return [str(s.meta.get("label") or s.name) for s in ly.series]
        if ly.series and ly.series[0].x and all(isinstance(v, str) for v in ly.series[0].x):
            return [fmt_fn(str(v)) for v in ly.series[0].x]
    return []


def _eval_axis_formula(formula: str, x_val: float) -> float:
    expr = re.sub(r"\b[xX]\b", f"({float(x_val):.12g})", str(formula or "x").replace("^", "**"))
    safe_ns = {
        "__builtins__": {},
        "math": math,
        "ln": math.log,
        "log": math.log10,
        "log10": math.log10,
        "exp": math.exp,
        "sqrt": math.sqrt,
        "abs": abs,
    }
    return float(eval(expr, safe_ns, {}))


def _apply_axis_breaks_if_any(
    gl: Any,
    panel: cg.PanelSpec,
    x_bounds: Tuple[float, float],
    y_bounds: Tuple[float, float],
) -> None:
    x_ax = panel.x_axis
    y_ax = panel.y1_axis
    x_breaks = getattr(x_ax, "breaks", None) or []
    if x_breaks:
        bx = x_breaks[0]
        b0, b1 = float(bx["from"]), float(bx["to"])
        if not x_ax.invert:
            b0, b1 = min(b0, b1), max(b0, b1)
        pos_pct = float(bx.get("position_pct", bx.get("position", 48.0)))
        sc_after = str(bx.get("scale_after", "linear")).strip().lower()
        sc2_code = 2 if sc_after in ("log10", "log") else 1
        inc1 = bx.get("inc_before") or bx.get("inc1") or ob.compute_nice_linear_step(x_bounds[0], min(b0, b1), max_ticks=3) or 1.0
        inc2 = bx.get("inc_after") or bx.get("inc2") or (
            1 if sc2_code == 2 else (ob.compute_nice_linear_step(max(b0, b1), x_bounds[1], max_ticks=3) or 1.0)
        )
        gl.lt_exec(
            f"layer.x.breaks.enable=1; layer.x.breaks.count=1; "
            f"layer.x.break1.from={b0}; layer.x.break1.to={b1}; "
            f"layer.x.break1.pos={pos_pct}; "
            f"layer.x.inc={inc1}; layer.x.break1.inc={inc2}; layer.x.break1.inc1={inc1}; layer.x.break1.inc2={inc2}; "
            f"layer.x.break1.scale2={sc2_code};"
        )

    y_breaks = getattr(y_ax, "breaks", None) or []
    if y_breaks:
        by = y_breaks[0]
        yb0, yb1 = float(by["from"]), float(by["to"])
        if not y_ax.invert:
            yb0, yb1 = min(yb0, yb1), max(yb0, yb1)
        ypos_pct = float(by.get("position_pct", by.get("position", 48.0)))
        ysc_after = str(by.get("scale_after", "linear")).strip().lower()
        ysc2_code = 2 if ysc_after in ("log10", "log") else 1
        yinc1 = by.get("inc_before") or by.get("inc1") or ob.compute_nice_linear_step(y_bounds[0], min(yb0, yb1), max_ticks=3) or 1.0
        yinc2 = by.get("inc_after") or by.get("inc2") or (
            1 if ysc2_code == 2 else (ob.compute_nice_linear_step(max(yb0, yb1), y_bounds[1], max_ticks=3) or 1.0)
        )
        gl.lt_exec(
            f"layer.y.breaks.enable=1; layer.y.breaks.count=1; "
            f"layer.y.break1.from={yb0}; layer.y.break1.to={yb1}; "
            f"layer.y.break1.pos={ypos_pct}; "
            f"layer.y.inc={yinc1}; layer.y.break1.inc={yinc2}; layer.y.break1.inc1={yinc1}; layer.y.break1.inc2={yinc2}; "
            f"layer.y.break1.scale2={ysc2_code};"
        )


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
    max_x_ticks_override: Optional[int] = None,
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
        eff_rect_pct = ot.rect_in_to_page_pct(li, ti, wi, hi, pw_in, ph_in)
    elif rect_pct is not None and not (has_2d_mat and panel.equal_aspect):
        l_p, t_p, w_p, h_p = rect_pct
        gl.lt_exec(f"layer.unit=1; layer.left={l_p}; layer.top={t_p}; layer.width={w_p}; layer.height={h_p};")
        lw_in, lh_in = pw_in * (float(w_p) / 100.0), ph_in * (float(h_p) / 100.0)
        eff_rect_pct = rect_pct
    else:
        lw_in = float(spec["box_sq_side_in"] if has_2d_mat else spec["box_rect_w_in"])
        lh_in = float(spec["box_sq_side_in"] if has_2d_mat else spec["box_rect_h_in"])
        eff_rect_pct = rect_pct or ob._query_layer_rect_page_pct(op, gp, layer_num_1based, {})[:4]

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

    has_stat = any(ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box", "bar_dot_error") for ly in panel.layers)
    has_forest = any(ly.mark == "forest_ci" for ly in panel.layers)
    is_cat_x = ((x_ax.axis_kind == "categorical") or has_stat) and not has_2d_mat and not has_forest
    is_cat_y = (y_ax.axis_kind == "categorical" or has_forest) and not has_2d_mat
    x_ticks = 0 if is_cat_x else (5 if x_is_log else 1)
    if y_ax.axis_kind == "intensity_arbitrary" or hide_y_override or is_cat_y:
        y_ticks = 0
        y_labels = 0
    else:
        y_ticks = 5 if y_is_log else 1
        y_labels = 1

    has_linked_top_x = bool(getattr(x_ax, "linked_top", None))
    x_show_axes = 1 if has_linked_top_x else 3

    gl.lt_exec(
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.type={x_type}; layer.y.type={y_type}; "
        f"layer.x.showAxes={x_show_axes}; layer.y.showAxes=3; "
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

    is_1d_eq = panel.equal_aspect and not has_2d_mat and not is_cat_x and not is_cat_y and not x_is_log and not y_is_log
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
            if is_cat_x and cats:
                gl.lt_exec(f"layer.x.from={x_bounds[0]}; layer.x.to={x_bounds[1]}; layer.x.inc=1;")
        elif is_cat_x and cats:
            x_bounds = (0.4, float(len(cats)) + 0.6)
            gl.set_xlim(x_bounds[0], x_bounds[1])
            gl.lt_exec(f"layer.x.from={x_bounds[0]}; layer.x.to={x_bounds[1]}; layer.x.inc=1;")
        elif x_ax.invert:
            gl.set_xlim(x_bounds[1], x_bounds[0])
        else:
            gl.set_xlim(x_bounds[0], x_bounds[1])

        if y_ax.limits is not None and not reserve_top_legend_space:
            y_bounds = (float(min(y_ax.limits)), float(max(y_ax.limits)))
        y_from, y_to = (y_bounds[1], y_bounds[0]) if y_ax.invert else (y_bounds[0], y_bounds[1])
        gl.set_ylim(y_from, y_to)
        gl.lt_exec(f"layer.y.from={y_from}; layer.y.to={y_to};")

        max_auto_tks = (
            4
            if (has_forest or lw_in < 5.9 or (not x_is_log and abs(x_bounds[1] - x_bounds[0]) < 0.5))
            else (5 if panel.equal_aspect else 6)
        )
        eff_x_tks = int(max_x_ticks_override) if max_x_ticks_override is not None else max_auto_tks
        if x_ax.major_step is not None and x_ax.major_step > 0:
            gl.lt_exec(f"layer.x.inc={float(x_ax.major_step)};")
        elif not is_cat_x and not x_is_log and not has_2d_mat:
            auto_xs = ob.compute_nice_linear_step(x_bounds[0], x_bounds[1], max_ticks=eff_x_tks)
            if auto_xs:
                gl.lt_exec(f"layer.x.inc={auto_xs};")

        if y_ax.major_step is not None and y_ax.major_step > 0:
            gl.lt_exec(f"layer.y.inc={float(y_ax.major_step)};")
        elif y_labels and not y_is_log and not has_2d_mat and not is_cat_y:
            auto_ys = ob.compute_nice_linear_step(y_bounds[0], y_bounds[1], max_ticks=max_auto_tks)
            if auto_ys:
                gl.lt_exec(f"layer.y.inc={auto_ys};")

    _apply_axis_breaks_if_any(gl, panel, x_bounds, y_bounds)

    if is_cat_x and cats:
        # Compute true glyph visual width (stripping Origin `\-(...)` / `\g(...)` escapes) so 2-to-6 group
        # labels like `Low Dose`, `High Dose`, `Cluster 1..5`, `*OH`, `O\-(2)` stay crisp and horizontal
        # without unnecessary 30° tilting into the X-axis title!
        upi_cat = ob._origin_units_per_inch(spec)
        slot_w_in = lw_in / max(float(len(cats)), 1.0)
        vis_lens: List[int] = []
        vis_ems: List[float] = []
        for raw_cat in cats:
            vis_s = re.sub(r"\\[A-Za-z+-]+\(([^()]*)\)", r"\1", str(raw_cat))
            vis_lens.append(len(vis_s))
            em_v = sum(
                0.24
                if ch in " .,'|!"
                else (0.31 if ch in "iltfr1()-/" else (0.56 if (ch.isupper() or ch in "%+*=#") else 0.42))
                for ch in vis_s
            )
            vis_ems.append(em_v)
        max_vis_len = max(vis_lens, default=4)
        max_em_cat = max(vis_ems, default=2.5)
        horiz_pt = tk_pt_use
        # True glyph advance in Origin overlay is ~1.35x `em_v`; keep <=6-char tokens (`*OH`, `O\-(2)`, `S1..S5`)
        # crisp & horizontal, and render longer labels (`Low Dose`, `Cluster 1`) with tucked 28° tilt clear of `XB`!
        if max_vis_len <= 6 or (len(cats) <= 4 and max_vis_len <= 7) or (
            len(cats) <= 6 and ((1.38 * max_em_cat * tk_pt_use) / upi_cat) <= 0.84 * slot_w_in
        ):
            ob.activate_layer(op, gp, layer_num_1based)
            gl.lt_exec("layer.x.showLabels=0; layer.x.ticks=0; layer.x.showMinorTicks=0;")
            dy_h_pct = ((0.20 + 0.56 * (horiz_pt / upi_cat)) / ph_in) * 100.0
            x_span_cat = max(x_bounds[1] - x_bounds[0], 1e-6)
            for idx_c, c_str in enumerate(cats, start=1):
                xf_c = (float(idx_c) - x_bounds[0]) / x_span_cat
                ob._PENDING_DATA_TEXT_ITEMS.setdefault(gp.name, []).append(
                    {
                        "layer_num": int(layer_num_1based),
                        "mode": "cat_x_horiz",
                        "x_frac": xf_c,
                        "dy_below_pct": dy_h_pct,
                        "text": str(c_str),
                        "format_math": False,
                        "fontsize": horiz_pt,
                        "color_int": ink_int,
                        "rotate": 0,
                        "pos_scatter": 0,
                    }
                )
        else:
            ob.activate_layer(op, gp, layer_num_1based)
            gl.lt_exec("layer.x.showLabels=0; layer.x.ticks=0; layer.x.showMinorTicks=0;")
            tilt_pt = min(tk_pt_use, 20.5 if max_vis_len <= 11 else 19.0)
            rot_deg = 28
            rot_rad = math.radians(rot_deg)
            char_h_in = tilt_pt / upi_cat
            x_span_cat = max(x_bounds[1] - x_bounds[0], 1e-6)
            for idx_c, (c_str, v_len) in enumerate(zip(cats, vis_lens), start=1):
                xf_c = (float(idx_c) - x_bounds[0]) / x_span_cat
                lbl_len_in = (0.50 * max(v_len, 2) * tilt_pt) / upi_cat
                dx_tip_pct = ((0.44 * lbl_len_in * math.cos(rot_rad)) / pw_in) * 100.0
                # Keep >= 5.35% so `flush_page_overlays` classifies layer into `layers_with_cat2` (`bot_in + 1.44 in`),
                # while tucking top-right tip 0.08 in below bottom spine so bottom-left never touches `XB`!
                dy_tip_pct = max(
                    5.35,
                    ((0.08 + 0.46 * lbl_len_in * math.sin(rot_rad) + 0.46 * char_h_in * math.cos(rot_rad)) / ph_in)
                    * 100.0,
                )
                ob._PENDING_DATA_TEXT_ITEMS.setdefault(gp.name, []).append(
                    {
                        "layer_num": int(layer_num_1based),
                        "mode": "cat_x_tilt",
                        "x_frac": xf_c,
                        "dx_shift_pct": -dx_tip_pct + 0.16,
                        "dy_below_pct": dy_tip_pct,
                        "text": str(c_str),
                        "format_math": False,
                        "fontsize": tilt_pt,
                        "color_int": ink_int,
                        "rotate": rot_deg,
                        "pos_scatter": 0,
                    }
                )

    if is_cat_y:
        y_cats = list(y_ax.categories or [])
        if not y_cats:
            for ly in panel.layers:
                if ly.mark == "forest_ci" and ly.categories:
                    y_cats = [str(c) for c in ly.categories]
                    break
        if y_cats:
            upi_yc = ob._origin_units_per_inch(spec)
            max_yc_len = max((len(str(c)) for c in y_cats), default=6)
            max_yc_em = max(
                (
                    sum(
                        0.28
                        if ch in " .,'|!"
                        else (0.35 if ch in "iltfr1()-/" else (0.64 if (ch.isupper() or ch in "%+*=#") else 0.49))
                        for ch in str(c)
                    )
                    for c in y_cats
                ),
                default=4.0,
            )
            ob.register_custom_y_label_layer(gp, layer_num_1based, extra_gap=(3.6 if max_yc_len >= 12 else 1.8))
            left_edge_in = pw_in * (eff_rect_pct[0] / 100.0)
            avail_left_in = max(1.0, left_edge_in - (0.85 if y_ax.label else 0.52))
            fit_yc_pt = (avail_left_in * upi_yc) / max(max_yc_em * 1.16 + 0.35, 1.0)
            yc_fs = min(19.5 if len(y_cats) >= 9 else tk_pt_use, max(15.0, fit_yc_pt))
            y_span_c = max(y_bounds[1] - y_bounds[0], 1e-6)
            lx_cat_pct = eff_rect_pct[0] - (0.12 / pw_in) * 100.0
            for i_y, yc_lbl in enumerate(y_cats):
                yv_pos = float(i_y + 1)
                frac_top = (yv_pos - y_bounds[0]) / y_span_c if y_ax.invert else (y_bounds[1] - yv_pos) / y_span_c
                ry_cat_pct = eff_rect_pct[1] + frac_top * eff_rect_pct[3]
                ob.add_page_text_label(
                    op,
                    gp,
                    gl,
                    layer_num_1based,
                    f"ForestY_{i_y+1}",
                    str(yc_lbl),
                    lx_cat_pct,
                    ry_cat_pct,
                    fontsize=yc_fs,
                    color_int=ink_int,
                    pos_scatter=1,
                    format_math=False,
                )

            # Right-side formatted `est [low, high]` column inside reserved headroom for `forest_ci`
            for ly in panel.layers:
                if ly.mark == "forest_ci" and ly.series:
                    s_f = ly.series[0]
                    fmt_cis = s_f.meta.get("formatted_ci") or []
                    if (ly.show_value_labels or s_f.show_value_labels) and fmt_cis:
                        ci_fs = min(float(spec["callout_pt"]), 17.5 if len(y_cats) >= 6 else 18.5)
                        rx_ci_pct = eff_rect_pct[0] + eff_rect_pct[2] - 1.4
                        for i_ci, ci_txt in enumerate(fmt_cis):
                            if not ci_txt:
                                continue
                            yv_pos = float(i_ci + 1)
                            frac_top = (yv_pos - y_bounds[0]) / y_span_c if y_ax.invert else (y_bounds[1] - yv_pos) / y_span_c
                            ry_ci_pct = eff_rect_pct[1] + frac_top * eff_rect_pct[3]
                            ob.add_page_text_label(
                                op,
                                gp,
                                gl,
                                layer_num_1based,
                                f"ForestCI_{i_ci+1}",
                                str(ci_txt),
                                rx_ci_pct,
                                ry_ci_pct,
                                fontsize=ci_fs,
                                color_int=ink_int,
                                pos_scatter=1,
                                format_math=False,
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
    elif contour_layer.color_scheme and contour_layer.color_scheme in ("vik", "magma", "viridis", "diverging_blue_red", "sequential_blue_red"):
        stops = list(ot.get_scheme_color_stops(contour_layer.color_scheme))
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

    # Render any non-contour overlay layers on `contour_panel` (e.g. `vector_quiver` velocity arrows or streamlines)
    ov_layers_2d = [ly for ly in contour_panel.layers if ly.mark not in ("contour_pseudocolor", "matrix_heatmap")]
    if ov_layers_2d:
        for ov_ly in ov_layers_2d:
            _plot_layer_into_glayer(op, gp, gl_c, 1, ov_ly, contour_panel, wb_aux, used_sheets, pal_tmp_dir)
        ob.activate_layer(op, gp, 1)
        if side_panel is None:
            gl_c.lt_exec(
                f"layer.unit=2; layer.left={sq_left}; layer.top={sq_top}; layer.width={sq_side}; layer.height={sq_side};"
            )
        if is_heatmap:
            gl_c.set_xlim(x1 - 0.5, x2 + 0.5)
            gl_c.set_ylim(y2 + 0.5, y1 - 0.5)
        elif has_y_lbls:
            gl_c.set_xlim(x2 if contour_panel.x_axis.invert else x1, x1 if contour_panel.x_axis.invert else x2)
            gl_c.set_ylim(y_map_hi, y_map_lo)
        else:
            xf_c0, xf_c1 = (x2, x1) if contour_panel.x_axis.invert else (x1, x2)
            yf_c0, yf_c1 = (y2, y1) if contour_panel.y1_axis.invert else (y1, y2)
            gl_c.set_xlim(xf_c0, xf_c1)
            gl_c.set_ylim(yf_c0, yf_c1)
            gl_c.lt_exec(f"layer.x.from={xf_c0}; layer.x.to={xf_c1}; layer.y.from={yf_c0}; layer.y.to={yf_c1};")
        gl_c.lt_exec("label -r Legend;")

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


def _render_ternary_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    _ = pal_tmp_dir
    spec = ob.get_active_spec()
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    gp = op.new_graph(lname=page_lname, template="Ternary")
    ob.set_graph_page_inches(gp, pw, ph)
    gl = gp[0]
    ob.activate_layer(op, gp, 1)

    scale_min = min(pw / 10.4, ph / 7.8)
    side_in = round(4.75 * scale_min, 4)
    left_in = round(0.5 * (pw - side_in), 4)
    top_in = round(1.30 * (ph / 7.8), 4)
    gl.lt_exec(f"layer.unit=2; layer.left={left_in}; layer.top={top_in}; layer.width={side_in}; layer.height={side_in};")

    wb = op.new_book("w", lname=f"{page_lname}_Ternary")
    used_sheets: set[str] = set()
    all_series: List[cg.SeriesSpec] = [s for ly in panel.layers for s in ly.series]
    fb_cols = ot.resolve_series_colors(
        max(1, len(all_series)),
        scheme=(panel.layers[0].color_scheme if panel.layers else "okabe_ito"),
    )
    comp_labels = ["Component A (%)", "Component B (%)", "Component C (%)"]
    if all_series and all_series[0].meta.get("component_labels"):
        cl_raw = list(all_series[0].meta["component_labels"])
        if len(cl_raw) >= 3:
            comp_labels = [str(cl_raw[0]), str(cl_raw[1]), str(cl_raw[2])]
    elif panel.meta.get("component_labels") and len(panel.meta["component_labels"]) >= 3:
        cl_raw = list(panel.meta["component_labels"])
        comp_labels = [str(cl_raw[0]), str(cl_raw[1]), str(cl_raw[2])]

    plotted_info: List[Tuple[int, Any, cg.SeriesSpec, str]] = []
    for s_idx, s in enumerate(all_series):
        a_vals = [float(v) for v in (s.x or [])]
        b_vals = [float(v) for v in (s.y or [])]
        c_raw = s.meta.get("ternary_c") or s.meta.get("c") or s.meta.get("z")
        if c_raw is not None and len(c_raw) == len(a_vals):
            c_vals = [float(v) for v in c_raw]
        else:
            tot_sc = 100.0 if max(a_vals + b_vals, default=1.0) > 1.5 else 1.0
            c_vals = [max(0.0, tot_sc - av - bv) for av, bv in zip(a_vals, b_vals)]
        if not a_vals or len(a_vals) != len(b_vals):
            continue

        sh_nm = ob.unique_origin_short_name(f"Tern_{s_idx+1}", used_sheets, default="Tern")
        wks = wb[0] if len(used_sheets) == 1 else wb.add_sheet(sh_nm)
        if len(used_sheets) == 1:
            wks.name = sh_nm
        wks.cols = 3
        wks.from_list(0, a_vals, lname=comp_labels[0], axis="X")
        wks.from_list(1, b_vals, lname=comp_labels[1], axis="Y")
        wks.from_list(2, c_vals, lname=comp_labels[2], axis="Z")
        wks.cols_axis("XYZ")

        ob.activate_layer(op, gp, 1)
        p_t = gl.add_plot(wks, coly=1, colx=0, colz=2, type=245)
        p_idx_1 = len(gl.plot_list())
        c_hex = ot.normalize_hex(s.color or fb_cols[s_idx % len(fb_cols)])
        plotted_info.append((p_idx_1, p_t, s, c_hex))

    ob.activate_layer(op, gp, 1)
    try:
        gl.group(False)
    except Exception:
        pass

    leg_entries: List[Tuple[Any, ...]] = []
    for p_idx_1, _p_t, s, c_hex in plotted_info:
        c_lt = ot.hex_to_origin_rgb_int(c_hex)
        ls_raw = str(s.line_style or "none").strip().lower()
        has_ln = ls_raw not in ("none", "", "false")
        d_c = _line_style_code(ls_raw)
        raw_lw = float(s.line_width_pt or spec["curve_lw_pt"])
        cw_u = int(spec["curve_w_units"]) if abs(raw_lw - 2.8) < 0.4 else max(300, int(round(raw_lw * 500.0)))
        ms_raw = str(s.marker_style or ("circle" if not has_ln else "none")).strip().lower()
        m_sh, m_in = _marker_cmd_and_interior(ms_raw)
        if not has_ln and m_sh is None:
            m_sh, m_in = 2, 1
        ln_cmd = f"set rt -l 1; set rt -d {d_c}; set rt -w {cw_u};" if has_ln else "set rt -l 0;"
        if m_sh is not None:
            mk_sz = float(s.marker_size_pt or spec["marker_size_pt"])
            kf_code = 1 if int(m_in) == 2 else 0
            sym_cmd = f"set rt -k {int(m_sh)}; set rt -kf {kf_code}; set rt -z {mk_sz};"
        else:
            sym_cmd = "set rt -z 0;"
        gl.lt_exec(f"range rt = !{p_idx_1}; set rt -c {c_lt}; set rt -cl {c_lt}; {ln_cmd} {sym_cmd}")

        if not s.meta.get("skip_legend"):
            if has_ln and m_sh is not None:
                sw_k = "open_circle" if m_in == 2 else "line_sphere"
            elif has_ln:
                sw_k = "line_dashed" if d_c == 1 else "line"
            else:
                sw_k = "scatter_open" if m_in == 2 else "scatter"
            leg_entries.append((p_idx_1, s.name, c_hex, sw_k))

    ob.set_graph_page_inches(gp, pw, ph)
    ob.activate_layer(op, gp, 1)
    gl.lt_exec(f"layer.unit=2; layer.left={left_in}; layer.top={top_in}; layer.width={side_in}; layer.height={side_in};")

    bt = float(spec["box_lw_pt"])
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    f_id = ob.get_font_id(op)
    bold_i = int(spec["bold_int"])
    tk_base = min(float(spec["tick_label_pt"]), 21.0 * (ph / 7.8))
    comp_tk = ot.compensate_origin_layer_pt(tk_base, side_in, side_in, pw, ph)
    try:
        x_to_tern = float(op.po.LT_evaluate("layer.x.to"))
    except Exception:
        x_to_tern = 1.0
    tern_inc = 20 if x_to_tern > 5.0 else 0.2

    sub_ax_cmds: List[str] = ["layer.x.grid.show=0; layer.y.grid.show=0; layer.z.grid.show=0;"]
    for sax in ("x", "x2", "y", "y2", "z", "z2"):
        sub_ax_cmds.append(
            f"layer.{sax}.thickness={bt}; layer.{sax}.color={ink_int}; "
            f"layer.{sax}.ticks=1; layer.{sax}.showMinorTicks=0; "
            f"layer.{sax}.label.pt={comp_tk}; layer.{sax}.label.bold={bold_i}; layer.{sax}.label.color={ink_int};"
        )
        if f_id > 0:
            sub_ax_cmds.append(f"layer.{sax}.label.font={f_id};")
    sub_ax_cmds.append(f"layer.x.inc={tern_inc}; layer.y.inc={tern_inc}; layer.z.inc={tern_inc};")
    sub_ax_cmds.append("XB.show=0; YL.show=0; ZB.show=0; ZF.show=0; XT.show=0; YR.show=0; label -r Legend;")
    gl.lt_exec(" ".join(sub_ax_cmds))
    for go in list(gl.obj.GraphObjects):
        if getattr(go, "Name", "") in ("Legend", "BBUTN1", "XB", "YL", "ZB", "ZF", "XT", "YR"):
            try:
                go.Destroy()
            except Exception:
                pass

    try:
        u_t = int(round(float(op.po.LT_evaluate("layer.unit"))))
        ll_v = float(op.po.LT_evaluate("layer.left"))
        lt_v = float(op.po.LT_evaluate("layer.top"))
        lw_v = float(op.po.LT_evaluate("layer.width"))
        lh_v = float(op.po.LT_evaluate("layer.height"))
        if u_t == 2:
            ll_in, lt_in, lw_in, lh_in = ll_v, lt_v, lw_v, lh_v
        else:
            ll_in, lt_in, lw_in, lh_in = pw * ll_v / 100.0, ph * lt_v / 100.0, pw * lw_v / 100.0, ph * lh_v / 100.0
    except Exception:
        ll_in, lt_in, lw_in, lh_in = left_in, top_in, side_in, side_in * 0.866025

    ax_fs = min(float(spec["axis_title_pt"]), 24.5 * (ph / 7.8))
    d_edge = 0.84 * (ph / 7.8)
    d_bot = 0.86 * (ph / 7.8)
    # Left slanted edge (`X` = comp_labels[0]), Right slanted edge (`Y` = comp_labels[1]), Bottom edge (`Z` = comp_labels[2])
    lx_in = ll_in + 0.25 * lw_in - 0.866025 * d_edge
    ly_in = lt_in + 0.50 * lh_in - 0.500000 * d_edge
    rx_in = ll_in + 0.75 * lw_in + 0.866025 * d_edge
    ry_in = lt_in + 0.50 * lh_in - 0.500000 * d_edge
    bx_in = ll_in + 0.50 * lw_in
    by_in = min(ph - 0.34 * (ph / 7.8), lt_in + lh_in + d_bot)

    ob.add_page_text_label(
        op, gp, gl, 1, "TernLeft", comp_labels[0], (lx_in / pw) * 100.0, (ly_in / ph) * 100.0,
        fontsize=ax_fs, color_int=ink_int, rotate=60, pos_scatter=0, format_math=True,
    )
    ob.add_page_text_label(
        op, gp, gl, 1, "TernRight", comp_labels[1], (rx_in / pw) * 100.0, (ry_in / ph) * 100.0,
        fontsize=ax_fs, color_int=ink_int, rotate=300, pos_scatter=0, format_math=True,
    )
    ob.add_page_text_label(
        op, gp, gl, 1, "TernBottom", comp_labels[2], (bx_in / pw) * 100.0, (by_in / ph) * 100.0,
        fontsize=ax_fs, color_int=ink_int, rotate=0, pos_scatter=0, format_math=True,
    )

    if panel.legend_style != "none" and leg_entries:
        ob.configure_custom_legend(
            gl,
            leg_entries,
            fontsize=min(float(spec["legend_pt"]), 19.5 * (ph / 7.8)),
            horizontal=False,
            pos_mode="page_upper_right",
            layer_rect_pct=(62.5, 3.8, 34.5, 25.0),
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
    return gp


def _compute_polygon_vertical_band(
    poly_x: Sequence[float],
    poly_y: Sequence[float],
    n_grid: int = 160,
) -> Tuple[List[float], List[float], List[float]]:
    px = [float(v) for v in poly_x]
    py = [float(v) for v in poly_y]
    if len(px) < 3:
        return [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
    if abs(px[0] - px[-1]) > 1e-9 or abs(py[0] - py[-1]) > 1e-9:
        px.append(px[0])
        py.append(py[0])
    xmin, xmax = min(px), max(px)
    if xmax - xmin <= 1e-9:
        return [xmin, xmax], [min(py), min(py)], [max(py), max(py)]
    xg = np.linspace(xmin + 1e-6, xmax - 1e-6, n_grid)
    y_up: List[float] = []
    y_lo: List[float] = []
    n_seg = len(px) - 1
    for xv in xg:
        hits: List[float] = []
        for i in range(n_seg):
            x0, y0, x1, y1 = px[i], py[i], px[i + 1], py[i + 1]
            if (x0 <= xv <= x1) or (x1 <= xv <= x0):
                if abs(x1 - x0) < 1e-12:
                    hits.extend([y0, y1])
                else:
                    t = (xv - x0) / (x1 - x0)
                    hits.append(y0 + t * (y1 - y0))
        if hits:
            y_lo.append(float(min(hits)))
            y_up.append(float(max(hits)))
        else:
            y_lo.append(0.0)
            y_up.append(0.0)
    return xg.tolist(), y_up, y_lo


def _render_polar_radar_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    _ = pal_tmp_dir
    spec = ob.get_active_spec()
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    coord_mode = str(getattr(panel, "coord", "polar") or "polar").strip().lower()
    if coord_mode not in ("polar", "radar"):
        has_cats = bool(panel.x_axis.categories or any(ly.categories for ly in panel.layers))
        coord_mode = "radar" if has_cats else "polar"

    all_series: List[cg.SeriesSpec] = [s for ly in panel.layers for s in ly.series]
    fb_cols = ot.resolve_series_colors(
        max(1, len(all_series)),
        scheme=(panel.layers[0].color_scheme if panel.layers else "okabe_ito"),
    )
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    bt = float(spec["box_lw_pt"])
    bold_i = int(spec["bold_int"])
    f_id = ob.get_font_id(op)

    if coord_mode == "polar":
        gp = op.new_graph(lname=page_lname, template="Polar")
        ob.set_graph_page_inches(gp, pw, ph)
        gl = gp[0]
        ob.activate_layer(op, gp, 1)
        for go in list(gl.obj.GraphObjects):
            gnm = getattr(go, "Name", "")
            if gnm in ("BBUTN1", "Legend", "YL", "XB", "XT", "YR", "label") or "BUTN" in gnm.upper():
                try:
                    go.Destroy()
                except Exception:
                    pass

        wb = op.new_book("w", lname=f"{page_lname}_Polar")
        used_sheets: set[str] = set()
        plotted_pol: List[Tuple[int, Any, cg.SeriesSpec, str]] = []
        all_r_vals: List[float] = []

        for s_idx, s in enumerate(all_series):
            th_vals = [float(v) for v in (s.x or s.meta.get("theta") or [])]
            r_vals = [float(v) for v in (s.y or s.meta.get("r") or [])]
            if not th_vals or len(th_vals) != len(r_vals):
                continue
            all_r_vals.extend(r_vals)
            sh_nm = ob.unique_origin_short_name(f"Pol_{s_idx+1}", used_sheets, default="Pol")
            wks = wb[0] if len(used_sheets) == 1 else wb.add_sheet(sh_nm)
            if len(used_sheets) == 1:
                wks.name = sh_nm
            wks.cols = 2
            wks.from_list(0, th_vals, lname="Theta_deg", axis="X")
            wks.from_list(1, r_vals, lname=s.name, axis="Y")
            wks.cols_axis("XY")

            ob.activate_layer(op, gp, 1)
            p_p = gl.add_plot(wks, coly=1, colx=0, type=192)
            p_idx_1 = len(gl.plot_list())
            c_hex = ot.normalize_hex(s.color or fb_cols[s_idx % len(fb_cols)])
            plotted_pol.append((p_idx_1, p_p, s, c_hex))

        ob.activate_layer(op, gp, 1)
        try:
            gl.group(False)
        except Exception:
            pass

        leg_entries: List[Tuple[Any, ...]] = []
        for p_idx_1, _p_p, s, c_hex in plotted_pol:
            c_lt = ot.hex_to_origin_rgb_int(c_hex)
            ls_raw = str(s.line_style or "solid").strip().lower()
            has_ln = ls_raw not in ("none", "", "false")
            d_c = _line_style_code(ls_raw)
            raw_lw = float(s.line_width_pt or spec["curve_lw_pt"])
            cw_u = int(spec["curve_w_units"]) if abs(raw_lw - 2.8) < 0.4 else max(300, int(round(raw_lw * 500.0)))
            m_sh, m_in = _marker_cmd_and_interior(s.marker_style)
            if not has_ln and m_sh is None:
                m_sh, m_in = 2, 1
            ln_cmd = f"set rp -l 1; set rp -d {d_c}; set rp -w {cw_u};" if has_ln else "set rp -l 0;"
            if m_sh is not None:
                mk_sz = float(s.marker_size_pt or spec["marker_size_pt"])
                kf_code = 1 if int(m_in) == 2 else 0
                sym_cmd = f"set rp -k {int(m_sh)}; set rp -kf {kf_code}; set rp -z {mk_sz};"
            else:
                sym_cmd = "set rp -z 0;"
            gl.lt_exec(f"range rp = !{p_idx_1}; set rp -c {c_lt}; set rp -cl {c_lt}; {ln_cmd} {sym_cmd}")

            if not s.meta.get("skip_legend"):
                sw_k = (
                    ("open_circle" if m_in == 2 else "line_sphere")
                    if (has_ln and m_sh is not None)
                    else (("line_dashed" if d_c == 1 else "line") if has_ln else "scatter")
                )
                leg_entries.append((p_idx_1, s.name, c_hex, sw_k))

        scale_min = min(pw / 10.4, ph / 7.8)
        side_in = round(4.45 * scale_min, 4)
        left_in = round(0.5 * (pw - side_in), 4)
        top_in = round(0.96 * (ph / 7.8), 4)
        ob.set_graph_page_inches(gp, pw, ph)
        ob.activate_layer(op, gp, 1)

        if panel.y1_axis.limits is not None:
            r_lo, r_max = float(panel.y1_axis.limits[0]), float(panel.y1_axis.limits[1])
            r_step = panel.y1_axis.major_step or ob.compute_nice_linear_step(r_lo, r_max, max_ticks=4) or ((r_max - r_lo) / 3.0)
        else:
            r_lo = min(0.0, min(all_r_vals, default=0.0))
            raw_hi = max(all_r_vals, default=1.0)
            if raw_hi <= r_lo:
                raw_hi = r_lo + 1.0
            r_step = panel.y1_axis.major_step or ob.compute_nice_linear_step(r_lo, raw_hi * 1.08, max_ticks=4) or ((raw_hi - r_lo) / 3.0)
            r_max = math.ceil((raw_hi * 1.06) / r_step) * r_step if r_lo == 0.0 else (raw_hi + 0.08 * (raw_hi - r_lo))

        tk_base = min(float(spec["tick_label_pt"]), 20.5 * (ph / 7.8))
        comp_tk = ot.compensate_origin_layer_pt(tk_base, side_in, side_in, pw, ph)
        f_cmd = (
            f"layer.x.label.font={f_id}; layer.x2.label.font={f_id}; "
            f"layer.y.label.font={f_id}; layer.y2.label.font={f_id}; "
            if f_id > 0
            else ""
        )

        gl.lt_exec(
            f"layer.unit=2; layer.left={left_in}; layer.top={top_in}; layer.width={side_in}; layer.height={side_in}; "
            f"layer.x.from=0; layer.x.to=360; layer.x.inc=45; layer.x2.inc=45; "
            f"layer.x.thickness={bt}; layer.x2.thickness={bt}; layer.x.color={ink_int}; layer.x2.color={ink_int}; "
            f"layer.x.label.pt={comp_tk}; layer.x2.label.pt={comp_tk}; "
            f"layer.x.label.bold={bold_i}; layer.x2.label.bold={bold_i}; "
            f"layer.x.label.color={ink_int}; layer.x2.label.color={ink_int}; "
            f"layer.y.from={r_lo}; layer.y.to={r_max}; layer.y.inc={r_step}; "
            f"layer.y.showAxes=0; layer.y.ticks=0; layer.y.showLabels=0; "
            f"layer.y2.showAxes=0; layer.y2.ticks=0; layer.y2.showLabels=0; "
            f"layer.y.grid.show=1; layer.x.grid.show=1; "
            f"{f_cmd}"
            f"XB.show=0; YL.show=0; XT.show=0; YR.show=0; label -r Legend;"
        )
        for go in list(gl.obj.GraphObjects):
            gnm = getattr(go, "Name", "")
            if gnm in ("BBUTN1", "Legend", "YL", "XB", "XT", "YR", "label") or "BUTN" in gnm.upper():
                try:
                    go.Destroy()
                except Exception:
                    pass

        if panel.y1_axis.label:
            ob.add_page_text_label(
                op, gp, gl, 1, "PolarRadialTitle", panel.y1_axis.label,
                50.0, 91.5,
                fontsize=min(float(spec["axis_title_pt"]), 24.0 * (ph / 7.8)),
                color_int=ink_int, pos_scatter=0, format_math=True,
            )

        if panel.legend_style != "none" and leg_entries:
            ob.configure_custom_legend(
                gl,
                leg_entries,
                fontsize=min(float(spec["legend_pt"]), 19.5 * (ph / 7.8)),
                horizontal=False,
                pos_mode="page_upper_right",
                layer_rect_pct=(63.5, 3.8, 33.5, 24.0),
                op=op,
                gp=gp,
                layer_num_1based=1,
            )
        return gp

    # Cartesian Equal-Aspect Radar Web (`panel.coord == "radar"`)
    gp = op.new_graph(lname=page_lname)
    ob.set_graph_page_inches(gp, pw, ph)
    gl = gp[0]
    ob.activate_layer(op, gp, 1)

    scale_min = min(pw / 10.4, ph / 7.8)
    side_in = round(4.80 * scale_min, 4)
    left_in = round(0.5 * (pw - side_in) - 0.20 * (pw / 10.4), 4)
    top_in = round(1.22 * (ph / 7.8), 4)
    rect_rad_pct = ot.rect_in_to_page_pct(left_in, top_in, side_in, side_in, pw, ph)

    cats = list(
        panel.x_axis.categories
        or next((ly.categories for ly in panel.layers if ly.categories), None)
        or ([str(v) for v in all_series[0].x] if (all_series and all_series[0].x) else ["Dim 1", "Dim 2", "Dim 3", "Dim 4", "Dim 5"])
    )
    n_spokes = max(3, len(cats))
    thetas = [math.pi / 2.0 - 2.0 * math.pi * k / float(n_spokes) for k in range(n_spokes)]

    all_y_rad = [float(v) for s in all_series for v in (s.y or []) if isinstance(v, (int, float))]
    if panel.y1_axis.limits is not None:
        r_min_v, r_max_v = float(panel.y1_axis.limits[0]), float(panel.y1_axis.limits[1])
    elif all_y_rad and max(all_y_rad) > 1.05:
        r_min_v = 0.0
        r_max_v = 100.0 if max(all_y_rad) <= 100.0 else math.ceil(max(all_y_rad) / 10.0) * 10.0
    else:
        r_min_v, r_max_v = 0.0, 1.0
    r_span_v = max(r_max_v - r_min_v, 1e-9)

    wb = op.new_book("w", lname=f"{page_lname}_Radar")
    wks_web = wb[0]
    wks_web.name = "RadarWeb"
    web_cols: List[Tuple[str, str, List[float]]] = []
    ring_fracs = (0.25, 0.50, 0.75, 1.00)
    for rf_i, rf in enumerate(ring_fracs, start=1):
        rx_l = [rf * math.cos(th) for th in thetas] + [rf * math.cos(thetas[0])]
        ry_l = [rf * math.sin(th) for th in thetas] + [rf * math.sin(thetas[0])]
        web_cols.append(("X", f"Ring{rf_i}_X", rx_l))
        web_cols.append(("Y", f"Ring{rf_i}_Y", ry_l))
    for sp_k, th in enumerate(thetas, start=1):
        web_cols.append(("X", f"Spoke{sp_k}_X", [0.0, math.cos(th)]))
        web_cols.append(("Y", f"Spoke{sp_k}_Y", [0.0, math.sin(th)]))

    wks_web.cols = len(web_cols)
    for ci, (ax_r, c_nm, c_vs) in enumerate(web_cols):
        wks_web.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
    wks_web.cols_axis("".join(c[0] for c in web_cols))

    grid_oc = ob._hex_to_origin_color(op, "#CBD5E1")
    outer_oc = ob._hex_to_origin_color(op, "#94A3B8")
    grid_w = max(350, int(round(0.65 * float(spec["sub_w_units"]))))
    outer_w = max(550, int(spec["sub_w_units"]))
    for seg_i in range(len(web_cols) // 2):
        p_w = gl.add_plot(wks_web, coly=2 * seg_i + 1, colx=2 * seg_i, type="l")
        is_outer = seg_i == 3
        p_w.color = outer_oc if is_outer else grid_oc
        p_idx_w = len(gl.plot_list())
        gl.lt_exec(f"range rw = !{p_idx_w}; set rw -w {outer_w if is_outer else grid_w}; set rw -d 0;")

    # Model polygons: subtle translucent interior fill + crisp closed stroke & 2D circle vertices
    wks_mod = wb.add_sheet("Models")
    mod_cols: List[Tuple[str, str, List[float]]] = []
    mod_plan: List[Dict[str, Any]] = []
    for s_idx, s in enumerate(all_series):
        yv_s = [float(v) for v in (s.y or [])]
        if len(yv_s) < n_spokes:
            continue
        r_norms = [max(0.0, min(1.05, (yv_s[k] - r_min_v) / r_span_v)) for k in range(n_spokes)]
        px_l = [r_norms[k] * math.cos(thetas[k]) for k in range(n_spokes)] + [r_norms[0] * math.cos(thetas[0])]
        py_l = [r_norms[k] * math.sin(thetas[k]) for k in range(n_spokes)] + [r_norms[0] * math.sin(thetas[0])]
        xg_b, yup_b, ylo_b = _compute_polygon_vertical_band(px_l, py_l, n_grid=140)
        c_hex = ot.normalize_hex(s.color or fb_cols[s_idx % len(fb_cols)])
        c_bx = len(mod_cols)
        mod_cols.append(("X", f"M{s_idx+1}_BX", xg_b))
        mod_cols.append(("Y", f"M{s_idx+1}_BUp", yup_b))
        mod_cols.append(("Y", f"M{s_idx+1}_BLo", ylo_b))
        c_px = len(mod_cols)
        mod_cols.append(("X", f"M{s_idx+1}_PX", px_l))
        mod_cols.append(("Y", s.name, py_l))
        mod_plan.append({"name": s.name, "c_hex": c_hex, "bx": c_bx, "bup": c_bx + 1, "blo": c_bx + 2, "px": c_px, "py": c_px + 1, "s": s})

    if mod_cols:
        wks_mod.cols = len(mod_cols)
        for ci, (ax_r, c_nm, c_vs) in enumerate(mod_cols):
            wks_mod.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
        wks_mod.cols_axis("".join(c[0] for c in mod_cols))

    for mp in mod_plan:
        fill_oc = ob._hex_to_origin_color(op, mp["c_hex"])
        p_up = gl.add_plot(wks_mod, coly=int(mp["bup"]), colx=int(mp["bx"]), type="l")
        up_i = len(gl.plot_list())
        p_lo = gl.add_plot(wks_mod, coly=int(mp["blo"]), colx=int(mp["bx"]), type="l")
        lo_i = len(gl.plot_list())
        p_up.color = fill_oc
        p_lo.color = fill_oc
        p_up.set_fill_area(above=fill_oc, type=9, below=fill_oc)
        p_up.transparency = 84
        p_lo.transparency = 100
        gl.lt_exec(f"range rup = !{up_i}; set rup -w 0; range rlo = !{lo_i}; set rlo -w 0;")

    leg_entries_rad: List[Tuple[Any, ...]] = []
    cw_rad = int(spec["curve_w_units"])
    mk_sz_rad = float(spec["marker_size_pt"]) * 0.92
    for mp in mod_plan:
        s_m: cg.SeriesSpec = mp["s"]
        c_oc = ob._hex_to_origin_color(op, mp["c_hex"])
        p_poly = gl.add_plot(wks_mod, coly=int(mp["py"]), colx=int(mp["px"]), type="y")
        m_i = len(gl.plot_list())
        p_poly.color = c_oc
        d_c = _line_style_code(s_m.line_style)
        gl.lt_exec(f"range rmp = !{m_i}; set rmp -w {cw_rad}; set rmp -d {d_c};")
        p_poly.symbol_kind = 2
        p_poly.symbol_interior = 0
        p_poly.symbol_size = mk_sz_rad
        if not s_m.meta.get("skip_legend"):
            leg_entries_rad.append((m_i, mp["name"], mp["c_hex"], "line_sphere"))

    ob.activate_layer(op, gp, 1)
    gl.lt_exec(
        f"layer.unit=2; layer.left={left_in}; layer.top={top_in}; layer.width={side_in}; layer.height={side_in}; "
        "layer.x.showAxes=0; layer.y.showAxes=0; layer.x.showLabels=0; layer.y.showLabels=0; "
        "layer.x.ticks=0; layer.y.ticks=0; layer.x2.ticks=0; layer.y2.ticks=0; "
        "layer.x.grid.show=0; layer.y.grid.show=0; "
        "XB.show=0; YL.show=0; YR.show=0; XT.show=0; label -r Legend;"
    )
    gl.set_xlim(-1.35, 1.35)
    gl.set_ylim(-1.35, 1.35)
    gl.lt_exec("layer.x.from=-1.35; layer.x.to=1.35; layer.y.from=-1.35; layer.y.to=1.35;")

    # Subtle radial scale labels along top spoke + crisp spoke category labels around radius 1.18
    slate_int = ot.hex_to_origin_rgb_int("#64748B")
    ring_fs = max(5.5, float(spec["tick_label_pt"]) * 0.64)
    for rf in (0.50, 1.00):
        rv_val = r_min_v + rf * r_span_v
        rv_txt = f"{int(round(rv_val))}" if r_max_v >= 10.0 else f"{rv_val:.2g}"
        xf_r = (0.04 - (-1.35)) / 2.70
        yf_r = (1.35 - rf) / 2.70
        ob.add_page_text_label(
            op, gp, gl, 1, f"RadTick_{rf}", rv_txt,
            rect_rad_pct[0] + xf_r * rect_rad_pct[2],
            rect_rad_pct[1] + yf_r * rect_rad_pct[3],
            fontsize=ring_fs, color_int=slate_int, pos_scatter=2, format_math=False,
        )

    spoke_fs = min(float(spec["tick_label_pt"]) * 0.90, 21.0 * (ph / 7.8))
    r_lbl = 1.16
    for k_sp, (cat_nm, th) in enumerate(zip(cats, thetas)):
        cx_sp = r_lbl * math.cos(th)
        cy_sp = r_lbl * math.sin(th)
        xf_s = (cx_sp - (-1.35)) / 2.70
        yf_s = (1.35 - cy_sp) / 2.70
        xp_s = rect_rad_pct[0] + xf_s * rect_rad_pct[2]
        yp_s = rect_rad_pct[1] + yf_s * rect_rad_pct[3]
        if math.cos(th) > 0.22:
            pos_sc_s = 2
        elif math.cos(th) < -0.22:
            pos_sc_s = 1
        else:
            pos_sc_s = 0
            yp_s += -1.0 if math.sin(th) > 0 else 1.2
        ob.add_page_text_label(
            op, gp, gl, 1, f"RadarSpoke_{k_sp+1}", str(cat_nm),
            xp_s, yp_s, fontsize=spoke_fs, color_int=ink_int, pos_scatter=pos_sc_s, format_math=False,
        )

    if panel.legend_style != "none" and leg_entries_rad:
        ob.configure_custom_legend(
            gl,
            leg_entries_rad,
            fontsize=min(float(spec["legend_pt"]), 19.0 * (ph / 7.8)),
            horizontal=False,
            pos_mode="page_upper_right",
            layer_rect_pct=(64.0, 3.5, 33.5, 24.0),
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
    return gp


def _render_multi_track_page(
    op: Any,
    fig_spec: cg.FigureSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    spec = ob.get_active_spec()
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    sx, sy = pw / 10.40, ph / 7.80

    gp = op.new_graph(lname=page_lname)
    ob.set_graph_page_inches(gp, pw, ph)
    wb = op.new_book("w", lname=f"{page_lname}_Tracks")
    used_sheets: set[str] = set()

    tracks = fig_spec.panels
    K = max(1, len(tracks))
    total_left = 1.90 * sx
    total_right = 9.85 * sx
    gap_in = (0.26 if K >= 5 else 0.34) * sx
    top_in = 1.05 * sy
    h_in = 4.85 * sy
    track_w_in = max(0.35 * sx, ((total_right - total_left) - gap_in * max(0, K - 1)) / float(K))

    # Resolve shared depth/vertical `(y_lo, y_hi)` across all K tracks
    all_ys_t: List[float] = []
    for p_t in tracks:
        if p_t.y1_axis.limits is not None:
            all_ys_t.extend([float(p_t.y1_axis.limits[0]), float(p_t.y1_axis.limits[1])])
        for ly_t in p_t.layers:
            for s_t in ly_t.series:
                all_ys_t.extend([float(v) for v in (s_t.y or []) if isinstance(v, (int, float))])
    y_lo_sh = min(all_ys_t) if all_ys_t else 0.0
    y_hi_sh = max(all_ys_t) if all_ys_t else 100.0
    if y_hi_sh <= y_lo_sh:
        y_hi_sh = y_lo_sh + 1.0

    horizons = tracks[0].meta.get("horizons") or fig_spec.meta.get("horizons") or []
    upi_mt = ob._origin_units_per_inch(spec)
    tk_pt_mt = min(float(spec["tick_label_pt"]), 18.5 * sy)
    yl_pt_mt = float(spec["axis_title_pt"])
    track_layout_records: List[Tuple[int, Any, cg.PanelSpec, Tuple[float, float, float, float], Tuple[float, float]]] = []

    for idx_t, pnl in enumerate(tracks):
        cur_lay = idx_t + 1
        gl_t = gp[0] if idx_t == 0 else gp.add_layer(0)
        ob.activate_layer(op, gp, cur_lay)
        left_i = round(total_left + idx_t * (track_w_in + gap_in), 4)
        box_t_in = (left_i, round(top_in, 4), round(track_w_in, 4), round(h_in, 4))
        rect_t_pct = ot.rect_in_to_page_pct(*box_t_in, pw, ph)
        pnl.y1_axis.limits = (y_lo_sh, y_hi_sh)

        # Infer X bounds ahead so cross-track horizon bands span the full track width cleanly beneath data!
        xb_pre, _ = _infer_panel_xy_bounds(pnl, y_axis_filter="y1")
        if horizons:
            hz_sh = ob.unique_origin_short_name(f"HzT{cur_lay}", used_sheets, default="Hz")
            wks_hz = wb[0] if len(used_sheets) == 1 else wb.add_sheet(hz_sh)
            if len(used_sheets) == 1:
                wks_hz.name = hz_sh
            hz_cols: List[Tuple[str, str, List[float]]] = []
            hz_colors: List[str] = []
            for h_i, hz in enumerate(horizons):
                if not isinstance(hz, dict):
                    continue
                d0 = float(hz.get("depth_start", hz.get("start", y_lo_sh)))
                d1 = float(hz.get("depth_end", hz.get("end", y_hi_sh)))
                hz_cols.append(("X", f"HX{h_i+1}", [xb_pre[0] - 0.5 * (xb_pre[1] - xb_pre[0]), xb_pre[1] + 0.5 * (xb_pre[1] - xb_pre[0])]))
                hz_cols.append(("Y", f"HU{h_i+1}", [d0, d0]))
                hz_cols.append(("Y", f"HL{h_i+1}", [d1, d1]))
                hz_colors.append(str(hz.get("color") or "#DCEAFB"))
            if hz_cols:
                wks_hz.cols = len(hz_cols)
                for ci, (ax_r, c_nm, c_vs) in enumerate(hz_cols):
                    wks_hz.from_list(ci, c_vs, lname=c_nm, axis=ax_r)
                wks_hz.cols_axis("".join(c[0] for c in hz_cols))
                for h_i, hc_hex in enumerate(hz_colors):
                    hz_oc = ob._hex_to_origin_color(op, ot.normalize_hex(hc_hex))
                    p_hu = gl_t.add_plot(wks_hz, coly=3 * h_i + 1, colx=3 * h_i, type="l")
                    hu_idx = len(gl_t.plot_list())
                    p_hl = gl_t.add_plot(wks_hz, coly=3 * h_i + 2, colx=3 * h_i, type="l")
                    hl_idx = len(gl_t.plot_list())
                    p_hu.color = hz_oc
                    p_hl.color = hz_oc
                    p_hu.set_fill_area(above=hz_oc, type=9, below=hz_oc)
                    p_hu.transparency = 48
                    p_hl.transparency = 100
                    bdr_hz_oc = ot.hex_to_origin_rgb_int("#94A3B8")
                    gl_t.lt_exec(
                        f"range rhu = !{hu_idx}; set rhu -c {bdr_hz_oc}; set rhu -w 400; set rhu -d 1; "
                        f"range rhl = !{hl_idx}; set rhl -c {bdr_hz_oc}; set rhl -w 400; set rhl -d 1;"
                    )

        for ly_t in pnl.layers:
            _plot_layer_into_glayer(op, gp, gl_t, cur_lay, ly_t, pnl, wb, used_sheets, pal_tmp_dir)

        vis_xb = re.sub(r"\\[A-Za-z+-]+\(([^()]*)\)", r"\1", str(pnl.x_axis.label or ""))
        max_xb_fit = ((track_w_in + 0.24 * sx) * upi_mt) / (0.55 * max(len(vis_xb), 4))
        xb_pt_track = min(float(spec["axis_title_pt"]), 20.5 * sy, max(6.0 if ph < 4.8 else 14.5, max_xb_fit))

        x_b, y_b = _apply_single_axis_layer_style(
            op,
            gp,
            gl_t,
            cur_lay,
            pnl,
            rect_pct=rect_t_pct,
            rect_in=box_t_in,
            axis_title_pt=(yl_pt_mt if idx_t == 0 else xb_pt_track),
            tick_label_pt=tk_pt_mt,
            hide_y_override=(idx_t > 0),
            max_x_ticks_override=3,
        )
        if idx_t == 0 and xb_pt_track < yl_pt_mt:
            ob.style_origin_native_axis_title(
                gl_t, "XB", pnl.x_axis.label, fontsize=xb_pt_track,
                color_int=ot.hex_to_origin_rgb_int(pnl.y1_axis.color or "#111111"),
                op=op, gp=gp, layer_num_1based=1,
            )
        if idx_t > 0:
            ob.activate_layer(op, gp, cur_lay)
            gl_t.lt_exec("layer.y.ticks=1; layer.y.showLabels=0;")

        # Re-lock shared Y & track X bounds after horizon bands
        ob.activate_layer(op, gp, cur_lay)
        xf0_t, xf1_t = (x_b[1], x_b[0]) if pnl.x_axis.invert else (x_b[0], x_b[1])
        yf0_t, yf1_t = (y_lo_sh, y_hi_sh) if not pnl.y1_axis.invert else (y_hi_sh, y_lo_sh)
        gl_t.set_xlim(xf0_t, xf1_t)
        gl_t.set_ylim(yf0_t, yf1_t)
        gl_t.lt_exec(f"layer.x.from={xf0_t}; layer.x.to={xf1_t}; layer.y.from={yf0_t}; layer.y.to={yf1_t}; label -r Legend;")

        if pnl.guides:
            _render_guides_into_glayer(
                op, gp, gl_t, cur_lay, pnl.guides, wb, used_sheets, x_b, y_b,
                rect_pct=rect_t_pct, invert_x=pnl.x_axis.invert, invert_y=pnl.y1_axis.invert,
                log_x=(pnl.x_axis.scale == "log10"), log_y=(pnl.y1_axis.scale == "log10"),
            )

        # Track header label above top spine
        hdr_txt = str(pnl.meta.get("track_name") or pnl.tag or "")
        if hdr_txt:
            y_hdr_t = ((top_in - 0.36 * sy) / ph) * 100.0
            c_hdr_hex = pnl.layers[0].series[0].color if (pnl.layers and pnl.layers[0].series and pnl.layers[0].series[0].color) else "#111111"
            ob.add_page_text_label(
                op, gp, gl_t, cur_lay, f"TrackHdr_{cur_lay}", hdr_txt,
                rect_t_pct[0] + 0.5 * rect_t_pct[2], max(2.2, y_hdr_t),
                fontsize=min(xb_pt_track, 19.5 * sy),
                color_int=ot.hex_to_origin_rgb_int(c_hdr_hex),
                pos_scatter=0, format_math=True,
            )

        track_layout_records.append((cur_lay, gl_t, pnl, rect_t_pct, x_b))

    # Render cross-track horizon labels on whichever track & side (`left`/`right`) maximizes curve clearance!
    if horizons and track_layout_records:
        hz_fs = min(float(spec["callout_pt"]), 15.0 * sy)
        hz_ink = ot.hex_to_origin_rgb_int("#334155")
        for h_i, hz in enumerate(horizons):
            if not isinstance(hz, dict) or not hz.get("label"):
                continue
            d_s = float(hz.get("depth_start", hz.get("start", y_lo_sh)))
            d_e = float(hz.get("depth_end", hz.get("end", y_hi_sh)))
            d_lo_h, d_hi_h = min(d_s, d_e), max(d_s, d_e)
            d_mid = 0.5 * (d_lo_h + d_hi_h)
            d_pad = 0.04 * (y_hi_sh - y_lo_sh)

            best_cand: Optional[Tuple[float, int, Any, Tuple[float, float, float, float], str, cg.PanelSpec]] = None
            for t_idx_0, (c_lay, gl_cand, pnl_cand, r_pct_cand, xb_cand) in enumerate(track_layout_records):
                xfs_band: List[float] = []
                for ly_c in pnl_cand.layers:
                    for s_c in ly_c.series:
                        xs_c = list(s_c.x or [])
                        ys_c = list(s_c.y or [])
                        for k_pt in range(len(ys_c)):
                            xv_c, yv_c = xs_c[k_pt], ys_c[k_pt]
                            if isinstance(xv_c, (int, float)) and isinstance(yv_c, (int, float)):
                                if (d_lo_h - d_pad) <= float(yv_c) <= (d_hi_h + d_pad):
                                    xfs_band.append(
                                        ob._map_data_to_frac(float(xv_c), xb_cand[0], xb_cand[1], pnl_cand.x_axis.invert, pnl_cand.x_axis.scale == "log10")
                                    )
                        # Also interpolate segment crossings at d_mid so sparse profiles are accurately scored
                        for k_pt in range(len(ys_c) - 1):
                            y0_c, y1_c = float(ys_c[k_pt]), float(ys_c[k_pt + 1])
                            if (y0_c <= d_mid <= y1_c) or (y1_c <= d_mid <= y0_c):
                                t_int = 0.5 if abs(y1_c - y0_c) < 1e-9 else (d_mid - y0_c) / (y1_c - y0_c)
                                x_int = float(xs_c[k_pt]) + t_int * (float(xs_c[k_pt + 1]) - float(xs_c[k_pt]))
                                xfs_band.append(
                                    ob._map_data_to_frac(x_int, xb_cand[0], xb_cand[1], pnl_cand.x_axis.invert, pnl_cand.x_axis.scale == "log10")
                                )
                left_clear = min(xfs_band) if xfs_band else 0.85
                right_clear = min(1.0 - v for v in xfs_band) if xfs_band else 0.85
                tie_bonus = 0.03 * (t_idx_0 / max(1, K - 1))
                for side_nm, clr_v in (("right", right_clear), ("left", left_clear)):
                    score_c = clr_v + tie_bonus
                    if best_cand is None or score_c > best_cand[0]:
                        best_cand = (score_c, c_lay, gl_cand, r_pct_cand, side_nm, pnl_cand)

            if best_cand is not None:
                _sc, chosen_lay, chosen_gl, chosen_rpct, chosen_side, chosen_pnl = best_cand
                frac_top_h = (
                    (d_mid - y_lo_sh) / max(y_hi_sh - y_lo_sh, 1e-6)
                    if chosen_pnl.y1_axis.invert
                    else (y_hi_sh - d_mid) / max(y_hi_sh - y_lo_sh, 1e-6)
                )
                yp_hz = chosen_rpct[1] + frac_top_h * chosen_rpct[3]
                if chosen_side == "right":
                    xp_hz = chosen_rpct[0] + chosen_rpct[2] - 0.75
                    pos_hz = 1
                else:
                    xp_hz = chosen_rpct[0] + 0.75
                    pos_hz = 2
                ob.add_page_text_label(
                    op, gp, chosen_gl, chosen_lay, f"HzLbl_{h_i+1}", str(hz["label"]),
                    xp_hz, yp_hz, fontsize=hz_fs, color_int=hz_ink, pos_scatter=pos_hz, format_math=False,
                )

    return gp


def _render_single_panel_page(
    op: Any,
    panel: cg.PanelSpec,
    page_lname: str,
    pal_tmp_dir: Path,
) -> Any:
    coord_mode = str(getattr(panel, "coord", "cartesian") or "cartesian").strip().lower()
    if coord_mode == "ternary" or any(ly.mark == "ternary_scatter" for ly in panel.layers):
        return _render_ternary_page(op, panel, page_lname, pal_tmp_dir)
    if coord_mode in ("polar", "radar") or any(ly.mark == "polar_line" for ly in panel.layers):
        return _render_polar_radar_page(op, panel, page_lname, pal_tmp_dir)

    if panel.y2_axis is not None and any(ly.y_axis == "y2" for ly in panel.layers):
        return _render_dual_y_panel_page(op, panel, page_lname, pal_tmp_dir)

    if any(ly.mark in ("contour_pseudocolor", "matrix_heatmap") for ly in panel.layers):
        dummy_fig = cg.FigureSpec(title=page_lname, mode="contour_pseudocolor_2d", panels=[panel])
        return _render_contour_2d_page(op, dummy_fig, panel, None, page_lname, pal_tmp_dir)

    spec = ob.get_active_spec()
    tpl = _resolve_clean_origin_template(panel.layers)
    gp = op.new_graph(lname=page_lname, template=tpl) if tpl else op.new_graph(lname=page_lname)

    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    sy_pg = ph / 7.80
    at_risk_tbl = panel.meta.get("at_risk_table") if isinstance(panel.meta.get("at_risk_table"), dict) else None
    has_at_risk = bool(at_risk_tbl and at_risk_tbl.get("times") and at_risk_tbl.get("rows"))
    linked_top = getattr(panel.x_axis, "linked_top", None)
    has_linked_top = isinstance(linked_top, dict) and bool(linked_top.get("formula"))

    if has_at_risk and at_risk_tbl is not None:
        t_ar_list = [float(v) for v in at_risk_tbl["times"]]
        if len(t_ar_list) >= 2 and panel.x_axis.major_step is None:
            dt_ar = round(t_ar_list[1] - t_ar_list[0], 8)
            if dt_ar > 0:
                panel.x_axis.major_step = dt_ar
        if panel.x_axis.limits is None and t_ar_list:
            max_data_t = max(
                (max((float(v) for v in (s.x or [0.0])), default=0.0) for ly in panel.layers for s in ly.series),
                default=t_ar_list[-1],
            )
            x_lo_ar = min(0.0, min(t_ar_list))
            x_hi_ar = max(max(t_ar_list), max_data_t)
            panel.x_axis.limits = (x_lo_ar, x_hi_ar + 0.025 * max(x_hi_ar - x_lo_ar, 1.0))

    forest_max_y_len = max(
        (
            max((len(str(c)) for c in (panel.y1_axis.categories or ly.categories or [])), default=0)
            for ly in panel.layers
            if ly.mark == "forest_ci"
        ),
        default=0,
    )
    if has_at_risk and at_risk_tbl is not None:
        max_arm_ch_pre = max((len(str(r.get("name", ""))) for r in at_risk_tbl.get("rows", [])), default=8)
        sx_pg = pw / 10.40
        base_l = float(spec["box_rect_left_in"])
        base_w = float(spec["box_rect_w_in"])
        left_ar = max(base_l, min(2.68 * sx_pg, (0.62 + 0.125 * max_arm_ch_pre) * sx_pg))
        w_ar = max(4.20 * sx_pg, base_l + base_w - left_ar)
        box_in = (
            round(left_ar, 4),
            round(0.72 * sy_pg, 4),
            round(w_ar, 4),
            round(3.65 * sy_pg, 4),
        )
    elif has_linked_top:
        box_in = (
            float(spec["box_rect_left_in"]),
            round(1.52 * sy_pg, 4),
            float(spec["box_rect_w_in"]),
            round(4.28 * sy_pg, 4),
        )
    elif forest_max_y_len >= 12 and pw >= 6.0:
        left_f = min(3.15, max(2.55, 0.55 + 0.13 * forest_max_y_len))
        w_f = max(5.40, 8.55 - left_f)
        box_in = (
            round(left_f, 3),
            float(spec["box_rect_top_in"]),
            round(w_f, 3),
            float(spec["box_rect_h_in"]),
        )
    else:
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

    # Re-assert canvas inches after plotting (some Origin statistical templates reset page dimensions)
    ob.set_graph_page_inches(gp, pw, ph)

    has_stacked_100 = any(ly.mark == "bar_stacked_100pct" for ly in panel.layers if ly.y_axis == "y1")
    has_stacked = any(ly.mark in ("bar_stacked", "bar_stacked_100pct") for ly in panel.layers)
    has_stat = any(ly.mark in ("stat_distribution", "stat_box_jitter", "violin_box") for ly in panel.layers)
    has_volcano = any(ly.layer_id == "volcano_main" for ly in panel.layers) or bool(panel.meta.get("point_callouts"))
    has_dense_guides = sum(1 for g in panel.guides if g.kind in ("hline", "span_v")) >= 3
    n_leg = len(all_leg)
    want_leg = (panel.legend_style != "none") and bool(all_leg)
    use_interior_top_leg = (
        (has_stacked or has_volcano or (has_stat and n_leg <= 7) or (has_dense_guides and n_leg <= 4 and not panel.insets))
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
            rect_pct=rect_for_leg,
            invert_x=panel.x_axis.invert,
            invert_y=panel.y1_axis.invert,
            log_x=(panel.x_axis.scale == "log10"),
            log_y=(panel.y1_axis.scale == "log10"),
        )

    pt_callouts = panel.meta.get("point_callouts")
    if isinstance(pt_callouts, list) and pt_callouts:
        _render_point_callouts_into_glayer(
            op,
            gp,
            gl,
            1,
            pt_callouts,
            wb,
            used_sheets,
            x_bounds,
            y_bounds,
            rect_for_leg,
            invert_x=panel.x_axis.invert,
            log_x=(panel.x_axis.scale == "log10"),
            log_y=(panel.y1_axis.scale == "log10"),
            top_reserved_pct=(8.5 if use_interior_top_leg else 4.2),
        )

    # Re-lock exact axis bounds after guide/leader `add_plot` calls (prevents ViolinBox / template auto-rescale drift!)
    if not has_stacked_100:
        ob.activate_layer(op, gp, 1)
        xf0, xf1 = (x_bounds[1], x_bounds[0]) if panel.x_axis.invert else (x_bounds[0], x_bounds[1])
        yf0, yf1 = (y_bounds[1], y_bounds[0]) if panel.y1_axis.invert else (y_bounds[0], y_bounds[1])
        gl.set_xlim(xf0, xf1)
        gl.set_ylim(yf0, yf1)
        gl.lt_exec(f"layer.x.from={xf0}; layer.x.to={xf1}; layer.y.from={yf0}; layer.y.to={yf1};")
        _apply_axis_breaks_if_any(gl, panel, x_bounds, y_bounds)

    # Nonlinear Formula-Linked Top X Axis (`panel.x_axis.linked_top`)
    if has_linked_top and isinstance(linked_top, dict):
        ob.activate_layer(op, gp, 1)
        gl.lt_exec("layer.x.showAxes=1; layer.y.showAxes=3;")
        raw_formula = str(linked_top.get("formula") or "1239.84193/x").strip()
        expr_x1 = re.sub(r"\b[xX]\b", "X1", raw_formula)
        expr_x2 = re.sub(r"\b[xX]\b", "X2", raw_formula)
        gp.activate()
        op.lt_exec(
            f"layadd userdef:=1 bottom:=0 top:=1 left:=0 right:=0 linkto:=1 xaxis:=custom x1:={expr_x1} x2:={expr_x2};"
        )
        lay_tx_num = int(gp.obj.Layers.Count)
        gl_tx = gp[lay_tx_num - 1]
        ob.activate_layer(op, gp, lay_tx_num)
        bt_tx = float(spec["box_lw_pt"])
        ink_tx = ot.hex_to_origin_rgb_int(panel.y1_axis.color or "#111111")
        fid_tx = ob.get_font_id(op)
        bold_tx = int(spec["bold_int"])
        comp_tk_tx = ot.compensate_origin_layer_pt(float(spec["tick_label_pt"]), box_in[2], box_in[3], pw, ph)
        f_tx_clause = f"layer.x.label.font={fid_tx}; layer.x2.label.font={fid_tx}; " if fid_tx > 0 else ""
        gl_tx.lt_exec(
            f"layer.x.grid.show=0; layer.y.grid.show=0; "
            f"layer.x.thickness={bt_tx}; layer.x2.thickness={bt_tx}; "
            f"layer.x.color={ink_tx}; layer.x2.color={ink_tx}; "
            f"layer.x.ticks=1; layer.x2.ticks=1; "
            f"layer.x.showMinorTicks=0; layer.x2.showMinorTicks=0; "
            f"layer.x.maxTicks=5; layer.x2.maxTicks=5; "
            f"{f_tx_clause}"
            f"layer.x.label.pt={comp_tk_tx}; layer.x2.label.pt={comp_tk_tx}; "
            f"layer.x.label.bold={bold_tx}; layer.x2.label.bold={bold_tx}; "
            f"layer.x.label.color={ink_tx}; layer.x2.label.color={ink_tx}; "
            f"XB.show=0; XT.show=0; YL.show=0; YR.show=0; label -r Legend;"
        )
        try:
            xf0_cur = (x_bounds[1] if panel.x_axis.invert else x_bounds[0])
            xf1_cur = (x_bounds[0] if panel.x_axis.invert else x_bounds[1])
            tx1 = _eval_axis_formula(raw_formula, xf0_cur)
            tx2 = _eval_axis_formula(raw_formula, xf1_cur)
            auto_tx_step = linked_top.get("major_step") or ob.compute_nice_linear_step(min(tx1, tx2), max(tx1, tx2), max_ticks=5)
            if auto_tx_step and float(auto_tx_step) > 0:
                gl_tx.lt_exec(f"layer.x.inc={float(auto_tx_step)}; layer.x2.inc={float(auto_tx_step)};")
        except Exception:
            pass
        top_lbl = str(linked_top.get("label") or "").strip()
        if top_lbl:
            ob.style_origin_native_axis_title(
                gl_tx,
                "XT",
                top_lbl,
                fontsize=float(spec["axis_title_pt"]),
                color_int=ink_tx,
                op=op,
                gp=gp,
                layer_num_1based=lay_tx_num,
            )
        ob.activate_layer(op, gp, 1)

    if panel.insets:
        _render_insets_for_panel(op, gp, gl, 1, panel, wb, used_sheets, pal_tmp_dir, x_bounds, y_bounds)
        if panel.equal_aspect and panel.insets:
            _draw_zoom_connectors(op, gp, gl, 1, panel, panel.insets, x_bounds, y_bounds, wb, used_sheets)

    # Configure main layer custom legend STRICTLY INSIDE plot box!
    chosen_leg_corner = "corner_upper_right"
    if not want_leg:
        ob.activate_layer(op, gp, 1)
        gl.lt_exec("label -r Legend;")
    elif use_interior_top_leg:
        chosen_leg_corner = "interior_top"
        ob.configure_custom_legend(
            gl,
            all_leg,
            fontsize=(20.0 if n_leg >= 5 and ph >= 4.8 else float(spec["legend_pt"])),
            horizontal=True,
            pos_mode="interior_top",
            layer_rect_pct=rect_for_leg,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
    else:
        pos_m = _pick_cleanest_legend_corner(panel, x_bounds, y_bounds)
        chosen_leg_corner = pos_m
        ob.configure_custom_legend(
            gl,
            all_leg,
            fontsize=(19.5 if n_leg >= 6 and ph >= 4.8 else float(spec["legend_pt"])),
            pos_mode=pos_m,
            layer_rect_pct=rect_for_leg,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )

    # Kaplan-Meier Aligned `Number at risk` Table + `Log-rank p / HR` Summary Block
    if has_at_risk and at_risk_tbl is not None:
        ink_ar = ot.hex_to_origin_rgb_int("#111111")
        times_ar = [float(t) for t in at_risk_tbl["times"]]
        rows_ar = list(at_risk_tbl["rows"])
        n_arms_ar = max(1, len(rows_ar))
        arm_color_lookup = {
            str(s.name): ot.normalize_hex(s.color or "#111111")
            for ly in panel.layers
            for s in ly.series
        }
        fb_ar_cols = [ot.normalize_hex(ent[2]) for ent in all_leg] if all_leg else ["#2B6CB0", "#D84B5C", "#2F855A"]
        hdr_fs = min(float(spec["callout_pt"]), 18.5 * sy_pg)
        cnt_fs = min(float(spec["tick_label_pt"]) * 0.80, 18.5 * sy_pg)
        max_arm_ch = max((len(str(r.get("name", ""))) for r in rows_ar), default=8)
        upi_ar = ob._origin_units_per_inch(spec)
        avail_arm_w_in = max(0.55 * (pw / 10.4), pw * ((rect_for_leg[0] - 5.4) / 100.0))
        fit_arm_fs = (avail_arm_w_in * upi_ar) / max(0.54 * max_arm_ch, 1.0)
        arm_lbl_fs = min(cnt_fs * 0.86, 15.0 * sy_pg, max(5.5 if ph < 4.8 else 12.0, fit_arm_fs))

        lx_hdr_pct = max(2.2, rect_for_leg[0] - min(rect_for_leg[0] - 2.2, (0.54 * max_arm_ch * arm_lbl_fs / upi_ar / pw) * 100.0 + 3.2))
        y_hdr_pct = ((5.72 * sy_pg) / ph) * 100.0
        ob.add_page_text_label(
            op, gp, gl, 1, "AtRiskHdr", "Number at risk",
            lx_hdr_pct, y_hdr_pct, fontsize=hdr_fs, color_int=ink_ar, pos_scatter=2, format_math=False,
        )
        row_dy_in = min(0.44, 1.24 / float(n_arms_ar))
        x_span_ar = max(x_bounds[1] - x_bounds[0], 1e-6)
        for r_idx, r_dict in enumerate(rows_ar):
            arm_nm = str(r_dict.get("name", f"Arm {r_idx+1}"))
            arm_hex = ot.normalize_hex(str(r_dict.get("color") or arm_color_lookup.get(arm_nm, fb_ar_cols[r_idx % len(fb_ar_cols)])))
            arm_int = ot.hex_to_origin_rgb_int(arm_hex)
            y_row_pct = (((6.18 + r_idx * row_dy_in) * sy_pg) / ph) * 100.0
            ob.add_page_text_label(
                op, gp, gl, 1, f"AtRiskArm_{r_idx+1}", arm_nm,
                rect_for_leg[0] - 3.2, y_row_pct, fontsize=arm_lbl_fs, color_int=arm_int, pos_scatter=1, format_math=False,
            )
            for t_idx, (t_val, c_val) in enumerate(zip(times_ar, r_dict.get("counts", []))):
                xf_t = (t_val - x_bounds[0]) / x_span_ar
                if -0.02 <= xf_t <= 1.02:
                    xp_cnt = rect_for_leg[0] + xf_t * rect_for_leg[2]
                    ob.add_page_text_label(
                        op, gp, gl, 1, f"AtRiskCnt_{r_idx+1}_{t_idx+1}", f"{int(c_val)}",
                        xp_cnt, y_row_pct, fontsize=cnt_fs, color_int=ink_ar, pos_scatter=0, format_math=False,
                    )

    km_sum_lines = panel.meta.get("km_summary_lines")
    if isinstance(km_sum_lines, list) and km_sum_lines:
        sum_fs = min(float(spec["callout_pt"]) * 0.86, 17.5 * sy_pg)
        sum_ink = ot.hex_to_origin_rgb_int("#1E293B")
        line_dy_pct = max(3.6, (0.36 * sy_pg / ph) * 100.0)
        # Check lower-left occupancy (`fx < 0.46, fy < 0.36`): KM curves start at `(0, 1.0)` top-left, so lower-left is almost always pristine!
        ll_hits = 0
        for ly_k in panel.layers:
            for s_k in ly_k.series:
                for xv_k, yv_k in zip(s_k.x or [], s_k.y or []):
                    if isinstance(xv_k, (int, float)) and isinstance(yv_k, (int, float)):
                        fx_k = ob._map_data_to_frac(float(xv_k), x_bounds[0], x_bounds[1], panel.x_axis.invert, False)
                        fy_k = ob._map_data_to_frac(float(yv_k), y_bounds[0], y_bounds[1], False, False)
                        if fx_k < 0.46 and fy_k < 0.34:
                            ll_hits += 1
        if ll_hits == 0 and chosen_leg_corner != "corner_lower_left":
            sx_pct = rect_for_leg[0] + 2.4
            sy0_pct = rect_for_leg[1] + rect_for_leg[3] - (len(km_sum_lines) - 1) * line_dy_pct - 4.4
            pos_km = 2
        else:
            sx_pct = rect_for_leg[0] + rect_for_leg[2] - 2.2
            leg_offset_pct = (len(all_leg) * 4.8 + 5.5) if chosen_leg_corner == "corner_upper_right" else 4.5
            sy0_pct = rect_for_leg[1] + leg_offset_pct
            pos_km = 1
        for k_li, k_txt in enumerate(km_sum_lines):
            ob.add_page_text_label(
                op, gp, gl, 1, f"KMSum_{k_li+1}", _format_origin_guide_text(str(k_txt)),
                sx_pct, sy0_pct + k_li * line_dy_pct, fontsize=sum_fs, color_int=sum_ink, pos_scatter=pos_km, format_math=False,
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
                rect_pct=rect,
                invert_x=panel.x_axis.invert,
                invert_y=panel.y1_axis.invert,
                log_x=(panel.x_axis.scale == "log10"),
                log_y=(panel.y1_axis.scale == "log10"),
            )
        pt_call_sub = panel.meta.get("point_callouts")
        if isinstance(pt_call_sub, list) and pt_call_sub:
            _render_point_callouts_into_glayer(
                op,
                gp,
                gl_p,
                cur_lay_num,
                pt_call_sub,
                wb,
                used_sheets,
                x_b,
                y_b,
                rect,
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
        tag_case = str(ob.get_active_spec().get("panel_tag_case", "paren_lower")).lower()
        if tag_raw.startswith("("):
            tag_txt = tag_raw
        elif tag_case == "lower_bold":
            tag_txt = tag_raw.lower()
        elif tag_case == "upper_bold":
            tag_txt = tag_raw.upper()
        else:
            tag_txt = f"({tag_raw})"
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
    Mode 20+: `xy_fit_and_band` & `dose_response_4pl`
    Supports >= 1 series (including multi-compound 4PL sigmoid curves on `log10` X axis),
    rendering each series' pure 2D circle scatter (`symbol_kind=2, symbol_interior=0`),
    smooth fit curve (`type='l'`), `type=9` 95% CI band, `IC50` drop-line guides, and clean equation/`IC50`/`R²` callouts.
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

    curve_fits = panel.meta.get("curve_fits") if isinstance(panel.meta.get("curve_fits"), list) else []
    n_fit_groups = len(curve_fits)
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

    raw_leg: List[Tuple[Any, ...]] = []
    for ly in panel.layers:
        raw_leg.extend(_plot_layer_into_glayer(op, gp, gl, 1, ly, panel, wb, used_sheets, pal_tmp_dir))

    # For multi-series curve comparison (>= 2 groups, e.g. Compound 1 vs Compound 2), merge scatter + fit into 1 crisp `line_sphere` swatch per group
    if n_fit_groups >= 2:
        all_leg: List[Tuple[Any, ...]] = []
        for cf in curve_fits:
            cf_nm = str(cf.get("name", "Series"))
            cf_col = ot.normalize_hex(str(cf.get("color", "#3E86DE")))
            match_idx = next((ent[0] for ent in raw_leg if cf_nm in str(ent[1])), raw_leg[0][0] if raw_leg else 1)
            all_leg.append((match_idx, cf_nm, cf_col, "line_sphere"))
    else:
        all_leg = raw_leg

    is_4pl = any(isinstance(cf, dict) and cf.get("model") == "dose_response_4pl" for cf in curve_fits)
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
        reserve_top_legend_space=(not is_4pl),
    )
    if is_4pl and panel.y1_axis.limits is None:
        # Clean 0..115% (or min..max*1.12) bounds for 4PL sigmoid curves so upper 100% plateau has neat room without jumping to 140%
        y_hi_4pl = max(108.0, min(118.0, y_bounds[1])) if (y_bounds[1] >= 95.0 and y_bounds[0] >= -15.0) else y_bounds[1]
        y_lo_4pl = min(0.0, y_bounds[0]) if y_bounds[0] >= -5.0 else y_bounds[0]
        y_bounds = (y_lo_4pl, y_hi_4pl)
        gl.set_ylim(y_lo_4pl, y_hi_4pl)
        st_4pl = 20.0 if (y_hi_4pl - y_lo_4pl) >= 85.0 else (ob.compute_nice_linear_step(y_lo_4pl, y_hi_4pl, max_ticks=6) or 20.0)
        gl.lt_exec(f"layer.y.from={y_lo_4pl}; layer.y.to={y_hi_4pl}; layer.y.inc={st_4pl};")

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
            rect_pct=rect_use,
            invert_x=panel.x_axis.invert,
            invert_y=panel.y1_axis.invert,
            log_x=(panel.x_axis.scale == "log10"),
            log_y=(panel.y1_axis.scale == "log10"),
        )

    leg_corner = _pick_cleanest_legend_corner(panel, x_bounds, y_bounds)
    if panel.legend_style != "none" and all_leg:
        ob.configure_custom_legend(
            gl,
            all_leg,
            fontsize=float(spec["legend_pt"]),
            horizontal=False,
            pos_mode=leg_corner,
            layer_rect_pct=rect_use,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
    else:
        ob.activate_layer(op, gp, 1)
        gl.lt_exec("label -r Legend;")

    # Build clean annotation lines (per-compound IC50 + R^2 for multi-series 4PL, or single equation + R^2)
    ann_lines: List[str] = []
    x_unit_match = re.search(r"\(([^()]+)\)\s*$", str(panel.x_axis.label or ""))
    x_unit_tok = (panel.x_axis.unit or (x_unit_match.group(1) if x_unit_match else "")).strip()

    if is_4pl and curve_fits:
        if n_fit_groups >= 2:
            ann_lines.append("4PL IC\\-(50):")
        for cf in curve_fits:
            km = cf.get("key_metrics") or {}
            if "IC50" not in km:
                continue
            ic_v = float(km["IC50"])
            ic_s = f"{ic_v:.3g}"
            u_sfx = f" {x_unit_tok}" if x_unit_tok and len(x_unit_tok) <= 6 else ""
            r2_c = float(cf.get("r2", 0.0))
            if n_fit_groups >= 2:
                ann_lines.append(f"{cf['name']}: {ic_s}{u_sfx}")
            else:
                ann_lines.append(f"IC\\-(50) = {ic_s}{u_sfx},  \\i(R)\\+(2) = {r2_c:.3f}")
    elif n_fit_groups >= 2:
        for cf in curve_fits[:3]:
            r2_c = float(cf.get("r2", 0.0))
            ann_lines.append(f"{cf['name']}: \\i(R)\\+(2) = {r2_c:.4f}")
    elif eq_text or r2_val != "":
        eq_clean = eq_text.replace("R²", "\\i(R)\\+(2)").replace("×", "\\g(\\xD7)")
        eq_clean = re.sub(r"\s*\*\s*(?=[xX]\b)", " ", eq_clean)
        eq_clean = re.sub(r"\s*\*\s*", lambda _: " \\g(\\xD7) ", eq_clean)
        eq_clean = re.sub(r"\^\{([^}]+)\}", lambda m: f"\\+({m.group(1)})", eq_clean)
        eq_clean = re.sub(r"\^(-?\d+(?:\.\d+)?)", lambda m: f"\\+({m.group(1)})", eq_clean)
        eq_clean = re.sub(r"\by\b", lambda _: "\\i(y)", eq_clean)
        eq_clean = re.sub(r"\bx\b", lambda _: "\\i(x)", eq_clean)
        r2_str = f"{float(r2_val):.4f}" if isinstance(r2_val, (int, float)) else str(r2_val)
        if eq_clean and ("R\\+(2)" in eq_clean or "R^2" in eq_clean):
            ann_lines.append(eq_clean)
        elif eq_clean and r2_str:
            ann_lines.append(f"{eq_clean},  \\i(R)\\+(2) = {r2_str}")
        else:
            ann_lines.append(eq_clean or f"\\i(R)\\+(2) = {r2_str}")

    if ann_lines:
        l_p, t_p, w_p, h_p = rect_use
        max_line_len = max(len(ln) for ln in ann_lines)
        eq_fs = min(float(spec["callout_pt"]), 18.0 if (len(ann_lines) >= 2 or max_line_len >= 26) else float(spec["callout_pt"]))
        n_leg_rows = len(all_leg) if (panel.legend_style != "none" and all_leg) else 0
        row_h_pct = max(5.2, float(spec["legend_pt"]) * 0.255)
        line_step_pct = max(4.5, eq_fs * 0.235)

        # For 4PL sigmoid curves with legend at upper-right, place multi-line IC50 readout in the open lower-left quadrant
        # below the 50% dashed line and left of the first IC50 drop-line so text NEVER crosses the sigmoid curves!
        ann_corner = leg_corner
        min_ic_xf = 0.5
        if is_4pl and leg_corner == "corner_upper_right" and len(ann_lines) >= 2:
            ic_xs = [
                float(g.value)
                for g in panel.guides
                if g.kind == "vline" and g.value is not None and g.meta.get("guide_role") == "ic50_drop"
            ]
            min_ic_xf = (
                min(ob._map_data_to_frac(xv, x_bounds[0], x_bounds[1], panel.x_axis.invert, panel.x_axis.scale == "log10") for xv in ic_xs)
                if ic_xs
                else 0.5
            )
            if min_ic_xf >= 0.34:
                ann_corner = "corner_lower_left_standalone"

        if ann_corner == "corner_lower_left_standalone":
            eq_x = l_p + 1.8
            avail_w_pct = max(8.0, min_ic_xf * w_p - 3.6)
            upi_ann = ob._origin_units_per_inch(spec)
            max_vis_ann = max(
                len(re.sub(r"\\[A-Za-z+-]+\(([^()]*)\)", r"\1", str(ln_s))) for ln_s in ann_lines
            )
            est_w_pct = ((0.57 * max_vis_ann + 0.35) * eq_fs / (pw * upi_ann)) * 100.0
            if est_w_pct > avail_w_pct:
                eq_fs = max(13.0, eq_fs * (avail_w_pct / est_w_pct))
                line_step_pct = max(3.6, eq_fs * 0.235)
            base_y = t_p + h_p - len(ann_lines) * line_step_pct - 2.2
            eq_align = 2
        elif leg_corner == "corner_upper_right":
            eq_x, base_y, eq_align = l_p + w_p - 2.3, t_p + 5.0 + n_leg_rows * row_h_pct + 1.3, 1
        elif leg_corner == "corner_lower_right":
            eq_x, base_y, eq_align = (
                l_p + w_p - 2.3,
                max(t_p + 5.0, t_p + h_p - n_leg_rows * row_h_pct - len(ann_lines) * line_step_pct - 2.2),
                1,
            )
        elif leg_corner == "corner_lower_left":
            eq_x, base_y, eq_align = (
                l_p + 2.6,
                max(t_p + 5.0, t_p + h_p - n_leg_rows * row_h_pct - len(ann_lines) * line_step_pct - 2.2),
                2,
            )
        else:
            eq_x, base_y, eq_align = l_p + 2.6, t_p + 5.0 + n_leg_rows * row_h_pct + 1.3, 2

        for ln_i, ln_txt in enumerate(ann_lines):
            ob.add_page_text_label(
                op,
                gp,
                gl,
                1,
                f"FitEqBox_{ln_i+1}",
                ln_txt,
                eq_x,
                base_y + ln_i * line_step_pct,
                fontsize=eq_fs,
                pos_scatter=eq_align,
                format_math=False,
            )

    # Re-lock exact axis bounds after guide plots
    ob.activate_layer(op, gp, 1)
    xf0, xf1 = (x_bounds[1], x_bounds[0]) if panel.x_axis.invert else (x_bounds[0], x_bounds[1])
    yf0, yf1 = (y_bounds[1], y_bounds[0]) if panel.y1_axis.invert else (y_bounds[0], y_bounds[1])
    gl.set_xlim(xf0, xf1)
    gl.set_ylim(yf0, yf1)
    gl.lt_exec(f"layer.x.from={xf0}; layer.x.to={xf1}; layer.y.from={yf0}; layer.y.to={yf1};")

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
    export_pdf: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Render a validated `FigureSpec` natively in OriginPro 2024:
    - Saves full editable `.opju` project (`out_opju` when `fig_spec.build_opju` is True)
    - Exports 600 DPI lossless LZW `.tif` + 300 DPI `.png` + `<=960 px` `_qa_previews/*_preview.jpg`
      (and vector `.pdf` when `export_pdf=True` or `spec.meta.get('export_pdf')` is True)
      via `export_origin_publication_figures` strictly AFTER all styling/Theme/Overlay commits finish.
    """
    spec = fig_spec if isinstance(fig_spec, cg.FigureSpec) else cg.FigureSpec.from_dict(fig_spec)
    ob.set_active_style(spec.theme if spec.theme else spec.style_preset)
    out_p = Path(out_dir).resolve()
    out_p.mkdir(parents=True, exist_ok=True)
    want_pdf = bool(export_pdf) if export_pdf is not None else bool(spec.meta.get("export_pdf", False))

    stem = _sanitize_file_stem(spec.title, default=f"SciOrigin_{spec.mode}")
    opju_target = Path(out_opju).resolve() if out_opju is not None else (out_p / f"{stem}.opju")

    panel_figures: Dict[str, Dict[str, str]] = {}
    all_exported_files: List[str] = []
    graph_names: List[str] = []

    is_bode_dual = (
        spec.mode == "bode_dual_panel"
        or (len(spec.panels) == 2 and any(p.meta.get("bode_panel") for p in spec.panels))
    )
    is_multi_track = (
        spec.mode == "multi_track_profile"
        or any(p.meta.get("multi_track") for p in spec.panels)
    )
    is_xy_fit_band = (
        spec.mode in ("xy_fit_and_band", "dose_response_4pl")
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
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
                    all_exported_files.extend(primary_figures.values())

            elif is_xy_fit_band and len(spec.panels) >= 1:
                gp_main = _render_xy_fit_and_band_page(op, spec.panels[0], stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
                    all_exported_files.extend(primary_figures.values())

            elif is_bode_dual and len(spec.panels) >= 2:
                gp_main = _render_bode_dual_panel_page(op, spec, stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
                    all_exported_files.extend(primary_figures.values())

            elif is_multi_track and len(spec.panels) >= 1:
                gp_main = _render_multi_track_page(op, spec, stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
                    all_exported_files.extend(primary_figures.values())

            elif len(spec.panels) == 1:
                gp_main = _render_single_panel_page(op, spec.panels[0], stem, pal_tmp_dir)
                graph_names.append(gp_main.name)

                primary_figures = {}
                if export_images:
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
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
                    primary_figures = export_origin_publication_figures(op, gp_main, out_p, stem, export_pdf=want_pdf)
                    all_exported_files.extend(primary_figures.values())
                    for pid, sub_stem, gp_sub in standalone_pages:
                        p_figs = export_origin_publication_figures(op, gp_sub, out_p, sub_stem, export_pdf=want_pdf)
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
