"""
origin_theme.py - Pure-Python OriginPro-native visual theme, semantic color engine,
axis tick-decision matrix, and Microsoft RIFF (.pal) palette binary generator.

Zero dependency on matplotlib or Origin COM runtime.
Default global preset: presets/style_publication_minimal.json (with backward-compatible
loading for style_academic_acs_nature.json and custom JSON presets).
"""
from __future__ import annotations

import copy
import json
import math
import re
import struct
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
PRESET_DIR = SCRIPT_DIR.parent / "presets"

DEFAULT_STYLE_PRESET = "style_publication_minimal"
LEGACY_ACS_STYLE_PRESET = "style_academic_acs_nature"

# Standard paired blue/red & neutral semantic palette
SEMANTIC_PALETTE: Dict[str, str] = {
    "ice": "#C5DBF5",
    "blue": "#3E86DE",
    "indigo": "#6579BE",
    "pink": "#E8A3AF",
    "rose": "#D84B5C",
    "wine": "#A02333",
    "slate": "#D8DEE9",
    "ink": "#111111",
    "charcoal": "#222222",
}

SEQUENTIAL_BLUE_RED_STOPS: List[str] = [
    "#2B6CB0",
    "#3E86DE",
    "#6579BE",
    "#D97B8D",
    "#D84B5C",
    "#A02333",
]

# Deep blue-to-red ramp for >= 8 high-rate discharge curve clusters
DEEP_BLUE_TO_RED_STOPS: List[str] = [
    "#08306B",
    "#2171B5",
    "#4292C6",
    "#6579BE",
    "#D97B8D",
    "#D84B5C",
    "#A02333",
]

PSEUDOCOLOR_ZERO_WHITE_STOPS: List[str] = [
    "#F7FAFE",
    "#CFE2FA",
    "#5A98DC",
    "#6579BE",
    "#D84B5C",
    "#A02333",
]

DIVERGING_BLUE_WHITE_RED_STOPS: List[str] = [
    "#2B6CB0",
    "#9EC5F0",
    "#FFFFFF",
    "#F0A3B0",
    "#D84B5C",
    "#A02333",
]

SANDWICH_STACK_ORDERED: List[str] = [
    "#A8C4E8",
    "#C2D8F2",
    "#6579BE",
    "#3E86DE",
    "#E88B9C",
    "#D84B5C",
    "#A02333",
]

_SANDWICH_BY_COUNT: Dict[int, List[str]] = {
    1: ["#3E86DE"],
    2: ["#A8C4E8", "#D84B5C"],
    3: ["#A8C4E8", "#3E86DE", "#D84B5C"],
    4: ["#A8C4E8", "#3E86DE", "#D84B5C", "#A02333"],
    5: ["#A8C4E8", "#6579BE", "#3E86DE", "#D84B5C", "#A02333"],
    6: ["#A8C4E8", "#7BA8E0", "#6579BE", "#3E86DE", "#D84B5C", "#A02333"],
    7: list(SANDWICH_STACK_ORDERED),
}

_PAIRED_INTERLEAVED: List[str] = [
    "#2B6CB0",
    "#D84B5C",
    "#6579BE",
    "#A02333",
    "#3E86DE",
    "#8C3B5E",
]

_HEX_RE = re.compile(r"^#?(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$")
_SAMPLE_PREFIX_RE = re.compile(r"^[A-Za-z]\s*:\s+")

VALID_COLOR_SCHEMES = (
    "paired_semantic",
    "sandwich_stack",
    "sequential_blue_red",
    "deep_blue_to_red",
    "pseudocolor_zero_white",
    "diverging_blue_white_red",
)

VALID_AXIS_KINDS = (
    "intensity_arbitrary",
    "categorical",
    "quantitative",
    "dual_y_left",
    "dual_y_right",
    "inset",
)

VALID_AXIS_SCALES = ("linear", "log10")


