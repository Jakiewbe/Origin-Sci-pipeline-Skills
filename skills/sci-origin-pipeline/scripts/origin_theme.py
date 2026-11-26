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

# Colorblind-safe categorical palette (Okabe-Ito, high-contrast on white ordered first)
OKABE_ITO_COLORS: List[str] = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
    "#222222",
    "#F0E442",
]

# Multi-cluster categorical palette for omics / ML / single-cell (Paul Tol Muted, 10 colors)
TOL_MUTED_COLORS: List[str] = [
    "#332288",
    "#88CCEE",
    "#44AA99",
    "#117733",
    "#999933",
    "#DDCC77",
    "#CC6677",
    "#882255",
    "#AA4499",
    "#6699CC",
]

# Perceptually uniform continuous scientific colormaps (8 stops each)
VIRIDIS_STOPS: List[str] = [
    "#440154",
    "#46327E",
    "#365C8D",
    "#277F8E",
    "#1FA187",
    "#4AC16D",
    "#A0DA39",
    "#FDE725",
]

CIVIDIS_STOPS: List[str] = [
    "#00204D",
    "#1F3B6D",
    "#46546C",
    "#686B70",
    "#8B8675",
    "#B1A471",
    "#D8C45C",
    "#FFEA46",
]

BATLOW_STOPS: List[str] = [
    "#011959",
    "#124260",
    "#30675D",
    "#5E7B50",
    "#9A8944",
    "#D8984C",
    "#F8B480",
    "#FACCFA",
]

# Perceptual diverging Crameri vik (#001260 -> #EAEDE9 -> #601200)
VIK_STOPS: List[str] = [
    "#001260",
    "#134B8A",
    "#71A7C4",
    "#EAEDE9",
    "#D29773",
    "#9C3B1A",
    "#601200",
]

# Perceptually uniform sequential magma
MAGMA_STOPS: List[str] = [
    "#000004",
    "#1D1147",
    "#51127C",
    "#832681",
    "#B73779",
    "#E75263",
    "#FC8961",
    "#FCFDBF",
]

_HEX_RE = re.compile(r"^#?(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$")
_SAMPLE_PREFIX_RE = re.compile(
    r"^[A-F]\s*:\s+(?=(?:Sample|Pristine|Control|Discharged|CF|\d+\s*C\b))"
)

VALID_COLOR_SCHEMES = (
    "paired_semantic",
    "sandwich_stack",
    "sequential_blue_red",
    "deep_blue_to_red",
    "pseudocolor_zero_white",
    "diverging_blue_white_red",
    "okabe_ito",
    "tol_muted",
    "viridis",
    "cividis",
    "batlow",
    "vik",
    "magma",
)

VALID_JOURNAL_SPECS = (
    "presentation_4_3",
    "nature_single_89mm",
    "nature_double_183mm",
    "science_single_55mm",
    "science_double_184mm",
    "cell_single_85mm",
    "cell_double_174mm",
    "acs_single_3.25in",
    "ieee_single_3.5in",
)

_JOURNAL_SPEC_ALIASES: Dict[str, str] = {
    "default": "presentation_4_3",
    "presentation": "presentation_4_3",
    "nature_single": "nature_single_89mm",
    "nature_double": "nature_double_183mm",
    "science_single": "science_single_55mm",
    "science_double": "science_double_184mm",
    "cell_single": "cell_single_85mm",
    "cell_double": "cell_double_174mm",
    "acs_single": "acs_single_3.25in",
    "ieee_single": "ieee_single_3.5in",
}

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

    if scheme in ("okabe_ito", "tol_muted"):
        discrete_pool = OKABE_ITO_COLORS if scheme == "okabe_ito" else TOL_MUTED_COLORS
        base_disc = [discrete_pool[i % len(discrete_pool)] for i in range(n)]
        if roles is not None:
            resolved_disc: List[str] = []
            for idx, r_hint in enumerate(roles):
                cls, val = _classify_semantic_role(r_hint)
                resolved_disc.append(val if cls == "direct" and val else base_disc[idx])
            return resolved_disc
        return base_disc

    if scheme in ("viridis", "cividis", "batlow", "vik", "magma"):
        ramp_map = {
            "viridis": VIRIDIS_STOPS,
            "cividis": CIVIDIS_STOPS,
            "batlow": BATLOW_STOPS,
            "vik": VIK_STOPS,
            "magma": MAGMA_STOPS,
        }
        base_ramp = interpolate_color_stops(ramp_map[scheme], n)
        if roles is not None:
            resolved_ramp: List[str] = []
            for idx, r_hint in enumerate(roles):
                cls, val = _classify_semantic_role(r_hint)
                resolved_ramp.append(val if cls == "direct" and val else base_ramp[idx])
            return resolved_ramp
        return base_ramp

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
    # Family B: 1:1 Square Single Panel (EIS, DRT Contour, Heatmap) -> 3120 x 2340 px @ 300 DPI
    # Shares EXACT SAME 10.40 x 7.80 in canvas, top (0.95 in), and bottom (5.75 in) as Family A so equal-width layouts never distort!
    "page_sq_w_in": 10.40,
    "page_sq_h_in": 7.80,
    "box_sq_left_in": 2.80,
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


