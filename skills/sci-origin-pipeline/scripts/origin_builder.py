from __future__ import annotations

import math
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import origin_theme as ot

# Active runtime style specification (Preset 1 TNR Bold by default; switchable to Preset 2 Arial Regular)
_ACTIVE_SPEC: Dict[str, Any] = ot.resolve_runtime_spec()

# Session-scoped overlay registries (cleared on every origin_session start/exit)
_FONT_FACE_CACHE: Dict[Tuple[int, str], int] = {}
_PENDING_AXIS_TITLES: Dict[str, List[Dict[str, Any]]] = {}
_PENDING_TEXT_ITEMS: Dict[str, List[Dict[str, Any]]] = {}
_PENDING_DATA_TEXT_ITEMS: Dict[str, List[Dict[str, Any]]] = {}
_PENDING_LEGENDS: Dict[str, List[Dict[str, Any]]] = {}
_CUSTOM_Y_LABEL_LAYERS: Dict[Tuple[str, int], float] = {}
_FLUSHED_PAGES: set[str] = set()


def set_active_style(theme_or_name: Optional[Dict[str, Any] | str | Path] = None) -> Dict[str, Any]:
    """Set the active style preset (`style_publication_minimal` TNR Bold or `style_arial_clean` Arial Regular)."""
    global _ACTIVE_SPEC
    _ACTIVE_SPEC = ot.resolve_runtime_spec(theme_or_name)
    return _ACTIVE_SPEC


def get_active_spec() -> Dict[str, Any]:
    """Return the active resolved runtime layout, stroke, and font specification."""
    return _ACTIVE_SPEC


def _origin_units_per_inch(spec: Optional[Dict[str, Any]] = None) -> float:
    """
    Calibrated Origin `tr.Label.Size` em-units per physical inch (`Size=19` -> `69 px` cap-height @ 300 DPI,
    corresponding to `~61.5` em-units/in for `Times New Roman` and `~57.5` em-units/in for wider `Arial`).
    """
    s = spec if spec is not None else _ACTIVE_SPEC
    fam = str(s.get("font_family", "Times New Roman")).lower()
    return 57.5 if "arial" in fam else 61.5


def register_custom_y_label_layer(gp: Any, layer_num_1based: int, extra_gap: float = 0.0) -> None:
    """Mark `(gp.name, layer_num_1based)` as carrying custom overlay Y-tick labels even when `layer.y.showLabels=0`."""
    if gp is not None:
        key = (gp.name, int(layer_num_1based))
        _CUSTOM_Y_LABEL_LAYERS[key] = max(_CUSTOM_Y_LABEL_LAYERS.get(key, 0.0), float(extra_gap))


def compute_nice_linear_step(lo: float, hi: float, max_ticks: int = 6) -> Optional[float]:
    """Choose a clean `1 / 2 / 2.5 / 5 × 10^k` major tick increment so `24 pt` tick labels never crowd."""
    a, b = min(float(lo), float(hi)), max(float(lo), float(hi))
    span = b - a
    if not math.isfinite(span) or span <= 1e-12:
        return None
    raw = span / max(2, int(max_ticks) - 1)
    exp10 = 10.0 ** math.floor(math.log10(raw))
    mults = (1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0)
    for m in mults:
        if m in (2.5, 25.0) and span >= 15.0:
            continue
        step = m * exp10
        if step <= 0:
            continue
        first_i = math.ceil((a - 1e-7 * span) / step)
        last_i = math.floor((b + 1e-7 * span) / step)
        n_tks = max(0, last_i - first_i + 1)
        if n_tks <= int(max_ticks):
            return float(round(step, 10))
    return float(round(50.0 * exp10, 10))


_NYQ_4_3_STEPS: Tuple[float, ...] = (
    0.05,
    0.1,
    0.2,
    0.25,
    0.3,
    0.5,
    1.0,
    2.0,
    2.5,
    3.0,
    5.0,
    10.0,
    15.0,
    20.0,
    25.0,
    30.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
    250.0,
    300.0,
    500.0,
    750.0,
    1000.0,
    1500.0,
    2000.0,
    2500.0,
    3000.0,
    5000.0,
    10000.0,
)


def compute_isometric_4_3_bounds(
    max_zr: float,
    max_nzi: float,
) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    """Compute physical 1:1 Ohm/inch `4:3` bounds `((0, 4*step), (0, 3*step), step)` for standard `6.40 x 4.80 in` frame."""
    if max_nzi > 2.2 * max(max_zr, 1.0):
        req_y = min(max_nzi * 1.08, max(900.0, max_zr * 1.45))
        req_x = max(max_zr * 1.08, 1.0)
    else:
        req_x = max(max_zr * 1.08, 1.0)
        req_y = max(max_nzi * 1.08, 1.0)
    need = max(req_x / 4.0, req_y / 3.0, 1e-6)
    step = float(math.ceil(need / 5000.0) * 5000.0)
    for cand in _NYQ_4_3_STEPS:
        if cand + 1e-9 >= need:
            step = float(cand)
            break
    return (0.0, round(4.0 * step, 6)), (0.0, round(3.0 * step, 6)), step


def _reset_session_overlay_state() -> None:
    _FONT_FACE_CACHE.clear()
    _PENDING_AXIS_TITLES.clear()
    _PENDING_TEXT_ITEMS.clear()
    _PENDING_DATA_TEXT_ITEMS.clear()
    _PENDING_LEGENDS.clear()
    _CUSTOM_Y_LABEL_LAYERS.clear()
    _FLUSHED_PAGES.clear()


@contextmanager
def _interprocess_origin_lock(timeout_s: float = 120.0) -> Iterator[None]:
    """Serialize headless OriginPro COM sessions across parallel processes/subagents on Windows."""
    lock_file = Path(tempfile.gettempdir()) / "sciorigin_origin_com.lock"
    fh = open(lock_file, "a+b")
    acquired = False
    t0 = time.time()
    try:
        if os.name == "nt":
            import msvcrt

            while time.time() - t0 < timeout_s:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.35)
            if not acquired:
                raise TimeoutError(f"Timed out waiting {timeout_s}s for OriginPro COM inter-process lock.")
        yield
    finally:
        if acquired and os.name == "nt":
            import msvcrt

            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        fh.close()