class GradientLabelColors(NamedTuple):
    """
    Supports 3-tuple unpacking `(top_hex, bottom_hex, label_hex)`, attribute access,
    and dict-key lookup (`res["top_hex"]`, `res["bottom_hex"]`, `res["label_hex"]`).
    """

    top_hex: str
    bottom_hex: str
    label_hex: str

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, str):
            alias_map = {
                "top": self.top_hex,
                "top_hex": self.top_hex,
                "top_color": self.top_hex,
                "bottom": self.bottom_hex,
                "bottom_hex": self.bottom_hex,
                "bottom_color": self.bottom_hex,
                "label": self.label_hex,
                "label_hex": self.label_hex,
                "label_color": self.label_hex,
            }
            if key in alias_map:
                return alias_map[key]
            raise KeyError(f"Unknown GradientLabelColors key: {key!r}")
        return tuple.__getitem__(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def to_dict(self) -> Dict[str, str]:
        return {
            "top_hex": self.top_hex,
            "bottom_hex": self.bottom_hex,
            "label_hex": self.label_hex,
        }


def parse_hex_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Parse '#RRGGBB' or '#RGB' (or named semantic key) into (r, g, b) in [0, 255]."""
    if not isinstance(hex_color, str):
        raise TypeError(f"Expected hex color string, got {type(hex_color).__name__}")
    token = hex_color.strip()
    lower_key = token.lower()
    if lower_key in SEMANTIC_PALETTE:
        token = SEMANTIC_PALETTE[lower_key]
    if not _HEX_RE.match(token):
        raise ValueError(f"Invalid hex color or semantic color name: {hex_color!r}")
    raw = token.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def rgb_to_hex(r: int | float, g: int | float, b: int | float) -> str:
    """Clamp RGB channels to [0, 255] and format as uppercase '#RRGGBB'."""
    ri = max(0, min(255, int(round(r))))
    gi = max(0, min(255, int(round(g))))
    bi = max(0, min(255, int(round(b))))
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def normalize_hex(hex_color: str) -> str:
    """Normalize a hex string or semantic palette token to uppercase '#RRGGBB'."""
    return rgb_to_hex(*parse_hex_rgb(hex_color))


def mix_hex(color_a: str, color_b: str, weight_b: float = 0.45) -> str:
    """Linearly mix `color_a` toward `color_b` by `weight_b` in [0.0, 1.0]."""
    t = max(0.0, min(1.0, float(weight_b)))
    ra, ga, ba = parse_hex_rgb(color_a)
    rb, gb, bb = parse_hex_rgb(color_b)
    return rgb_to_hex(
        ra * (1.0 - t) + rb * t,
        ga * (1.0 - t) + gb * t,
        ba * (1.0 - t) + bb * t,
    )


def relative_luminance(hex_color: str) -> float:
    """Compute perceptual relative luminance in [0.0, 1.0] (matching pubstyle luminance)."""
    r, g, b = parse_hex_rgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def origin_rgb_int(r: int, g: int, b: int) -> int:
    """
    Encode (r, g, b) to Origin LabTalk 24-bit ocolor integer:
        16777216 + r + g*256 + b*65536
    Remaps pure black (0, 0, 0) -> (1, 1, 1) (16843009) to prevent Origin's green-black bug.
    """
    ri = max(0, min(255, int(r)))
    gi = max(0, min(255, int(g)))
    bi = max(0, min(255, int(b)))
    if ri == 0 and gi == 0 and bi == 0:
        ri = gi = bi = 1
    return 16777216 + ri + gi * 256 + bi * 65536


def hex_to_origin_rgb_int(
    color_or_r: str | Sequence[int] | int,
    g: Optional[int] = None,
    b: Optional[int] = None,
) -> int:
    """
    Convert a hex string ('#RRGGBB'), an (r, g, b) sequence, or three (r, g, b) integers
    into an Origin LabTalk RGB integer, safely remapping (0, 0, 0) -> (1, 1, 1) (16843009).
    """
    if isinstance(color_or_r, str):
        if g is not None or b is not None:
            raise TypeError("Pass either a single hex string or three (r, g, b) integers.")
        return origin_rgb_int(*parse_hex_rgb(color_or_r))
    if isinstance(color_or_r, (tuple, list)):
        if len(color_or_r) != 3:
            raise ValueError(f"Expected 3-element RGB sequence, got length {len(color_or_r)}")
        return origin_rgb_int(int(color_or_r[0]), int(color_or_r[1]), int(color_or_r[2]))
    if g is None or b is None:
        raise TypeError("When passing integer r, both g and b must also be provided.")
    return origin_rgb_int(int(color_or_r), int(g), int(b))


def interpolate_color_stops(hex_stops: Sequence[str], n_colors: int) -> List[str]:
    """Piecewise-linearly interpolate `n_colors` '#RRGGBB' colors across `hex_stops`."""
    if n_colors < 0:
        raise ValueError(f"n_colors must be >= 0, got {n_colors}")
    if n_colors == 0:
        return []
    if not hex_stops:
        raise ValueError("hex_stops must contain at least one color.")
    stops_rgb = [parse_hex_rgb(c) for c in hex_stops]
    if len(stops_rgb) == 1:
        single = rgb_to_hex(*stops_rgb[0])
        return [single] * n_colors
    if n_colors == 1:
        mid = stops_rgb[len(stops_rgb) // 2]
        return [rgb_to_hex(*mid)]

    m = len(stops_rgb) - 1
    out: List[str] = []
    for idx in range(n_colors):
        pos = (idx / (n_colors - 1)) * m
        seg = min(m - 1, int(pos))
        frac = pos - seg
        r0, g0, b0 = stops_rgb[seg]
        r1, g1, b1 = stops_rgb[seg + 1]
        out.append(
            rgb_to_hex(
                r0 + (r1 - r0) * frac,
                g0 + (g1 - g0) * frac,
                b0 + (b1 - b0) * frac,
            )
        )
    return out


def _classify_semantic_role(role: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Classify a role hint into ('direct', hex), ('control', modifier), ('pulse', modifier),
    ('inert', None), ('middle', None), or ('auto', None).
    """
    if not role:
        return "auto", None
    raw = str(role).strip()
    if not raw:
        return "auto", None
    low = raw.lower()
    if low in SEMANTIC_PALETTE:
        return "direct", SEMANTIC_PALETTE[low]
    if _HEX_RE.match(raw):
        return "direct", normalize_hex(raw)

    inert_tokens = ("inert", "binder", "pvdf", "background", "bg", "slate", "bottom", "惰性", "背景", "基底")
    if any(tok in low for tok in inert_tokens):
        return "inert", None

    pulse_tokens = (
        "pulse", "treat", "treatment", "mod", "modified", "active", "dominant",
        "target", "fast", "high_rate", "retest", "des", "desorption", "top",
        "脉冲", "处理", "改性", "活性", "复测", "强极化",
    )
    control_tokens = (
        "control", "ctrl", "ref", "reference", "pristine", "raw", "initial",
        "base", "baseline", "conv", "conventional", "normal", "const", "cc",
        "galvanostatic", "ads", "adsorption", "slow", "covalent",
        "对照", "常规", "原始", "恒流", "初测", "基准",
    )

    is_light = any(tok in low for tok in ("light", "mild", "pristine", "initial", "weak", "原始", "轻", "浅"))
    is_strong = any(tok in low for tok in ("strong", "deep", "heavy", "severe", "max", "dominant", "强", "深", "重"))
    modifier = "light" if is_light else ("strong" if is_strong else None)

    if any(tok in low for tok in pulse_tokens):
        return "pulse", modifier
    if any(tok in low for tok in control_tokens):
        return "control", modifier
    if "middle" in low or "mid" in low:
        return "middle", modifier
    return "auto", modifier


def resolve_series_colors(
    n: int,
    roles: Optional[Sequence[Optional[str]]] = None,
    scheme: str = "paired_semantic",
) -> List[str]:
    """
    Resolve `n` semantic series colors for OriginPro / Chart Grammar layers:
      - `paired_semantic`: control/baseline -> paired blues, pulse/treatment -> paired reds,
        guaranteeing strong within-plot luminance & hue contrast.
      - `sandwich_stack`: bottom inert/baseline (slate/ice) -> middle conventional (indigo/blue)
        -> top active/dominant (pink/rose/wine).
      - `sequential_blue_red`: smooth monotonic ramp across
        `#C5DBF5 -> #6579BE -> #3E86DE -> #D84B5C -> #A02333` (ideal for >5 ordered curves).
    """
    if n < 0:
        raise ValueError(f"Series count n must be >= 0, got {n}")
    if n == 0:
        return []
    if scheme not in VALID_COLOR_SCHEMES:
        raise ValueError(f"Unsupported color scheme {scheme!r}; expected one of {VALID_COLOR_SCHEMES}")
    if roles is not None and len(roles) != n:
        raise ValueError(f"Length of roles ({len(roles)}) must match n ({n})")

    if scheme == "sequential_blue_red":
        if roles is not None:
            resolved = []
            base_seq = interpolate_color_stops(SEQUENTIAL_BLUE_RED_STOPS, n)
            for idx, r_hint in enumerate(roles):
                cls, val = _classify_semantic_role(r_hint)
                resolved.append(val if cls == "direct" and val else base_seq[idx])
            return resolved
        return interpolate_color_stops(SEQUENTIAL_BLUE_RED_STOPS, n)

    if scheme == "deep_blue_to_red":
        if roles is not None:
            resolved = []
            base_seq = interpolate_color_stops(DEEP_BLUE_TO_RED_STOPS, n)
            for idx, r_hint in enumerate(roles):
                cls, val = _classify_semantic_role(r_hint)
                resolved.append(val if cls == "direct" and val else base_seq[idx])
            return resolved
        return interpolate_color_stops(DEEP_BLUE_TO_RED_STOPS, n)

    if scheme == "pseudocolor_zero_white":
        return interpolate_color_stops(PSEUDOCOLOR_ZERO_WHITE_STOPS, n)

    if scheme == "diverging_blue_white_red":
        return interpolate_color_stops(DIVERGING_BLUE_WHITE_RED_STOPS, n)

    if scheme == "sandwich_stack":
        base_stack = (
            list(_SANDWICH_BY_COUNT[n])
            if n in _SANDWICH_BY_COUNT
            else interpolate_color_stops(SANDWICH_STACK_ORDERED, n)
        )
        if roles is None:
            return base_stack
        inert_pool = ["#A8C4E8", "#C2D8F2"]
        mid_pool = ["#6579BE", "#3E86DE"]
        top_pool = ["#D84B5C", "#A02333", "#E88B9C"]
        c_inert = c_mid = c_top = 0
        out_stack: List[str] = []
        for idx, r_hint in enumerate(roles):
            cls, val = _classify_semantic_role(r_hint)
            if cls == "direct" and val:
                out_stack.append(val)
            elif cls == "inert":
                out_stack.append(inert_pool[c_inert % len(inert_pool)])
                c_inert += 1
            elif cls in ("control", "middle"):
                out_stack.append(mid_pool[c_mid % len(mid_pool)])
                c_mid += 1
            elif cls == "pulse":
                out_stack.append(top_pool[c_top % len(top_pool)])
                c_top += 1
            else:
                out_stack.append(base_stack[idx])
        return out_stack

    # scheme == "paired_semantic"
    if roles is None:
        if n <= len(_PAIRED_INTERLEAVED):
            return list(_PAIRED_INTERLEAVED[:n])
        # Extend beyond 6 while keeping high adjacent contrast
        extra = interpolate_color_stops(SEQUENTIAL_BLUE_RED_STOPS, n - len(_PAIRED_INTERLEAVED))
        return list(_PAIRED_INTERLEAVED) + extra

    classified = [_classify_semantic_role(r) for r in roles]
    total_ctrl = sum(1 for c, _ in classified if c == "control")
    total_pulse = sum(1 for c, _ in classified if c == "pulse")

    # High-contrast within-family pools (never pale near-white on white paper)
    ctrl_pool = ["#7BA8E0", "#2B6CB0", "#6579BE"] if total_ctrl >= 2 and total_pulse == 0 else ["#2B6CB0", "#3E86DE", "#6579BE"]
    pulse_pool = ["#E07A8C", "#A02333", "#D84B5C"] if total_pulse >= 2 and total_ctrl == 0 else ["#D84B5C", "#A02333", "#E07A8C"]
    inert_pool = ["#9BB8E0", "#B5CCE8"]

    i_ctrl = i_pulse = i_inert = i_auto = 0
    colors: List[str] = []
    for cls, mod in classified:
        if cls == "direct" and mod:
            colors.append(mod)
        elif cls == "inert":
            colors.append(inert_pool[i_inert % len(inert_pool)])
            i_inert += 1
        elif cls == "control":
            if mod == "light":
                colors.append("#7BA8E0")
            elif mod == "strong":
                colors.append("#2B6CB0" if "#2B6CB0" not in colors else "#6579BE")
            else:
                colors.append(ctrl_pool[i_ctrl % len(ctrl_pool)])
                i_ctrl += 1
        elif cls == "pulse":
            if mod == "light":
                colors.append("#E07A8C")
            elif mod == "strong":
                colors.append("#A02333")
            else:
                colors.append(pulse_pool[i_pulse % len(pulse_pool)])
                i_pulse += 1
        else:
            colors.append(_PAIRED_INTERLEAVED[i_auto % len(_PAIRED_INTERLEAVED)])
            i_auto += 1
    return colors


# ---------------------------------------------------------------------------
# Unified Publication Layout & Typography Spec (Single Source of Truth)
# ---------------------------------------------------------------------------
UNIFIED_SPEC: Dict[str, Any] = {
    # Family A: Standard 4:3 Rectangular Single Panel -> 3120 x 2340 px @ 300 DPI (exact 4:3 outer & inner!)
    "page_rect_w_in": 10.40,
    "page_rect_h_in": 7.80,
    "box_rect_left_in": 2.15,
    "box_rect_top_in": 0.95,
    "box_rect_w_in": 6.40,
    "box_rect_h_in": 4.80,
    # Family B: 1:1 Square Single Panel (EIS, DRT Contour, Heatmap) -> 2700 x 2340 px @ 300 DPI
    # Shares EXACT SAME height (7.80 in), left (2.15 in), top (0.95 in), and bottom (5.75 in) as Family A!
    "page_sq_w_in": 9.00,
    "page_sq_h_in": 7.80,
    "box_sq_left_in": 2.15,
    "box_sq_top_in": 0.95,
    "box_sq_side_in": 4.80,
    # Bode Dual-Panel (total top..bottom = 0.95 .. 5.75 in = 4.80 in, aligned 0 px with Family A & B!)
    "bode_top_in": 0.95,
    "bode_sub_h_in": 2.22,
    "bode_gap_in": 0.36,
    # Default Typography & Font Profile (Preset 1: Times New Roman Bold 28/24/22/22 pt)
    "font_family": "Times New Roman",
    "bold": True,
    "bold_int": 1,
    "axis_title_pt": 28.0,
    "tick_label_pt": 24.0,
    "legend_pt": 22.0,
    "callout_pt": 22.0,
    "inset_tick_pt": 15.0,
    "inset_title_pt": 16.0,
    # Unified Stroke Hierarchy & 2D Pure Markers
    "box_lw_pt": 3.0,
    "curve_lw_pt": 3.0,
    "curve_w_units": 1500,
    "sub_lw_pt": 1.6,
    "sub_w_units": 800,
    "inset_box_lw_pt": 2.0,
    "bar_border_lw_pt": 1.5,
    "pastel_fill_weight": 0.36,
    "marker_cmd_2d": 2,  # Origin `-k 2`: pure 2D circle (interior 1=solid, 2=open white)
    "marker_size_pt": 7.5,
    "inset_marker_size_pt": 5.0,
}


def resolve_runtime_spec(theme_or_name: Optional[Dict[str, Any] | str | Path] = None) -> Dict[str, Any]:
    """
    Resolve a complete runtime layout/typography/stroke specification dictionary from either:
      - `None` -> `style_publication_minimal` (Times New Roman Bold, 3.0pt box, 3.0pt curves, 28/24/22/22 pt)
      - `"style_arial_clean"` / `"arial"` -> Arial Regular, 1.5pt box, 2.0pt curves, 28/24/22/22 pt
      - Any loaded theme dictionary from `load_theme(...)`
    """
    spec = copy.deepcopy(UNIFIED_SPEC)
    if theme_or_name is None:
        return spec
    th = theme_or_name if isinstance(theme_or_name, dict) else load_theme(theme_or_name)
    on = th.get("origin_native") or {}

    fam = str(th.get("font_family") or spec["font_family"]).strip()
    wt = str(th.get("font_weight") or "bold").strip().lower()
    is_bold = wt in ("bold", "700", "800", "900", "semibold", "demi")
    box_lw = float(th.get("figure_box_linewidth", on.get("box_linewidth_pt", spec["box_lw_pt"])))
    curve_lw = float(th.get("curve_linewidth", spec["curve_lw_pt"]))
    curve_w = int(round(float(on.get("curve_w", curve_lw * 500.0))))
    sub_lw = float(th.get("guide_linewidth", max(1.1, round(curve_lw * 0.56, 2))))
    sub_w = int(round(float(on.get("component_w", sub_lw * 500.0))))
    inset_lw = float(th.get("inset_box_linewidth", on.get("inset_box_linewidth_pt", max(1.0, round(box_lw * 0.67, 2)))))

    spec.update(
        {
            "preset_id": str(th.get("preset_id") or DEFAULT_STYLE_PRESET),
            "font_family": fam,
            "bold": is_bold,
            "bold_int": 1 if is_bold else 0,
            "box_lw_pt": box_lw,
            "curve_lw_pt": curve_lw,
            "curve_w_units": curve_w,
            "sub_lw_pt": sub_lw,
            "sub_w_units": sub_w,
            "inset_box_lw_pt": inset_lw,
            "bar_border_lw_pt": float(on.get("bar_border_linewidth_pt", spec["bar_border_lw_pt"])),
            "axis_title_pt": float(th.get("axis_label_size", on.get("axis_title_pt", spec["axis_title_pt"]))),
            "tick_label_pt": float(th.get("tick_label_size", on.get("tick_label_pt", spec["tick_label_pt"]))),
            "legend_pt": float(th.get("title_annot_size", on.get("legend_pt", spec["legend_pt"]))),
            "callout_pt": float(th.get("callout_font_size", on.get("value_label_pt", spec["callout_pt"]))),
            "inset_tick_pt": float(on.get("inset_tick_label_pt", spec["inset_tick_pt"])),
            "page_rect_w_in": float(on.get("page_rect_w_in", spec["page_rect_w_in"])),
            "page_rect_h_in": float(on.get("page_rect_h_in", spec["page_rect_h_in"])),
            "box_rect_left_in": float(on.get("box_rect_left_in", spec["box_rect_left_in"])),
            "box_rect_top_in": float(on.get("box_rect_top_in", spec["box_rect_top_in"])),
            "box_rect_w_in": float(on.get("box_rect_w_in", spec["box_rect_w_in"])),
            "box_rect_h_in": float(on.get("box_rect_h_in", spec["box_rect_h_in"])),
            "page_sq_w_in": float(on.get("page_sq_w_in", spec["page_sq_w_in"])),
            "page_sq_h_in": float(on.get("page_sq_h_in", spec["page_sq_h_in"])),
            "box_sq_left_in": float(on.get("box_sq_left_in", spec["box_sq_left_in"])),
            "box_sq_top_in": float(on.get("box_sq_top_in", spec["box_sq_top_in"])),
            "box_sq_side_in": float(on.get("box_sq_side_in", spec["box_sq_side_in"])),
            "marker_size_pt": float(on.get("marker_size_pt", spec["marker_size_pt"])),
        }
    )
    return spec


def rect_in_to_page_pct(
    left_in: float, top_in: float, width_in: float, height_in: float, page_w_in: float, page_h_in: float
) -> Tuple[float, float, float, float]:
    """Convert physical inch layer bounds into exact Page-% coordinates."""
    return (
        (float(left_in) / float(page_w_in)) * 100.0,
        (float(top_in) / float(page_h_in)) * 100.0,
        (float(width_in) / float(page_w_in)) * 100.0,
        (float(height_in) / float(page_h_in)) * 100.0,
    )


def compensate_origin_layer_pt(
    target_true_pt: float, lw_in: float, lh_in: float, pw_in: float, ph_in: float
) -> float:
    """
    Compensate Origin's automatic sub-layer font downscaling (`scale ~ sqrt(layer_area/page_area) / 0.93`)
    so native `layer.x.label.pt` / `layer.y.label.pt` render at the exact same pixel height as `gl_ov` true points.
    """
    area_ratio = (max(0.35, float(lw_in)) * max(0.35, float(lh_in))) / (
        max(2.0, float(pw_in)) * max(2.0, float(ph_in))
    )
    scale_fac = min(1.0, math.sqrt(area_ratio) / 0.93)
    return round(float(target_true_pt) / max(0.12, scale_fac), 2)


def compute_pastel_fill_and_border(
    hex_color: str, pastel_weight: Optional[float] = None
) -> Dict[str, str]:
    """
    Unified Bar / Stacked-Bar / Boxplot / Band visual language:
    Returns `{'fill_hex': luminous_pastel, 'border_hex': crisp_deep_stroke, 'label_hex': crisp_deep_stroke}`.
    """
    pw = float(UNIFIED_SPEC["pastel_fill_weight"] if pastel_weight is None else pastel_weight)
    primary = normalize_hex(hex_color)
    lum = relative_luminance(primary)
    r, g, b = parse_hex_rgb(primary)
    is_warm = (r > b) and (r > g)
    if lum >= 0.52:
        anchor = SEMANTIC_PALETTE["rose"] if is_warm else SEMANTIC_PALETTE["blue"]
        border_hex = mix_hex(primary, anchor, 0.55)
    else:
        border_hex = primary
    fill_hex = mix_hex("#FFFFFF", border_hex, pw)
    return {
        "fill_hex": fill_hex,
        "border_hex": border_hex,
        "label_hex": border_hex,
    }


def compute_gradient_pair_and_label_color(
    hex_color: str,
    light_luminance_threshold: float = 0.65,
) -> GradientLabelColors:
    """
    Compute vertical bar gradient `(top_hex, bottom_hex, label_hex)`:
      - Dark/medium bar (`luminance < 0.65`):
        top = `hex_color`, bottom = mixed with 34% `#FFFFFF` (visible pastel base, never vanishing), label = `hex_color`.
      - Light/pastel bar (`luminance >= 0.65`):
        top = deepened with 35% semantic accent, bottom = mixed with 22% `#FFFFFF` so the bar silhouette
        remains crisp from top to bottom on white paper backgrounds.
    """
    primary = normalize_hex(hex_color)
    r, g, b = parse_hex_rgb(primary)
    lum = relative_luminance(primary)
    is_warm = (r > b) and (r > g)

    if lum < light_luminance_threshold:
        top_hex = primary
        bottom_hex = mix_hex(primary, "#FFFFFF", 0.34)
        label_hex = primary
    else:
        accent_bottom = SEMANTIC_PALETTE["rose"] if is_warm else SEMANTIC_PALETTE["blue"]
        top_hex = mix_hex(primary, accent_bottom, 0.35)
        bottom_hex = mix_hex(primary, "#FFFFFF", 0.22)
        label_anchor = SEMANTIC_PALETTE["wine"] if is_warm else SEMANTIC_PALETTE["blue"]
        stepped = mix_hex(primary, label_anchor, 0.48)
        if relative_luminance(stepped) > 0.56:
            stepped = mix_hex(stepped, SEMANTIC_PALETTE["ink"], 0.25)
        label_hex = stepped

    return GradientLabelColors(top_hex=top_hex, bottom_hex=bottom_hex, label_hex=label_hex)


def resolve_axis_tick_policy(
    axis_kind: str,
    scale: str = "linear",
    *,
    right_axis_color: str = "#3E86DE",
    left_axis_color: str = "#111111",
    box_linewidth_pt: float = 3.0,
) -> Dict[str, Any]:
    """
    Enforce the publication-minimal axis tick decision matrix:
      - `intensity_arbitrary`: turn OFF left-Y ticks & tick labels; keep inward bottom-X major ticks.
      - `categorical`: turn OFF bottom-X tick lines (keep semantic labels); turn ON inward left-Y major ticks.
      - `quantitative`: turn ON inward bottom-X & left-Y major ticks; enable inward minor ticks ONLY when `scale == "log10"`.
      - `dual_y_left` / `dual_y_right`: turn ON inward major ticks on both left & right Y, turn OFF minor ticks,
        suppress overlapping right spine on layer 1 (`y.showAxes=1`), and bind right-Y axis/label color.
      - `inset`: sparse inward major ticks (`max_major_ticks=4`) + `1.6pt` closed frame + opaque `#FFFFFF` fill.
    """
    kind = str(axis_kind).strip().lower()
    if kind not in VALID_AXIS_KINDS:
        raise ValueError(f"Unsupported axis_kind {axis_kind!r}; expected one of {VALID_AXIS_KINDS}")

    sc = str(scale).strip().lower()
    if sc == "log":
        sc = "log10"
    if sc not in VALID_AXIS_SCALES:
        raise ValueError(f"Unsupported scale {scale!r}; expected one of {VALID_AXIS_SCALES}")

    is_log = sc == "log10"
    origin_scale_type = 2 if is_log else 1  # Origin LabTalk: 1 = Linear, 2 = Log10
    left_hex = normalize_hex(left_axis_color)
    right_hex = normalize_hex(right_axis_color)

    if kind == "intensity_arbitrary":
        bt = float(box_linewidth_pt)
        minor_flag = 1 if is_log else 0
        return {
            "axis_kind": kind,
            "scale": sc,
            "box_linewidth_pt": bt,
            "tick_direction": "in",
            "x_major_ticks": "in",
            "x_minor_ticks": is_log,
            "x_tick_labels": True,
            "y_major_ticks": "none",
            "y_minor_ticks": False,
            "y_tick_labels": False,
            "top_ticks": False,
            "right_ticks": False,
            "show_minor_ticks": is_log,
            "axis_color": left_hex,
            "axis_color_origin_int": hex_to_origin_rgb_int(left_hex),
            "origin": {
                "x_show_axes": 3,
                "y_show_axes": 3,
                "x_ticks": 1,
                "x_show_minor": minor_flag,
                "x_show_labels": 1,
                "y_ticks": 0,
                "y_show_minor": 0,
                "y_show_labels": 0,
                "x2_ticks": 0,
                "y2_ticks": 0,
                "scale_type": origin_scale_type,
                "lt_snippet": (
                    f"layer.x.showAxes=3; layer.y.showAxes=3; "
                    f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
                    f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
                    f"layer.x.ticks=1; layer.x.showMinorTicks={minor_flag}; "
                    f"layer.y.ticks=0; layer.y.showMinorTicks=0; layer.y.showLabels=0; "
                    f"layer.x2.ticks=0; layer.y2.ticks=0;"
                ),
            },
        }

    if kind == "categorical":
        bt = float(box_linewidth_pt)
        y_minor_flag = 1 if is_log else 0
        return {
            "axis_kind": kind,
            "scale": sc,
            "box_linewidth_pt": bt,
            "tick_direction": "in",
            "x_major_ticks": "none",
            "x_minor_ticks": False,
            "x_tick_labels": True,
            "y_major_ticks": "in",
            "y_minor_ticks": is_log,
            "y_tick_labels": True,
            "top_ticks": False,
            "right_ticks": False,
            "show_minor_ticks": is_log,
            "axis_color": left_hex,
            "axis_color_origin_int": hex_to_origin_rgb_int(left_hex),
            "origin": {
                "x_show_axes": 3,
                "y_show_axes": 3,
                "x_ticks": 0,
                "x_show_minor": 0,
                "x_show_labels": 1,
                "y_ticks": 1,
                "y_show_minor": y_minor_flag,
                "y_show_labels": 1,
                "x2_ticks": 0,
                "y2_ticks": 0,
                "scale_type": origin_scale_type,
                "lt_snippet": (
                    f"layer.x.showAxes=3; layer.y.showAxes=3; "
                    f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
                    f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
                    f"layer.x.ticks=0; layer.x.showMinorTicks=0; "
                    f"layer.y.ticks=1; layer.y.showMinorTicks={y_minor_flag}; layer.y.showLabels=1; "
                    f"layer.x2.ticks=0; layer.y2.ticks=0;"
                ),
            },
        }

    if kind == "quantitative":
        bt = float(box_linewidth_pt)
        minor_flag = 1 if is_log else 0
        return {
            "axis_kind": kind,
            "scale": sc,
            "box_linewidth_pt": bt,
            "tick_direction": "in",
            "x_major_ticks": "in",
            "x_minor_ticks": is_log,
            "x_tick_labels": True,
            "y_major_ticks": "in",
            "y_minor_ticks": is_log,
            "y_tick_labels": True,
            "top_ticks": False,
            "right_ticks": False,
            "show_minor_ticks": is_log,
            "axis_color": left_hex,
            "axis_color_origin_int": hex_to_origin_rgb_int(left_hex),
            "origin": {
                "x_show_axes": 3,
                "y_show_axes": 3,
                "x_ticks": 1,
                "x_show_minor": minor_flag,
                "x_show_labels": 1,
                "y_ticks": 1,
                "y_show_minor": minor_flag,
                "y_show_labels": 1,
                "x2_ticks": 0,
                "y2_ticks": 0,
                "scale_type": origin_scale_type,
                "lt_snippet": (
                    f"layer.x.showAxes=3; layer.y.showAxes=3; "
                    f"layer.x.thickness={bt}; layer.y.thickness={bt}; "
                    f"layer.x2.thickness={bt}; layer.y2.thickness={bt}; "
                    f"layer.x.ticks=1; layer.x.showMinorTicks={minor_flag}; "
                    f"layer.y.ticks=1; layer.y.showMinorTicks={minor_flag}; "
                    f"layer.x2.ticks=0; layer.y2.ticks=0;"
                ),
            },
        }

    if kind == "dual_y_left":
        bt = float(box_linewidth_pt)
        c_left_int = hex_to_origin_rgb_int(left_hex)
        return {
            "axis_kind": kind,
            "scale": sc,
            "box_linewidth_pt": bt,
            "tick_direction": "in",
            "x_major_ticks": "in",
            "x_minor_ticks": False,
            "x_tick_labels": True,
            "y_major_ticks": "in",
            "y_minor_ticks": False,
            "y_tick_labels": True,
            "y2_major_ticks": "in",
            "y2_minor_ticks": False,
            "top_ticks": False,
            "right_ticks": True,
            "show_minor_ticks": False,
            "bind_right_axis_color": True,
            "axis_color": left_hex,
            "axis_color_origin_int": c_left_int,
            "right_axis_color": right_hex,
            "right_axis_color_origin_int": hex_to_origin_rgb_int(right_hex),
            "align_zero": True,
            "origin": {
                "x_show_axes": 3,
                "y_show_axes": 1,  # Only left spine on Layer 1 so Layer 2 owns colored right Y spine
                "x_ticks": 1,
                "x_show_minor": 0,
                "y_ticks": 1,
                "y_show_minor": 0,
                "y_show_labels": 1,
                "x2_ticks": 0,
                "scale_type": origin_scale_type,
                "lt_snippet": (
                    f"layer.x.showAxes=3; layer.y.showAxes=1; "
                    f"layer.x.thickness={bt}; layer.x2.thickness={bt}; layer.y.thickness={bt}; "
                    f"layer.x.ticks=1; layer.x.showMinorTicks=0; layer.x2.ticks=0; "
                    f"layer.y.ticks=1; layer.y.showMinorTicks=0; "
                    f"layer.y.color={c_left_int}; layer.y.label.color={c_left_int}; YL.color={c_left_int};"
                ),
            },
        }

    if kind == "dual_y_right":
        bt = float(box_linewidth_pt)
        c_right_int = hex_to_origin_rgb_int(right_hex)
        return {
            "axis_kind": kind,
            "scale": sc,
            "box_linewidth_pt": bt,
            "tick_direction": "in",
            "y_major_ticks": "in",
            "y_minor_ticks": False,
            "y2_major_ticks": "in",
            "y2_minor_ticks": False,
            "y2_tick_labels": True,
            "top_ticks": False,
            "right_ticks": True,
            "show_minor_ticks": False,
            "bind_right_axis_color": True,
            "axis_color": right_hex,
            "axis_color_origin_int": c_right_int,
            "right_axis_color": right_hex,
            "right_axis_color_origin_int": c_right_int,
            "align_zero": True,
            "origin": {
                "layer_add_type": 2,  # gp.add_layer(2) -> linked Right-Y layer
                "y2_ticks": 1,
                "y2_show_minor": 0,
                "y2_show_labels": 1,
                "scale_type": origin_scale_type,
                "lt_snippet": (
                    f"layer.y.thickness={bt}; layer.y2.thickness={bt}; "
                    f"layer.y.ticks=1; layer.y2.ticks=1; "
                    f"layer.y.showMinorTicks=0; layer.y2.showMinorTicks=0; "
                    f"layer.y.color={c_right_int}; layer.y2.color={c_right_int}; "
                    f"layer.y.label.color={c_right_int}; layer.y2.label.color={c_right_int}; "
                    f"YR.color={c_right_int}; Legend.show=0;"
                ),
            },
        }

    # kind == "inset"
    inset_bt = 1.6
    minor_flag = 1 if is_log else 0
    white_int = hex_to_origin_rgb_int("#FFFFFF")
    return {
        "axis_kind": "inset",
        "scale": sc,
        "box_linewidth_pt": inset_bt,
        "tick_direction": "in",
        "x_major_ticks": "in",
        "x_minor_ticks": is_log,
        "x_tick_labels": True,
        "y_major_ticks": "in",
        "y_minor_ticks": is_log,
        "y_tick_labels": True,
        "sparse_major_ticks": True,
        "max_major_ticks": 4,
        "top_ticks": False,
        "right_ticks": False,
        "show_minor_ticks": is_log,
        "omit_redundant_axis_titles": True,
        "background_color": "#FFFFFF",
        "axis_color": left_hex,
        "axis_color_origin_int": hex_to_origin_rgb_int(left_hex),
        "origin": {
            "layer_add_type": 6,  # gp.add_layer(6) -> linked inset
            "layer_unit": 7,      # % of Linked Parent Layer (never unit=2 inches!)
            "background_origin_int": white_int,
            "x_show_axes": 3,
            "y_show_axes": 3,
            "x_ticks": 1,
            "y_ticks": 1,
            "x_show_minor": minor_flag,
            "y_show_minor": minor_flag,
            "x2_ticks": 0,
            "y2_ticks": 0,
            "tick_label_pt": 15,
            "scale_type": origin_scale_type,
            "lt_snippet": (
                f"layer.unit=7; layer.color={white_int}; "
                f"layer.x.showAxes=3; layer.y.showAxes=3; "
                f"layer.x.thickness={inset_bt}; layer.y.thickness={inset_bt}; "
                f"layer.x2.thickness={inset_bt}; layer.y2.thickness={inset_bt}; "
                f"layer.x.ticks=1; layer.y.ticks=1; "
                f"layer.x.showMinorTicks={minor_flag}; layer.y.showMinorTicks={minor_flag}; "
                f"layer.x2.ticks=0; layer.y2.ticks=0; "
                f"layer.x.label.pt=15; layer.y.label.pt=15; Legend.show=0;"
            ),
        },
    }


def _pack_riff_pal_256(rgbs_256: Sequence[Tuple[int, int, int]], out_path: str | Path) -> str:
    """
    Write a standard 1052-byte Microsoft/OriginPro 256-entry RIFF `.pal` binary file:
      - 12B RIFF header: b'RIFF' + uint32(1044) + b'PAL '
      - 12B LOGPALETTE header: b'data' + uint32(1032) + uint16(0x0300) + uint16(256)
      - 1024B PALETTEENTRY[256]: 256 * <BBBB(r, g, b, 0)
      - 4B LOGPALETTE trailing struct pad: b'\\x00\\x00\\x00\\x00'
      Total = 12 + 12 + 1024 + 4 = 1052 bytes (matches OriginPro native Palettes/*.PAL).
    """
    if len(rgbs_256) != 256:
        raise ValueError(f"RIFF .pal requires 256 RGB slots, got {len(rgbs_256)}")
    p = Path(out_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    entries = b"".join(
        struct.pack("<BBBB", max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), 0)
        for r, g, b in rgbs_256
    )
    trailing_pad = b"\x00\x00\x00\x00"
    data_payload = struct.pack("<HH", 0x0300, 256) + entries + trailing_pad  # 4 + 1024 + 4 = 1032B
    data_chunk = struct.pack("<4sI", b"data", len(data_payload)) + data_payload  # 8 + 1032 = 1040B
    riff_bytes = struct.pack("<4sI4s", b"RIFF", 4 + len(data_chunk), b"PAL ") + data_chunk  # 12 + 1040 = 1052B
    p.write_bytes(riff_bytes)
    return str(p)


def write_discrete_riff_pal(path: str | Path, hex_list: Sequence[str]) -> str:
    """
    Generate a 1052-byte discrete Microsoft RIFF `.pal` cycling `hex_list` across 256 slots
    for Origin `STACKCOLUMN` / `StackColP` / `COLUMN` (`plot1.colorlist` with `stretchpal=0`).
    """
    if not hex_list:
        raise ValueError("hex_list must contain at least one color.")
    parsed = [parse_hex_rgb(c) for c in hex_list]
    rgbs_256 = [parsed[i % len(parsed)] for i in range(256)]
    return _pack_riff_pal_256(rgbs_256, path)


def write_continuous_riff_pal(
    path: str | Path,
    hex_stops: Sequence[str],
    n_colors: int = 256,
) -> str:
    """
    Generate a 1052-byte continuous (or `n_colors`-quantized) Microsoft RIFF `.pal`
    interpolated across `hex_stops` for Origin 2D `CONTOUR` / `HeatMap` (`p.colormap`).
    """
    if not hex_stops or len(hex_stops) < 2:
        raise ValueError("hex_stops must contain at least 2 color stops for continuous interpolation.")
    if n_colors < 2 or n_colors > 256:
        raise ValueError(f"n_colors must be in [2, 256], got {n_colors}")

    ramp_hex = interpolate_color_stops(hex_stops, n_colors)
    ramp_rgb = [parse_hex_rgb(c) for c in ramp_hex]
    if n_colors == 256:
        rgbs_256 = ramp_rgb
    else:
        rgbs_256 = [ramp_rgb[min(n_colors - 1, (i * n_colors) // 256)] for i in range(256)]
    return _pack_riff_pal_256(rgbs_256, path)


def compute_optimal_bar_spacing(n_categories: int, n_series: int = 1) -> Dict[str, int]:
    """
    Compute optimal OriginPro bar gap/overlap/grad_lightness settings to prevent
    over-fat single bars while keeping multi-series grouped bars with breathing space.

    Returns:
        dict with keys: "gap" (int), "overlap" (int), "grad_lightness" (int)

    Gap rules (n_categories):
        <= 2  -> gap=50  (防过胖)
        == 3  -> gap=38
        == 4  -> gap=28
        >= 5  -> gap=20

    n_series >= 2 (grouped clusters):
        overlap=-18  (留白呼吸缝)
        grad_lightness=85
    """
    nc = max(1, int(n_categories))
    ns = max(1, int(n_series))

    if nc <= 2:
        gap = 50
    elif nc == 3:
        gap = 38
    elif nc == 4:
        gap = 28
    else:
        gap = 20

    if ns >= 2:
        overlap = -18
        grad_lightness = 85
    else:
        overlap = 0
        grad_lightness = 80

    return {"gap": gap, "overlap": overlap, "grad_lightness": grad_lightness}


_FILE_EXT_RE = re.compile(
    r"\s*\(\.(?:ndax|nda|bin|mpt|dta|csv|txt|xlsx?)\)\s*$",
    re.IGNORECASE,
)

def clean_semantic_sample_name(name: str, enabled: bool = True) -> str:
    """
    Strip redundant 'A: ' / 'B: ' sample prefixes and trailing file extension
    suffixes like (.ndax) / (.nda) / (.bin) / (.mpt) / (.dta) while preserving
    semantic names.
    """
    text = str(name or "").strip()
    if not enabled:
        return text
    text = _FILE_EXT_RE.sub("", text)
    return _SAMPLE_PREFIX_RE.sub("", text)


def format_generic_sample_labels(count: int, prefix: str = "Sample") -> List[str]:
    """Generate clean sequential generic labels `['Sample 1', 'Sample 2', ...]`."""
    pfx = str(prefix or "Sample").strip()
    return [f"{pfx} {i + 1}" for i in range(max(0, int(count)))]


_GREEK_LATEX_TO_ORIGIN: Tuple[Tuple[str, str], ...] = (
    ("\\Gamma", "\\g(G)"),
    ("\\Delta", "\\g(D)"),
    ("\\Theta", "\\g(Q)"),
    ("\\Lambda", "\\g(L)"),
    ("\\Pi", "\\g(P)"),
    ("\\Sigma", "\\g(S)"),
    ("\\Phi", "\\g(F)"),
    ("\\Psi", "\\g(Y)"),
    ("\\Omega", "\\g(W)"),
    ("\\varepsilon", "\\g(e)"),
    ("\\vartheta", "\\g(q)"),
    ("\\varphi", "\\g(f)"),
    ("\\alpha", "\\g(a)"),
    ("\\beta", "\\g(b)"),
    ("\\gamma", "\\g(g)"),
    ("\\delta", "\\g(d)"),
    ("\\epsilon", "\\g(e)"),
    ("\\eta", "\\g(h)"),
    ("\\theta", "\\g(q)"),
    ("\\kappa", "\\g(k)"),
    ("\\lambda", "\\g(l)"),
    ("\\mu", "\\g(m)"),
    ("\\nu", "\\g(n)"),
    ("\\pi", "\\g(p)"),
    ("\\rho", "\\g(r)"),
    ("\\sigma", "\\g(s)"),
    ("\\tau", "\\g(t)"),
    ("\\phi", "\\g(f)"),
    ("\\chi", "\\g(c)"),
    ("\\psi", "\\g(y)"),
    ("\\omega", "\\g(w)"),
)

_GREEK_UNICODE_TO_ORIGIN: Tuple[Tuple[str, str], ...] = (
    ("Γ", "\\g(G)"),
    ("Δ", "\\g(D)"),
    ("Θ", "\\g(Q)"),
    ("Λ", "\\g(L)"),
    ("Π", "\\g(P)"),
    ("Σ", "\\g(S)"),
    ("Φ", "\\g(F)"),
    ("Ψ", "\\g(Y)"),
    ("Ω", "\\g(W)"),
    ("α", "\\g(a)"),
    ("β", "\\g(b)"),
    ("γ", "\\g(g)"),
    ("δ", "\\g(d)"),
    ("ε", "\\g(e)"),
    ("η", "\\g(h)"),
    ("θ", "\\g(q)"),
    ("κ", "\\g(k)"),
    ("λ", "\\g(l)"),
    ("μ", "\\g(m)"),
    ("µ", "\\g(m)"),
    ("ν", "\\g(n)"),
    ("π", "\\g(p)"),
    ("ρ", "\\g(r)"),
    ("σ", "\\g(s)"),
    ("τ", "\\g(t)"),
    ("φ", "\\g(f)"),
    ("χ", "\\g(c)"),
    ("ψ", "\\g(y)"),
    ("ω", "\\g(w)"),
)


def format_origin_axis_title(label: str, bold: bool = True) -> str:
    """
    Convert plain/LaTeX scientific axis titles into Origin native GraphObject rich text.
    Special conversions (in order):
      - '2theta' / '2\theta' -> '2\g(q)'  (number-prefixed: bypasses word-boundary)
      - '(\mu m)' / Unicode mu -> '(\g(m)m)'
      - Z' / -Z'' -> italic \i(Z') / -\i(Z'')
      - g-factor -> \i(g)-factor
      - I_D/I_G, A_D/A_G -> \i(I)\-(D) / \i(I)\-(G)
    """
    s = str(label or "").strip()
    if not s:
        return ""
    s = s.replace("$", "").replace("\\ ", " ")

    # Unwrap LaTeX font macros from inside out
    for _ in range(4):
        updated = re.sub(r"\\(?:mathrm|text|mathbf|mathit|mathsf)\{([^{}]*)\}", r"\1", s)
        if updated == s:
            break
        s = updated
    s = re.sub(r"\\(?:mathrm|text|mathbf|mathit|mathsf)\b", "", s)
    s = re.sub(r"\\(log|ln|sin|cos|tan|exp)\b", r"\1", s)

    # 2theta / 2\theta -> 2\g(q)   (number-prefix safe: use group ref in lambda)
    def _sub_2theta_plain(m):
        return m.group(1) + r"\g(q)"
    s = re.sub(r"(\b2)\s*theta\b", _sub_2theta_plain, s, flags=re.IGNORECASE)
    def _sub_2theta_latex(m):
        return m.group(1) + r"\g(q)"
    s = re.sub(r"(\b2)\s*\\theta\b", _sub_2theta_latex, s)

    # (\mu m) / Unicode mu -> (\g(m)m)
    s = re.sub(r"\(\\mu\s*m\)", r"(\\g(m)m)", s)
    s = re.sub(r"\([\xb5\u03bc]m\)", r"(\\g(m)m)", s)

    # Impedance italic: -Z'' then Z' (order matters)
    s = re.sub(r"(?<![A-Za-z\\])-Z''", r"-\\i(Z'')", s)
    s = re.sub(r"(?<![A-Za-z\\])Z'(?!')", r"\\i(Z')", s)

    # g-factor
    s = re.sub(r"\bg-factor\b", r"\\i(g)-factor", s)

    # I_D / I_G, A_D / A_G -> italic stem + subscript
    def _sub_I_dg(m):
        return r"\i(I)" + r"\-(" + m.group(1) + ")"
    s = re.sub(r"\bI_([DG])\b", _sub_I_dg, s)
    def _sub_A_dg(m):
        return r"\i(A)" + r"\-(" + m.group(1) + ")"
    s = re.sub(r"\bA_([DG])\b", _sub_A_dg, s)

    # Greek tokens (from module-level lookup tables)
    for latex_tok, orig_sym in _GREEK_LATEX_TO_ORIGIN:
        s = re.sub(rf"{re.escape(latex_tok)}(?![A-Za-z])", lambda _, rep=orig_sym: rep, s)
    for uni_ch, orig_sym in _GREEK_UNICODE_TO_ORIGIN:
        s = s.replace(uni_ch, orig_sym)
    s = re.sub(r"\bDelta\s+(?=[A-Za-z])", lambda _: r"\g(D)", s)
    s = re.sub(r"\b(tau)\b", lambda _: r"\g(t)", s)
    s = re.sub(r"\b(gamma)\b", lambda _: r"\g(g)", s)
    # theta only when NOT preceded by a digit (preserve "2\g(q)" already substituted above)
    s = re.sub(r"(?<!\d)\b(theta)\b", lambda _: r"\g(q)", s)

    # Normalize multi-part subscript tokens
    s = s.replace("pulse_end", "pulse,end")

    # Superscripts
    s = re.sub(r"\^\{([^{}]+)\}", r"\\+(\1)", s)
    s = re.sub(r"\^([+-]?\d+[+-]?|[+-])", r"\\+(\1)", s)

    # Subscripts
    s = re.sub(r"_\{([^{}]+)\}", r"\\-(\1)", s)
    s = re.sub(r"\b([A-Za-z0-9]+)_([A-Za-z0-9,+-]+)\b", r"\1\\-(\2)", s)

    s = re.sub(r"\{\s*([^{}]*)\s*\}", r"\1", s)
    if bold and not s.startswith("\\b("):
        return f"\\b({s})"
    return s


def load_theme(preset_name_or_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """
    Load an OriginPro visual theme preset dictionary.
    Defaults to `style_publication_minimal.json` while retaining full compatibility
    with `style_academic_acs_nature.json` and explicit `.json` file paths.
    """
    default_file = PRESET_DIR / f"{DEFAULT_STYLE_PRESET}.json"
    if not default_file.exists():
        raise FileNotFoundError(f"Default theme preset missing: {default_file}")
    base_theme: Dict[str, Any] = json.loads(default_file.read_text(encoding="utf-8"))

    if preset_name_or_path is None or str(preset_name_or_path).strip() == "":
        return copy.deepcopy(base_theme)

    raw_spec = str(preset_name_or_path).strip()
    alias_map = {
        "style_publication_minimal": PRESET_DIR / "style_publication_minimal.json",
        "publication_minimal": PRESET_DIR / "style_publication_minimal.json",
        "minimal": PRESET_DIR / "style_publication_minimal.json",
        "times": PRESET_DIR / "style_publication_minimal.json",
        "tnr": PRESET_DIR / "style_publication_minimal.json",
        "style_arial_clean": PRESET_DIR / "style_arial_clean.json",
        "arial_clean": PRESET_DIR / "style_arial_clean.json",
        "style_arial": PRESET_DIR / "style_arial_clean.json",
        "arial": PRESET_DIR / "style_arial_clean.json",
        "style_academic_acs_nature": PRESET_DIR / "style_academic_acs_nature.json",
        "academic_acs_nature": PRESET_DIR / "style_academic_acs_nature.json",
        "acs_nature": PRESET_DIR / "style_academic_acs_nature.json",
    }

    if raw_spec in alias_map:
        target = alias_map[raw_spec]
    else:
        cand = Path(raw_spec)
        if cand.is_absolute() and cand.exists():
            target = cand
        elif (PRESET_DIR / raw_spec).exists():
            target = PRESET_DIR / raw_spec
        elif (PRESET_DIR / f"{raw_spec}.json").exists():
            target = PRESET_DIR / f"{raw_spec}.json"
        elif cand.exists():
            target = cand.resolve()
        else:
            raise FileNotFoundError(f"Style preset not found: {preset_name_or_path}")

    loaded: Dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    if target.stem == DEFAULT_STYLE_PRESET:
        return copy.deepcopy(loaded)

    # Preserve all explicit settings while deep-merging structural sub-dicts (`origin_native`, `semantic_palette`, etc.)
    merged = copy.deepcopy(base_theme)
    if "minimal_axes" not in loaded:
        merged["minimal_axes"] = False
    merged["preset_id"] = target.stem
    for k, v in copy.deepcopy(loaded).items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


# Alias for drop-in compatibility with existing pipeline callers
load_style = load_theme