def load_journal_specs() -> Dict[str, Dict[str, Any]]:
    """Load orthogonal journal physical print layout specifications from `presets/journal_specs.json`."""
    spec_file = PRESET_DIR / "journal_specs.json"
    if not spec_file.exists():
        raise FileNotFoundError(f"Journal specs preset missing: {spec_file}")
    raw_data: Dict[str, Any] = json.loads(spec_file.read_text(encoding="utf-8"))
    specs = raw_data["specs"] if isinstance(raw_data.get("specs"), dict) else raw_data
    return copy.deepcopy(specs)


def apply_journal_spec(theme_dict: Dict[str, Any], journal_spec: Optional[str]) -> Dict[str, Any]:
    """
    Apply an orthogonal journal physical layout & typography spec (`nature_single_89mm`,
    `science_single_55mm`, `cell_single_85mm`, `acs_single_3.25in`, `ieee_single_3.5in`, etc.)
    onto `theme_dict` while strictly preserving `font_family` and `font_weight` of the style preset.
    Returns an untouched deep copy when `journal_spec` is `None` or `'presentation_4_3'`.
    """
    out = copy.deepcopy(theme_dict)
    if journal_spec is None or str(journal_spec).strip() == "":
        return out

    raw_key = str(journal_spec).strip()
    spec_key = _JOURNAL_SPEC_ALIASES.get(raw_key.lower(), raw_key)
    all_specs = load_journal_specs()
    if spec_key not in all_specs:
        raise ValueError(
            f"Unsupported journal_spec {journal_spec!r}; expected one of {VALID_JOURNAL_SPECS}"
        )

    out["journal_spec"] = spec_key
    js = all_specs[spec_key]
    if spec_key == "presentation_4_3" or bool(js.get("preserve_theme_typography", False)):
        out["_journal_spec_applied"] = spec_key
        return out

    if out.get("_journal_spec_applied") == spec_key:
        return out

    box_lw = float(js["box_lw_pt"])
    curve_lw = float(js["curve_lw_pt"])
    guide_lw = float(js.get("guide_lw_pt", max(0.55, round(curve_lw * 0.6, 2))))
    inset_box_lw = float(js.get("inset_box_lw_pt", max(0.5, round(box_lw * 0.72, 2))))
    bar_border_lw = float(js.get("bar_border_lw_pt", max(0.5, round(box_lw * 0.8, 2))))
    axis_pt = float(js["axis_title_pt"])
    tick_pt = float(js["tick_label_pt"])
    leg_pt = float(js["legend_pt"])
    callout_pt = float(js.get("callout_pt", leg_pt))
    inset_tk_pt = float(js.get("inset_tick_pt", max(5.0, tick_pt - 1.5)))
    inset_ttl_pt = float(js.get("inset_title_pt", max(5.5, tick_pt - 1.0)))
    mk_pt = float(js.get("marker_size_pt", 3.5))
    inset_mk_pt = float(js.get("inset_marker_size_pt", max(2.2, round(mk_pt * 0.7, 2))))

    out.update(
        {
            "width_mm": float(js["width_mm"]),
            "height_mm": float(js["height_mm"]),
            "panel_tag_case": str(js.get("panel_tag_case", "lower_bold")),
            "figure_box_linewidth": box_lw,
            "inset_box_linewidth": inset_box_lw,
            "curve_linewidth": curve_lw,
            "guide_linewidth": guide_lw,
            "callout_leader_linewidth": guide_lw,
            "axis_label_size": axis_pt,
            "tick_label_size": tick_pt,
            "title_annot_size": leg_pt,
            "callout_font_size": callout_pt,
            "bar_value_label_size": callout_pt,
            "tick_width": box_lw,
            "major_tick_length": max(2.4, round(box_lw * 3.6, 2)),
            "log_minor_tick_length": max(1.5, round(box_lw * 2.2, 2)),
        }
    )

    on = out.setdefault("origin_native", {})
    on.update(
        {
            "page_rect_w_in": float(js["page_rect_w_in"]),
            "page_rect_h_in": float(js["page_rect_h_in"]),
            "box_rect_left_in": float(js["box_rect_left_in"]),
            "box_rect_top_in": float(js["box_rect_top_in"]),
            "box_rect_w_in": float(js["box_rect_w_in"]),
            "box_rect_h_in": float(js["box_rect_h_in"]),
            "page_sq_w_in": float(js["page_sq_w_in"]),
            "page_sq_h_in": float(js["page_sq_h_in"]),
            "box_sq_left_in": float(js["box_sq_left_in"]),
            "box_sq_top_in": float(js["box_sq_top_in"]),
            "box_sq_side_in": float(js["box_sq_side_in"]),
            "equal_aspect_square_inch": float(js["box_sq_side_in"]),
            "box_linewidth_pt": box_lw,
            "inset_box_linewidth_pt": inset_box_lw,
            "bar_border_linewidth_pt": bar_border_lw,
            "axis_title_pt": axis_pt,
            "dual_y_axis_title_pt": axis_pt,
            "tick_label_pt": tick_pt,
            "legend_pt": leg_pt,
            "value_label_pt": callout_pt,
            "inset_tick_label_pt": inset_tk_pt,
            "inset_title_pt": inset_ttl_pt,
            "curve_w": int(round(curve_lw * 500.0)),
            "fit_envelope_w": int(round(curve_lw * 500.0)),
            "component_w": int(round(guide_lw * 500.0)),
            "baseline_w": int(round(guide_lw * 460.0)),
            "guide_w": int(round(guide_lw * 500.0)),
            "marker_size_pt": mk_pt,
            "inset_marker_size_pt": inset_mk_pt,
        }
    )

    if isinstance(out.get("axis_tick_matrix"), dict):
        for ak, apol in out["axis_tick_matrix"].items():
            if isinstance(apol, dict):
                apol["box_linewidth_pt"] = inset_box_lw if ak == "inset" else box_lw

    if isinstance(out.get("bar_style"), dict) and isinstance(out["bar_style"].get("grouped_gradient"), dict):
        gg = out["bar_style"]["grouped_gradient"]
        gg["edge_linewidth_pt"] = bar_border_lw
        gg["value_label_size_pt"] = callout_pt
        gg["dense_value_label_size_pt"] = max(5.0, round(callout_pt - 1.0, 2))
        gg["error_bar_linewidth_pt"] = guide_lw

    if isinstance(out.get("composite_print_profile"), dict):
        cpp = out["composite_print_profile"]
        cpp["panel_tag_pt"] = float(js.get("panel_tag_pt", axis_pt + 0.5))
        cpp["axis_title_pt"] = axis_pt
        cpp["tick_label_pt"] = tick_pt
        cpp["legend_pt"] = leg_pt
        cpp["box_linewidth_pt"] = box_lw
        cpp["curve_linewidth_pt"] = curve_lw

    out["_journal_spec_applied"] = spec_key
    return out