@contextmanager
def origin_session() -> Iterator[Any]:
    """Context-managed headless OriginPro COM session with inter-process mutex & retry backoff."""
    import originpro as op

    with _interprocess_origin_lock():
        _reset_session_overlay_state()
        last_err = None
        for attempt in range(3):
            try:
                op.set_show(False)
                op.new()
                break
            except Exception as exc:
                last_err = exc
                time.sleep(0.8 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed to initialize OriginPro COM session after 3 attempts: {last_err}")

        try:
            yield op
        finally:
            _reset_session_overlay_state()
            try:
                op.exit()
            except Exception:
                pass


def _unwrap_origin_cmd_balanced(s: str, prefix: str) -> str:
    """Unwrap balanced Origin escape wrappers like `\\b(...)` or `\\f:Times New Roman(...)`."""
    out = s
    while True:
        idx = out.find(prefix)
        if idx < 0:
            break
        start_inner = idx + len(prefix)
        depth = 1
        pos = start_inner
        while pos < len(out) and depth > 0:
            if out[pos] == "(" and (pos == 0 or out[pos - 1] != "\\"):
                depth += 1
            elif out[pos] == ")" and (pos == 0 or out[pos - 1] != "\\"):
                depth -= 1
            pos += 1
        if depth == 0:
            out = out[:idx] + out[start_inner : pos - 1] + out[pos:]
        else:
            break
    return out


def prepare_plot_label_rich_text(raw_text: str, format_math: bool = True) -> str:
    """
    Prepare clean Origin `tr.Label` rich text (`\\i(...)`, `\\-(...)`, `\\+(...)`, `\\g(...)`)
    for `Form=4` (`PLOTLABEL_UI_FORM_CUSTOM`) rendering with active `Face` and `Bold` settings.
    """
    s = str(raw_text or "").strip()
    if not s:
        return ""
    s = _unwrap_origin_cmd_balanced(s, "\\f:Times New Roman(")
    s = _unwrap_origin_cmd_balanced(s, "\\f:Arial(")
    s = _unwrap_origin_cmd_balanced(s, "\\b(")
    if format_math:
        s = ot.format_origin_axis_title(s, bold=False)
    s = re.sub(r"\bOhm\b", lambda _: "\\g(W)", s)
    s = s.replace("-CF2-", "-CF\\-(2)-").replace("-CF3", "-CF\\-(3)")
    s = _unwrap_origin_cmd_balanced(s, "\\f:Times New Roman(")
    s = _unwrap_origin_cmd_balanced(s, "\\f:Arial(")
    s = _unwrap_origin_cmd_balanced(s, "\\b(")
    return s.strip()


def origin_rgb_int(r: int, g: int, b: int) -> int:
    """Encode (r, g, b) to Origin LabTalk color integer; map pure (0,0,0) -> (1,1,1) to avoid Origin's green-black bug."""
    return ot.origin_rgb_int(r, g, b)


def sanitize_origin_short_name(name: str, default: str = "Sheet1", max_len: int = 24) -> str:
    """Return an ASCII alphanumeric Origin short name (no underscores, which Origin silently renames)."""
    cleaned = "".join(ch for ch in (name or "") if ch.isascii() and ch.isalnum())
    if not cleaned:
        cleaned = "".join(ch for ch in (default or "Sheet1") if ch.isascii() and ch.isalnum()) or "Sheet1"
    if cleaned[0].isdigit():
        cleaned = f"S{cleaned}"
    return cleaned[:max_len]


def unique_origin_short_name(name: str, used: set[str], default: str = "Sheet", max_len: int = 24) -> str:
    """Return an Origin short name unique within `used` (alphanumeric only, no underscores)."""
    base = sanitize_origin_short_name(name, default=default, max_len=max_len)
    cand = base
    idx = 2
    while cand in used:
        suffix = str(idx)
        cand = f"{base[: max(1, max_len - len(suffix))]}{suffix}"
        idx += 1
    used.add(cand)
    return cand


def _hex_to_origin_color(op: Any, hex_str: str) -> Any:
    r, g, b = ot.parse_hex_rgb(hex_str or "#3E86DE")
    if r == 0 and g == 0 and b == 0:
        r, g, b = 1, 1, 1
    return op.ocolor((r, g, b))


def get_font_id(op: Any, family: Optional[str] = None) -> int:
    """Resolve Origin's runtime LabTalk integer Font ID for `family` (defaults to active preset font)."""
    fam = str(family or get_active_spec()["font_family"]).strip()
    try:
        return int(op.po.LT_evaluate(f'font("{fam}")'))
    except Exception:
        return 0


def get_tnr_font_id(op: Any) -> int:
    """Backward-compatible alias resolving the active preset's LabTalk Font ID (`Times New Roman` or `Arial`)."""
    return get_font_id(op)


def get_font_face_dword(op: Any, family: Optional[str] = None) -> int:
    """Resolve Origin's internal `TreeNode` `Font.Face` DWORD for `family` (used by `tr.Label.Face`)."""
    fam = str(family or get_active_spec()["font_family"]).strip()
    key = (id(op), fam)
    if key in _FONT_FACE_CACHE:
        return _FONT_FACE_CACHE[key]
    dword = 1852392883
    try:
        prev_pe = op.pe.cd()
        f_lt = get_font_id(op, fam)
        gp_tmp = op.new_graph()
        if f_lt > 0:
            gp_tmp[0].lt_exec(f"YL.font = {f_lt};")
        val = int(gp_tmp[0].obj.GraphObjects["YL"].Theme.Font.GetIntValue("Face"))
        if val != 0:
            dword = val
        gp_tmp.destroy()
        op.pe.cd(prev_pe)
    except Exception:
        pass
    _FONT_FACE_CACHE[key] = dword
    return dword


def get_tnr_face_dword(op: Any) -> int:
    """Backward-compatible alias resolving the active preset's `Font.Face` DWORD (`Times New Roman` or `Arial`)."""
    return get_font_face_dword(op)


def wrap_tnr_bold(rich_txt: str) -> str:
    """Wrap Origin rich text in the active preset's font escape."""
    s = str(rich_txt or "").strip()
    if not s:
        return ""
    if s.startswith("\\f:"):
        return s
    fam = str(get_active_spec()["font_family"])
    return f"\\f:{fam}({s})"


def activate_layer(op: Any, gp: Any, layer_num_1based: int = 1) -> None:
    """Explicitly activate `gp` and set `page.active` so LabTalk commands hit the intended layer."""
    op.lt_exec(f'win -a "{gp.name}"; page.active = {int(layer_num_1based)};')


_PAGE_TARGET_INCHES: Dict[str, Tuple[float, float]] = {}


def set_graph_page_inches(gp: Any, width_in: float = 8.0, height_in: float = 6.0) -> None:
    """
    Set GraphPage physical canvas dimensions in inches (`Units = 0`) and record exact target
    dimensions so `export_origin_publication_figures` re-locks them right before `expGraph`.
    NEVER use `page.unit=2` in LabTalk (which is pixels on Page and shrinks canvas to 7x5 px).
    """
    w_f, h_f = float(width_in), float(height_in)
    gp.obj.Units = 0
    gp.obj.Width = w_f
    gp.obj.Height = h_f
    try:
        _PAGE_TARGET_INCHES[gp.name] = (w_f, h_f)
    except Exception:
        pass


def sanitize_layer_frames_and_grids(
    gl: Any,
    remove_default_legend: bool = True,
    *,
    op: Optional[Any] = None,
    gp: Optional[Any] = None,
    layer_num_1based: Optional[int] = None,
) -> None:
    """
    Suppress `Light Grids` system theme & `GraphObject` overline artifacts:
    - Turn off X/Y grid lines
    - Hide native `XB`, `YL`, `YR`, `XT` `GraphObjects` (all typography is rendered via zero-overline `tr.Label` overlay)
    - Remove default `Legend` via `label -r Legend;` (NEVER `legend -r;`, which reconstructs it!)
    """
    if op is not None and gp is not None and layer_num_1based is not None:
        activate_layer(op, gp, layer_num_1based)
    gl.lt_exec("layer.x.grid.show=0; layer.y.grid.show=0;")
    for nm in ("XB", "YL", "YR", "XT"):
        try:
            gl.lt_exec(f"{nm}.show=0; {nm}.box=0; {nm}.background=0;")
        except Exception:
            pass
    if remove_default_legend:
        gl.lt_exec("label -r Legend;")


def _split_balanced_two_lines(text: str, max_chars: int = 12) -> List[str]:
    s = ot.clean_semantic_sample_name(str(text or "").strip(), True)
    if len(s) <= max_chars or " " not in s:
        return [s]
    # Keep short "Sample N" / "State N" tokens on one crisp line
    if re.match(r"^(?:Sample|State|Group|Cell)\s+#?\d+$", s, flags=re.IGNORECASE):
        return [s]
    mid = len(s) // 2
    spaces = [i for i, ch in enumerate(s) if ch == " "]
    best = min(spaces, key=lambda i: abs(i - mid))
    l1, l2 = s[:best].strip(), s[best + 1 :].strip()
    if not l1 or not l2:
        return [s]
    return [l1, l2]


def render_categorical_x_labels_clean(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    categories: Sequence[str],
    *,
    xlim_lo: float = 0.4,
    xlim_hi: Optional[float] = None,
    tick_label_pt: Optional[float] = None,
    color_int: Optional[int] = None,
    show_outward_ticks: bool = False,
) -> bool:
    """
    Render categorical X-axis labels strictly at full `tick_label_pt` (`24.0 pt` on single panels,
    NEVER shrinking X labels smaller than Y ticks!): if labels fit horizontally within 90% of bar slot,
    render horizontal; otherwise tilt cleanly at `30°` anchored by top-right tip below the bottom spine.
    """
    _ = show_outward_ticks
    n_cats = len(categories)
    if n_cats == 0:
        return False
    spec = get_active_spec()
    x_hi = float(xlim_hi) if xlim_hi is not None else (float(n_cats) + 0.6)
    c_use = int(color_int) if color_int is not None else ot.hex_to_origin_rgb_int("#111111")
    pt_full = float(spec["tick_label_pt"] if tick_label_pt is None else tick_label_pt)

    activate_layer(op, gp, layer_num_1based)
    gl.lt_exec("layer.x.showLabels=0; layer.x.ticks=0; layer.x.showMinorTicks=0;")

    tgt_wh = _PAGE_TARGET_INCHES.get(gp.name)
    pw_in = tgt_wh[0] if tgt_wh else max(1.5, float(getattr(gp.obj, "Width", spec["page_rect_w_in"])))
    ph_in = tgt_wh[1] if tgt_wh else max(1.2, float(getattr(gp.obj, "Height", spec["page_rect_h_in"])))
    try:
        lw_val = float(op.po.LT_evaluate("layer.width"))
        lu_val = int(round(float(op.po.LT_evaluate("layer.unit"))))
        layer_w_in = lw_val if lu_val == 2 else pw_in * (lw_val / 100.0)
    except Exception:
        layer_w_in = float(spec["box_rect_w_in"])

    upi = _origin_units_per_inch(spec)
    slot_in = layer_w_in / max(float(n_cats), 1.0)
    cleaned_cats = [ot.clean_semantic_sample_name(str(c), True) for c in categories]
    max_single_len = max((len(c) for c in cleaned_cats), default=6)
    req_horiz_in = (0.55 * max_single_len * pt_full) / upi

    if req_horiz_in <= 0.86 * slot_in and n_cats <= 5:
        dy_h_pct = ((0.20 + 0.56 * (pt_full / upi)) / ph_in) * 100.0
        for idx, clean_c in enumerate(cleaned_cats, start=1):
            x_frac = (float(idx) - float(xlim_lo)) / max(x_hi - float(xlim_lo), 1e-6)
            _PENDING_DATA_TEXT_ITEMS.setdefault(gp.name, []).append(
                {
                    "layer_num": int(layer_num_1based),
                    "mode": "cat_x_horiz",
                    "x_frac": x_frac,
                    "dy_below_pct": dy_h_pct,
                    "text": clean_c,
                    "format_math": False,
                    "fontsize": pt_full,
                    "color_int": c_use,
                    "rotate": 0,
                    "pos_scatter": 0,
                }
            )
        return False

    rot_deg = 30
    rot_rad = math.radians(rot_deg)
    char_h_in = pt_full / upi
    for idx, clean_c in enumerate(cleaned_cats, start=1):
        x_frac = (float(idx) - float(xlim_lo)) / max(x_hi - float(xlim_lo), 1e-6)
        lbl_len_in = (0.55 * max(len(clean_c), 2) * pt_full) / upi
        dx_tip_pct = ((0.46 * lbl_len_in * math.cos(rot_rad)) / pw_in) * 100.0
        dy_tip_pct = ((0.22 + 0.50 * lbl_len_in * math.sin(rot_rad) + 0.52 * char_h_in * math.cos(rot_rad)) / ph_in) * 100.0
        _PENDING_DATA_TEXT_ITEMS.setdefault(gp.name, []).append(
            {
                "layer_num": int(layer_num_1based),
                "mode": "cat_x_tilt",
                "x_frac": x_frac,
                "dx_shift_pct": -dx_tip_pct + 0.14,
                "dy_below_pct": dy_tip_pct,
                "text": clean_c,
                "format_math": False,
                "fontsize": pt_full,
                "color_int": c_use,
                "rotate": rot_deg,
                "pos_scatter": 0,
            }
        )
    return True


def add_page_text_label(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    obj_name: str,
    rich_text: str,
    x_page_pct: float,
    y_page_pct: float,
    *,
    fontsize: float = 19.0,
    color_int: Optional[int] = None,
    rotate: int = 0,
    pos_scatter: int = 2,
    format_math: bool = True,
) -> None:
    """
    Queue a borderless `Times New Roman` bold label in exact Page-% coordinates (`x_page_pct` from left,
    `y_page_pct` from top) onto the page's zero-overline `tr.Label` overlay layer.
    `pos_scatter`: `0` = Center, `1` = Left of anchor, `2` = Right of anchor (left-aligned starting at `x_page_pct`).
    """
    _ = (op, gl, layer_num_1based, obj_name)
    txt = str(rich_text or "").strip()
    if not txt:
        return
    c_use = int(color_int) if color_int is not None else ot.hex_to_origin_rgb_int("#111111")
    _PENDING_TEXT_ITEMS.setdefault(gp.name, []).append(
        {
            "x_pct": float(x_page_pct),
            "y_top_pct": float(y_page_pct),
            "text": txt,
            "format_math": bool(format_math),
            "fontsize": float(fontsize),
            "color_int": c_use,
            "rotate": int(rotate),
            "pos_scatter": int(pos_scatter),
        }
    )


def queue_overlay_data_text(
    op: Any,
    gp: Any,
    layer_num_1based: int,
    data_x: float,
    data_y: float,
    x_bounds: Tuple[float, float],
    y_bounds: Tuple[float, float],
    *,
    rich_text: str,
    fontsize: float = 18.0,
    color_int: Optional[int] = None,
    invert_x: bool = False,
    log_x: bool = False,
    log_y: bool = False,
    pos_scatter: int = 0,
    rotate: int = 0,
    dx_pct: float = 0.0,
    dy_top_pct: float = 0.0,
    format_math: bool = True,
    no_repel: bool = False,
) -> None:
    """Queue a data-anchored callout label to be mapped into exact Page-% coordinates at flush time."""
    _ = op
    txt = str(rich_text or "").strip()
    if not txt:
        return
    c_use = int(color_int) if color_int is not None else ot.hex_to_origin_rgb_int("#111111")
    _PENDING_DATA_TEXT_ITEMS.setdefault(gp.name, []).append(
        {
            "layer_num": int(layer_num_1based),
            "mode": "data_xy",
            "data_x": float(data_x),
            "data_y": float(data_y),
            "x_bounds": (float(x_bounds[0]), float(x_bounds[1])),
            "y_bounds": (float(y_bounds[0]), float(y_bounds[1])),
            "invert_x": bool(invert_x),
            "log_x": bool(log_x),
            "log_y": bool(log_y),
            "dx_pct": float(dx_pct),
            "dy_top_pct": float(dy_top_pct),
            "text": txt,
            "format_math": bool(format_math),
            "fontsize": float(fontsize),
            "color_int": c_use,
            "rotate": int(rotate),
            "pos_scatter": int(pos_scatter),
            "no_repel": bool(no_repel),
        }
    )


def _int_to_hex_rgb(c_int: int) -> str:
    if c_int <= 0:
        return "#3E86DE"
    # Origin RGB int: R + (G << 8) + (B << 16) when >= 16777216 or raw COLORREF
    raw = int(c_int) & 0xFFFFFF
    r = raw & 0xFF
    g = (raw >> 8) & 0xFF
    b = (raw >> 16) & 0xFF
    if r == 0 and g == 0 and b == 0:
        return "#111111"
    return f"#{r:02X}{g:02X}{b:02X}"


def pick_cleanest_box_corner(
    series_xy_list: List[Dict[str, Any]],
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    invert_x: bool = False,
    box_w_frac: float = 0.36,
    box_h_frac: float = 0.28,
    exclude_corners: Sequence[str] = (),
) -> str:
    """
    Score data point density in four candidate corners and return the least-occupied one.
    Returns one of: 'corner_upper_left', 'corner_upper_right', 'corner_lower_left', 'corner_lower_right'.
    """
    x_lo, x_hi = min(xlim), max(xlim)
    y_lo, y_hi = min(ylim), max(ylim)
    x_span = max(x_hi - x_lo, 1e-9)
    y_span = max(y_hi - y_lo, 1e-9)

    excluded = set(exclude_corners)
    # Four corners: (x_start_frac, y_start_frac, label)
    all_corners = [
        (0.0, 1.0 - box_h_frac, "corner_upper_left"),
        (1.0 - box_w_frac, 0.0, "corner_lower_right"),
        (1.0 - box_w_frac, 1.0 - box_h_frac, "corner_upper_right"),
        (0.0, 0.0, "corner_lower_left"),
    ]
    corners = [c for c in all_corners if c[2] not in excluded] or all_corners
    scores = {c[2]: 0 for c in corners}

    for series in series_xy_list:
        xs = np.asarray(series.get("x", []), dtype=float)
        ys = np.asarray(series.get("y", []), dtype=float)
        if len(xs) == 0:
            continue
        xf = (xs - x_lo) / x_span
        if invert_x:
            xf = 1.0 - xf
        yf = (ys - y_lo) / y_span
        for cx, cy, label in corners:
            mask = (xf >= cx) & (xf <= cx + box_w_frac) & (yf >= cy) & (yf <= cy + box_h_frac)
            scores[label] += int(np.sum(mask))

    return min(scores, key=lambda k: scores[k])


def configure_custom_legend(
    gl: Any,
    entries: Sequence[Tuple[Any, ...]],
    *,
    fontsize: float = 18.0,
    horizontal: bool = False,
    pos_mode: str = "corner_upper_left",
    layer_rect_pct: Tuple[float, float, float, float] = (16.0, 10.0, 76.0, 74.0),
    op: Optional[Any] = None,
    gp: Optional[Any] = None,
    layer_num_1based: int = 1,
) -> None:
    """
    Delete Origin's auto-reconstructing `Legend` (`label -r Legend;`) and queue a clean, borderless,
    zero-overline `Times New Roman` vector-swatch legend on the page overlay layer.
    `entries` accepts either `(plot_idx_1based, label)` 2-tuples or `(plot_idx_1based, label, color_hex, swatch_kind)` 4-tuples.
    """
    if op is not None and gp is not None:
        activate_layer(op, gp, layer_num_1based)
    gl.lt_exec("label -r Legend;")

    if not entries or pos_mode == "none" or gp is None:
        return

    norm_entries: List[Tuple[str, str, str]] = []
    for item in entries:
        if len(item) >= 4:
            _p_idx, lbl, c_hex, sw_kind = item[0], str(item[1]), str(item[2] or "#3E86DE"), str(item[3] or "line")
        elif len(item) == 3:
            _p_idx, lbl, c_hex = item[0], str(item[1]), str(item[2] or "#3E86DE")
            sw_kind = "line_sphere"
        else:
            p_idx, lbl = int(item[0]), str(item[1])
            c_hex = "#3E86DE"
            try:
                c_val = int(gl.get_int(f"plot{p_idx}.color"))
                c_hex = _int_to_hex_rgb(c_val)
            except Exception:
                pass
            sw_kind = "line_sphere"
        norm_entries.append((lbl, c_hex, sw_kind))

    _PENDING_LEGENDS.setdefault(gp.name, []).append(
        {
            "layer_num": int(layer_num_1based),
            "entries": norm_entries,
            "fontsize": float(fontsize),
            "horizontal": bool(horizontal),
            "pos_mode": str(pos_mode),
            "fallback_rect_pct": tuple(float(v) for v in layer_rect_pct),
        }
    )


def style_origin_native_axis_title(
    gl: Any,
    obj_name: str,
    text: str,
    fontsize: float = 25.0,
    color_int: Optional[int] = None,
    *,
    op: Optional[Any] = None,
    gp: Optional[Any] = None,
    layer_num_1based: Optional[int] = None,
) -> bool:
    """
    Hide overlined native `XB`/`YL`/`YR` `GraphObject` (`show=0; box=0; background=0;`) and queue
    crisp zero-overline `Times New Roman` bold axis title onto the page overlay layer.
    """
    if op is not None and gp is not None and layer_num_1based is not None:
        activate_layer(op, gp, layer_num_1based)

    try:
        gl.lt_exec(f"{obj_name}.show=0; {obj_name}.box=0; {obj_name}.background=0;")
    except Exception:
        pass

    clean_txt = (text or "").strip()
    if not clean_txt or gp is None:
        return False

    c_use = int(color_int) if color_int is not None else ot.hex_to_origin_rgb_int("#111111")
    lay_n = int(layer_num_1based or 1)

    # Deduplicate if called multiple times for the same (layer_num, obj_name)
    lst = _PENDING_AXIS_TITLES.setdefault(gp.name, [])
    lst[:] = [it for it in lst if not (it["layer_num"] == lay_n and it["obj_name"] == obj_name)]
    lst.append(
        {
            "layer_num": lay_n,
            "obj_name": obj_name,
            "text": clean_txt,
            "fontsize": float(fontsize),
            "color_int": c_use,
        }
    )
    return True


def _query_layer_rect_page_pct(
    op: Any,
    gp: Any,
    layer_num_1based: int,
    cache: Dict[int, Tuple[float, float, float, float, int, int]],
    fallback: Tuple[float, float, float, float] = (16.0, 10.0, 76.0, 74.0),
) -> Tuple[float, float, float, float, int, int]:
    """Return `(l_pct, t_pct, w_pct, h_pct, unit_code, y_show_labels)` for `layer_num_1based`."""
    if layer_num_1based in cache:
        return cache[layer_num_1based]

    pw = max(1.0, float(getattr(gp.obj, "Width", 8.0)))
    ph = max(1.0, float(getattr(gp.obj, "Height", 6.0)))
    try:
        activate_layer(op, gp, layer_num_1based)
        u = int(round(float(op.po.LT_evaluate("layer.unit"))))
        ll = float(op.po.LT_evaluate("layer.left"))
        lt = float(op.po.LT_evaluate("layer.top"))
        lw = float(op.po.LT_evaluate("layer.width"))
        lh = float(op.po.LT_evaluate("layer.height"))
        y_sl = int(round(float(op.po.LT_evaluate("layer.y.showLabels"))))
    except Exception:
        res = (fallback[0], fallback[1], fallback[2], fallback[3], 1, 1)
        cache[layer_num_1based] = res
        return res

    if u == 2:
        l_p, t_p, w_p, h_p = (ll / pw) * 100.0, (lt / ph) * 100.0, (lw / pw) * 100.0, (lh / ph) * 100.0
    elif u == 7 and layer_num_1based > 1:
        pl, pt, pw_p, ph_p, _pu, _psl = _query_layer_rect_page_pct(op, gp, 1, cache, fallback)
        l_p = pl + (ll / 100.0) * pw_p
        t_p = pt + (lt / 100.0) * ph_p
        w_p = (lw / 100.0) * pw_p
        h_p = (lh / 100.0) * ph_p
    else:
        l_p, t_p, w_p, h_p = ll, lt, lw, lh

    res = (l_p, t_p, w_p, h_p, u, y_sl)
    cache[layer_num_1based] = res
    return res


def _map_data_to_frac(val: float, lo: float, hi: float, invert: bool, is_log: bool) -> float:
    a, b = (max(lo, hi), min(lo, hi)) if invert else (min(lo, hi), max(lo, hi))
    if is_log and a > 0 and b > 0 and val > 0:
        la, lb, lv = math.log10(a), math.log10(b), math.log10(val)
        return (lv - la) / (lb - la) if abs(lb - la) > 1e-9 else 0.5
    return (val - a) / (b - a) if abs(b - a) > 1e-9 else 0.5


def flush_page_overlays(op: Any, gp: Any) -> None:
    """
    Materialize all queued axis titles, legends, categorical wrapped labels, and callouts onto a single
    transparent `[0..100, 0..100]` `GLayer` using `tr.Label` (`Form=4`, `%(?,@LL)`, `Face=tnr_dword`),
    achieving 100% crisp `Times New Roman` bold typography with ZERO `GraphObject` overline artifacts.
    """
    gname = gp.name
    if gname in _FLUSHED_PAGES:
        return

    ax_items = _PENDING_AXIS_TITLES.get(gname, [])
    txt_items = _PENDING_TEXT_ITEMS.get(gname, [])
    dtxt_items = _PENDING_DATA_TEXT_ITEMS.get(gname, [])
    leg_items = _PENDING_LEGENDS.get(gname, [])

    tgt_ov_wh = _PAGE_TARGET_INCHES.get(gname)
    if getattr(gp.obj, "Units", 0) != 0:
        w_cur = float(getattr(gp.obj, "Width", 8.0))
        h_cur = float(getattr(gp.obj, "Height", 6.0))
        gp.obj.Units = 0
        gp.obj.Width = tgt_ov_wh[0] if tgt_ov_wh else (8.0 if (w_cur > 30.0 or w_cur < 1.2) else w_cur)
        gp.obj.Height = tgt_ov_wh[1] if tgt_ov_wh else (6.0 if (h_cur > 30.0 or h_cur < 1.0) else h_cur)

    if not ax_items and not txt_items and not dtxt_items and not leg_items:
        _FLUSHED_PAGES.add(gname)
        return

    rect_cache: Dict[int, Tuple[float, float, float, float, int, int]] = {}
    layers_with_cat2 = {
        it["layer_num"]
        for it in dtxt_items
        if it.get("mode") in ("cat_x_90", "cat_x_tilt") or (it.get("mode") == "cat_x_horiz" and float(it.get("dy_below_pct", 0.0)) > 5.2)
    }
    layers_with_cat1 = {
        it["layer_num"]
        for it in dtxt_items
        if it.get("mode") == "cat_x_horiz"
    }

    pw_in = tgt_ov_wh[0] if tgt_ov_wh else max(1.5, float(getattr(gp.obj, "Width", 8.0)))
    ph_in = tgt_ov_wh[1] if tgt_ov_wh else max(1.2, float(getattr(gp.obj, "Height", 6.0)))

    active_spec = get_active_spec()
    upi = _origin_units_per_inch(active_spec)

    # Query Y-axis tick width profile per layer so YL never collides with scientific/4-digit/categorical ticks
    y_wide_layers: Dict[int, float] = {}
    for ax in ax_items:
        ln = ax["layer_num"]
        if ax["obj_name"] == "YL" and ln not in y_wide_layers:
            extra_gap = _CUSTOM_Y_LABEL_LAYERS.get((gname, ln), 0.0)
            try:
                activate_layer(op, gp, ln)
                y_tp = int(round(float(op.po.LT_evaluate("layer.y.type"))))
                y_lt = int(round(float(op.po.LT_evaluate("layer.y.label.type"))))
                y_f = abs(float(op.po.LT_evaluate("layer.y.from")))
                y_t = abs(float(op.po.LT_evaluate("layer.y.to")))
                ym = max(y_f, y_t)
                if y_lt == 8:
                    extra_gap = max(extra_gap, 4.0)
                elif y_tp == 2:
                    extra_gap = max(extra_gap, 3.0)
                elif ym >= 1000.0 or (0.0 < ym < 0.01):
                    extra_gap = max(extra_gap, 2.8)
            except Exception:
                pass
            y_wide_layers[ln] = extra_gap

    # Final list of text primitives: (x_pct, y_bot_pct, rich_str, fontsize, color_int, rotate, pos_scatter)
    final_texts: List[Tuple[float, float, str, float, int, int, int]] = []
    # Final list of line swatches: (x_list, y_bot_list, color_hex, width_units, style_code)
    final_lines: List[Tuple[List[float], List[float], str, int, int]] = []
    # Final list of marker swatches: (x_val, y_bot_val, color_hex, kind_code, interior_code, sym_size)
    final_markers: List[Tuple[float, float, str, int, int, float]] = []

    # 1. Resolve Axis Titles (`XB`, `XT`, `YL`, `YR`)
    for ax in ax_items:
        ln = ax["layer_num"]
        onm = ax["obj_name"]
        fs = ax["fontsize"]
        col_i = ax["color_int"]
        rich = prepare_plot_label_rich_text(ax["text"], format_math=True)
        if not rich:
            continue
        l_p, t_p, w_p, h_p, u_code, y_sl = _query_layer_rect_page_pct(op, gp, ln, rect_cache)

        if onm == "XB":
            xp = l_p + 0.5 * w_p
            bot_in = ph_in * ((t_p + h_p) / 100.0)
            if ph_in < 4.8:
                sy_j = ph_in / 7.80
                if u_code == 7:
                    y_in = bot_in + 0.44 * sy_j
                elif h_p < 48.0 and t_p < 12.0:
                    y_in = min(ph_in - 0.34 * sy_j, bot_in + 0.78 * sy_j)
                elif ln in layers_with_cat2:
                    y_in = min(ph_in - 0.34 * sy_j, bot_in + 1.44 * sy_j)
                else:
                    y_in = min(ph_in - 0.34 * sy_j, bot_in + 0.98 * sy_j)
            elif u_code == 7:
                y_in = bot_in + 0.44
            elif h_p < 48.0 and t_p < 12.0:
                y_in = min(ph_in - 0.36, bot_in + 0.78 * (ph_in / 7.80))
            elif h_p < 42.0 and fs < 24.0:
                y_in = min(ph_in - 0.26, bot_in + 0.68)
            elif ln in layers_with_cat2:
                y_in = min(ph_in - 0.36, bot_in + 1.44)
            elif ln in layers_with_cat1:
                y_in = min(ph_in - 0.36, bot_in + 0.98)
            else:
                y_in = min(ph_in - 0.36, bot_in + 0.98)
            y_top = (y_in / ph_in) * 100.0
            final_texts.append((xp, 100.0 - y_top, rich, fs, col_i, 0, 0))

        elif onm == "XT":
            xp = l_p + 0.5 * w_p
            top_in = ph_in * (t_p / 100.0)
            y_in = max(0.36 * (ph_in / 7.8), top_in - 0.88 * (ph_in / 7.8))
            y_top = (y_in / ph_in) * 100.0
            final_texts.append((xp, 100.0 - y_top, rich, fs, col_i, 0, 0))

        elif onm in ("YL", "YR"):
            orig_fs = fs
            vis_txt = rich
            for _ in range(4):
                nxt = re.sub(r"\\(?:f:[^()]+|[a-zA-Z+-]+\d*)\(([^()]*)\)", r"\1", vis_txt)
                if nxt == vis_txt:
                    break
                vis_txt = nxt
            n_ch = max(1, len(vis_txt.strip()))
            sy_j = (ph_in / 7.80) if ph_in < 4.8 else 1.0
            sx_j = (pw_in / 10.40) if pw_in < 5.5 else 1.0
            layer_h_in = max(0.65 * sy_j, ph_in * (h_p / 100.0))
            cy_in = ph_in * ((t_p + 0.5 * h_p) / 100.0)
            edge_pad_y = 0.30 * sy_j
            edge_safe_span_in = max(0.55 * sy_j, 2.0 * min(cy_in - edge_pad_y, ph_in - cy_in - edge_pad_y))
            max_span_in = min(edge_safe_span_in, layer_h_in * (0.94 if h_p < 42.0 else 1.22))
            max_pts_fit = (max_span_in * upi) / (0.55 * n_ch)
            min_fs_floor = 5.5 if ph_in < 4.8 else 12.5
            fs = min(fs, max(min_fs_floor, max_pts_fit))
            y_top = t_p + 0.5 * h_p
            l_in = pw_in * (l_p / 100.0)
            w_in = pw_in * (w_p / 100.0)
            has_vis_y_lbl = (y_sl != 0) or ((gname, ln) in _CUSTOM_Y_LABEL_LAYERS)
            if onm == "YL":
                w_extra = y_wide_layers.get(ln, 0.0)
                if pw_in < 5.5:
                    if u_code == 7:
                        x_in = max(0.22 * sx_j, l_in - 0.74 * sx_j)
                    elif not has_vis_y_lbl:
                        x_in = max(0.28 * sx_j, l_in - (0.42 if w_p < 42.0 else 0.56) * sx_j)
                    elif w_p < 42.0:
                        x_in = max(0.28 * sx_j, l_in - (0.90 + 0.08 * w_extra) * sx_j)
                    else:
                        x_in = max(0.34 * sx_j, l_in - (1.36 + 0.09 * w_extra) * sx_j)
                elif u_code == 7 or (orig_fs <= 17.0 and w_p < 36.0):
                    x_in = max(0.24, l_in - 0.74)
                elif not has_vis_y_lbl:
                    x_in = max(0.32, l_in - (0.42 if w_p < 42.0 else 0.56))
                elif w_p < 42.0:
                    x_in = max(0.32, l_in - (0.90 + 0.08 * w_extra))
                else:
                    x_in = max(0.38, l_in - (1.36 + 0.09 * w_extra))
                xp = (x_in / pw_in) * 100.0
            else:
                x_in = min(pw_in - 0.38 * sx_j, l_in + w_in + (0.86 if w_p < 42.0 else 1.30) * sx_j)
                xp = (x_in / pw_in) * 100.0
            final_texts.append((xp, 100.0 - y_top, rich, fs, col_i, 90, 0))

    # 2. Resolve Direct Page-% Text Items
    for ti in txt_items:
        rich = prepare_plot_label_rich_text(ti["text"], format_math=ti["format_math"])
        if not rich:
            continue
        xp = max(1.0, min(99.0, ti["x_pct"]))
        y_top = max(1.5, min(98.5, ti["y_top_pct"]))
        final_texts.append((xp, 100.0 - y_top, rich, ti["fontsize"], ti["color_int"], ti["rotate"], ti["pos_scatter"]))

    # 3. Resolve Data-Anchored & Categorical X Items (with vertical collision repulsion on data callouts!)
    resolved_callouts: List[List[Any]] = []
    for di in dtxt_items:
        ln = di["layer_num"]
        l_p, t_p, w_p, h_p, _u, _ysl = _query_layer_rect_page_pct(op, gp, ln, rect_cache)
        rich = prepare_plot_label_rich_text(di["text"], format_math=di["format_math"])
        if not rich:
            continue

        mode = di["mode"]
        if mode in ("cat_x_horiz", "cat_x_90", "cat_x_tilt"):
            xp = l_p + di["x_frac"] * w_p + float(di.get("dx_shift_pct", 0.0))
            y_top = min(97.5, t_p + h_p + di["dy_below_pct"])
            final_texts.append((xp, 100.0 - y_top, rich, di["fontsize"], di["color_int"], di["rotate"], di["pos_scatter"]))
        else:
            xf = _map_data_to_frac(di["data_x"], di["x_bounds"][0], di["x_bounds"][1], di["invert_x"], di["log_x"])
            yf = _map_data_to_frac(di["data_y"], di["y_bounds"][0], di["y_bounds"][1], False, di["log_y"])
            xp = l_p + max(0.03, min(0.97, xf)) * w_p + di["dx_pct"]
            y_top = t_p + (1.0 - max(0.04, min(0.96, yf))) * h_p + di["dy_top_pct"]
            y_lo_clamp = t_p + 3.8
            y_hi_clamp = t_p + h_p - 3.8
            y_top = max(y_lo_clamp, min(y_hi_clamp, y_top))
            if di.get("no_repel"):
                final_texts.append((xp, 100.0 - y_top, rich, di["fontsize"], di["color_int"], di["rotate"], di["pos_scatter"]))
            else:
                est_w = max(8.0, len(rich) * (di["fontsize"] * 0.055))
                pos_sc = di["pos_scatter"]
                x_center = xp + (0.5 * est_w if pos_sc == 2 else (-0.5 * est_w if pos_sc == 1 else 0.0))
                resolved_callouts.append([xp, y_top, rich, di["fontsize"], di["color_int"], di["rotate"], pos_sc, x_center, est_w, y_lo_clamp, y_hi_clamp])

    # Iterative vertical separation solver for nearby data callouts
    if len(resolved_callouts) >= 2:
        for _pass in range(12):
            moved = False
            resolved_callouts.sort(key=lambda r: r[1])
            for i in range(len(resolved_callouts)):
                for j in range(i + 1, len(resolved_callouts)):
                    a, b = resolved_callouts[i], resolved_callouts[j]
                    x_dist = abs(a[7] - b[7])
                    x_thresh = 0.58 * (a[8] + b[8]) + 4.0
                    min_dy = max(6.4, (a[3] + b[3]) * 0.21)
                    cur_dy = b[1] - a[1]
                    if x_dist < x_thresh and cur_dy < min_dy:
                        push = 0.52 * (min_dy - cur_dy)
                        a[1] = max(a[9], a[1] - push)
                        b[1] = min(b[10], b[1] + push)
                        if b[1] - a[1] < min_dy * 0.92:
                            if a[1] <= a[9] + 0.2:
                                b[1] = min(b[10], a[1] + min_dy)
                            else:
                                a[1] = max(a[9], b[1] - min_dy)
                        moved = True
            if not moved:
                break

    for c_it in resolved_callouts:
        final_texts.append((c_it[0], 100.0 - c_it[1], c_it[2], c_it[3], c_it[4], c_it[5], c_it[6]))

    # 4. Resolve Custom Vector-Swatch Legends (100% Inside Box on Single Panels; Grid Header Only on `above_frame_grid`)
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    last_interior_y_by_layer: Dict[int, float] = {}
    for lg in leg_items:
        ln = lg["layer_num"]
        fb = lg["fallback_rect_pct"]
        pmode = lg["pos_mode"]
        if pmode == "page_upper_right" or lg.get("use_explicit_rect"):
            l_p, t_p, w_p, h_p = fb
        else:
            l_p, t_p, w_p, h_p, _u, _ysl = _query_layer_rect_page_pct(op, gp, ln, rect_cache, fallback=fb)
        fs = lg["fontsize"]
        horiz = lg["horizontal"]
        ents: List[Tuple[str, str, str]] = lg["entries"]
        n_e = len(ents)
        if n_e == 0:
            continue

        # Remap any single-panel `above_frame` request into centered `interior_top` rows inside the black box!
        if pmode in ("above_frame", "above_frame_right"):
            pmode = "interior_top"

        sw_w = 2.0 if w_p < 40.0 else 2.8
        txt_gap = 0.55 if w_p < 40.0 else 0.75
        unit_to_pct_w = 100.0 / (pw_in * upi)
        cap_to_pct_h = 100.0 / (ph_in * 78.0)
        row_step = max(3.5 if h_p < 45.0 else 5.1, fs * 1.92 * cap_to_pct_h)

        if horiz:
            is_grid_hdr = pmode == "above_frame_grid"
            if is_grid_hdr:
                l_p, t_p, w_p, h_p = fb

            if not is_grid_hdr and w_p >= 40.0 and n_e >= 6 and fs > 19.0:
                fs = 19.0
                row_step = max(4.8, fs * 1.88 * cap_to_pct_h)
            elif not is_grid_hdr and w_p >= 40.0 and n_e >= 4 and fs > 20.0:
                fs = 20.0
                row_step = max(5.0, fs * 1.90 * cap_to_pct_h)

            item_widths: List[float] = []
            rich_labels: List[str] = []
            inter_gap = (1.6 if w_p < 40.0 else (1.9 if n_e >= 5 else 2.2)) if not is_grid_hdr else 3.0
            for raw_l, _chx, _sk in ents:
                rl = prepare_plot_label_rich_text(raw_l, format_math=True)
                rich_labels.append(rl)
                plain_vis = re.sub(r"\\[A-Za-z+-]+\(([^()]*)\)", r"\1", rl)
                em_sum = sum(
                    0.30
                    if ch in " .,'|!"
                    else (
                        0.36
                        if ch in "iltf()-/"
                        else (0.64 if (ch.isupper() or ch.isdigit() or ch in "%+*=#") else 0.50)
                    )
                    for ch in plain_vis
                )
                txt_w_pct = max(3.0, (em_sum + 0.15) * fs * unit_to_pct_w)
                item_widths.append(sw_w + txt_gap + txt_w_pct + inter_gap)

            max_row_span = min(90.0, max(w_p + 8.0, 74.0)) if is_grid_hdr else max(16.0, w_p - (2.4 if w_p < 40.0 else 3.6))
            rows_packed: List[List[Tuple[str, str, str, str, float]]] = []
            cur_row: List[Tuple[str, str, str, str, float]] = []
            cur_w = 0.0
            for (raw_l, c_hex, sw_kind), rl, iw in zip(ents, rich_labels, item_widths):
                eff_w = iw - inter_gap
                if cur_row and (cur_w + eff_w > max_row_span):
                    rows_packed.append(cur_row)
                    cur_row = [(raw_l, c_hex, sw_kind, rl, iw)]
                    cur_w = iw
                else:
                    cur_row.append((raw_l, c_hex, sw_kind, rl, iw))
                    cur_w += iw
            if cur_row:
                rows_packed.append(cur_row)

            n_rows_p = len(rows_packed)
            if is_grid_hdr:
                avail_top = max(2.5, t_p - 6.8 - 2.6)
                eff_step = min(row_step, avail_top / max(1, n_rows_p - 1)) if n_rows_p > 1 else row_step
                eff_step = max(3.2, eff_step)
                y_bot_row = max(3.0 + (n_rows_p - 1) * eff_step, t_p - 6.8)
                y_row0 = max(2.6, y_bot_row - (n_rows_p - 1) * eff_step)
                x_min_clamp, x_max_clamp = 3.5, 96.5
            else:
                if pmode == "interior_top_row2":
                    prev_y = last_interior_y_by_layer.get(1, last_interior_y_by_layer.get(ln, t_p + 4.4))
                    y_row0 = prev_y + row_step
                else:
                    y_row0 = t_p + (3.4 if h_p < 42.0 else 4.4)
                eff_step = row_step
                pad_in_x = 1.2 if w_p < 40.0 else 1.8
                x_min_clamp, x_max_clamp = l_p + pad_in_x, l_p + w_p - pad_in_x

            last_y_used = y_row0
            for r_idx_p, r_items in enumerate(rows_packed):
                row_tot_w = sum(it[4] for it in r_items) - inter_gap
                cur_x = max(x_min_clamp, min(x_max_clamp - row_tot_w, l_p + 0.5 * (w_p - row_tot_w)))
                cur_y_top = y_row0 + r_idx_p * eff_step
                last_y_used = cur_y_top
                yb = 100.0 - cur_y_top
                for _raw_l, c_hex, sw_kind, rl, iw in r_items:
                    _append_swatch_primitives(cur_x, yb, sw_w, c_hex, sw_kind, fs, final_lines, final_markers)
                    final_texts.append((cur_x + sw_w + txt_gap, yb, rl, fs, ink_int, 0, 2))
                    cur_x += iw
            if not is_grid_hdr:
                last_interior_y_by_layer[1] = last_y_used
                last_interior_y_by_layer[ln] = last_y_used
        else:
            # Vertical stacked in-box corner legend (calibrated with true `em_upi` glyph widths)
            max_em_v = 3.4
            for raw_e, _ce, _ske in ents:
                rl_e = prepare_plot_label_rich_text(raw_e, format_math=True)
                pv_e = re.sub(r"\\[A-Za-z+-]+\(([^()]*)\)", r"\1", rl_e)
                em_e = sum(
                    0.30
                    if ch in " .,'|!"
                    else (
                        0.36
                        if ch in "iltf()-/"
                        else (0.65 if (ch.isupper() or ch.isdigit() or ch in "%+*=#") else 0.51)
                    )
                    for ch in pv_e
                )
                max_em_v = max(max_em_v, em_e)
            r_pad = 1.4 if w_p < 40.0 else 2.2
            pad_blk = 1.2 if w_p < 40.0 else 1.8
            block_w = sw_w + txt_gap + (max_em_v + 0.20) * fs * unit_to_pct_w + pad_blk
            min_leg_fs = 5.5 if ph_in < 4.8 else 14.5

            if pmode == "page_upper_right":
                max_allow_w = max(14.0, w_p - 1.2)
                if block_w > max_allow_w:
                    avail_txt = max(8.0, max_allow_w - sw_w - txt_gap - pad_blk)
                    fs = max(min_leg_fs, min(fs, avail_txt / max((max_em_v + 0.20) * unit_to_pct_w, 1e-6)))
                    row_step = max(3.4 if ph_in < 4.8 else 4.2, fs * 1.88 * cap_to_pct_h)
                    block_w = sw_w + txt_gap + (max_em_v + 0.20) * fs * unit_to_pct_w + pad_blk
                x0 = max(l_p, min(97.2 - block_w, l_p + w_p - block_w - 0.8))
                y0_top = max(3.2, t_p)
            else:
                max_inbox_w = 0.52 * w_p
                if block_w > max_inbox_w and w_p >= 35.0:
                    avail_txt = max(8.0, max_inbox_w - sw_w - txt_gap - pad_blk)
                    fs = max(min_leg_fs, min(fs, avail_txt / max((max_em_v + 0.20) * unit_to_pct_w, 1e-6)))
                    row_step = max(3.5 if h_p < 45.0 else 4.4, fs * 1.88 * cap_to_pct_h)
                    block_w = sw_w + txt_gap + (max_em_v + 0.20) * fs * unit_to_pct_w + pad_blk

                if pmode == "corner_upper_right":
                    x0 = max(l_p + 1.8, l_p + w_p - block_w - r_pad)
                    y0_top = t_p + (3.6 if h_p < 45.0 else 4.8)
                elif pmode == "corner_lower_left":
                    x0 = l_p + (1.8 if w_p < 40.0 else 2.6)
                    y0_top = max(t_p + 4.6, t_p + h_p - max(0, n_e - 1) * row_step - 5.6)
                elif pmode == "corner_lower_right":
                    x0 = max(l_p + 1.8, l_p + w_p - block_w - r_pad)
                    y0_top = max(t_p + 4.6, t_p + h_p - max(0, n_e - 1) * row_step - 5.6)
                else:
                    # corner_upper_left
                    x0 = l_p + (1.8 if w_p < 40.0 else 2.6)
                    y0_top = t_p + (3.6 if h_p < 45.0 else 4.8)

            for idx_e, (raw_l, c_hex, sw_kind) in enumerate(ents):
                rl = prepare_plot_label_rich_text(raw_l, format_math=True)
                yb = 100.0 - (y0_top + idx_e * row_step)
                _append_swatch_primitives(x0, yb, sw_w, c_hex, sw_kind, fs, final_lines, final_markers)
                final_texts.append((x0 + sw_w + txt_gap, yb, rl, fs, ink_int, 0, 2))

    if not final_texts and not final_lines and not final_markers:
        _FLUSHED_PAGES.add(gname)
        return

    # 5. Materialize Overlay Worksheet & Transparent Full-Page GLayer
    face_dword = get_font_face_dword(op)
    bold_flag = int(active_spec["bold_int"])
    prev_pe = op.pe.cd()
    try:
        ov_folder = op.pe.mkdir("_Typography_Overlay", True)
        op.pe.cd(ov_folder)
    except Exception:
        pass

    wb_ov = op.new_book("w", lname=f"{gname}_Typography")
    wks_ov = wb_ov[0]
    wks_ov.name = "Anchors"
    total_cols = 2 * (len(final_lines) + len(final_markers) + len(final_texts))
    wks_ov.cols = max(2, total_cols)

    # Disable page-level Legend AutoUpdate (prevents CONTOUR.otp from auto-creating Legend on gl_ov!)
    try:
        tr_pg = gp.obj.Theme
        if tr_pg.Legends is not None:
            tr_pg.Legends.SetIntValue(0, "AutoUpdate")
            tr_pg.Legends.SetIntValue(0, "Type")
        gp.obj.Theme = tr_pg
    except Exception:
        pass

    op.pe.cd(prev_pe)
    op.lt_exec(f'win -a "{gname}";')
    gl_ov = gp.add_layer(0)
    ov_lay_num = int(gp.obj.Layers.Count)
    activate_layer(op, gp, ov_lay_num)
    try:
        tr_lov = gl_ov.obj.Theme
        if tr_lov.Misc is not None and tr_lov.Misc.Legend is not None:
            tr_lov.Misc.Legend.SetIntValue(0, "AutoUpdateLegend")
            tr_lov.Misc.Legend.SetIntValue(0, "Type")
        gl_ov.obj.Theme = tr_lov
    except Exception:
        pass

    c_ptr = 0
    for xl, yl, c_hex, w_u, d_code in final_lines:
        wks_ov.from_list(c_ptr, xl, axis="X")
        wks_ov.from_list(c_ptr + 1, yl, axis="Y")
        p_ln = gl_ov.add_plot(wks_ov, coly=c_ptr + 1, colx=c_ptr, type="l")
        p_ln.color = _hex_to_origin_color(op, c_hex)
        p_idx = len(gl_ov.plot_list())
        gl_ov.lt_exec(f"range rl = !{p_idx}; set rl -w {int(w_u)}; set rl -d {int(d_code)};")
        c_ptr += 2

    for mx, my, c_hex, k_code, int_code, s_sz in final_markers:
        wks_ov.from_list(c_ptr, [mx], axis="X")
        wks_ov.from_list(c_ptr + 1, [my], axis="Y")
        p_mk = gl_ov.add_plot(wks_ov, coly=c_ptr + 1, colx=c_ptr, type="s")
        p_mk.color = _hex_to_origin_color(op, c_hex)
        p_mk.symbol_size = float(s_sz)
        p_idx = len(gl_ov.plot_list())
        if k_code == 20:
            gl_ov.lt_exec(f"range rm = !{p_idx}; set rm -k 20;")
        else:
            # Origin C `symbol.kind`: 1=Square, 2=Circle, 3=UpTri, 4=DownTri, 5=Diamond; `symbol.interior`: 0=Solid(●), 1=Open(○)
            p_mk.symbol_kind = int(k_code)
            p_mk.symbol_interior = 1 if int(int_code) == 2 else 0
        c_ptr += 2

    for xp, yb, r_str, fs, col_i, rot, pos_sc in final_texts:
        wks_ov.from_list(c_ptr, [float(xp)], axis="X")
        wks_ov.from_list(c_ptr + 1, [float(yb)], lname=r_str, axis="Y")
        p_tx = gl_ov.add_plot(wks_ov, coly=c_ptr + 1, colx=c_ptr, type="s")
        p_tx.symbol_size = 0
        # Two-step commit for Form=4 (PLOTLABEL_UI_FORM_CUSTOM -> "%(?,@LL)")
        tr = p_tx.obj.Theme
        tr.Label.SetIntValue(1, "Enable")
        tr.Label.SetIntValue(4, "Form")
        p_tx.obj.Theme = tr

        tr = p_tx.obj.Theme
        lb = tr.Label
        lb.SetIntValue(1, "Enable")
        lb.SetIntValue(4, "Form")
        lb.SetStrValue("%(?,@LL)", "FormatString")
        lb.SetIntValue(int(face_dword), "Face")
        lb.SetDoubleValue(float(fs), "Size")
        lb.SetIntValue(int(bold_flag), "Bold")
        lb.SetIntValue(int(col_i), "Color")
        lb.SetIntValue(int(rot), "Rotate")
        lb.SetIntValue(int(pos_sc), "PosScatter")
        lb.SetIntValue(0, "FrameType")
        lb.SetIntValue(0, "WhiteOut")
        p_tx.obj.Theme = tr
        c_ptr += 2

    activate_layer(op, gp, ov_lay_num)
    gl_ov.lt_exec(
        "layer.unit=1; layer.left=0; layer.top=0; layer.width=100; layer.height=100; "
        "layer.x.showAxes=0; layer.y.showAxes=0; layer.x.showLabels=0; layer.y.showLabels=0; "
        "layer.x.ticks=0; layer.y.ticks=0; layer.x2.ticks=0; layer.y2.ticks=0; "
        "layer.x.grid.show=0; layer.y.grid.show=0; layer.clip=0; "
        "XB.show=0; YL.show=0; YR.show=0; XT.show=0; label -r Legend;"
    )
    gl_ov.set_xlim(0.0, 100.0)
    gl_ov.set_ylim(0.0, 100.0)
    gl_ov.lt_exec("XB.show=0; YL.show=0; YR.show=0; XT.show=0; label -r Legend;")
    n_tot_layers = int(gp.obj.Layers.Count)
    for l_idx in range(n_tot_layers):
        try:
            activate_layer(op, gp, l_idx + 1)
            op.lt_exec("label -r Legend;")
            lay_obj = gp[l_idx].obj
            for go in list(lay_obj.GraphObjects):
                if getattr(go, "Name", "").lower() == "legend":
                    go.Destroy()
        except Exception:
            pass
    activate_layer(op, gp, 1)
    _FLUSHED_PAGES.add(gname)


def _append_swatch_primitives(
    x0: float,
    yb: float,
    sw_w: float,
    c_hex: str,
    sw_kind: str,
    fontsize: float,
    final_lines: List[Tuple[List[float], List[float], str, int, int]],
    final_markers: List[Tuple[float, float, str, int, int, float]],
) -> None:
    spec = get_active_spec()
    cw_u = int(spec["curve_w_units"])
    bdr_u = int(round(float(spec["bar_border_lw_pt"]) * 450.0))
    sk = sw_kind.lower()
    sym_sz = max(5.0, min(7.2, fontsize * 0.34))
    if sk == "bar":
        pb = ot.compute_pastel_fill_and_border(c_hex)
        fill_hex, bdr_hex = pb["fill_hex"], pb["border_hex"]
        rx0, rx1 = x0 + 0.10 * sw_w, x0 + 0.90 * sw_w
        ry_h = max(0.86, min(1.32, fontsize * 0.056))
        bar_w_u = int(round(max(1900, min(3200, fontsize * 145.0))))
        final_lines.append(([rx0 + 0.08 * sw_w, rx1 - 0.08 * sw_w], [yb, yb], fill_hex, bar_w_u, 0))
        final_lines.append(([rx0, rx1, rx1, rx0, rx0], [yb - ry_h, yb - ry_h, yb + ry_h, yb + ry_h, yb - ry_h], bdr_hex, bdr_u, 0))
    elif sk == "scatter":
        final_markers.append((x0 + 0.5 * sw_w, yb, c_hex, 2, 1, sym_sz))
    elif sk == "scatter_open":
        final_markers.append((x0 + 0.5 * sw_w, yb, c_hex, 2, 2, sym_sz))
    elif sk == "open_circle":
        final_lines.append(([x0, x0 + sw_w], [yb, yb], c_hex, cw_u, 0))
        final_markers.append((x0 + 0.5 * sw_w, yb, c_hex, 2, 2, sym_sz))
    elif sk == "line_dashed":
        final_lines.append(([x0, x0 + sw_w], [yb, yb], c_hex, cw_u, 1))
    elif sk == "line":
        final_lines.append(([x0, x0 + sw_w], [yb, yb], c_hex, cw_u, 0))
    else:
        final_lines.append(([x0, x0 + sw_w], [yb, yb], c_hex, cw_u, 0))
        final_markers.append((x0 + 0.5 * sw_w, yb, c_hex, 2, 1, sym_sz))


def apply_clamped_0_100_y_ticks(
    op: Any,
    gp: Any,
    gl: Any,
    layer_num_1based: int,
    wb: Any,
    used_sheets: set[str],
    xlim_lo: float,
    xlim_hi: float,
    *,
    ylim_top: float = 126.0,
    max_tick_val: float = 100.0,
    step_val: float = 20.0,
    side: str = "left",
    color_hex: str = "#111111",
    tick_pt: Optional[float] = None,
) -> None:
    """
    Set `ylim = (0.0, ylim_top)` (reserving `[max_tick_val .. ylim_top]` as clean interior white sky
    for in-box legends) while rendering inward ticks & `tick_pt` labels ONLY up to `max_tick_val`
    (so no spurious `120%` tick ever appears!).
    """
    spec = get_active_spec()
    pt_use = float(spec["tick_label_pt"] if tick_pt is None else tick_pt)
    tk_w_u = int(round(max(550.0, float(spec["box_lw_pt"]) * 360.0)))

    activate_layer(op, gp, layer_num_1based)
    gl.set_ylim(0.0, float(ylim_top))
    if side == "right":
        gl.lt_exec("layer.y.ticks=0; layer.y2.ticks=0; layer.y.showLabels=0; layer.y2.showLabels=0;")
    else:
        gl.lt_exec("layer.y.ticks=0; layer.y2.ticks=0; layer.y.showLabels=0;")
        register_custom_y_label_layer(gp, layer_num_1based)

    tgt_wh = _PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
    pw_in, _ph_in = tgt_wh
    cache_tmp: Dict[int, Tuple[float, float, float, float, int, int]] = {}
    l_p, t_p, w_p, h_p, _u, _ysl = _query_layer_rect_page_pct(op, gp, layer_num_1based, cache_tmp)

    x_span = float(xlim_hi) - float(xlim_lo)
    layer_w_in = max(1.0, pw_in * (w_p / 100.0))
    tick_len_x = (6.2 / (layer_w_in * 72.0)) * x_span

    n_steps = int(round(max_tick_val / max(step_val, 1e-6)))
    tick_vals = [round(i * step_val, 4) for i in range(n_steps + 1)]

    t_sh = unique_origin_short_name(f"YTicks{layer_num_1based}{side[0].upper()}", used_sheets, default="YTks")
    wks_t = wb.add_sheet(t_sh)
    wks_t.cols = 2 * len(tick_vals)
    c_oc = _hex_to_origin_color(op, color_hex)
    c_int = ot.hex_to_origin_rgb_int(color_hex)

    activate_layer(op, gp, layer_num_1based)
    for idx_t, tv in enumerate(tick_vals):
        if side == "right":
            xs_seg = [float(xlim_hi) - tick_len_x, float(xlim_hi)]
        else:
            xs_seg = [float(xlim_lo), float(xlim_lo) + tick_len_x]
        wks_t.from_list(2 * idx_t, xs_seg, axis="X")
        wks_t.from_list(2 * idx_t + 1, [tv, tv], axis="Y")
        p_tk = gl.add_plot(wks_t, coly=2 * idx_t + 1, colx=2 * idx_t, type="l")
        p_tk.color = c_oc
        tk_idx = len(gl.plot_list())
        gl.lt_exec(f"range rtk = !{tk_idx}; set rtk -w {tk_w_u};")

        yf = tv / max(float(ylim_top), 1e-6)
        y_page_pct = t_p + (1.0 - yf) * h_p
        lbl_str = f"{int(round(tv))}" if abs(tv - round(tv)) < 1e-4 else f"{tv:g}"
        if side == "right":
            x_page_pct = l_p + w_p + (0.11 / pw_in) * 100.0
            pos_sc = 2
        else:
            x_page_pct = l_p - (0.11 / pw_in) * 100.0
            pos_sc = 1
        add_page_text_label(
            op, gp, gl, layer_num_1based, f"YTkLbl_{side}_{idx_t}", lbl_str,
            x_page_pct, y_page_pct, fontsize=pt_use, color_int=c_int, pos_scatter=pos_sc, format_math=False
        )
    gl.lt_exec("label -r Legend;")


def _flush_all_pending_pages(op: Any) -> None:
    all_names = (
        set(_PENDING_AXIS_TITLES.keys())
        | set(_PENDING_TEXT_ITEMS.keys())
        | set(_PENDING_DATA_TEXT_ITEMS.keys())
        | set(_PENDING_LEGENDS.keys())
    )
    prev_pe = op.pe.cd()
    for gname in list(all_names):
        if gname in _FLUSHED_PAGES:
            continue
        gp = op.find_graph(gname)
        if gp is not None:
            flush_page_overlays(op, gp)
    op.pe.cd(prev_pe)


def _safe_save_opju(op: Any, out_p: Path) -> str:
    """Flush any un-exported graph overlays and save `.opju` safely."""
    _flush_all_pending_pages(op)
    out_p = Path(out_p).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if out_p.exists():
        try:
            with open(out_p, "r+b"):
                pass
        except PermissionError:
            stamp = time.strftime("%H%M%S")
            out_p = out_p.with_name(f"{out_p.stem}_unlocked_{stamp}{out_p.suffix}")
    op.save(str(out_p))
    return str(out_p)


def apply_origin_bar_gradient_and_label(
    p: Any,
    c_prim: int,
    c_bottom: Optional[int] = None,
    *,
    shading_mode: int = 2,
    grad_lightness: int = 90,
    grad_dir: int = 0,
    gap: int = 24,
    border_color: int = -4,
    border_width: float = 1.0,
    label_color: Optional[int] = None,
    label_size: float = 21.0,
    label_fmt: str = ".2",
    has_yerr: bool = True,
    gl: Optional[Any] = None,
    plot_idx_1based: Optional[int] = None,
    tnr_font_id: int = 0,
    tnr_face_dword: int = 1852392883,
) -> None:
    """
    Two-step OriginExt.TreeNode commit for vertical bar gradient (`ShadingMode=2` explicit two-color
    soft-white gradient or `ShadingMode=1` lightness gradient) + top bold `Times New Roman` value labels.
    """
    _ = tnr_font_id
    tr = p.obj.Theme
    fill = tr.Pattern.Fill
    fill.SetIntValue(int(c_prim), "FillColor")
    fill.SetIntValue(int(shading_mode), "ShadingMode")
    p.obj.Theme = tr

    tr = p.obj.Theme
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
        lbl.SetIntValue(int(get_active_spec()["bold_int"]), "Bold")
        lbl.SetIntValue(int(label_color), "Color")
        lbl.SetIntValue(0, "FrameType")
        lbl.SetIntValue(0, "WhiteOut")
        lbl.SetIntValue(1, "Form")
        lbl.SetStrValue(str(label_fmt), "FormatString")
        lbl.SetIntValue(18 if has_yerr else 8, "YOffset")
        if tnr_face_dword:
            lbl.SetIntValue(int(tnr_face_dword), "Face")

    p.obj.Theme = tr
    if gl is not None and plot_idx_1based is not None:
        gl.lt_exec(f"range rr = !{int(plot_idx_1based)}; set rr -pbc {int(border_color)};")
    else:
        p.set_cmd(f"-pbc {int(border_color)}")


def export_origin_publication_figures(
    op: Any,
    gp: Any,
    out_dir: str | Path,
    stem: str,
    width_in: float = 0.0,
    make_qa_preview: bool = True,
) -> Dict[str, str]:
    """
    Flush zero-overline typography overlays, then export publication-grade 600 DPI lossless LZW `.tif`
    + 300 DPI `.png` directly from OriginPro via headless `expGraph` (`tr.Margin:=2` page bounds),
    plus `<=960 px` JPEG `quality=80` QA preview.
    """
    out_p = Path(out_dir).resolve()
    out_p.mkdir(parents=True, exist_ok=True)

    if getattr(gp.obj, "Units", 0) != 0:
        w_cur = float(getattr(gp.obj, "Width", 8.0))
        h_cur = float(getattr(gp.obj, "Height", 6.0))
        gp.obj.Units = 0
        if w_cur > 30.0 or w_cur < 1.5:
            gp.obj.Width = 8.0
            gp.obj.Height = 6.0
        else:
            gp.obj.Width = w_cur
            gp.obj.Height = h_cur

    flush_page_overlays(op, gp)

    # Re-assert exact target physical canvas dimensions AFTER `flush_page_overlays` (`add_layer(0)`)
    # so `expGraph` (`tr.Margin:=2` = Page bounds) exports 100% pixel-identical dimensions across every figure!
    tgt_wh = _PAGE_TARGET_INCHES.get(gp.name)
    if tgt_wh is not None:
        gp.obj.Units = 0
        gp.obj.Width = float(tgt_wh[0])
        gp.obj.Height = float(tgt_wh[1])

    op.lt_exec(f'win -a "{gp.name}";')
    size_clause = f"tr1.Unit:=0 tr1.Width:={float(width_in)} " if (width_in and float(width_in) > 0.0) else ""

    # 1) 600 DPI lossless LZW .tif (never pass ColorSpace:=0!)
    op.po.LT_set_str("__LASTEXP", "")
    op.lt_exec(
        f'expGraph type:=tif filename:="{stem}" path:="{out_p}" overwrite:=replace '
        f"tr.Margin:=2 {size_clause}"
        f"tr2.TIF.dotsperinch:=600 tr2.TIF.BitsPerPixel:=24 tr2.TIF.compression:=LZW -sw;"
    )
    tif_str = op.po.LT_get_str("__LASTEXP") or str(out_p / f"{stem}.tif")
    tif_path = Path(tif_str)
    if not tif_path.exists() or tif_path.stat().st_size == 0:
        fallback_tif = out_p / f"{stem}.tif"
        if fallback_tif.exists() and fallback_tif.stat().st_size > 0:
            tif_path = fallback_tif
        else:
            raise RuntimeError(f"Origin expGraph failed to export 600 DPI LZW TIFF for '{gp.name}' -> {out_p / (stem + '.tif')}")

    # 2) 300 DPI .png
    op.po.LT_set_str("__LASTEXP", "")
    op.lt_exec(
        f'expGraph type:=png filename:="{stem}" path:="{out_p}" overwrite:=replace '
        f"tr.Margin:=2 {size_clause}"
        f"tr2.PNG.dotsperinch:=300 -sw;"
    )
    png_str = op.po.LT_get_str("__LASTEXP") or str(out_p / f"{stem}.png")
    png_path = Path(png_str)
    if not png_path.exists() or png_path.stat().st_size == 0:
        fallback_png = out_p / f"{stem}.png"
        if fallback_png.exists() and fallback_png.stat().st_size > 0:
            png_path = fallback_png
        else:
            raise RuntimeError(f"Origin expGraph failed to export 300 DPI PNG for '{gp.name}' -> {out_p / (stem + '.png')}")

    res: Dict[str, str] = {
        "png": str(png_path.resolve()),
        "tif": str(tif_path.resolve()),
    }

    if make_qa_preview:
        from PIL import Image

        qa_dir = out_p / "_qa_previews"
        qa_dir.mkdir(parents=True, exist_ok=True)
        qa_path = qa_dir / f"{stem}_preview.jpg"
        with Image.open(png_path) as im:
            im_rgb = im.convert("RGB")
            im_rgb.thumbnail((960, 960), Image.Resampling.LANCZOS)
            im_rgb.save(qa_path, format="JPEG", quality=80, optimize=True)
        res["qa_preview_jpg"] = str(qa_path.resolve())

    return res


def export_origin_graph_png(gp: Any, out_png: str | Path, width: int = 1600) -> str:
    """Export an Origin graph page via native expGraph (`gp.save_fig`) for true WYSIWYG verification."""
    out_p = Path(out_png).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    res_path = gp.save_fig(str(out_p), width=int(width))
    if not res_path or not Path(res_path).exists() or Path(res_path).stat().st_size == 0:
        if not out_p.exists() or out_p.stat().st_size == 0:
            raise RuntimeError(f"Origin expGraph failed to produce non-empty PNG at {out_p}")
        return str(out_p)
    return str(res_path)


def snapshot_origin_graph_state(op: Any, graph_name: str) -> Dict[str, Any]:
    """Capture plot count, GraphObjects count, and axis ranges to protect user-polished Origin graphs from edits."""
    gp = op.find_graph(graph_name)
    if gp is None:
        raise KeyError(f"Origin graph not found: {graph_name}")
    op.lt_exec(f"win -a {gp.name};")
    layers_state: List[Dict[str, Any]] = []
    idx = 0
    while True:
        try:
            gl = gp[idx]
        except Exception:
            break
        if gl is None:
            break
        op.lt_exec(f"page.active={idx + 1};")
        try:
            obj_count = int(gl.obj.GraphObjects.Count)
        except Exception:
            obj_count = -1
        try:
            xlim = tuple(float(v) for v in gl.xlim)
        except Exception:
            xlim = ()
        try:
            ylim = tuple(float(v) for v in gl.ylim)
        except Exception:
            ylim = ()
        layers_state.append(
            {
                "layer_index": idx,
                "plot_count": len(gl.plot_list()),
                "object_count": obj_count,
                "xlim": xlim,
                "ylim": ylim,
            }
        )
        idx += 1
    return {"graph_name": gp.name, "layer_count": len(layers_state), "layers": layers_state}


def _style_origin_layer_boxed(
    gl: Any,
    x_title: str,
    y_title: str,
    log_x: bool = False,
    log_y: bool = False,
    hide_y_labels: bool = False,
    minimal_ticks: bool = True,
    box_thickness: Optional[float] = None,
    x_tick_mode: str = "auto",
    tick_label_pt: Optional[float] = None,
    axis_title_pt: Optional[float] = None,
    layer_rect_pct: Optional[Tuple[float, float, float, float]] = None,
    layer_rect_in: Optional[Tuple[float, float, float, float]] = None,
    remove_legend: bool = True,
    op: Optional[Any] = None,
    gp: Optional[Any] = None,
    layer_num_1based: int = 1,
) -> None:
    spec = get_active_spec()
    if op is not None and gp is not None:
        activate_layer(op, gp, layer_num_1based)

    tgt_wh = (
        _PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
        if gp is not None
        else (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"]))
    )
    pw_in, ph_in = tgt_wh

    if layer_rect_in is not None:
        li, ti, wi, hi = layer_rect_in
        gl.lt_exec(f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi};")
        lw_in, lh_in = float(wi), float(hi)
    elif layer_rect_pct is not None:
        l_p, t_p, w_p, h_p = layer_rect_pct
        gl.lt_exec(f"layer.unit=1; layer.left={l_p}; layer.top={t_p}; layer.width={w_p}; layer.height={h_p};")
        lw_in, lh_in = pw_in * (float(w_p) / 100.0), ph_in * (float(h_p) / 100.0)
    else:
        li, ti, wi, hi = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        gl.lt_exec(f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi};")
        lw_in, lh_in = wi, hi

    if box_thickness is None or abs(float(box_thickness) - 3.0) < 0.05:
        bt = float(spec["box_lw_pt"])
    else:
        bt = float(box_thickness)
    tk_pt_req = float(spec["tick_label_pt"] if tick_label_pt is None else tick_label_pt)
    ax_pt_req = float(spec["axis_title_pt"] if axis_title_pt is None else axis_title_pt)
    comp_tick_pt = ot.compensate_origin_layer_pt(tk_pt_req, lw_in, lh_in, pw_in, ph_in)
    ink_int = ot.hex_to_origin_rgb_int("#111111")
    f_id = get_font_id(op) if op is not None else 0
    font_clause = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""
    bold_i = int(spec["bold_int"])

    gl.lt_exec(
        f"layer.x.grid.show=0; layer.y.grid.show=0; "
        f"layer.x.showAxes=3; layer.y.showAxes=3; "
        f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
        f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
        f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
        f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
        f"{font_clause}"
        f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
        f"layer.x.label.pt={comp_tick_pt}; layer.y.label.pt={comp_tick_pt}; "
        f"layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i};"
    )

    if log_x:
        gl.lt_exec("layer.x.type=2; layer.x.minorTicks=8; layer.x.label.numFormat=2;")
    if log_y:
        gl.lt_exec("layer.y.type=2; layer.y.minorTicks=8; layer.y.label.numFormat=2;")

    mode = x_tick_mode if x_tick_mode != "auto" else ("minimal" if minimal_ticks else "full")
    if mode in ("minimal", "continuous_minor1"):
        x_tick_code = 5 if log_x else 1
        gl.lt_exec(f"layer.x.ticks={x_tick_code}; layer.x2.ticks=0; layer.y2.ticks=0;")
    elif mode == "none":
        gl.lt_exec("layer.x.ticks=0; layer.x2.ticks=0; layer.y2.ticks=0;")
    else:
        gl.lt_exec("layer.x.ticks=5;")

    if mode != "full":
        if hide_y_labels:
            gl.lt_exec("layer.y.showLabels=0; layer.y.ticks=0;")
        else:
            y_tick_code = 5 if log_y else 1
            gl.lt_exec(f"layer.y.ticks={y_tick_code}; layer.y.showLabels=1;")
    else:
        gl.lt_exec("layer.y.ticks=5;")
        if hide_y_labels:
            gl.lt_exec("layer.y.showLabels=0; layer.y.ticks=0;")

    style_origin_native_axis_title(
        gl, "XB", x_title, fontsize=ax_pt_req, color_int=ink_int, op=op, gp=gp, layer_num_1based=layer_num_1based
    )
    style_origin_native_axis_title(
        gl, "YL", y_title, fontsize=ax_pt_req, color_int=ink_int, op=op, gp=gp, layer_num_1based=layer_num_1based
    )
    sanitize_layer_frames_and_grids(
        gl, remove_default_legend=True, op=op, gp=gp, layer_num_1based=layer_num_1based
    )
    if not remove_legend:
        gl.lt_exec("label -r Legend;")


def _populate_deconv_layer(
    op: Any,
    gp: Any,
    wks: Any,
    gl: Any,
    layer_num_1based: int,
    res: Dict[str, Any],
    *,
    minimal_ticks: bool = True,
    box_thickness: Optional[float] = None,
    layer_rect_pct: Optional[Tuple[float, float, float, float]] = None,
    layer_rect_in: Optional[Tuple[float, float, float, float]] = None,
    axis_title_pt: Optional[float] = None,
    tick_label_pt: Optional[float] = None,
    panel_title: str = "",
) -> List[Tuple[Any, ...]]:
    spec = get_active_spec()
    activate_layer(op, gp, layer_num_1based)
    x = np.asarray(res["x"], dtype=float)
    invert_x = bool(res.get("invert_x", False))
    bg_col_int = _hex_to_origin_color(op, "#222222")
    theme_deconv = ot.load_theme().get("deconv_colors", {})
    comp_pal = theme_deconv.get(
        "components", ["#3E86DE", "#D84B5C", "#6579BE", "#E88B9C", "#A8C4E8", "#2B6CB0"]
    )
    is_small_cell = bool((layer_rect_in and layer_rect_in[2] < 4.3) or (layer_rect_pct and layer_rect_pct[2] < 48.0))
    comp_w = int(round(spec["sub_w_units"] * (0.85 if is_small_cell else 1.0)))
    fit_w = int(round(spec["curve_w_units"] * (0.82 if is_small_cell else 1.0)))

    leg_entries: List[Tuple[Any, ...]] = []
    for i, m in enumerate(res["components"]):
        raw_c_hex = ot.normalize_hex(m.get("color") or comp_pal[i % len(comp_pal)])
        pb = ot.compute_pastel_fill_and_border(raw_c_hex)
        bdr_int = _hex_to_origin_color(op, pb["border_hex"])
        fill_int = _hex_to_origin_color(op, pb["fill_hex"])
        area_pct_v = float(m.get("area_pct", 100.0))
        p_c = gl.add_plot(wks, coly=4 + i, colx=0, type="l")
        p_c.color = bdr_int
        c_idx_1 = len(gl.plot_list())
        gl.lt_exec(f"range rc = !{c_idx_1}; set rc -w {comp_w};")

        p_bg_anchor = gl.add_plot(wks, coly=2, colx=0, type="l")
        p_bg_anchor.color = bg_col_int
        bg_idx_1 = len(gl.plot_list())
        gl.lt_exec(f"range rb = !{bg_idx_1}; set rb -w {max(500, comp_w - 80)};")

        p_c.set_fill_area(above=fill_int, type=9, below=fill_int)
        p_c.transparency = 16
        if area_pct_v >= 0.35 or len(res["components"]) <= 2:
            leg_entries.append((c_idx_1, m.get("label") or m["name"], pb["border_hex"], "bar"))

    raw_hex = "#111111"
    raw_x_col, raw_y_col = 0, 1
    try:
        if wks.cols >= 6 + len(res["components"]):
            raw_x_col = 5 + len(res["components"])
            raw_y_col = 6 + len(res["components"])
    except Exception:
        pass
    p_raw = gl.add_plot(wks, coly=raw_y_col, colx=raw_x_col, type="s")
    raw_idx_1 = len(gl.plot_list())
    p_raw.color = _hex_to_origin_color(op, raw_hex)
    p_raw.symbol_size = 4.4 if is_small_cell else 6.2
    p_raw.symbol_kind = 2
    p_raw.symbol_interior = 0

    fit_hex = ot.normalize_hex(theme_deconv.get("envelope_fit", "#A02333"))
    p_fit = gl.add_plot(wks, coly=3, colx=0, type="l")
    fit_idx_1 = len(gl.plot_list())
    p_fit.color = _hex_to_origin_color(op, fit_hex)
    gl.lt_exec(f"range rfit = !{fit_idx_1}; set rfit -w {fit_w};")

    leg_final: List[Tuple[Any, ...]] = [
        (raw_idx_1, "Experimental", raw_hex, "scatter"),
        (fit_idx_1, "Fitted", fit_hex, "line"),
    ] + leg_entries

    gl.rescale()
    ymin = float(np.min(np.minimum(res["y_raw"], res["baseline"])))
    ymax = float(np.max(np.maximum(res["y_raw"], res["y_fit"])))
    yspan = max(ymax - ymin, 1e-6)
    n_comp_vis = len(leg_final)
    top_headroom = 0.32 if is_small_cell else (0.94 if n_comp_vis >= 6 else (0.72 if n_comp_vis >= 4 else 0.56))
    gl.set_ylim(ymin - 0.08 * yspan, ymax + top_headroom * yspan)
    x_min_v, x_max_v = float(np.min(x)), float(np.max(x))
    x_pad = 0.02 * max(x_max_v - x_min_v, 1e-6)
    if invert_x:
        gl.set_xlim(x_max_v + x_pad, x_min_v - x_pad)
    else:
        gl.set_xlim(x_min_v - x_pad, x_max_v + x_pad)

    _style_origin_layer_boxed(
        gl,
        res.get("x_label", "X").replace("$", ""),
        "Intensity (a.u.)",
        hide_y_labels=True,
        minimal_ticks=minimal_ticks,
        box_thickness=box_thickness,
        x_tick_mode="minimal" if minimal_ticks else "auto",
        tick_label_pt=tick_label_pt,
        axis_title_pt=axis_title_pt,
        layer_rect_pct=layer_rect_pct,
        layer_rect_in=layer_rect_in,
        remove_legend=True,
        op=op,
        gp=gp,
        layer_num_1based=layer_num_1based,
    )
    if not is_small_cell:
        x_step_dec = compute_nice_linear_step(x_min_v, x_max_v, max_ticks=6)
        if x_step_dec:
            gl.lt_exec(f"layer.x.inc={x_step_dec};")

    if panel_title:
        t_clean = ot.clean_semantic_sample_name(panel_title, True)
        tgt_wh = _PAGE_TARGET_INCHES.get(gp.name, (float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])))
        if layer_rect_in is not None:
            l_p, t_p, w_p, _h_p = ot.rect_in_to_page_pct(*layer_rect_in, tgt_wh[0], tgt_wh[1])
        elif layer_rect_pct is not None:
            l_p, t_p, w_p, _h_p = layer_rect_pct
        else:
            l_p, t_p, w_p, _h_p = 20.7, 12.2, 61.5, 61.5
        if is_small_cell:
            add_page_text_label(
                op,
                gp,
                gl,
                layer_num_1based,
                f"PnlTitle{layer_num_1based}",
                t_clean,
                l_p + 0.5 * w_p,
                max(1.8, t_p - 2.6),
                fontsize=max(15.0, float(axis_title_pt or spec["axis_title_pt"]) * 0.86),
                pos_scatter=0,
                format_math=False,
            )
        else:
            # Place sample/region label below the horizontal legend on whichever outer X-wing has lower spectrum height
            y_fit_arr = np.asarray(res["y_fit"], dtype=float)
            x_sp_v = max(x_max_v - x_min_v, 1e-6)
            if invert_x:
                left_mask = x >= (x_max_v - 0.28 * x_sp_v)
                right_mask = x <= (x_min_v + 0.28 * x_sp_v)
            else:
                left_mask = x <= (x_min_v + 0.28 * x_sp_v)
                right_mask = x >= (x_max_v - 0.28 * x_sp_v)
            l_pk = float(np.max(y_fit_arr[left_mask])) if np.any(left_mask) else ymax
            r_pk = float(np.max(y_fit_arr[right_mask])) if np.any(right_mask) else ymax
            y_title_off = 21.8 if n_comp_vis >= 6 else 17.2
            if r_pk <= l_pk + 0.05 * yspan:
                tx_p, p_sc = l_p + w_p - 2.6, 1
            else:
                tx_p, p_sc = l_p + 2.6, 2
            add_page_text_label(
                op,
                gp,
                gl,
                layer_num_1based,
                f"PnlTitle{layer_num_1based}",
                t_clean,
                tx_p,
                t_p + y_title_off,
                fontsize=float(spec["callout_pt"]),
                pos_scatter=p_sc,
                format_math=False,
            )

    return leg_final


def _create_deconv_sheet(
    op: Any,
    sample_name: str,
    reg_name: str,
    res: Dict[str, Any],
    wb: Optional[Any] = None,
    used_names: Optional[set[str]] = None,
    use_first_sheet: bool = False,
) -> Any:
    x = np.asarray(res["x"], dtype=float)
    invert_x = bool(res.get("invert_x", False))
    order = np.argsort(-x) if invert_x else np.argsort(x)

    cols_dict: Dict[str, Any] = {
        "X": x[order],
        "Raw": np.asarray(res["y_raw"], dtype=float)[order],
        "Backgnd.": np.asarray(res["baseline"], dtype=float)[order],
        "Fitting": np.asarray(res["y_fit"], dtype=float)[order],
    }
    for m, c_bg in zip(res["components"], res["comp_curves_with_bg"]):
        cols_dict[m["name"]] = np.asarray(c_bg, dtype=float)[order]
    cols_dict["Residuals"] = np.asarray(res["residuals"], dtype=float)[order]

    x_ord = x[order]
    y_raw_ord = np.asarray(res["y_raw"], dtype=float)[order]
    n_tot = len(x_ord)
    step_sub = max(1, int(math.ceil(n_tot / 135.0)))
    sub_x = [float(x_ord[k]) if k % step_sub == 0 else np.nan for k in range(n_tot)]
    sub_y = [float(y_raw_ord[k]) if k % step_sub == 0 else np.nan for k in range(n_tot)]
    cols_dict["RawSub_X"] = sub_x
    cols_dict["RawSub_Y"] = sub_y

    df = pd.DataFrame(cols_dict)
    if wb is None:
        wb = op.new_book("w", lname=f"{sample_name}_{reg_name}_Book")
        wks = wb[0]
        wks.name = sanitize_origin_short_name(reg_name, "Spec")
    elif use_first_sheet:
        sh_name = unique_origin_short_name(
            f"{sample_name}{reg_name}", used_names if used_names is not None else set(), default="Spec"
        )
        wks = wb[0]
        wks.name = sh_name
    else:
        sh_name = unique_origin_short_name(
            f"{sample_name}{reg_name}", used_names if used_names is not None else set(), default="Spec"
        )
        wks = wb.add_sheet(sh_name)

    wks.from_df(df)
    n_base_y = 4 + len(res["components"])
    wks.cols_axis("X" + "Y" * n_base_y + "XY")
    x_unit = "eV" if "eV" in res.get("x_label", "") else "cm^-1"
    y_unit = "Counts / s" if x_unit == "eV" else "Counts"
    wks.set_label(0, res.get("x_label", "X").replace("$", ""), "L")
    wks.set_label(0, x_unit, "U")
    for c_idx in range(1, 1 + n_base_y):
        wks.set_label(c_idx, y_unit, "U")
        if 4 <= c_idx < 4 + len(res["components"]):
            wks.set_label(c_idx, "Baseline-anchored component", "C")
    return wks