def resolve_runtime_spec(theme_or_name: Optional[Dict[str, Any] | str | Path] = None) -> Dict[str, Any]:
    """
    Resolve a complete runtime layout/typography/stroke specification dictionary from either:
      - `None` -> `style_publication_minimal` (Times New Roman Bold, 3.0pt box, 3.0pt curves, 28/24/22/22 pt)
      - `"style_arial_clean"` / `"arial"` -> Arial Regular, 1.5pt box, 2.0pt curves, 28/24/22/22 pt
      - Any loaded theme dictionary from `load_theme(...)` (honoring `th.get("journal_spec")` if present)
    """
    spec = copy.deepcopy(UNIFIED_SPEC)
    if theme_or_name is None:
        return spec
    th = theme_or_name if isinstance(theme_or_name, dict) else load_theme(theme_or_name)
    if th.get("journal_spec"):
        th = apply_journal_spec(th, th.get("journal_spec"))
    on = th.get("origin_native") or {}

    fam = str(th.get("font_family") or spec["font_family"]).strip()
    wt = str(th.get("font_weight") or "bold").strip().lower()
    is_bold = wt in ("bold", "700", "800", "900", "semibold", "demi")
    box_lw = float(th.get("figure_box_linewidth", on.get("box_linewidth_pt", spec["box_lw_pt"])))
    curve_lw = float(th.get("curve_linewidth", spec["curve_lw_pt"]))
    curve_w = int(round(float(on.get("curve_w", curve_lw * 500.0))))
    sub_lw = float(th.get("guide_linewidth", max(0.55, round(curve_lw * 0.56, 2))))
    sub_w = int(round(float(on.get("component_w", sub_lw * 500.0))))
    inset_lw = float(th.get("inset_box_linewidth", on.get("inset_box_linewidth_pt", max(0.5, round(box_lw * 0.67, 2)))))
    page_rect_h = float(on.get("page_rect_h_in", spec["page_rect_h_in"]))
    box_rect_top = float(on.get("box_rect_top_in", spec["box_rect_top_in"]))
    box_rect_h = float(on.get("box_rect_h_in", spec["box_rect_h_in"]))
    sy_scale = page_rect_h / 7.80

    spec.update(
        {
            "preset_id": str(th.get("preset_id") or DEFAULT_STYLE_PRESET),
            "journal_spec": th.get("journal_spec"),
            "panel_tag_case": str(th.get("panel_tag_case") or "lower_bold"),
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
            "inset_title_pt": float(on.get("inset_title_pt", spec["inset_title_pt"])),
            "page_rect_w_in": float(on.get("page_rect_w_in", spec["page_rect_w_in"])),
            "page_rect_h_in": page_rect_h,
            "box_rect_left_in": float(on.get("box_rect_left_in", spec["box_rect_left_in"])),
            "box_rect_top_in": box_rect_top,
            "box_rect_w_in": float(on.get("box_rect_w_in", spec["box_rect_w_in"])),
            "box_rect_h_in": box_rect_h,
            "page_sq_w_in": float(on.get("page_sq_w_in", spec["page_sq_w_in"])),
            "page_sq_h_in": float(on.get("page_sq_h_in", spec["page_sq_h_in"])),
            "box_sq_left_in": float(on.get("box_sq_left_in", spec["box_sq_left_in"])),
            "box_sq_top_in": float(on.get("box_sq_top_in", spec["box_sq_top_in"])),
            "box_sq_side_in": float(on.get("box_sq_side_in", spec["box_sq_side_in"])),
            "bode_top_in": box_rect_top,
            "bode_gap_in": round(0.36 * sy_scale, 4),
            "bode_sub_h_in": round(0.5 * max(0.4, box_rect_h - 0.36 * sy_scale), 4),
            "marker_size_pt": float(on.get("marker_size_pt", spec["marker_size_pt"])),
            "inset_marker_size_pt": float(on.get("inset_marker_size_pt", spec["inset_marker_size_pt"])),
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


def compute_origin_layer_scale(lw_in: float, lh_in: float, pw_in: float, ph_in: float) -> float:
    """Return Origin's effective `layer.fsize=1` sub-layer scaling factor (`~ sqrt(layer_area / page_area) / 0.93`)."""
    area_ratio = (max(0.35, float(lw_in)) * max(0.35, float(lh_in))) / (
        max(2.0, float(pw_in)) * max(2.0, float(ph_in))
    )
    return max(0.12, min(1.0, math.sqrt(area_ratio) / 0.93))


def compensate_origin_layer_pt(
    target_true_pt: float, lw_in: float, lh_in: float, pw_in: float, ph_in: float
) -> float:
    """
    Compensate Origin's automatic sub-layer font downscaling (`scale ~ sqrt(layer_area/page_area) / 0.93`)
    so native `layer.x.label.pt` / `layer.y.label.pt` render at the exact same pixel height as `gl_ov` true points.
    """
    scale_fac = compute_origin_layer_scale(lw_in, lh_in, pw_in, ph_in)
    return round(float(target_true_pt) / scale_fac, 2)


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


def get_scheme_color_stops(scheme: str) -> List[str]:
    """Return canonical hex stop/palette list for any supported color scheme name."""
    key = str(scheme or "paired_semantic").strip().lower()
    scheme_map: Dict[str, List[str]] = {
        "paired_semantic": list(_PAIRED_INTERLEAVED),
        "sandwich_stack": list(SANDWICH_STACK_ORDERED),
        "sequential_blue_red": list(SEQUENTIAL_BLUE_RED_STOPS),
        "deep_blue_to_red": list(DEEP_BLUE_TO_RED_STOPS),
        "pseudocolor_zero_white": list(PSEUDOCOLOR_ZERO_WHITE_STOPS),
        "diverging_blue_white_red": list(DIVERGING_BLUE_WHITE_RED_STOPS),
        "okabe_ito": list(OKABE_ITO_COLORS),
        "tol_muted": list(TOL_MUTED_COLORS),
        "viridis": list(VIRIDIS_STOPS),
        "cividis": list(CIVIDIS_STOPS),
        "batlow": list(BATLOW_STOPS),
        "vik": list(VIK_STOPS),
        "magma": list(MAGMA_STOPS),
    }
    if key not in scheme_map:
        raise ValueError(f"Unsupported color scheme {scheme!r}; expected one of {VALID_COLOR_SCHEMES}")
    return scheme_map[key]


def _pack_riff_pal_256_bytes(rgbs_256: Sequence[Tuple[int, int, int]]) -> bytes:
    """Build standard 1052-byte Microsoft/OriginPro 256-entry RIFF `.pal` binary payload."""
    if len(rgbs_256) != 256:
        raise ValueError(f"RIFF .pal requires 256 RGB slots, got {len(rgbs_256)}")
    entries = b"".join(
        struct.pack("<BBBB", max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), 0)
        for r, g, b in rgbs_256
    )
    trailing_pad = b"\x00\x00\x00\x00"
    data_payload = struct.pack("<HH", 0x0300, 256) + entries + trailing_pad  # 4 + 1024 + 4 = 1032B
    data_chunk = struct.pack("<4sI", b"data", len(data_payload)) + data_payload  # 8 + 1032 = 1040B
    return struct.pack("<4sI4s", b"RIFF", 4 + len(data_chunk), b"PAL ") + data_chunk  # 12 + 1040 = 1052B


def _pack_riff_pal_256(rgbs_256: Sequence[Tuple[int, int, int]], out_path: str | Path) -> str:
    """
    Write a standard 1052-byte Microsoft/OriginPro 256-entry RIFF `.pal` binary file:
      - 12B RIFF header: b'RIFF' + uint32(1044) + b'PAL '
      - 12B LOGPALETTE header: b'data' + uint32(1032) + uint16(0x0300) + uint16(256)
      - 1024B PALETTEENTRY[256]: 256 * <BBBB(r, g, b, 0)
      - 4B LOGPALETTE trailing struct pad: b'\\x00\\x00\\x00\\x00'
      Total = 12 + 12 + 1024 + 4 = 1052 bytes (matches OriginPro native Palettes/*.PAL).
    """
    riff_bytes = _pack_riff_pal_256_bytes(rgbs_256)
    p = Path(out_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(riff_bytes)
    return str(p)


def build_riff_palette_bytes(
    hex_stops_or_scheme: Sequence[str] | str,
    *,
    continuous: Optional[bool] = None,
    n_colors: int = 256,
) -> bytes:
    """
    Build 1052-byte OriginPro RIFF `.pal` bytes from either a color scheme name
    ('viridis', 'cividis', 'batlow', 'okabe_ito', 'tol_muted', etc.) or a list of hex colors.
    """
    if isinstance(hex_stops_or_scheme, str):
        scheme_key = hex_stops_or_scheme.strip().lower()
        stops = get_scheme_color_stops(scheme_key)
        if continuous is None:
            continuous = scheme_key not in ("okabe_ito", "tol_muted", "paired_semantic", "sandwich_stack")
    else:
        stops = list(hex_stops_or_scheme)
        if continuous is None:
            continuous = True

    if not stops:
        raise ValueError("Palette stops cannot be empty.")

    if not continuous:
        parsed = [parse_hex_rgb(c) for c in stops]
        rgbs_256 = [parsed[i % len(parsed)] for i in range(256)]
        return _pack_riff_pal_256_bytes(rgbs_256)

    if len(stops) < 2:
        raise ValueError("Continuous RIFF .pal requires at least 2 color stops.")
    if n_colors < 2 or n_colors > 256:
        raise ValueError(f"n_colors must be in [2, 256], got {n_colors}")

    ramp_hex = interpolate_color_stops(stops, n_colors)
    ramp_rgb = [parse_hex_rgb(c) for c in ramp_hex]
    if n_colors == 256:
        rgbs_256 = ramp_rgb
    else:
        rgbs_256 = [ramp_rgb[min(n_colors - 1, (i * n_colors) // 256)] for i in range(256)]
    return _pack_riff_pal_256_bytes(rgbs_256)


def write_origin_pal_file(
    path: str | Path,
    hex_stops_or_scheme: Sequence[str] | str,
    *,
    continuous: Optional[bool] = None,
    n_colors: int = 256,
) -> str:
    """Write a 1052-byte OriginPro `.pal` file from a scheme name or hex color sequence."""
    payload = build_riff_palette_bytes(hex_stops_or_scheme, continuous=continuous, n_colors=n_colors)
    p = Path(path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return str(p)


def write_discrete_riff_pal(path: str | Path, hex_list: Sequence[str] | str) -> str:
    """
    Generate a 1052-byte discrete Microsoft RIFF `.pal` cycling `hex_list` across 256 slots
    for Origin `STACKCOLUMN` / `StackColP` / `COLUMN` (`plot1.colorlist` with `stretchpal=0`).
    """
    stops = get_scheme_color_stops(hex_list) if isinstance(hex_list, str) else list(hex_list)
    if not stops:
        raise ValueError("hex_list must contain at least one color.")
    parsed = [parse_hex_rgb(c) for c in stops]
    rgbs_256 = [parsed[i % len(parsed)] for i in range(256)]
    return _pack_riff_pal_256(rgbs_256, path)


def write_continuous_riff_pal(
    path: str | Path,
    hex_stops: Sequence[str] | str,
    n_colors: int = 256,
) -> str:
    """
    Generate a 1052-byte continuous (or `n_colors`-quantized) Microsoft RIFF `.pal`
    interpolated across `hex_stops` (or a named scheme like 'viridis'/'cividis'/'batlow')
    for Origin 2D `CONTOUR` / `HeatMap` (`p.colormap`).
    """
    stops = get_scheme_color_stops(hex_stops) if isinstance(hex_stops, str) else list(hex_stops)
    if not stops or len(stops) < 2:
        raise ValueError("hex_stops must contain at least 2 color stops for continuous interpolation.")
    if n_colors < 2 or n_colors > 256:
        raise ValueError(f"n_colors must be in [2, 256], got {n_colors}")

    ramp_hex = interpolate_color_stops(stops, n_colors)
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

def clean_semantic_sample_name(
    name: str,
    strip_prefix: bool = False,
    *,
    enabled: bool = True,
) -> str:
    """
    Strip trailing file extension suffixes like (.ndax) / (.nda) / (.bin) / (.mpt) / (.dta)
    while preserving scientific colon notation ('B:T Ratio', 'G1: S', 'WT:KO', 'p: 0.01',
    '1:10 Dilution'). Legacy slot prefixes ('A: Sample 1') are stripped ONLY when
    `strip_prefix=True` and matched by `_SAMPLE_PREFIX_RE`.
    """
    text = str(name or "").strip()
    if not enabled:
        return text
    text = _FILE_EXT_RE.sub("", text)
    if strip_prefix:
        text = _SAMPLE_PREFIX_RE.sub("", text)
    return text


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