def _populate_deconv_book_and_graph(
    op: Any,
    sample_name: str,
    reg_name: str,
    res: Dict[str, Any],
    minimal_ticks: bool = True,
    box_thickness: Optional[float] = None,
    region_title: str = "",
) -> Any:
    spec = get_active_spec()
    wks = _create_deconv_sheet(op, sample_name, reg_name, res)
    gp = op.new_graph(lname=f"{sample_name}_{reg_name}")
    pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
    set_graph_page_inches(gp, pw, ph)
    gl = gp[0]
    box_in = (
        float(spec["box_rect_left_in"]),
        float(spec["box_rect_top_in"]),
        float(spec["box_rect_w_in"]),
        float(spec["box_rect_h_in"]),
    )
    rect_pct = ot.rect_in_to_page_pct(*box_in, pw, ph)
    leg = _populate_deconv_layer(
        op,
        gp,
        wks,
        gl,
        1,
        res,
        minimal_ticks=minimal_ticks,
        box_thickness=box_thickness,
        layer_rect_pct=rect_pct,
        layer_rect_in=box_in,
        panel_title=region_title or reg_name,
    )
    leg_fs = 20.0 if len(leg) >= 3 else float(spec["legend_pt"])
    configure_custom_legend(
        gl,
        leg,
        fontsize=leg_fs,
        horizontal=True,
        pos_mode="interior_top",
        layer_rect_pct=rect_pct,
        op=op,
        gp=gp,
        layer_num_1based=1,
    )
    return gp


def build_deconv_opju(
    regions_results: Dict[str, Dict[str, Any]],
    out_opju: str | Path,
    sample_name: str = "Sample",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    stem_template: str = "{sample}_{reg}",
    region_titles: Optional[Dict[str, str]] = None,
    exported_figures_out: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        built_pages: List[Tuple[str, Any]] = []
        for reg_name, res in regions_results.items():
            r_title = (region_titles or {}).get(reg_name, f"{sample_name} {reg_name}")
            gp = _populate_deconv_book_and_graph(
                op,
                sample_name,
                reg_name,
                res,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                region_title=r_title,
            )
            built_pages.append((reg_name, gp))

        if export_dir is not None:
            for reg_name, gp in built_pages:
                stem = stem_template.format(sample=sample_name, reg=reg_name)
                figs = export_origin_publication_figures(op, gp, export_dir, stem)
                if exported_figures_out is not None:
                    exported_figures_out[reg_name] = figs

        return _safe_save_opju(op, out_p)


def build_deconv_grid_opju(
    panel_items: List[Dict[str, Any]],
    out_opju: str | Path,
    *,
    ncols: int = 2,
    project_title: str = "Deconv_Grid",
    minimal_ticks: bool = True,
    box_thickness: float = 2.2,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    out_p = Path(out_opju).resolve()
    n_panels = max(1, len(panel_items))
    ncols_eff = max(1, min(int(ncols), n_panels))
    nrows_eff = int(math.ceil(n_panels / ncols_eff))

    with origin_session() as op:
        wb = op.new_book("w", lname=f"{project_title}_Book")
        used_sh: set[str] = set()
        gp = op.new_graph(lname=f"{project_title}_Grid")
        set_graph_page_inches(gp, 4.8 * ncols_eff, 4.1 * nrows_eff)

        cell_w = 88.0 / ncols_eff
        cell_h = 84.0 / nrows_eff

        for idx, item in enumerate(panel_items):
            r_i = idx // ncols_eff
            c_i = idx % ncols_eff
            rect = (
                7.5 + c_i * cell_w + cell_w * 0.08,
                7.5 + r_i * cell_h + cell_h * 0.11,
                cell_w * 0.83,
                cell_h * 0.66,
            )
            sh_wks = _create_deconv_sheet(
                op,
                item["name"],
                f"P{idx+1}",
                item["fit"],
                wb=wb,
                used_names=used_sh,
                use_first_sheet=(idx == 0),
            )
            gl = gp[0] if idx == 0 else gp.add_layer(0)
            lay_num = idx + 1
            # For Raman panels: enforce X axis increment of 500 cm-1
            _fit_meta = item.get("fit", {})
            _xlbl = (_fit_meta.get("x_label") or "").lower()
            if "raman" in _xlbl or "cm" in _xlbl or _fit_meta.get("region", "").lower() in ("firstorder", "first_order", "g_band", "d_band"):
                gl.lt_exec("layer.x.inc=500;")
            leg = _populate_deconv_layer(
                op,
                gp,
                sh_wks,
                gl,
                lay_num,
                item["fit"],
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                layer_rect_pct=rect,
                axis_title_pt=14.5,
                tick_label_pt=12.0,
                panel_title=("Component Fraction (%)" if item["name"].lower().replace(" ", "_") in ("firstorder", "first_order") else item["name"]),
            )
            # No per-cell legend: shared legend added after all cells
            gl.lt_exec("label -r Legend;")
            # Bold no-paren corner label (a, b, c...)
            cell_letter = chr(ord("a") + idx)
            add_page_text_label(
                op, gp, gl, lay_num,
                f"CellLbl{lay_num}",
                cell_letter,
                max(1.0, rect[0] - 4.5),
                max(1.0, rect[1] - 2.8),
                fontsize=14.0,
                pos_scatter=0,
                format_math=False,
            )

        # Shared legend above the grid top frame, using entries from first panel
        if panel_items:
            gl_first = gp[0]
            first_rect = (
                7.5 + 0 * (88.0 / ncols_eff) + (88.0 / ncols_eff) * 0.08,
                7.5 + 0 * (84.0 / nrows_eff) + (84.0 / nrows_eff) * 0.11,
                (88.0 / ncols_eff) * 0.83,
                (84.0 / nrows_eff) * 0.66,
            )
            # Collect full entry list from first panel's _populate result (re-run to get entries)
            # Use a simplified entry set: Experimental + Fitted Envelope + components
            first_fit = panel_items[0]["fit"]
            comp_pal = ot.load_theme().get("deconv_colors", {}).get(
                "components", ["#3E86DE", "#D84B5C", "#6579BE", "#E8A3AF", "#A02333", "#C5DBF5"]
            )
            shared_leg = [(None, "Experimental", "#111111", "scatter"), (None, "Fitted", "#A02333", "line")]
            for ci, m in enumerate(first_fit.get("components", [])):
                c_hex = ot.normalize_hex(m.get("color") or comp_pal[ci % len(comp_pal)])
                shared_leg.append((None, m.get("label") or m["name"], c_hex, "line"))
            configure_custom_legend(
                gl_first,
                shared_leg,
                fontsize=14.0,
                horizontal=True,
                pos_mode="above_frame",
                layer_rect_pct=first_rect,
                op=op,
                gp=gp,
                layer_num_1based=1,
            )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or f"{project_title}_Grid")
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_batch_deconv_opju(
    cohort_aggregates: List[Dict[str, Any]],
    reg_name: str,
    comp_labels: List[str],
    comp_colors: List[str],
    pct_matrix: np.ndarray,
    out_opju: str | Path,
    project_title: str = "Batch_Cohort",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    grid_ncols: int = 3,
    export_dir: Optional[str | Path] = None,
    exported_figures_out: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with tempfile.TemporaryDirectory(prefix="sciorigin_pal_") as tmp_pal_dir:
        with origin_session() as op:
            root_path = op.pe.cd()
            sub_sum = op.pe.mkdir("00_Cohort_Summary", True)
            op.pe.cd(sub_sum)

            wb_sum = op.new_book("w", lname=f"{project_title}_Summary")
            wks_sum = wb_sum[0]
            wks_sum.name = "AreaFractionPct"
            used_sum_sh: set[str] = {"AreaFractionPct"}
            sample_ids = [
                ot.clean_semantic_sample_name(str(e.get("name") or e["id"]), True) for e in cohort_aggregates
            ]
            sum_dict: Dict[str, Any] = {"Sample": sample_ids}
            K = len(comp_labels)
            for c_i, cl in enumerate(comp_labels):
                sum_dict[cl] = pct_matrix[:, c_i].tolist()
            wks_sum.from_df(pd.DataFrame(sum_dict))
            wks_sum.set_label(0, "Sample", "L")
            for c_i, cl in enumerate(comp_labels):
                wks_sum.set_label(1 + c_i, str(cl), "L")
                wks_sum.set_label(1 + c_i, "%", "U")
            wks_sum.cols_axis("X" + "Y" * K)

            pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
            box_in = (
                float(spec["box_rect_left_in"]),
                float(spec["box_rect_top_in"]),
                float(spec["box_rect_w_in"]),
                float(spec["box_rect_h_in"]),
            )
            bar_rect = ot.rect_in_to_page_pct(*box_in, pw, ph)

            gp_bar = op.new_graph(lname=f"{project_title}_StackedColumn", template="STACKCOLUMN")
            set_graph_page_inches(gp_bar, pw, ph)
            op.lt_exec(f"plotxy iy:={wks_sum.lt_range(False)}!(1,2:{1 + K}) plot:=213 ogl:=[{gp_bar.name}]1!;")
            gl_bar = gp_bar[0]

            resolved_cols = (
                [ot.normalize_hex(c) for c in comp_colors]
                if comp_colors
                else ot.resolve_series_colors(K, scheme="sandwich_stack")
            )
            pastel_fills = [ot.compute_pastel_fill_and_border(c)["fill_hex"] for c in resolved_cols]
            pal_path = ot.write_discrete_riff_pal(Path(tmp_pal_dir) / "batch_stack.pal", pastel_fills)
            gl_bar.set_str("plot1.colorlist", pal_path)
            gl_bar.set_int("plot1.cmap.stretchpal", 0)
            gl_bar.set_int("plot1.colorinc", 1)

            bdr_int = ot.hex_to_origin_rgb_int("#2B3440")
            bdr_lw = float(spec["bar_border_lw_pt"])
            for k_i in range(1, K + 1):
                gl_bar.lt_exec(f"range rr = !{k_i}; set rr -pbc {bdr_int}; set rr -pbw {bdr_lw};")
            try:
                dp0 = gl_bar.obj.DataPlots[0]
                tr0 = dp0.Theme
                if tr0.Pattern.Border is not None:
                    tr0.Pattern.Border.SetIntValue(bdr_int, "Color")
                    tr0.Pattern.Border.SetDoubleValue(bdr_lw, "Width")
                if tr0.Spacing is not None:
                    tr0.Spacing.SetIntValue(26, "Gap")
                if tr0.Label is not None:
                    tr0.Label.SetIntValue(0, "Enable")
                dp0.Theme = tr0
            except Exception:
                pass

            n_bars = len(sample_ids)
            x_lo_b, x_hi_b = 0.4, float(n_bars) + 0.6
            gl_bar.rescale()
            gl_bar.set_xlim(x_lo_b, x_hi_b)
            y_bar_lbl = "Component Fraction (%)" if reg_name.lower() in ("firstorder", "first_order") else f"{reg_name} Fraction (%)"
            _style_origin_layer_boxed(
                gl_bar,
                "",
                y_bar_lbl,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                x_tick_mode="none",
                layer_rect_pct=bar_rect,
                layer_rect_in=box_in,
                remove_legend=True,
                op=op,
                gp=gp_bar,
                layer_num_1based=1,
            )
            apply_clamped_0_100_y_ticks(
                op,
                gp_bar,
                gl_bar,
                1,
                wb_sum,
                used_sum_sh,
                x_lo_b,
                x_hi_b,
                ylim_top=126.0,
                max_tick_val=100.0,
                step_val=20.0,
                tick_pt=float(spec["tick_label_pt"]),
            )
            render_categorical_x_labels_clean(
                op,
                gp_bar,
                gl_bar,
                1,
                sample_ids,
                xlim_lo=x_lo_b,
                xlim_hi=x_hi_b,
                tick_label_pt=float(spec["tick_label_pt"]),
            )
            leg_bar = [
                (k_i, str(comp_labels[k_i - 1]), resolved_cols[(k_i - 1) % len(resolved_cols)], "bar")
                for k_i in range(1, K + 1)
            ]
            configure_custom_legend(
                gl_bar,
                leg_bar,
                fontsize=float(spec["legend_pt"]),
                horizontal=True,
                pos_mode="interior_top",
                layer_rect_pct=bar_rect,
                op=op,
                gp=gp_bar,
                layer_num_1based=1,
            )

            # Cohort Representative 2x3 Grid (exact 4:3 physical cells `3.60 x 2.70 in` with dedicated header band)
            n_samp = max(1, len(cohort_aggregates))
            nc = max(1, min(int(grid_ncols), n_samp))
            nr = int(math.ceil(n_samp / nc))
            grid_pw = 1.05 + 4.55 * nc
            grid_ph = 1.50 + 4.25 * nr
            gp_grid = op.new_graph(lname=f"{project_title}_PanelGrid")
            set_graph_page_inches(gp_grid, grid_pw, grid_ph)
            wb_grid = op.new_book("w", lname=f"{project_title}_GridBook")
            used_gsh: set[str] = set()
            cell_bt = round(max(1.2, float(spec["box_lw_pt"]) * 0.80), 2)

            for s_i, entry in enumerate(cohort_aggregates):
                r_i, c_i = s_i // nc, s_i % nc
                c_left_in = 1.25 + c_i * 4.55
                c_top_in = 1.68 + r_i * 4.25
                c_box_in = (c_left_in, c_top_in, 3.60, 2.70)
                rect_g = ot.rect_in_to_page_pct(*c_box_in, grid_pw, grid_ph)

                fit_r = entry["agg"]["representative_fit"]
                wks_g = _create_deconv_sheet(
                    op,
                    entry["id"],
                    reg_name,
                    fit_r,
                    wb=wb_grid,
                    used_names=used_gsh,
                    use_first_sheet=(s_i == 0),
                )
                gl_g = gp_grid[0] if s_i == 0 else gp_grid.add_layer(0)
                lay_num = s_i + 1
                _populate_deconv_layer(
                    op,
                    gp_grid,
                    wks_g,
                    gl_g,
                    lay_num,
                    fit_r,
                    minimal_ticks=minimal_ticks,
                    box_thickness=cell_bt,
                    layer_rect_pct=rect_g,
                    layer_rect_in=c_box_in,
                    axis_title_pt=20.0,
                    tick_label_pt=16.5,
                    panel_title=entry.get("name", entry["id"]),
                )
                activate_layer(op, gp_grid, lay_num)
                gl_g.lt_exec("layer.x.maxTicks=4; label -r Legend;")
                cell_letter_g = chr(ord("a") + s_i)
                add_page_text_label(
                    op, gp_grid, gl_g, lay_num,
                    f"GCell{lay_num}",
                    cell_letter_g,
                    max(1.2, rect_g[0] - 3.6),
                    max(1.5, rect_g[1] - 2.6),
                    fontsize=22.0,
                    pos_scatter=0,
                    format_math=False,
                )

            if cohort_aggregates:
                gl_grid0 = gp_grid[0]
                first_fit_g = cohort_aggregates[0]["agg"]["representative_fit"]
                theme_dec_g = ot.load_theme().get("deconv_colors", {})
                comp_pal_g = theme_dec_g.get(
                    "components", ["#3E86DE", "#D84B5C", "#6579BE", "#E88B9C", "#A8C4E8", "#2B6CB0"]
                )
                fit_hex_g = ot.normalize_hex(theme_dec_g.get("envelope_fit", "#A02333"))
                shared_leg_g = [(None, "Experimental", "#111111", "scatter"), (None, "Fitted", fit_hex_g, "line")]
                for ci, m in enumerate(first_fit_g.get("components", [])):
                    c_hex_g = ot.normalize_hex(m.get("color") or comp_pal_g[ci % len(comp_pal_g)])
                    shared_leg_g.append((None, m.get("label") or m["name"], c_hex_g, "bar"))
                top_row_pct = (1.68 / grid_ph) * 100.0
                full_grid_span = (8.0, top_row_pct, 84.0, (2.70 / grid_ph) * 100.0)
                configure_custom_legend(
                    gl_grid0,
                    shared_leg_g,
                    fontsize=20.0,
                    horizontal=True,
                    pos_mode="above_frame_grid",
                    layer_rect_pct=full_grid_span,
                    op=op,
                    gp=gp_grid,
                    layer_num_1based=1,
                )

            for idx, entry in enumerate(cohort_aggregates, start=1):
                op.pe.cd(root_path)
                safe_folder = f"{idx:02d}_Sample_{sanitize_origin_short_name(entry['id'], f'S{idx}')}"
                sub_p = op.pe.mkdir(safe_folder, True)
                op.pe.cd(sub_p)
                _populate_deconv_book_and_graph(
                    op,
                    entry["id"],
                    reg_name,
                    entry["agg"]["representative_fit"],
                    minimal_ticks=minimal_ticks,
                    box_thickness=box_thickness,
                )

            op.pe.cd(root_path)
            if export_dir is not None:
                bar_figs = export_origin_publication_figures(op, gp_bar, export_dir, f"{project_title}_StackedBar")
                grid_figs = export_origin_publication_figures(op, gp_grid, export_dir, f"{project_title}_PanelGrid")
                if exported_figures_out is not None:
                    exported_figures_out["stacked_bar"] = bar_figs
                    exported_figures_out["panel_grid"] = grid_figs

            return _safe_save_opju(op, out_p)


def build_waterfall_opju(
    processed_curves: List[Dict[str, Any]],
    out_opju: str | Path,
    x_label: str,
    y_label: str = "Intensity (a.u.)",
    invert_x: bool = False,
    project_title: str = "Waterfall",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    markers: Optional[List[Dict[str, Any]]] = None,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        wb = op.new_book("w", lname=f"{project_title}_Data")
        wks = wb[0]
        wks.name = "StackedOffset"
        n_curves = len(processed_curves)
        n_markers = len(markers or [])
        wks.cols = n_curves * 2 + n_markers * 2

        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(*box_in, pw, ph)

        gp = op.new_graph(lname=f"{project_title}_Graph")
        set_graph_page_inches(gp, pw, ph)
        gl = gp[0]

        pal = ot.resolve_series_colors(n_curves, scheme="sequential_blue_red" if n_curves >= 5 else "paired_semantic")
        xmin_all, xmax_all, ymin_all, ymax_all = [], [], [], []
        leg_entries: List[Tuple[Any, ...]] = []
        col_idx = 0
        marker_col_start = n_curves * 2

        for idx, item in enumerate(processed_curves):
            nm = ot.clean_semantic_sample_name(str(item["name"]), True)
            xv = np.asarray(item["x"], dtype=float)
            yv = np.asarray(item["y_offset"], dtype=float)
            wks.from_list(col_idx, xv.tolist(), lname=f"{nm}_X", axis="X")
            wks.from_list(col_idx + 1, yv.tolist(), lname=nm, axis="Y")
            xmin_all.append(float(np.min(xv)))
            xmax_all.append(float(np.max(xv)))
            ymin_all.append(float(np.min(yv)))
            ymax_all.append(float(np.max(yv)))
            col_idx += 2

        ymin_g = min(ymin_all) if ymin_all else 0.0
        ymax_g = max(ymax_all) if ymax_all else 1.0
        yspan_g = max(ymax_g - ymin_g, 1e-6)
        y_lo = ymin_g - 0.06 * yspan_g
        # Reserve dedicated interior headroom for peak tags + 3-column horizontal in-box legend rows!
        if n_curves >= 5:
            y_hi = ymax_g + (1.24 if markers else 0.50) * yspan_g
        else:
            y_hi = ymax_g + (0.78 if markers else 0.36) * yspan_g
        x_span_wf = max((max(xmax_all) - min(xmin_all)) if xmin_all else 1.0, 1e-6)

        def _local_top_curve_y(pos_x: float) -> float:
            loc_hi = ymin_g
            win = 0.035 * x_span_wf
            for it_c in processed_curves:
                xc = np.asarray(it_c["x"], dtype=float)
                yc = np.asarray(it_c["y_offset"], dtype=float)
                msk = np.abs(xc - pos_x) <= win
                if np.any(msk):
                    loc_hi = max(loc_hi, float(np.max(yc[msk])))
            return loc_hi if loc_hi > ymin_g else ymax_g

        mk_col_pool = ["#D84B5C", "#2B6CB0", "#6579BE", "#A02333", "#3E86DE"]
        col_m = marker_col_start
        sub_w = int(spec["sub_w_units"])
        if markers:
            for m_i, mk in enumerate(markers):
                m_pos = float(mk["pos"])
                m_col_hex = mk.get("color") or mk_col_pool[m_i % len(mk_col_pool)]
                loc_top = _local_top_curve_y(m_pos) + 0.042 * yspan_g
                wks.from_list(col_m, [m_pos, m_pos], lname=f"Guide_{m_i+1}_X", axis="X")
                wks.from_list(col_m + 1, [y_lo, loc_top], lname=f"Guide_{m_i+1}_Y", axis="Y")
                p_mk = gl.add_plot(wks, coly=col_m + 1, colx=col_m, type="l")
                p_mk.color = _hex_to_origin_color(op, m_col_hex)
                mk_idx_1 = len(gl.plot_list())
                gl.lt_exec(f"range rmk = !{mk_idx_1}; set rmk -d 1; set rmk -w {sub_w};")
                col_m += 2

        col_idx = 0
        cw_u = int(spec["curve_w_units"])
        for idx, item in enumerate(processed_curves):
            nm = ot.clean_semantic_sample_name(str(item["name"]), True)
            plt_obj = gl.add_plot(wks, coly=col_idx + 1, colx=col_idx, type="l")
            c_hex = ot.normalize_hex(item.get("color") or pal[idx % len(pal)])
            plt_obj.color = _hex_to_origin_color(op, c_hex)
            p_idx_1 = len(gl.plot_list())
            gl.lt_exec(f"range rr = !{p_idx_1}; set rr -w {cw_u};")
            leg_entries.append((p_idx_1, nm, c_hex, "line"))
            col_idx += 2

        wks_raw = wb.add_sheet("RawUnshifted")
        wks_raw.cols = n_curves * 2
        r_col = 0
        for item in processed_curves:
            nm = str(item["name"])
            wks_raw.from_list(r_col, np.asarray(item["x"], dtype=float).tolist(), lname=f"{nm}_X", axis="X")
            wks_raw.from_list(r_col + 1, np.asarray(item["y_raw"], dtype=float).tolist(), lname=f"{nm}_Raw", axis="Y")
            r_col += 2

        gl.rescale()
        gl.set_ylim(y_lo, y_hi)
        x_lo_all, x_hi_all = min(xmin_all), max(xmax_all)
        if invert_x:
            gl.set_xlim(x_hi_all, x_lo_all)
        else:
            gl.set_xlim(x_lo_all, x_hi_all)

        _style_origin_layer_boxed(
            gl,
            x_label,
            y_label,
            hide_y_labels=True,
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            layer_rect_pct=rect,
            layer_rect_in=box_in,
            remove_legend=True,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
        x_inc_wf = compute_nice_linear_step(x_lo_all, x_hi_all, max_ticks=6)
        if x_inc_wf:
            gl.lt_exec(f"layer.x.inc={x_inc_wf};")

        if markers:
            x_span_all = max(x_hi_all - x_lo_all, 1e-6)
            vis_markers = []
            for m_i, mk in enumerate(markers):
                raw_x = float(mk["pos"])
                vis_fx = (x_hi_all - raw_x) / x_span_all if invert_x else (raw_x - x_lo_all) / x_span_all
                vis_markers.append((vis_fx, m_i, mk))
            vis_markers.sort(key=lambda t: t[0])

            prev_fx = -1.0
            tier = 0
            for vis_fx, m_i, mk in vis_markers:
                m_lbl = str(mk.get("label", "")).strip()
                if not m_lbl:
                    continue
                if vis_fx - prev_fx < 0.25:
                    tier = 1 - tier
                else:
                    tier = 0
                prev_fx = vis_fx

                loc_pk = _local_top_curve_y(float(mk["pos"]))
                if n_curves >= 5:
                    tier0_y = max(ymax_g + 0.20 * yspan_g, loc_pk + 0.20 * yspan_g)
                    y_sh = (ymax_g + 0.44 * yspan_g) if tier == 1 else min(ymax_g + 0.34 * yspan_g, tier0_y)
                else:
                    tier0_y = max(ymax_g + 0.14 * yspan_g, loc_pk + 0.15 * yspan_g)
                    y_sh = (ymax_g + 0.30 * yspan_g) if tier == 1 else min(ymax_g + 0.24 * yspan_g, tier0_y)
                est_half_fx = min(0.22, 0.0115 * max(len(m_lbl), 4))
                clamped_fx = max(est_half_fx + 0.02, min(1.0 - est_half_fx - 0.02, vis_fx))
                pos_sc_m = 0
                dx_m = (clamped_fx - vis_fx) * x_span_all * (-1.0 if invert_x else 1.0)
                c_int = ot.hex_to_origin_rgb_int(mk.get("color") or mk_col_pool[m_i % len(mk_col_pool)])
                queue_overlay_data_text(
                    op,
                    gp,
                    1,
                    float(mk["pos"]) + dx_m,
                    y_sh,
                    (x_lo_all, x_hi_all),
                    (y_lo, y_hi),
                    rich_text=m_lbl,
                    fontsize=min(float(spec["callout_pt"]), 19.5 if len(vis_markers) >= 3 else 21.0),
                    color_int=c_int,
                    invert_x=invert_x,
                    pos_scatter=pos_sc_m,
                    no_repel=True,
                )

        configure_custom_legend(
            gl,
            list(reversed(leg_entries)),
            fontsize=float(spec["legend_pt"]),
            horizontal=True,
            pos_mode="interior_top",
            layer_rect_pct=rect,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or project_title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_nyquist_opju(
    eis_series: List[Dict[str, Any]],
    out_opju: str | Path,
    project_title: str = "EIS_Nyquist",
    add_hf_inset: bool = True,
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        f_id = get_font_id(op)
        bold_i = int(spec["bold_int"])
        cw_u = int(spec["curve_w_units"])
        sub_w = int(spec["sub_w_units"])
        mk_sz = float(spec["marker_size_pt"])

        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        rect_w, rect_h = float(spec["box_rect_w_in"]), float(spec["box_rect_h_in"])
        rect_box_in = (float(spec["box_rect_left_in"]), float(spec["box_rect_top_in"]), rect_w, rect_h)
        rect_pct = ot.rect_in_to_page_pct(*rect_box_in, pw, ph)

        wb = op.new_book("w", lname=f"{project_title}_Book")
        gp = op.new_graph(lname=f"{project_title}_Graph")
        set_graph_page_inches(gp, pw, ph)
        gl = gp[0]

        pal = ot.resolve_series_colors(len(eis_series), scheme="paired_semantic")
        max_zr = 0.0
        max_nzi = 0.0
        hf_zr_max = 0.0
        hf_nzi_max = 0.0
        sheets_created = []
        leg_entries: List[Tuple[Any, ...]] = []
        used_sheets: set[str] = set()

        for idx, item in enumerate(eis_series):
            nm = ot.clean_semantic_sample_name(str(item["name"]), True)
            sh_short = unique_origin_short_name(nm, used_sheets, default=f"EIS{idx + 1}")
            wks = wb[0] if idx == 0 else wb.add_sheet(sh_short)
            if idx == 0:
                wks.name = sh_short
            df = pd.DataFrame(
                {
                    "Freq": item["freq_Hz"],
                    "Z_real": item["z_real"],
                    "Neg_Z_imag": item["neg_z_imag"],
                    "Z_mod": item["z_mod"],
                    "Phase": item["phase_deg"],
                }
            )
            wks.from_df(df)
            wks.set_label(0, "Frequency", "L")
            wks.set_label(0, "Hz", "U")
            wks.set_label(1, "Z'", "L")
            wks.set_label(1, "Ohm", "U")
            wks.set_label(2, "-Z''", "L")
            wks.set_label(2, "Ohm", "U")
            wks.cols_axis("NXYyy")
            c_hex = ot.normalize_hex(item.get("color") or pal[idx % len(pal)])
            sheets_created.append((wks, item, c_hex))

            p_eis = gl.add_plot(wks, coly=2, colx=1, type="y")
            p_eis.color = _hex_to_origin_color(op, c_hex)
            p_eis.symbol_size = mk_sz
            p_idx_1 = len(gl.plot_list())
            gl.lt_exec(f"range rr = !{p_idx_1}; set rr -w {cw_u};")
            p_eis.symbol_kind = 2
            p_eis.symbol_interior = 0
            leg_entries.append((p_idx_1, nm, c_hex, "line_sphere"))

            zr, nzi = np.asarray(item["z_real"], dtype=float), np.asarray(item["neg_z_imag"], dtype=float)
            max_zr = max(max_zr, float(np.max(zr)))
            max_nzi = max(max_nzi, float(np.max(nzi)))
            n_hf = max(6, len(zr) // 3)
            hf_zr_max = max(hf_zr_max, float(np.max(zr[:n_hf])))
            hf_nzi_max = max(hf_nzi_max, float(np.max(nzi[:n_hf])))

        x_lim_43, y_lim_43, step_cand = compute_isometric_4_3_bounds(max_zr, max_nzi)
        xlim_top = x_lim_43[1]
        ylim_top = y_lim_43[1]

        gl.set_xlim(0.0, xlim_top)
        gl.set_ylim(0.0, ylim_top)
        _style_origin_layer_boxed(
            gl,
            "\\i(Z') (\\g(W))",
            "-\\i(Z'') (\\g(W))",
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            layer_rect_pct=rect_pct,
            layer_rect_in=rect_box_in,
            remove_legend=True,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
        gl.lt_exec(
            f"layer.x.from=0; layer.x.to={xlim_top}; layer.x.inc={step_cand}; "
            f"layer.y.from=0; layer.y.to={ylim_top}; layer.y.inc={step_cand};"
        )

        hf_max = max(hf_zr_max, hf_nzi_max)
        if add_hf_inset and 0.0 < hf_max < 0.45 * xlim_top:
            in_u_raw = max((hf_zr_max * 1.16) / 4.0, (hf_nzi_max * 1.16) / 3.0)
            in_u = math.ceil(in_u_raw / 5.0) * 5.0 if in_u_raw >= 15.0 else max(round(in_u_raw, 2), 0.5)
            in_xlim = 4.0 * in_u
            in_ylim = 3.0 * in_u
            zb_sh = unique_origin_short_name("HFZoomBox", used_sheets, default="ZBox")
            wks_zb = wb.add_sheet(zb_sh)
            wks_zb.cols = 2
            eps_x = 0.008 * xlim_top
            eps_y = 0.008 * ylim_top
            wks_zb.from_list(0, [eps_x, in_xlim, in_xlim, eps_x, eps_x], lname="ZBox_X", axis="X")
            wks_zb.from_list(1, [eps_y, eps_y, in_ylim, in_ylim, eps_y], lname="ZBox_Y", axis="Y")
            p_zb = gl.add_plot(wks_zb, coly=1, colx=0, type="l")
            p_zb.color = _hex_to_origin_color(op, "#6579BE")
            zb_idx = len(gl.plot_list())
            gl.lt_exec(f"range rzb = !{zb_idx}; set rzb -d 1; set rzb -w {sub_w}; label -r Legend;")

            gl_in = gp.add_layer(6)
            activate_layer(op, gp, 2)
            gl_in.lt_exec("layer.fsize=1;")
            white_int = ot.hex_to_origin_rgb_int("#FFFFFF")
            white_oc = _hex_to_origin_color(op, "#FFFFFF")
            ink_int = ot.hex_to_origin_rgb_int("#111111")
            font_in = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""
            wks_in_bg = op.new_book("w", lname="Nyquist_InBG")[0]
            wks_in_bg.cols = 3
            wks_in_bg.from_list(0, [0.0, in_xlim], axis="X")
            wks_in_bg.from_list(1, [in_ylim, in_ylim], axis="Y")
            wks_in_bg.from_list(2, [0.0, 0.0], axis="Y")
            p_bg_u = gl_in.add_plot(wks_in_bg, coly=1, colx=0, type="l")
            p_bg_l = gl_in.add_plot(wks_in_bg, coly=2, colx=0, type="l")
            p_bg_u.color = white_oc
            p_bg_l.color = white_oc
            p_bg_u.set_fill_area(above=white_oc, type=9, below=white_oc)
            p_bg_u.transparency = 0
            p_bg_l.transparency = 100
            gl_in.lt_exec("range rbu = !1; set rbu -w 0; range rbl = !2; set rbl -w 0;")
            ins_w_in = 0.42 * rect_w
            ins_h_in = 0.42 * rect_h
            ins_scale = ot.compute_origin_layer_scale(ins_w_in, ins_h_in, pw, ph)
            ins_w_u = int(round((cw_u * 0.72) / ins_scale))
            ins_mk_sz = round(4.8 / ins_scale, 1)
            for _idx, (wks, _item, c_hex) in enumerate(sheets_created):
                p_in = gl_in.add_plot(wks, coly=2, colx=1, type="y")
                p_in.color = _hex_to_origin_color(op, c_hex)
                p_in.symbol_size = ins_mk_sz
                in_idx_1 = len(gl_in.plot_list())
                gl_in.lt_exec(f"range rin = !{in_idx_1}; set rin -w {ins_w_u};")
                p_in.symbol_kind = 2
                p_in.symbol_interior = 0
            gl_in.set_xlim(0.0, in_xlim)
            gl_in.set_ylim(0.0, in_ylim)
            ins_bt = float(spec["inset_box_lw_pt"])
            ins_comp_pt = ot.compensate_origin_layer_pt(float(spec["inset_tick_pt"]), ins_w_in, ins_h_in, pw, ph)
            inc_ix = compute_nice_linear_step(0.0, in_xlim, max_ticks=4) or in_u
            inc_iy = compute_nice_linear_step(0.0, in_ylim, max_ticks=4) or in_u
            gl_in.lt_exec(
                f"layer.fsize=1; "
                f"layer.unit=7; layer.left=51; layer.top=44; layer.width=42; layer.height=42; "
                f"layer.color={white_int}; "
                f"layer.x.grid.show=0; layer.y.grid.show=0; "
                f"layer.x.showAxes=3; layer.y.showAxes=3; "
                f"layer.x.thickness={ins_bt}; layer.y.thickness={ins_bt}; layer.x2.thickness={ins_bt}; layer.y2.thickness={ins_bt}; "
                f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
                f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
                f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
                f"layer.x.ticks=1; layer.y.ticks=1; "
                f"layer.x2.ticks=0; layer.y2.ticks=0; "
                f"layer.x.from=0; layer.x.to={in_xlim}; layer.x.inc={inc_ix}; "
                f"layer.y.from=0; layer.y.to={in_ylim}; layer.y.inc={inc_iy}; "
                f"layer.x.maxTicks=4; layer.y.maxTicks=4; "
                f"{font_in}"
                f"layer.x.label.pt={ins_comp_pt}; layer.y.label.pt={ins_comp_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
                f"XB.show=0; YL.show=0; label -r Legend;"
            )
            style_origin_native_axis_title(
                gl_in, "XB", "", fontsize=16.0, color_int=ink_int, op=op, gp=gp, layer_num_1based=2
            )
            style_origin_native_axis_title(
                gl_in, "YL", "", fontsize=16.0, color_int=ink_int, op=op, gp=gp, layer_num_1based=2
            )

        configure_custom_legend(
            gl,
            leg_entries,
            fontsize=float(spec["legend_pt"]),
            pos_mode="corner_upper_right",
            layer_rect_pct=rect_pct,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or project_title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_bet_opju(
    isotherm: Dict[str, Any],
    psd: Dict[str, Any],
    out_opju: str | Path,
    title: str = "BET",
    bet_surface_area_m2_g: Optional[float] = None,
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        f_id = get_font_id(op)
        bold_i = int(spec["bold_int"])
        cw_u = int(spec["curve_w_units"])
        mk_sz = float(spec["marker_size_pt"])

        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(*box_in, pw, ph)

        wb_iso = op.new_book("w", lname=f"{title}_Isotherm_Book")
        wks_iso = wb_iso[0]
        wks_iso.name = "Isotherm"
        wks_iso.cols = 4
        wks_iso.from_list(0, np.asarray(isotherm["ads_p_p0"], dtype=float).tolist(), lname="Ads_P/P0", axis="X")
        wks_iso.from_list(
            1, np.asarray(isotherm["ads_vol"], dtype=float).tolist(), lname="Adsorption", units="cm^3/g STP", axis="Y"
        )
        wks_iso.from_list(2, np.asarray(isotherm["des_p_p0"], dtype=float).tolist(), lname="Des_P/P0", axis="X")
        wks_iso.from_list(
            3, np.asarray(isotherm["des_vol"], dtype=float).tolist(), lname="Desorption", units="cm^3/g STP", axis="Y"
        )

        wb_psd = op.new_book("w", lname=f"{title}_PSD_Book")
        wks_psd = wb_psd[0]
        wks_psd.name = "PoreSizeDist"
        wks_psd.from_df(
            pd.DataFrame(
                {
                    "Diameter_nm": psd["diameter_nm"],
                    "Diff_Pore_Vol": psd["diff_vol"],
                    "Cum_Pore_Vol": psd["cum_pore_vol"],
                }
            )
        )

        gp_iso = op.new_graph(lname=f"{title}_Isotherm")
        set_graph_page_inches(gp_iso, pw, ph)
        gl_iso = gp_iso[0]
        p1 = gl_iso.add_plot(wks_iso, coly=1, colx=0, type="y")
        p1.color = _hex_to_origin_color(op, "#3E86DE")
        p1.symbol_size = mk_sz
        gl_iso.lt_exec(f"range r1 = !1; set r1 -w {cw_u};")
        p1.symbol_kind = 2
        p1.symbol_interior = 0

        p2 = gl_iso.add_plot(wks_iso, coly=3, colx=2, type="y")
        p2.color = _hex_to_origin_color(op, "#D84B5C")
        p2.symbol_size = mk_sz
        gl_iso.lt_exec(f"range r2 = !2; set r2 -w {cw_u};")
        p2.symbol_kind = 2
        p2.symbol_interior = 1

        gl_iso.rescale()
        ymax_iso = float(max(np.max(isotherm["ads_vol"]), np.max(isotherm["des_vol"])))
        ymin_iso = float(min(np.min(isotherm["ads_vol"]), np.min(isotherm["des_vol"])))
        gl_iso.set_xlim(-0.04, 1.05)
        gl_iso.set_ylim(ymin_iso - 0.06 * max(ymax_iso, 1.0), ymax_iso * 1.96)

        _style_origin_layer_boxed(
            gl_iso,
            "Relative Pressure (P/P_0)",
            "Quantity Adsorbed (cm^3 g^-1 STP)",
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            layer_rect_pct=rect,
            layer_rect_in=box_in,
            remove_legend=True,
            op=op,
            gp=gp_iso,
            layer_num_1based=1,
        )

        if bet_surface_area_m2_g is not None:
            add_page_text_label(
                op,
                gp_iso,
                gl_iso,
                1,
                "BetSA",
                f"\\i(S)\\-(BET) = {float(bet_surface_area_m2_g):.1f} m\\+(2) g\\+(-1)",
                rect[0] + 3.0,
                rect[1] + 10.8,
                fontsize=float(spec["callout_pt"]),
                pos_scatter=2,
                format_math=False,
            )

        gl_in = gp_iso.add_layer(6)
        activate_layer(op, gp_iso, 2)
        gl_in.lt_exec("layer.fsize=1;")
        white_int = ot.hex_to_origin_rgb_int("#FFFFFF")
        white_oc = _hex_to_origin_color(op, "#FFFFFF")
        ink_int = ot.hex_to_origin_rgb_int("#111111")
        font_in = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""

        d_nm = np.asarray(psd["diameter_nm"], dtype=float)
        dv_arr = np.asarray(psd["diff_vol"], dtype=float)
        in_win_mask = (d_nm >= 1.0) & (d_nm <= 52.0)
        psd_ymax = float(np.max(dv_arr[in_win_mask])) if np.any(in_win_mask) else float(np.max(dv_arr))
        psd_ytop = max(psd_ymax * 1.30, 1e-4)

        wks_bet_bg = op.new_book("w", lname=f"{title}_InBG")[0]
        wks_bet_bg.cols = 3
        wks_bet_bg.from_list(0, [1.0, 50.0], axis="X")
        wks_bet_bg.from_list(1, [psd_ytop, psd_ytop], axis="Y")
        wks_bet_bg.from_list(2, [0.0, 0.0], axis="Y")
        p_bbu = gl_in.add_plot(wks_bet_bg, coly=1, colx=0, type="l")
        p_bbl = gl_in.add_plot(wks_bet_bg, coly=2, colx=0, type="l")
        p_bbu.color = white_oc
        p_bbl.color = white_oc
        p_bbu.set_fill_area(above=white_oc, type=9, below=white_oc)
        p_bbu.transparency = 0
        p_bbl.transparency = 100
        gl_in.lt_exec("range rbu = !1; set rbu -w 0; range rbl = !2; set rbl -w 0;")

        c_fill_psd = _hex_to_origin_color(op, "#9EC5F0")
        p_in_fill = gl_in.add_plot(wks_psd, coly=1, colx=0, type="l")
        p_in_fill.color = c_fill_psd
        p_in_fill.set_fill_area(above=c_fill_psd, type=1, below=c_fill_psd)
        p_in_fill.transparency = 42
        gl_in.lt_exec("range rinf = !3; set rinf -w 0;")

        bet_ins_scale = ot.compute_origin_layer_scale(box_in[2] * 0.45, box_in[3] * 0.36, pw, ph)
        c_line_psd = _hex_to_origin_color(op, "#2B6CB0")
        p_in = gl_in.add_plot(wks_psd, coly=1, colx=0, type="y")
        p_in.color = c_line_psd
        p_in.symbol_size = round(4.6 / bet_ins_scale, 1)
        p_in.transparency = 0
        ins_w_u = int(round((cw_u * 0.72) / bet_ins_scale))
        gl_in.lt_exec(f"range rin = !4; set rin -w {ins_w_u};")
        p_in.symbol_kind = 2
        p_in.symbol_interior = 0
        gl_in.rescale()
        gl_in.set_xlim(1.0, 50.0)
        gl_in.set_ylim(0.0, psd_ytop)

        inset_pos = (28, 28, 45, 36)
        ins_bt = float(spec["inset_box_lw_pt"])
        ins_comp_pt = ot.compensate_origin_layer_pt(
            float(spec["inset_tick_pt"]),
            box_in[2] * (inset_pos[2] / 100.0),
            box_in[3] * (inset_pos[3] / 100.0),
            pw,
            ph,
        )
        gl_in.lt_exec(
            f"layer.fsize=1; "
            f"layer.unit=7; layer.left={inset_pos[0]}; layer.top={inset_pos[1]}; layer.width={inset_pos[2]}; layer.height={inset_pos[3]}; "
            f"layer.color={white_int}; layer.x.grid.show=0; layer.y.grid.show=0; "
            f"layer.x.showAxes=3; layer.y.showAxes=3; "
            f"layer.x.thickness={ins_bt}; layer.y.thickness={ins_bt}; layer.x2.thickness={ins_bt}; layer.y2.thickness={ins_bt}; "
            f"layer.x.color={ink_int}; layer.y.color={ink_int}; "
            f"layer.x2.color={ink_int}; layer.y2.color={ink_int}; "
            f"layer.x.label.color={ink_int}; layer.y.label.color={ink_int}; "
            f"layer.x.ticks=1; layer.y.ticks=1; "
            f"layer.x2.ticks=0; layer.y2.ticks=0; layer.x.maxTicks=4; layer.y.maxTicks=4; "
            f"{font_in}"
            f"layer.x.label.pt={ins_comp_pt}; layer.y.label.pt={ins_comp_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
            f"XB.show=0; YL.show=0; label -r Legend;"
        )
        style_origin_native_axis_title(
            gl_in, "XB", "Pore Width (nm)", fontsize=15.5, color_int=ink_int, op=op, gp=gp_iso, layer_num_1based=2
        )
        style_origin_native_axis_title(
            gl_in, "YL", "dV/dD", fontsize=15.5, color_int=ink_int, op=op, gp=gp_iso, layer_num_1based=2
        )

        configure_custom_legend(
            gl_iso,
            [(1, "Adsorption", "#3E86DE", "line_sphere"), (2, "Desorption", "#D84B5C", "open_circle")],
            fontsize=float(spec["legend_pt"]),
            horizontal=True,
            pos_mode="interior_top",
            layer_rect_pct=rect,
            op=op,
            gp=gp_iso,
            layer_num_1based=1,
        )

        gp_psd = op.new_graph(lname=f"{title}_PSD")
        set_graph_page_inches(gp_psd, pw, ph)
        gl_psd = gp_psd[0]
        p_psd = gl_psd.add_plot(wks_psd, coly=1, colx=0, type="y")
        c_psd_int = _hex_to_origin_color(op, "#6579BE")
        p_psd.color = c_psd_int
        p_psd.symbol_size = mk_sz
        gl_psd.lt_exec(f"range rp = !1; set rp -w {cw_u};")
        p_psd.symbol_kind = 2
        p_psd.symbol_interior = 0
        p_psd.set_fill_area(above=c_psd_int, type=1, below=c_psd_int)
        p_psd.transparency = 60
        gl_psd.rescale()
        _style_origin_layer_boxed(
            gl_psd,
            "Pore Diameter (nm)",
            "Differential Pore Volume",
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            layer_rect_pct=rect,
            layer_rect_in=box_in,
            remove_legend=True,
            op=op,
            gp=gp_psd,
            layer_num_1based=1,
        )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp_iso, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_particle_size_opju(
    ps_data: Dict[str, Any],
    out_opju: str | Path,
    title: str = "ParticleSize",
    x_limits: Optional[Tuple[float, float]] = None,
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    size_arr = np.asarray(ps_data["size_um"], dtype=float)
    pos_sizes = size_arr[size_arr > 0]
    if x_limits is not None and len(x_limits) == 2 and x_limits[0] > 0 and x_limits[1] > x_limits[0]:
        x_lo, x_hi = float(x_limits[0]), float(x_limits[1])
    elif len(pos_sizes) > 0:
        nz_mask = (np.asarray(ps_data["diff_vol_pct"], dtype=float) > 0.01) & (size_arr > 0)
        s_rel = size_arr[nz_mask] if np.any(nz_mask) else pos_sizes
        x_lo = max(1e-3, float(np.min(s_rel)) * 0.5)
        x_hi = float(np.max(s_rel)) * 2.0
    else:
        x_lo, x_hi = 0.1, 1000.0

    with origin_session() as op:
        f_id = get_font_id(op)
        bold_i = int(spec["bold_int"])
        cw_u = int(spec["curve_w_units"])
        bt = float(spec["box_lw_pt"]) if abs(float(box_thickness) - 3.0) < 0.05 else float(box_thickness)
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        li, ti, wi, hi = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(li, ti, wi, hi, pw, ph)
        comp_tk_pt = ot.compensate_origin_layer_pt(float(spec["tick_label_pt"]), wi, hi, pw, ph)
        ax_t_pt = float(spec["axis_title_pt"])

        font_c1 = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""

        wb = op.new_book("w", lname=f"{title}_Book")
        wks = wb[0]
        wks.name = "Mastersizer"
        used_ps_sh: set[str] = {"Mastersizer"}
        wks.from_df(
            pd.DataFrame(
                {
                    "Size_um": ps_data["size_um"],
                    "Diff_Vol_Pct": ps_data["diff_vol_pct"],
                    "Cum_Vol_Pct": ps_data["cum_vol_pct"],
                }
            )
        )
        wks.set_label(0, "Particle Size", "L")
        wks.set_label(0, "um", "U")
        wks.set_label(1, "Volume Density", "L")
        wks.set_label(1, "%", "U")
        wks.set_label(2, "Cumulative Volume", "L")
        wks.set_label(2, "%", "U")

        gp = op.new_graph(lname=f"{title}_DualY_LogGraph")
        set_graph_page_inches(gp, pw, ph)
        c_left_hex = "#3E86DE"
        c_right_hex = "#A02333"
        c_left_int = ot.hex_to_origin_rgb_int(c_left_hex)
        c_right_int = ot.hex_to_origin_rgb_int(c_right_hex)
        ink_int = ot.hex_to_origin_rgb_int("#111111")

        gl1 = gp[0]
        c1 = _hex_to_origin_color(op, c_left_hex)
        pb_left = ot.compute_pastel_fill_and_border(c_left_hex)
        c1_fill = _hex_to_origin_color(op, pb_left["fill_hex"])
        p1 = gl1.add_plot(wks, coly=1, colx=0, type="l")
        p1.color = c1
        p1.set_fill_area(above=c1_fill, type=1, below=c1_fill)
        p1.transparency = 25
        gl1.lt_exec(f"range r1 = !1; set r1 -w {cw_u};")
        gl1.rescale()
        activate_layer(op, gp, 1)
        gl1.lt_exec(
            f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi}; "
            f"layer.x.grid.show=0; layer.y.grid.show=0; "
            f"layer.x.type=2; layer.x.showAxes=3; layer.y.showAxes=1; "
            f"layer.x.thickness={bt}; layer.x2.thickness={bt}; layer.y.thickness={bt}; "
            f"layer.x.color={ink_int}; layer.x2.color={ink_int}; layer.x.label.color={ink_int}; "
            f"layer.y.color={c_left_int}; layer.y.label.color={c_left_int}; "
            f"layer.x.ticks=5; layer.x.minorTicks=8; layer.x.label.numFormat=2; layer.x2.ticks=0; "
            f"layer.y.ticks=1; "
            f"{font_c1}"
            f"layer.x.label.pt={comp_tk_pt}; layer.y.label.pt={comp_tk_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
            f"XB.show=0; YL.show=0; label -r Legend;"
        )
        gl1.set_xlim(x_lo, x_hi)
        gl1.set_ylim(0.0, float(np.max(ps_data["diff_vol_pct"])) * 1.38)
        style_origin_native_axis_title(
            gl1, "XB", "Particle Size (\\mu m)", fontsize=ax_t_pt, color_int=ink_int, op=op, gp=gp, layer_num_1based=1
        )
        style_origin_native_axis_title(
            gl1, "YL", "Volume Density (%)", fontsize=ax_t_pt, color_int=c_left_int, op=op, gp=gp, layer_num_1based=1
        )

        gl2 = gp.add_layer(2)
        activate_layer(op, gp, 2)
        p2 = gl2.add_plot(wks, coly=2, colx=0, type="l")
        p2.color = _hex_to_origin_color(op, c_right_hex)
        gl2.lt_exec(f"range r2 = !1; set r2 -w {cw_u}; set r2 -d 1;")
        gl2.rescale()
        gl2.lt_exec(
            f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi}; "
            f"layer.x.grid.show=0; layer.y.grid.show=0; "
            f"layer.x.type=2; layer.x.link=1; layer.x.showAxes=0; layer.x.showLabels=0; "
            f"layer.y.showAxes=2; layer.y.showLabels=0; layer.y2.showAxes=2; layer.y2.showLabels=0; "
            f"layer.y.thickness={bt}; layer.y2.thickness={bt}; "
            f"layer.y.ticks=0; layer.y2.ticks=0; "
            f"layer.y.color={c_right_int}; layer.y2.color={c_right_int}; "
            f"XB.show=0; YL.show=0; YR.show=0; label -r Legend;"
        )
        gl2.set_xlim(x_lo, x_hi)
        # Render linear X-linked right ticks at 0..100 ONLY inside [0..128%] using log10-aware inward segments!
        gl2.set_ylim(0.0, 128.0)
        log_span = math.log10(max(x_hi, 1e-6)) - math.log10(max(x_lo, 1e-9))
        tk_frac = 6.2 / (wi * 72.0)
        x_tk_in = 10.0 ** (math.log10(x_hi) - tk_frac * log_span)
        t_sh = unique_origin_short_name("RightTicks0to100", used_ps_sh, default="RTks")
        wks_rt = wb.add_sheet(t_sh)
        wks_rt.cols = 12
        c_r_oc = _hex_to_origin_color(op, c_right_hex)
        tk_w_u = int(round(max(550.0, bt * 360.0)))
        for idx_rt, tv_r in enumerate((0, 20, 40, 60, 80, 100)):
            wks_rt.from_list(2 * idx_rt, [x_tk_in, x_hi], axis="X")
            wks_rt.from_list(2 * idx_rt + 1, [float(tv_r), float(tv_r)], axis="Y")
            p_rtk = gl2.add_plot(wks_rt, coly=2 * idx_rt + 1, colx=2 * idx_rt, type="l")
            p_rtk.color = c_r_oc
            rtk_idx = len(gl2.plot_list())
            gl2.lt_exec(f"range rrtk = !{rtk_idx}; set rrtk -w {tk_w_u};")
            y_pg_pct = rect[1] + (1.0 - float(tv_r) / 128.0) * rect[3]
            x_pg_pct = rect[0] + rect[2] + (0.11 / pw) * 100.0
            add_page_text_label(
                op, gp, gl2, 2, f"RTkLbl_{idx_rt}", str(tv_r), x_pg_pct, y_pg_pct,
                fontsize=float(spec["tick_label_pt"]), color_int=c_right_int, pos_scatter=2, format_math=False
            )
        gl2.lt_exec("label -r Legend;")

        style_origin_native_axis_title(
            gl2, "YR", "Cumulative Volume (%)", fontsize=ax_t_pt, color_int=c_right_int, op=op, gp=gp, layer_num_1based=2
        )

        configure_custom_legend(
            gl1,
            [(1, "Differential Vol.", c_left_hex, "bar"), (2, "Cumulative Vol.", c_right_hex, "line_dashed")],
            fontsize=float(spec["legend_pt"]),
            horizontal=True,
            pos_mode="interior_top",
            layer_rect_pct=rect,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_epr_opju(
    x: np.ndarray,
    epr_metrics: Dict[str, Any],
    out_opju: str | Path,
    x_label: str = "g-factor",
    title: str = "EPR",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        wb = op.new_book("w", lname=f"{title}_Book")
        wks = wb[0]
        wks.name = "EPRDeriv"
        y_corr = np.asarray(epr_metrics["y_corrected"], dtype=float)
        x_arr = np.asarray(x, dtype=float)
        g0 = float(epr_metrics["center_zero_crossing"])
        ymax_abs = max(abs(float(np.min(y_corr))), abs(float(np.max(y_corr))))
        ylo = -1.48 * ymax_abs
        yhi = +1.48 * ymax_abs
        xmin_v = float(np.min(x_arr))
        xmax_v = float(np.max(x_arr))

        wks.cols = 6
        wks.from_df(pd.DataFrame({"X": x_arr, "dI_dB": y_corr}))
        wks.from_list(2, [xmin_v, xmax_v], lname="Zero_X", axis="X")
        wks.from_list(3, [0.0, 0.0], lname="Zero_Y", axis="Y")
        wks.from_list(4, [g0, g0], lname="g0_X", axis="X")
        wks.from_list(5, [ylo, yhi], lname="g0_Y", axis="Y")

        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(*box_in, pw, ph)
        cw_u = int(spec["curve_w_units"])
        sub_w = int(spec["sub_w_units"])

        gp = op.new_graph(lname=f"{title}_Graph")
        set_graph_page_inches(gp, pw, ph)
        gl = gp[0]

        p_zero = gl.add_plot(wks, coly=3, colx=2, type="l")
        p_zero.color = _hex_to_origin_color(op, "#8C96A6")
        zero_idx_1 = len(gl.plot_list())
        gl.lt_exec(f"range rzero = !{zero_idx_1}; set rzero -d 2; set rzero -w {max(550, sub_w - 100)};")

        p_g0 = gl.add_plot(wks, coly=5, colx=4, type="l")
        p_g0.color = _hex_to_origin_color(op, "#A02333")
        g0_idx_1 = len(gl.plot_list())
        gl.lt_exec(f"range rg0 = !{g0_idx_1}; set rg0 -d 1; set rg0 -w {sub_w};")

        p = gl.add_plot(wks, coly=1, colx=0, type="l")
        p.color = _hex_to_origin_color(op, "#3E86DE")
        sp_idx_1 = len(gl.plot_list())
        gl.lt_exec(f"range r1 = !{sp_idx_1}; set r1 -w {cw_u};")

        gl.rescale()
        gl.set_ylim(ylo, yhi)
        if "g" in x_label.lower():
            gl.set_xlim(float(np.max(x_arr)), float(np.min(x_arr)))
        _style_origin_layer_boxed(
            gl,
            x_label.replace("$", ""),
            "dI / dB (a.u.)",
            hide_y_labels=True,
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            layer_rect_pct=rect,
            layer_rect_in=box_in,
            remove_legend=True,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )
        callout_fs = float(spec["callout_pt"])
        add_page_text_label(
            op,
            gp,
            gl,
            1,
            "G0Lbl",
            f"\\i(g) = {g0:.4f}",
            rect[0] + 2.8,
            rect[1] + 4.8,
            fontsize=callout_fs,
            color_int=ot.hex_to_origin_rgb_int("#A02333"),
            pos_scatter=2,
        )
        ptp_width = epr_metrics.get("peak_to_peak_width")
        if ptp_width is not None:
            is_g_axis = "g" in x_label.lower()
            ptp_str = (
                f"\\g(D)\\i(g)\\-(pp) = {float(ptp_width):.4f}"
                if is_g_axis
                else f"\\g(D)\\i(H)\\-(pp) = {float(ptp_width):.2f} G"
            )
            add_page_text_label(
                op,
                gp,
                gl,
                1,
                "PtPLbl",
                ptp_str,
                rect[0] + 2.8,
                rect[1] + 10.8,
                fontsize=callout_fs,
                color_int=ot.hex_to_origin_rgb_int("#D84B5C"),
                pos_scatter=2,
            )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_conductivity_opju(
    cond_data: Dict[str, Any],
    out_opju: str | Path,
    title: str = "Conductivity",
    log_conductivity: bool = True,
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    has_density = int(np.isfinite(cond_data["density_g_cm3"]).sum()) >= 3
    use_log_y = bool(log_conductivity) and bool(np.all(np.asarray(cond_data["conductivity"], dtype=float) > 0))

    with origin_session() as op:
        f_id = get_font_id(op)
        bold_i = int(spec["bold_int"])
        cw_u = int(spec["curve_w_units"])
        mk_sz = float(spec["marker_size_pt"])
        bt = float(spec["box_lw_pt"]) if abs(float(box_thickness) - 3.0) < 0.05 else float(box_thickness)
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        li, ti, wi, hi = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(li, ti, wi, hi, pw, ph)
        comp_tk_pt = ot.compensate_origin_layer_pt(float(spec["tick_label_pt"]), wi, hi, pw, ph)
        ax_t_pt = float(spec["axis_title_pt"])

        font_c1 = f"layer.x.label.font={f_id}; layer.y.label.font={f_id}; " if f_id > 0 else ""
        font_c2 = f"layer.y.label.font={f_id}; layer.y2.label.font={f_id}; " if f_id > 0 else ""

        wb = op.new_book("w", lname=f"{title}_Book")
        wks = wb[0]
        wks.name = "PressureCond"
        wks.from_df(
            pd.DataFrame(
                {
                    "Pressure_MPa": cond_data["pressure_MPa"],
                    "Conductivity": cond_data["conductivity"],
                    "CompactDensity_g_cm3": cond_data["density_g_cm3"],
                    "Resistivity_GOhm_cm": cond_data["resistivity"],
                }
            )
        )
        gp = op.new_graph(lname=f"{title}_DualY_Graph")
        set_graph_page_inches(gp, pw, ph)
        c_left_int = ot.hex_to_origin_rgb_int("#3E86DE")
        c_right_int = ot.hex_to_origin_rgb_int("#A02333")
        ink_int = ot.hex_to_origin_rgb_int("#111111")

        p_arr = np.asarray(cond_data["pressure_MPa"], dtype=float)
        c_arr = np.asarray(cond_data["conductivity"], dtype=float)
        p_min_v, p_max_v = float(np.nanmin(p_arr)), float(np.nanmax(p_arr))
        p_pad = max(1.2, 0.06 * (p_max_v - p_min_v))
        x_lo_p = max(0.0, p_min_v - p_pad) if p_min_v > 1.5 else -0.8
        x_hi_p = p_max_v + p_pad
        x_inc_p = 5 if (x_hi_p - x_lo_p) >= 20.0 else 2

        gl1 = gp[0]
        p1 = gl1.add_plot(wks, coly=1, colx=0, type="y")
        p1.color = _hex_to_origin_color(op, "#3E86DE")
        p1.symbol_size = mk_sz
        gl1.lt_exec(f"range r1 = !1; set r1 -w {cw_u};")
        p1.symbol_kind = 2
        p1.symbol_interior = 0

        if has_density:
            activate_layer(op, gp, 1)
            y_ticks_1 = 5 if use_log_y else 1
            y_type = 2 if use_log_y else 1
            log_clause_1 = "layer.y.minorTicks=8; layer.y.label.numFormat=2; " if use_log_y else ""
            gl1.lt_exec(
                f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi}; "
                f"layer.x.grid.show=0; layer.y.grid.show=0; "
                f"layer.y.type={y_type}; layer.x.showAxes=3; layer.y.showAxes=1; "
                f"layer.x.thickness={bt}; layer.x2.thickness={bt}; layer.y.thickness={bt}; "
                f"layer.x.color={ink_int}; layer.x2.color={ink_int}; layer.x.label.color={ink_int}; "
                f"layer.y.color={c_left_int}; layer.y.label.color={c_left_int}; "
                f"layer.x.ticks=1; layer.x2.ticks=0; "
                f"layer.y.ticks={y_ticks_1}; {log_clause_1}"
                f"{font_c1}"
                f"layer.x.label.pt={comp_tk_pt}; layer.y.label.pt={comp_tk_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
                f"XB.show=0; YL.show=0; label -r Legend;"
            )
            gl1.set_xlim(x_lo_p, x_hi_p)
            gl1.lt_exec(f"layer.x.inc={x_inc_p};")
            if use_log_y:
                pos_c = c_arr[c_arr > 0]
                y0_c = 10.0 ** math.floor(math.log10(float(np.min(pos_c)) * 0.55))
                y1_c = 10.0 ** math.ceil(math.log10(float(np.max(pos_c)) * 2.5))
                n_dec_c = round(math.log10(max(y1_c / max(y0_c, 1e-30), 10.0)))
                inc_dec = 2 if n_dec_c >= 7 else 1
                gl1.set_ylim(y0_c, y1_c)
                gl1.lt_exec(f"layer.y.from={y0_c}; layer.y.to={y1_c}; layer.y.inc={inc_dec};")
            else:
                gl1.set_ylim(0.0, float(np.nanmax(c_arr)) * 1.24)

            style_origin_native_axis_title(
                gl1, "XB", "Compaction Pressure (MPa)", fontsize=ax_t_pt, color_int=ink_int, op=op, gp=gp, layer_num_1based=1
            )
            style_origin_native_axis_title(
                gl1,
                "YL",
                cond_data["conductivity_label"].replace("$", ""),
                fontsize=ax_t_pt,
                color_int=c_left_int,
                op=op,
                gp=gp,
                layer_num_1based=1,
            )

            gl2 = gp.add_layer(2)
            activate_layer(op, gp, 2)
            p2 = gl2.add_plot(wks, coly=2, colx=0, type="y")
            p2.color = _hex_to_origin_color(op, "#A02333")
            p2.symbol_size = mk_sz
            gl2.lt_exec(f"range r2 = !1; set r2 -w {cw_u}; set r2 -d 1;")
            p2.symbol_kind = 2
            p2.symbol_interior = 1
            d_arr = np.asarray(cond_data["density_g_cm3"], dtype=float)
            d_fin = d_arr[np.isfinite(d_arr)]
            d_min_v, d_max_v = float(np.min(d_fin)), float(np.max(d_fin))
            d_span = max(d_max_v - d_min_v, 0.1)
            gl2.lt_exec(
                f"layer.unit=2; layer.left={li}; layer.top={ti}; layer.width={wi}; layer.height={hi}; "
                f"layer.x.grid.show=0; layer.y.grid.show=0; "
                f"layer.x.link=1; layer.x.showAxes=0; layer.x.showLabels=0; "
                f"layer.y.showAxes=2; layer.y.showLabels=2; layer.y2.showAxes=2; "
                f"layer.y.thickness={bt}; layer.y2.thickness={bt}; "
                f"layer.y.ticks=1; layer.y2.ticks=1; "
                f"layer.y.color={c_right_int}; layer.y2.color={c_right_int}; "
                f"layer.y.label.color={c_right_int}; layer.y2.label.color={c_right_int}; "
                f"{font_c2}"
                f"layer.y.label.pt={comp_tk_pt}; layer.y2.label.pt={comp_tk_pt}; layer.y.label.bold={bold_i}; layer.y2.label.bold={bold_i}; "
                f"XB.show=0; YL.show=0; YR.show=0; label -r Legend;"
            )
            gl2.set_xlim(x_lo_p, x_hi_p)
            gl2.set_ylim(max(0.0, d_min_v - 0.16 * d_span), d_max_v + 0.16 * d_span)
            style_origin_native_axis_title(
                gl2, "YR", "Compact Density (g cm^-3)", fontsize=ax_t_pt, color_int=c_right_int, op=op, gp=gp, layer_num_1based=2
            )

            configure_custom_legend(
                gl1,
                [(1, "Conductivity", "#3E86DE", "line_sphere"), (2, "Compact Density", "#A02333", "open_circle")],
                fontsize=float(spec["legend_pt"]),
                pos_mode="corner_lower_right",
                layer_rect_pct=rect,
                op=op,
                gp=gp,
                layer_num_1based=1,
            )
        else:
            _style_origin_layer_boxed(
                gl1,
                "Compaction Pressure (MPa)",
                cond_data["conductivity_label"].replace("$", ""),
                log_y=use_log_y,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                layer_rect_pct=rect,
                layer_rect_in=(li, ti, wi, hi),
                remove_legend=True,
                op=op,
                gp=gp,
                layer_num_1based=1,
            )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_xy_trend_opju(
    series_list: List[Dict[str, Any]],
    out_opju: str | Path,
    x_label: str,
    y_label: str,
    log_x: bool = False,
    log_y: bool = False,
    invert_x: bool = False,
    show_markers: Optional[bool] = None,
    title: str = "XY_Trend",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(*box_in, pw, ph)
        cw_u = int(spec["curve_w_units"])
        mk_sz = float(spec["marker_size_pt"])

        wb = op.new_book("w", lname=f"{title}_Book")
        wks = wb[0]
        wks.name = "XYXYSeries"
        wks.cols = len(series_list) * 2
        gp = op.new_graph(lname=f"{title}_Graph")
        set_graph_page_inches(gp, pw, ph)
        gl = gp[0]

        n_s = len(series_list)
        pal = ot.resolve_series_colors(n_s, scheme="sequential_blue_red" if n_s > 6 else "paired_semantic")
        xmin_all, xmax_all, ymin_all, ymax_all = [], [], [], []
        pos_y_all, pos_x_all = [], []
        leg_entries: List[Tuple[Any, ...]] = []
        series_for_corner: List[Dict[str, Any]] = []
        col_i = 0

        for idx, item in enumerate(series_list):
            nm = ot.clean_semantic_sample_name(str(item["name"]), True)
            xv = np.asarray(item["x"], dtype=float)
            yv = np.asarray(item["y"], dtype=float)
            wks.from_list(col_i, xv.tolist(), lname=f"{nm}_X", axis="X")
            wks.from_list(col_i + 1, yv.tolist(), lname=nm, axis="Y")
            if "plot_type" in item:
                plot_type = item["plot_type"]
            elif show_markers is not None:
                plot_type = "y" if (show_markers and len(xv) <= 120) else "l"
            else:
                plot_type = "y" if len(xv) <= 80 else "l"

            p_obj = gl.add_plot(wks, coly=col_i + 1, colx=col_i, type=plot_type)
            c_hex = ot.normalize_hex(item.get("color") or pal[idx % len(pal)])
            p_obj.color = _hex_to_origin_color(op, c_hex)
            p_idx_1 = len(gl.plot_list())
            if plot_type == "y":
                p_obj.symbol_size = mk_sz
                gl.lt_exec(f"range rr = !{p_idx_1}; set rr -w {cw_u};")
                p_obj.symbol_kind = 2
                p_obj.symbol_interior = 0
                sw_k = "line_sphere"
            else:
                gl.lt_exec(f"range rr = !{p_idx_1}; set rr -w {cw_u};")
                sw_k = "line"
            leg_entries.append((p_idx_1, nm, c_hex, sw_k))
            xmin_all.append(float(np.min(xv)))
            xmax_all.append(float(np.max(xv)))
            ymin_all.append(float(np.min(yv)))
            ymax_all.append(float(np.max(yv)))
            pos_y_all.extend(yv[yv > 0].tolist())
            pos_x_all.extend(xv[xv > 0].tolist())
            series_for_corner.append({"x": xv, "y": yv})
            col_i += 2

        clean_xl = x_label.replace("$", "")
        _style_origin_layer_boxed(
            gl,
            clean_xl,
            y_label.replace("$", ""),
            log_x=log_x,
            log_y=log_y,
            minimal_ticks=minimal_ticks,
            box_thickness=box_thickness,
            tick_label_pt=float(spec["tick_label_pt"]),
            axis_title_pt=float(spec["axis_title_pt"]),
            layer_rect_pct=rect,
            layer_rect_in=box_in,
            remove_legend=True,
            op=op,
            gp=gp,
            layer_num_1based=1,
        )

        activate_layer(op, gp, 1)
        x0_raw, x1_raw = min(xmin_all), max(xmax_all)
        x_sp = max(x1_raw - x0_raw, 1e-6)
        if log_x and pos_x_all:
            xl_lo = 10.0 ** math.floor(math.log10(min(pos_x_all) * 0.7))
            xl_hi = 10.0 ** math.ceil(math.log10(max(pos_x_all) * 1.5))
        elif not invert_x and x0_raw >= 0.0 and x0_raw <= 0.08 * x_sp:
            xl_lo, xl_hi = 0.0, x1_raw + 0.06 * x_sp
        else:
            xl_lo, xl_hi = x0_raw - 0.05 * x_sp, x1_raw + 0.05 * x_sp

        if invert_x:
            gl.set_xlim(xl_hi, xl_lo)
        else:
            gl.set_xlim(xl_lo, xl_hi)

        y0_raw, y1_raw = min(ymin_all), max(ymax_all)
        y_sp = max(y1_raw - y0_raw, 1e-6)
        if log_y and pos_y_all:
            yl_lo = 10.0 ** math.floor(math.log10(min(pos_y_all) * 0.65))
            yl_hi = 10.0 ** math.ceil(math.log10(max(pos_y_all) * 2.5))
            n_dec = round(math.log10(max(yl_hi / max(yl_lo, 1e-30), 10.0)))
            inc_y = 2 if n_dec >= 7 else 1
            gl.set_ylim(yl_lo, yl_hi)
            gl.lt_exec(f"layer.y.from={yl_lo}; layer.y.to={yl_hi}; layer.y.inc={inc_y};")
        else:
            yl_lo = y0_raw - 0.06 * y_sp
            yl_hi = y1_raw + (0.46 if n_s >= 5 else 0.26) * y_sp
            gl.set_ylim(yl_lo, yl_hi)
            if 1.1 <= (yl_hi - yl_lo) <= 4.8:
                gl.lt_exec("layer.y.inc=0.5;")

        if leg_entries:
            if n_s >= 5:
                configure_custom_legend(
                    gl,
                    leg_entries,
                    fontsize=20.0,
                    horizontal=True,
                    pos_mode="interior_top",
                    layer_rect_pct=rect,
                    op=op,
                    gp=gp,
                    layer_num_1based=1,
                )
            else:
                corner_xy_s = [
                    {"x": s["x"], "y": np.log10(np.maximum(s["y"], 1e-30)) if log_y else s["y"]}
                    for s in series_for_corner
                ]
                c_ylim = (math.log10(yl_lo), math.log10(yl_hi)) if log_y else (yl_lo, yl_hi)
                c_xlim = (xl_hi, xl_lo) if invert_x else (xl_lo, xl_hi)
                best_c = pick_cleanest_box_corner(corner_xy_s, xlim=c_xlim, ylim=c_ylim, box_w_frac=0.38, box_h_frac=0.32)
                configure_custom_legend(
                    gl,
                    leg_entries,
                    fontsize=float(spec["legend_pt"]),
                    pos_mode=best_c,
                    layer_rect_pct=rect,
                    op=op,
                    gp=gp,
                    layer_num_1based=1,
                )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        return _safe_save_opju(op, out_p)


def build_raw_preview_opju(
    regions_raw: Dict[str, Dict[str, Any]],
    out_opju: str | Path,
    sample_name: str = "Sample",
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    exported_figures_out: Optional[Dict[str, Dict[str, str]]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    with origin_session() as op:
        pw, ph = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_in = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect = ot.rect_in_to_page_pct(*box_in, pw, ph)
        cw_u = int(spec["curve_w_units"])

        wb = op.new_book("w", lname=f"{sample_name}_RawBook")
        used_sh: set[str] = set()
        pages: List[Tuple[str, Any]] = []

        for idx, (reg, d) in enumerate(regions_raw.items()):
            sh_short = unique_origin_short_name(reg, used_sh, default=f"Reg{idx+1}")
            wks = wb[0] if idx == 0 else wb.add_sheet(sh_short)
            if idx == 0:
                wks.name = sh_short
            xv = np.asarray(d["x"], dtype=float)
            yv = np.asarray(d["y"], dtype=float)
            wks.from_df(pd.DataFrame({"X": xv, "Intensity": yv}))

            gp = op.new_graph(lname=f"{sample_name}_{reg}_RawPreview")
            set_graph_page_inches(gp, pw, ph)
            gl = gp[0]
            p = gl.add_plot(wks, coly=1, colx=0, type="l")
            p.color = _hex_to_origin_color(op, "#3E86DE")
            gl.lt_exec(f"range r1 = !1; set r1 -w {cw_u};")
            gl.rescale()
            if d.get("invert_x", False):
                gl.set_xlim(float(np.max(xv)), float(np.min(xv)))
            else:
                gl.set_xlim(float(np.min(xv)), float(np.max(xv)))

            _style_origin_layer_boxed(
                gl,
                str(d.get("x_label", "X")).replace("$", ""),
                str(d.get("y_label", "Intensity (a.u.)")).replace("$", ""),
                hide_y_labels=True,
                minimal_ticks=minimal_ticks,
                box_thickness=box_thickness,
                layer_rect_pct=rect,
                layer_rect_in=box_in,
                remove_legend=True,
                op=op,
                gp=gp,
                layer_num_1based=1,
            )
            snr_v = d.get("snr")
            pk_x = d.get("peak_x")
            note_txt = f"{sample_name} {reg}" + (
                f"  (Peak: {pk_x:.2f}, SNR: {snr_v:.1f})" if (pk_x is not None and snr_v is not None) else ""
            )
            add_page_text_label(op, gp, gl, 1, "RawHdr", note_txt, rect[0] + 2.8, rect[1] + 5.5, fontsize=float(spec["callout_pt"]), pos_scatter=2, format_math=False)
            pages.append((reg, gp))

        if export_dir is not None:
            for reg, gp in pages:
                figs = export_origin_publication_figures(op, gp, export_dir, f"{sample_name}_{reg}_RawPreview")
                if exported_figures_out is not None:
                    exported_figures_out[reg] = figs

        return _safe_save_opju(op, out_p)


def build_composite_opju(
    panels_rendered: List[Dict[str, Any]],
    out_opju: str | Path,
    title: str = "Paper_Composite",
    ncols: int = 2,
    minimal_ticks: bool = True,
    box_thickness: float = 3.0,
    export_dir: Optional[str | Path] = None,
    export_stem: Optional[str] = None,
    exported_figures_out: Optional[Dict[str, str]] = None,
) -> str:
    spec = get_active_spec()
    out_p = Path(out_opju).resolve()
    n_panels = max(1, len(panels_rendered))
    nc = max(1, min(int(ncols), n_panels))
    nr = int(math.ceil(n_panels / nc))

    with origin_session() as op:
        root_path = op.pe.cd()
        panel_sheets: List[Tuple[str, Dict[str, Any], Any]] = []
        f_id_c = get_font_id(op)
        bold_i = int(spec["bold_int"])
        cw_u = int(spec["curve_w_units"])
        cell_cw_u = int(round(cw_u * 0.85))
        cell_bt = round(max(1.2, float(spec["box_lw_pt"]) * 0.82), 2)
        pw_s, ph_s = float(spec["page_rect_w_in"]), float(spec["page_rect_h_in"])
        box_s = (
            float(spec["box_rect_left_in"]),
            float(spec["box_rect_top_in"]),
            float(spec["box_rect_w_in"]),
            float(spec["box_rect_h_in"]),
        )
        rect_s = ot.rect_in_to_page_pct(*box_s, pw_s, ph_s)

        for idx, p in enumerate(panels_rendered):
            op.pe.cd(root_path)
            letter = chr(ord("a") + idx)
            pid = "".join(ch if ch.isalnum() else "_" for ch in p.get("panel_id", p["panel_type"]))[:18]
            sub = op.pe.mkdir(f"Panel_{letter}_{pid}", True)
            op.pe.cd(sub)

            ptype = p["panel_type"]
            if ptype == "deconvolve":
                _populate_deconv_book_and_graph(
                    op, f"Panel_{letter}", pid, p["fit_result"], minimal_ticks=minimal_ticks, box_thickness=box_thickness
                )
                wks_sub = op.find_sheet("w")
                panel_sheets.append((letter, p, wks_sub))

            elif ptype == "waterfall":
                proc = p["processed_curves"]
                wb = op.new_book("w", lname=f"Panel_{letter}_{pid}_Data")
                wks = wb[0]
                wks.name = sanitize_origin_short_name(f"WF{letter}", "WF")
                wks.cols = len(proc) * 2
                gp = op.new_graph(lname=f"Panel_{letter}_{pid}_Graph")
                set_graph_page_inches(gp, pw_s, ph_s)
                gl = gp[0]
                xmin_all, xmax_all = [], []
                leg_w: List[Tuple[Any, ...]] = []
                c_i = 0
                for item in proc:
                    nm = ot.clean_semantic_sample_name(str(item["name"]), True)
                    c_hex = ot.normalize_hex(item.get("color", "#3E86DE"))
                    wks.from_list(c_i, np.asarray(item["x"], dtype=float).tolist(), lname=f"{nm}_X", axis="X")
                    wks.from_list(c_i + 1, np.asarray(item["y_offset"], dtype=float).tolist(), lname=nm, axis="Y")
                    po = gl.add_plot(wks, coly=c_i + 1, colx=c_i, type="l")
                    po.color = _hex_to_origin_color(op, c_hex)
                    pi1 = len(gl.plot_list())
                    gl.lt_exec(f"range rr = !{pi1}; set rr -w {cw_u};")
                    leg_w.append((pi1, nm, c_hex, "line"))
                    xmin_all.append(float(np.min(item["x"])))
                    xmax_all.append(float(np.max(item["x"])))
                    c_i += 2
                gl.rescale()
                if p.get("invert_x") and xmin_all:
                    gl.set_xlim(max(xmax_all), min(xmin_all))
                _style_origin_layer_boxed(
                    gl,
                    p.get("x_label", "X").replace("$", ""),
                    p.get("y_label", "Intensity (a.u.)"),
                    hide_y_labels=True,
                    minimal_ticks=minimal_ticks,
                    box_thickness=box_thickness,
                    layer_rect_pct=rect_s,
                    layer_rect_in=box_s,
                    remove_legend=True,
                    op=op,
                    gp=gp,
                    layer_num_1based=1,
                )
                configure_custom_legend(
                    gl, list(reversed(leg_w)), fontsize=float(spec["legend_pt"]), pos_mode="corner_upper_left", layer_rect_pct=rect_s, op=op, gp=gp, layer_num_1based=1
                )
                panel_sheets.append((letter, p, wks))

            elif ptype == "nyquist":
                wb = op.new_book("w", lname=f"Panel_{letter}_EIS_Book")
                gp = op.new_graph(lname=f"Panel_{letter}_EIS_Graph")
                set_graph_page_inches(gp, pw_s, ph_s)
                gl = gp[0]
                max_zr_s = 0.0
                max_nzi_s = 0.0
                hf_zr_s = 0.0
                hf_nzi_s = 0.0
                used_sheets: set[str] = set()
                eis_wks_list = []
                leg_e: List[Tuple[Any, ...]] = []
                for s_i, item in enumerate(p["eis_series"]):
                    nm = ot.clean_semantic_sample_name(str(item["name"]), True)
                    c_hex = ot.normalize_hex(item.get("color", "#3E86DE"))
                    sh_short = unique_origin_short_name(nm, used_sheets, default=f"EIS{s_i + 1}", max_len=20)
                    wks = wb[0] if s_i == 0 else wb.add_sheet(sh_short)
                    if s_i == 0:
                        wks.name = sh_short
                    wks.from_df(pd.DataFrame({"Freq": item["freq_Hz"], "Z_real": item["z_real"], "Neg_Z_imag": item["neg_z_imag"]}))
                    wks.cols_axis("NXY")
                    pe = gl.add_plot(wks, coly=2, colx=1, type="y")
                    pe.color = _hex_to_origin_color(op, c_hex)
                    pe.symbol_size = float(spec["marker_size_pt"])
                    pi1 = len(gl.plot_list())
                    gl.lt_exec(f"range rr = !{pi1}; set rr -w {cw_u};")
                    pe.symbol_kind = 2
                    pe.symbol_interior = 0
                    leg_e.append((pi1, nm, c_hex, "line_sphere"))
                    eis_wks_list.append((wks, item))
                    zr_arr = np.asarray(item["z_real"], dtype=float)
                    nzi_arr = np.asarray(item["neg_z_imag"], dtype=float)
                    max_zr_s = max(max_zr_s, float(np.max(zr_arr)))
                    max_nzi_s = max(max_nzi_s, float(np.max(nzi_arr)))
                    n_hf_s = max(6, len(zr_arr) // 3)
                    hf_zr_s = max(hf_zr_s, float(np.max(zr_arr[:n_hf_s])))
                    hf_nzi_s = max(hf_nzi_s, float(np.max(nzi_arr[:n_hf_s])))

                x_lim_s, y_lim_s, step_s = compute_isometric_4_3_bounds(max_zr_s, max_nzi_s)
                gl.set_xlim(0.0, x_lim_s[1])
                gl.set_ylim(0.0, y_lim_s[1])
                _style_origin_layer_boxed(
                    gl,
                    "\\i(Z') (\\g(W))",
                    "-\\i(Z'') (\\g(W))",
                    minimal_ticks=minimal_ticks,
                    box_thickness=box_thickness,
                    layer_rect_pct=rect_s,
                    layer_rect_in=box_s,
                    remove_legend=True,
                    op=op,
                    gp=gp,
                    layer_num_1based=1,
                )
                gl.lt_exec(
                    f"layer.x.from=0; layer.x.to={x_lim_s[1]}; layer.x.inc={step_s}; "
                    f"layer.y.from=0; layer.y.to={y_lim_s[1]}; layer.y.inc={step_s};"
                )

                if p.get("add_hf_inset", False) and 0.0 < max(hf_zr_s, hf_nzi_s) < 0.45 * x_lim_s[1]:
                    in_u_s = max((hf_zr_s * 1.16) / 4.0, (hf_nzi_s * 1.16) / 3.0)
                    in_u_s = math.ceil(in_u_s / 5.0) * 5.0 if in_u_s >= 15.0 else max(round(in_u_s, 2), 0.5)
                    in_xl_s, in_yl_s = 4.0 * in_u_s, 3.0 * in_u_s
                    gl_in_s = gp.add_layer(6)
                    activate_layer(op, gp, 2)
                    gl_in_s.lt_exec("layer.fsize=1;")
                    white_s_int = ot.hex_to_origin_rgb_int("#FFFFFF")
                    white_s_oc = _hex_to_origin_color(op, "#FFFFFF")
                    ink_s_int = ot.hex_to_origin_rgb_int("#111111")
                    font_in_s = f"layer.x.label.font={f_id_c}; layer.y.label.font={f_id_c}; " if f_id_c > 0 else ""
                    wks_s_bg = wb.add_sheet(unique_origin_short_name("EISInBG", used_sheets, default="IBG"))
                    wks_s_bg.cols = 3
                    wks_s_bg.from_list(0, [0.0, in_xl_s], axis="X")
                    wks_s_bg.from_list(1, [in_yl_s, in_yl_s], axis="Y")
                    wks_s_bg.from_list(2, [0.0, 0.0], axis="Y")
                    ps_bu = gl_in_s.add_plot(wks_s_bg, coly=1, colx=0, type="l")
                    ps_bl = gl_in_s.add_plot(wks_s_bg, coly=2, colx=0, type="l")
                    ps_bu.color = white_s_oc
                    ps_bl.color = white_s_oc
                    ps_bu.set_fill_area(above=white_s_oc, type=9, below=white_s_oc)
                    ps_bu.transparency = 0
                    ps_bl.transparency = 100
                    gl_in_s.lt_exec("range rbu = !1; set rbu -w 0; range rbl = !2; set rbl -w 0;")
                    ins_s_w_in, ins_s_h_in = 0.42 * box_s[2], 0.42 * box_s[3]
                    ins_s_scale = ot.compute_origin_layer_scale(ins_s_w_in, ins_s_h_in, pw_s, ph_s)
                    for wks_e_s, item_s in eis_wks_list:
                        chx_s = ot.normalize_hex(item_s.get("color", "#3E86DE"))
                        pis = gl_in_s.add_plot(wks_e_s, coly=2, colx=1, type="y")
                        pis.color = _hex_to_origin_color(op, chx_s)
                        pis.symbol_size = round(4.8 / ins_s_scale, 1)
                        isi = len(gl_in_s.plot_list())
                        gl_in_s.lt_exec(f"range rin = !{isi}; set rin -w {int(round((cw_u * 0.72) / ins_s_scale))};")
                        pis.symbol_kind = 2
                        pis.symbol_interior = 0
                    gl_in_s.set_xlim(0.0, in_xl_s)
                    gl_in_s.set_ylim(0.0, in_yl_s)
                    ins_s_bt = float(spec["inset_box_lw_pt"])
                    ins_s_pt = ot.compensate_origin_layer_pt(float(spec["inset_tick_pt"]), ins_s_w_in, ins_s_h_in, pw_s, ph_s)
                    inc_sx = compute_nice_linear_step(0.0, in_xl_s, max_ticks=4) or in_u_s
                    inc_sy = compute_nice_linear_step(0.0, in_yl_s, max_ticks=4) or in_u_s
                    gl_in_s.lt_exec(
                        f"layer.fsize=1; layer.unit=7; layer.left=51; layer.top=44; layer.width=42; layer.height=42; "
                        f"layer.color={white_s_int}; layer.x.grid.show=0; layer.y.grid.show=0; "
                        f"layer.x.showAxes=3; layer.y.showAxes=3; "
                        f"layer.x.thickness={ins_s_bt}; layer.y.thickness={ins_s_bt}; layer.x2.thickness={ins_s_bt}; layer.y2.thickness={ins_s_bt}; "
                        f"layer.x.color={ink_s_int}; layer.y.color={ink_s_int}; layer.x2.color={ink_s_int}; layer.y2.color={ink_s_int}; "
                        f"layer.x.label.color={ink_s_int}; layer.y.label.color={ink_s_int}; "
                        f"layer.x.ticks=1; layer.y.ticks=1; layer.x2.ticks=0; layer.y2.ticks=0; "
                        f"layer.x.from=0; layer.x.to={in_xl_s}; layer.x.inc={inc_sx}; "
                        f"layer.y.from=0; layer.y.to={in_yl_s}; layer.y.inc={inc_sy}; "
                        f"layer.x.maxTicks=4; layer.y.maxTicks=4; {font_in_s}"
                        f"layer.x.label.pt={ins_s_pt}; layer.y.label.pt={ins_s_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
                        f"XB.show=0; YL.show=0; label -r Legend;"
                    )

                configure_custom_legend(
                    gl, leg_e, fontsize=float(spec["legend_pt"]), pos_mode="corner_upper_right", layer_rect_pct=rect_s, op=op, gp=gp, layer_num_1based=1
                )
                panel_sheets.append((letter, p, eis_wks_list))

            elif ptype == "xy_series":
                s_list = p["series_list"]
                wb = op.new_book("w", lname=f"Panel_{letter}_{pid}_Book")
                wks = wb[0]
                wks.name = sanitize_origin_short_name(f"XY{letter}", "XY")
                wks.cols = len(s_list) * 2
                gp = op.new_graph(lname=f"Panel_{letter}_{pid}_Graph")
                set_graph_page_inches(gp, pw_s, ph_s)
                gl = gp[0]
                leg_x: List[Tuple[Any, ...]] = []
                c_i = 0
                for s in s_list:
                    nm = ot.clean_semantic_sample_name(str(s["name"]), True)
                    c_hex = ot.normalize_hex(s.get("color", "#3E86DE"))
                    wks.from_list(c_i, np.asarray(s["x"], dtype=float).tolist(), lname=f"{nm}_X", axis="X")
                    wks.from_list(c_i + 1, np.asarray(s["y"], dtype=float).tolist(), lname=nm, axis="Y")
                    po = gl.add_plot(wks, coly=c_i + 1, colx=c_i, type="l")
                    po.color = _hex_to_origin_color(op, c_hex)
                    pi1 = len(gl.plot_list())
                    gl.lt_exec(f"range rr = !{pi1}; set rr -w {cw_u};")
                    leg_x.append((pi1, nm, c_hex, "line"))
                    c_i += 2
                gl.rescale()
                _style_origin_layer_boxed(
                    gl,
                    p.get("x_label", "X").replace("$", ""),
                    p.get("y_label", "Y").replace("$", ""),
                    log_x=bool(p.get("log_x")),
                    log_y=bool(p.get("log_y")),
                    minimal_ticks=minimal_ticks,
                    box_thickness=box_thickness,
                    layer_rect_pct=rect_s,
                    layer_rect_in=box_s,
                    remove_legend=True,
                    op=op,
                    gp=gp,
                    layer_num_1based=1,
                )
                configure_custom_legend(
                    gl, leg_x, fontsize=float(spec["legend_pt"]), pos_mode="corner_upper_right", layer_rect_pct=rect_s, op=op, gp=gp, layer_num_1based=1
                )
                panel_sheets.append((letter, p, wks))

        # Master 2x2 Composite Page (grid-aligned 4:3 `4.10 x 3.075 in` physical boxes across all 1D & EIS Nyquist panels)
        op.pe.cd(root_path)
        gp_comp = op.new_graph(lname=f"{title}_MasterComposite")
        col_step_in = 6.55
        row_step_in = 4.75
        comp_w_in = 1.25 + col_step_in * nc
        comp_h_in = 0.85 + row_step_in * nr
        set_graph_page_inches(gp_comp, comp_w_in, comp_h_in)
        wb_comp_deconv = None
        used_cd: set[str] = set()

        for idx, (letter, p, ref_obj) in enumerate(panel_sheets):
            r_i, c_i = idx // nc, idx % nc
            c_left_in = 1.70 + c_i * col_step_in
            c_top_in = 0.96 + r_i * row_step_in
            c_box_in = (c_left_in, c_top_in, 4.10, 3.075)
            rect_c = ot.rect_in_to_page_pct(*c_box_in, comp_w_in, comp_h_in)

            gl_c = gp_comp[0] if idx == 0 else gp_comp.add_layer(0)
            lay_num = int(gp_comp.obj.Layers.Count)
            activate_layer(op, gp_comp, lay_num)
            gl_c.lt_exec("layer.fsize=1;")
            ptype = p["panel_type"]
            p_title_str = ot.clean_semantic_sample_name(str(p.get("panel_title", "")).strip(), True)

            if ptype == "deconvolve":
                first_d = wb_comp_deconv is None
                if first_d:
                    wb_comp_deconv = op.new_book("w", lname=f"{title}_CompDeconv")
                wks_d = _create_deconv_sheet(
                    op,
                    f"P{letter}",
                    p.get("panel_id", "Spec"),
                    p["fit_result"],
                    wb=wb_comp_deconv,
                    used_names=used_cd,
                    use_first_sheet=first_d,
                )
                leg_c = _populate_deconv_layer(
                    op,
                    gp_comp,
                    wks_d,
                    gl_c,
                    lay_num,
                    p["fit_result"],
                    minimal_ticks=minimal_ticks,
                    box_thickness=cell_bt,
                    layer_rect_pct=rect_c,
                    layer_rect_in=c_box_in,
                    axis_title_pt=20.0,
                    tick_label_pt=16.5,
                    panel_title=p_title_str,
                )
                activate_layer(op, gp_comp, lay_num)
                res_f = p["fit_result"]
                ymin_d = float(np.min(np.minimum(res_f["y_raw"], res_f["baseline"])))
                ymax_d = float(np.max(np.maximum(res_f["y_raw"], res_f["y_fit"])))
                ysp_d = max(ymax_d - ymin_d, 1e-6)
                gl_c.set_ylim(ymin_d - 0.08 * ysp_d, ymax_d + 1.18 * ysp_d)
                gl_c.lt_exec("layer.x.maxTicks=5;")
                configure_custom_legend(
                    gl_c,
                    leg_c,
                    fontsize=12.0,
                    horizontal=True,
                    pos_mode="interior_top",
                    layer_rect_pct=rect_c,
                    op=op,
                    gp=gp_comp,
                    layer_num_1based=lay_num,
                )

            elif ptype == "waterfall":
                wks_w = ref_obj
                proc = p["processed_curves"]
                leg_c = []
                xmin_a, xmax_a, ymin_a, ymax_a = [], [], [], []
                for s_i, item in enumerate(proc):
                    c_hex = ot.normalize_hex(item.get("color", "#3E86DE"))
                    po = gl_c.add_plot(wks_w, coly=2 * s_i + 1, colx=2 * s_i, type="l")
                    po.color = _hex_to_origin_color(op, c_hex)
                    pi1 = len(gl_c.plot_list())
                    gl_c.lt_exec(f"range rr = !{pi1}; set rr -w {cell_cw_u};")
                    leg_c.append((pi1, ot.clean_semantic_sample_name(str(item["name"]), True), c_hex, "line"))
                    xmin_a.append(float(np.min(item["x"])))
                    xmax_a.append(float(np.max(item["x"])))
                    ymin_a.append(float(np.min(item["y_offset"])))
                    ymax_a.append(float(np.max(item["y_offset"])))
                gl_c.rescale()
                ysp_w = max(max(ymax_a) - min(ymin_a), 1e-6)
                gl_c.set_ylim(min(ymin_a) - 0.06 * ysp_w, max(ymax_a) + 0.34 * ysp_w)
                if p.get("invert_x") and xmin_a:
                    gl_c.set_xlim(max(xmax_a), min(xmin_a))
                _style_origin_layer_boxed(
                    gl_c,
                    p.get("x_label", "X").replace("$", ""),
                    p.get("y_label", "Intensity (a.u.)"),
                    hide_y_labels=True,
                    minimal_ticks=minimal_ticks,
                    box_thickness=cell_bt,
                    tick_label_pt=16.5,
                    axis_title_pt=20.0,
                    layer_rect_pct=rect_c,
                    layer_rect_in=c_box_in,
                    remove_legend=True,
                    op=op,
                    gp=gp_comp,
                    layer_num_1based=lay_num,
                )
                if p_title_str:
                    add_page_text_label(op, gp_comp, gl_c, lay_num, f"PnlTitle{lay_num}", p_title_str, rect_c[0] + 0.5 * rect_c[2], max(1.8, rect_c[1] - 2.3), fontsize=17.5, pos_scatter=0, format_math=False)
                configure_custom_legend(
                    gl_c, list(reversed(leg_c)), fontsize=14.5, pos_mode="corner_upper_left", layer_rect_pct=rect_c, op=op, gp=gp_comp, layer_num_1based=lay_num
                )

            elif ptype == "nyquist":
                max_zr_c, max_nzi_c, hf_zr_c, hf_nzi_c = 0.0, 0.0, 0.0, 0.0
                leg_c = []
                for wks_e, item in ref_obj:
                    c_hex = ot.normalize_hex(item.get("color", "#3E86DE"))
                    pe = gl_c.add_plot(wks_e, coly=2, colx=1, type="y")
                    pe.color = _hex_to_origin_color(op, c_hex)
                    pe.symbol_size = 5.5
                    pi1 = len(gl_c.plot_list())
                    gl_c.lt_exec(f"range rr = !{pi1}; set rr -w {cell_cw_u};")
                    pe.symbol_kind = 2
                    pe.symbol_interior = 0
                    leg_c.append((pi1, ot.clean_semantic_sample_name(str(item["name"]), True), c_hex, "line_sphere"))
                    zr_a = np.asarray(item["z_real"], dtype=float)
                    nzi_a = np.asarray(item["neg_z_imag"], dtype=float)
                    max_zr_c = max(max_zr_c, float(np.max(zr_a)))
                    max_nzi_c = max(max_nzi_c, float(np.max(nzi_a)))
                    n_hf_c = max(6, len(zr_a) // 3)
                    hf_zr_c = max(hf_zr_c, float(np.max(zr_a[:n_hf_c])))
                    hf_nzi_c = max(hf_nzi_c, float(np.max(nzi_a[:n_hf_c])))

                x_lim_c, y_lim_c, step_c = compute_isometric_4_3_bounds(max_zr_c, max_nzi_c)
                xlim_c_top = x_lim_c[1]
                ylim_c_top = y_lim_c[1]

                gl_c.set_xlim(0.0, xlim_c_top)
                gl_c.set_ylim(0.0, ylim_c_top)
                _style_origin_layer_boxed(
                    gl_c,
                    "\\i(Z') (\\g(W))",
                    "-\\i(Z'') (\\g(W))",
                    minimal_ticks=minimal_ticks,
                    box_thickness=cell_bt,
                    tick_label_pt=16.5,
                    axis_title_pt=20.0,
                    layer_rect_pct=rect_c,
                    layer_rect_in=c_box_in,
                    remove_legend=True,
                    op=op,
                    gp=gp_comp,
                    layer_num_1based=lay_num,
                )
                activate_layer(op, gp_comp, lay_num)
                gl_c.lt_exec(
                    f"layer.x.from=0; layer.x.to={xlim_c_top}; layer.x.inc={step_c}; "
                    f"layer.y.from=0; layer.y.to={ylim_c_top}; layer.y.inc={step_c};"
                )
                if p_title_str:
                    add_page_text_label(op, gp_comp, gl_c, lay_num, f"PnlTitle{lay_num}", p_title_str, rect_c[0] + 0.5 * rect_c[2], max(1.8, rect_c[1] - 2.3), fontsize=17.5, pos_scatter=0, format_math=False)

                hf_max_c = max(hf_zr_c, hf_nzi_c)
                if p.get("add_hf_inset", True) and 0.0 < hf_max_c < 0.45 * xlim_c_top:
                    in_u_c = max((hf_zr_c * 1.16) / 4.0, (hf_nzi_c * 1.16) / 3.0)
                    in_u_c = math.ceil(in_u_c / 5.0) * 5.0 if in_u_c >= 15.0 else max(round(in_u_c, 2), 0.5)
                    in_xl_c, in_yl_c = 4.0 * in_u_c, 3.0 * in_u_c
                    gl_in_c = gp_comp.add_layer(0)
                    in_lay_num = int(gp_comp.obj.Layers.Count)
                    activate_layer(op, gp_comp, in_lay_num)
                    white_i = ot.hex_to_origin_rgb_int("#FFFFFF")
                    white_oc_c = _hex_to_origin_color(op, "#FFFFFF")
                    ink_i = ot.hex_to_origin_rgb_int("#111111")
                    font_ic = f"layer.x.label.font={f_id_c}; layer.y.label.font={f_id_c}; " if f_id_c > 0 else ""
                    wks_c_bg = op.new_book("w", lname=f"{title}_CInBG")[0]
                    wks_c_bg.cols = 3
                    wks_c_bg.from_list(0, [0.0, in_xl_c], axis="X")
                    wks_c_bg.from_list(1, [in_yl_c, in_yl_c], axis="Y")
                    wks_c_bg.from_list(2, [0.0, 0.0], axis="Y")
                    pc_bu = gl_in_c.add_plot(wks_c_bg, coly=1, colx=0, type="l")
                    pc_bl = gl_in_c.add_plot(wks_c_bg, coly=2, colx=0, type="l")
                    pc_bu.color = white_oc_c
                    pc_bl.color = white_oc_c
                    pc_bu.set_fill_area(above=white_oc_c, type=9, below=white_oc_c)
                    pc_bu.transparency = 0
                    pc_bl.transparency = 100
                    gl_in_c.lt_exec("range rbu = !1; set rbu -w 0; range rbl = !2; set rbl -w 0;")
                    in_wi = 0.42 * c_box_in[2]
                    in_hi = 0.42 * c_box_in[3]
                    in_li = c_left_in + 0.51 * c_box_in[2]
                    in_ti = c_top_in + 0.42 * c_box_in[3]
                    ins_c_scale = ot.compute_origin_layer_scale(in_wi, in_hi, comp_w_in, comp_h_in)
                    for wks_e, item in ref_obj:
                        c_hex_i = ot.normalize_hex(item.get("color", "#3E86DE"))
                        p_ic = gl_in_c.add_plot(wks_e, coly=2, colx=1, type="y")
                        p_ic.color = _hex_to_origin_color(op, c_hex_i)
                        p_ic.symbol_size = round(3.8 / ins_c_scale, 1)
                        ic_idx = len(gl_in_c.plot_list())
                        gl_in_c.lt_exec(f"range ric = !{ic_idx}; set ric -w {int(round((cell_cw_u * 0.72) / ins_c_scale))};")
                        p_ic.symbol_kind = 2
                        p_ic.symbol_interior = 0
                    gl_in_c.set_xlim(0.0, in_xl_c)
                    gl_in_c.set_ylim(0.0, in_yl_c)
                    ins_c_bt = max(1.0, round(cell_bt * 0.72, 2))
                    ins_c_tk_pt = ot.compensate_origin_layer_pt(11.5, in_wi, in_hi, comp_w_in, comp_h_in)
                    inc_cx = compute_nice_linear_step(0.0, in_xl_c, max_ticks=3) or (2.0 * in_u_c)
                    inc_cy = compute_nice_linear_step(0.0, in_yl_c, max_ticks=3) or in_u_c
                    gl_in_c.lt_exec(
                        f"layer.fsize=1; "
                        f"layer.unit=2; layer.left={in_li}; layer.top={in_ti}; layer.width={in_wi}; layer.height={in_hi}; "
                        f"layer.color={white_i}; layer.x.grid.show=0; layer.y.grid.show=0; "
                        f"layer.x.showAxes=3; layer.y.showAxes=3; "
                        f"layer.x.thickness={ins_c_bt}; layer.y.thickness={ins_c_bt}; layer.x2.thickness={ins_c_bt}; layer.y2.thickness={ins_c_bt}; "
                        f"layer.x.color={ink_i}; layer.y.color={ink_i}; layer.x2.color={ink_i}; layer.y2.color={ink_i}; "
                        f"layer.x.label.color={ink_i}; layer.y.label.color={ink_i}; "
                        f"layer.x.ticks=1; layer.y.ticks=1; layer.x2.ticks=0; layer.y2.ticks=0; "
                        f"layer.x.from=0; layer.x.to={in_xl_c}; layer.x.inc={inc_cx}; "
                        f"layer.y.from=0; layer.y.to={in_yl_c}; layer.y.inc={inc_cy}; "
                        f"layer.x.maxTicks=3; layer.y.maxTicks=3; "
                        f"{font_ic}"
                        f"layer.x.label.pt={ins_c_tk_pt}; layer.y.label.pt={ins_c_tk_pt}; layer.x.label.bold={bold_i}; layer.y.label.bold={bold_i}; "
                        f"XB.show=0; YL.show=0; label -r Legend;"
                    )

                configure_custom_legend(
                    gl_c, leg_c, fontsize=13.5, pos_mode="corner_upper_right", layer_rect_pct=rect_c, op=op, gp=gp_comp, layer_num_1based=lay_num
                )

            elif ptype == "xy_series":
                wks_x = ref_obj
                s_list = p["series_list"]
                leg_c = []
                xmin_x, xmax_x, ymin_x, ymax_x = [], [], [], []
                for s_i, s in enumerate(s_list):
                    c_hex = ot.normalize_hex(s.get("color", "#3E86DE"))
                    po = gl_c.add_plot(wks_x, coly=2 * s_i + 1, colx=2 * s_i, type="l")
                    po.color = _hex_to_origin_color(op, c_hex)
                    pi1 = len(gl_c.plot_list())
                    gl_c.lt_exec(f"range rr = !{pi1}; set rr -w {cell_cw_u};")
                    leg_c.append((pi1, ot.clean_semantic_sample_name(str(s["name"]), True), c_hex, "line"))
                    xv_c, yv_c = np.asarray(s["x"], dtype=float), np.asarray(s["y"], dtype=float)
                    xmin_x.append(float(np.min(xv_c)))
                    xmax_x.append(float(np.max(xv_c)))
                    ymin_x.append(float(np.min(yv_c)))
                    ymax_x.append(float(np.max(yv_c)))
                _style_origin_layer_boxed(
                    gl_c,
                    p.get("x_label", "X").replace("$", ""),
                    p.get("y_label", "Y").replace("$", ""),
                    log_x=bool(p.get("log_x")),
                    log_y=bool(p.get("log_y")),
                    minimal_ticks=minimal_ticks,
                    box_thickness=cell_bt,
                    tick_label_pt=16.5,
                    axis_title_pt=20.0,
                    layer_rect_pct=rect_c,
                    layer_rect_in=c_box_in,
                    remove_legend=True,
                    op=op,
                    gp=gp_comp,
                    layer_num_1based=lay_num,
                )
                activate_layer(op, gp_comp, lay_num)
                gl_c.lt_exec("layer.x.maxTicks=5;")
                x0_c, x1_c = min(xmin_x), max(xmax_x)
                xsp_c = max(x1_c - x0_c, 1e-6)
                xl_lo_c = 0.0 if (x0_c >= 0.0 and x0_c <= 0.08 * xsp_c) else (x0_c - 0.04 * xsp_c)
                xl_hi_c = x1_c + 0.06 * xsp_c
                y0_c, y1_c = min(ymin_x), max(ymax_x)
                ysp_c = max(y1_c - y0_c, 1e-6)
                yl_lo_c = y0_c - 0.06 * ysp_c
                yl_hi_c = max(y1_c + 0.44 * ysp_c, 4.0)
                gl_c.set_xlim(xl_lo_c, xl_hi_c)
                gl_c.set_ylim(yl_lo_c, yl_hi_c)
                if 1.1 <= (yl_hi_c - yl_lo_c) <= 4.5:
                    gl_c.lt_exec("layer.y.inc=0.5;")
                if p_title_str:
                    add_page_text_label(op, gp_comp, gl_c, lay_num, f"PnlTitle{lay_num}", p_title_str, rect_c[0] + 0.5 * rect_c[2], max(1.8, rect_c[1] - 2.3), fontsize=17.5, pos_scatter=0, format_math=False)
                configure_custom_legend(
                    gl_c, leg_c, fontsize=13.5, pos_mode="corner_upper_right", layer_rect_pct=rect_c, op=op, gp=gp_comp, layer_num_1based=lay_num
                )

            tag_left_in = c_left_in - 1.24
            tag_top_in = max(0.28, c_top_in - 0.30)
            add_page_text_label(
                op,
                gp_comp,
                gl_c,
                lay_num,
                f"PnlTag{letter}",
                letter,
                max(1.2, (tag_left_in / comp_w_in) * 100.0),
                max(1.8, (tag_top_in / comp_h_in) * 100.0),
                fontsize=23.0,
                pos_scatter=0,
                format_math=False,
            )

        if export_dir is not None:
            figs = export_origin_publication_figures(op, gp_comp, export_dir, export_stem or title)
            if exported_figures_out is not None:
                exported_figures_out.update(figs)

        op.lt_exec(f'win -a "{gp_comp.name}";')
        return _safe_save_opju(op, out_p)
