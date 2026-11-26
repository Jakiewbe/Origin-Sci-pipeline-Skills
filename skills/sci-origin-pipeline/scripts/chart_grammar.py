"""
chart_grammar.py - Declarative Scientific Chart Grammar & Mode Compiler for SciOrigin.

Pure-Python module (zero matplotlib dependency, zero Origin COM session startup).
Compiles declarative `task_config.json` dictionaries (and optional pre-loaded tables)
into validated `FigureSpec -> PanelSpec -> LayerSpec / AxisSpec / InsetSpec / GuideSpec`
trees ready for OriginPro native `.opju` builders and Source-Data Excel exporters.
"""
from __future__ import annotations

import copy
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import origin_theme as ot

SUPPORTED_LAYER_MARKS = (
    "line_scatter",
    "scatter",
    "bar_grouped_gradient",
    "bar_stacked",
    "bar_stacked_100pct",
    "contour_pseudocolor",
    "matrix_heatmap",
    "waterfall",
    "deconv_envelope",
    "stat_distribution",
    "stat_box_jitter",
    "line_band",
    "bar_dot_error",
    "violin_box",
    "forest_ci",
    "step_line",
    "energy_step",
    "km_step",
    "ternary_scatter",
    "polar_line",
    "vector_quiver",
)
VALID_MARKS = SUPPORTED_LAYER_MARKS

SUPPORTED_GUIDE_KINDS = (
    "vline",
    "hline",
    "span_v",
    "span_h",
    "peak_tag",
    "trend_arrow",
    "text",
    "sig_bracket",
    "slope_triangle",
)
VALID_GUIDE_KINDS = SUPPORTED_GUIDE_KINDS

SUPPORTED_PANEL_COORDS = (
    "cartesian",
    "ternary",
    "polar",
    "radar",
)

SUPPORTED_GRAMMAR_MODES = (
    "bar_grouped_gradient",
    "bar_stacked",
    "bar_stacked_100pct",
    "dual_y_combo",
    "curve_with_inset",
    "electrochem_kinetics",
    "contour_pseudocolor_2d",
    "chart_grammar",
    "xy_fit_and_band",
    "bode_dual_panel",
    "stat_distribution",
    "matrix_heatmap",
    "stat_bar_dot_sig",
    "stat_violin_raincloud",
    "volcano_plot",
    "forest_ablation_plot",
    "free_energy_diagram",
    "dose_response_4pl",
    "kaplan_meier_plot",
    "roc_pr_curve",
    "nmr_spectrum",
    "broken_axis_plot",
    "dual_x_optical_spectrum",
    "ternary_diagram",
    "polar_radar_plot",
    "multi_track_profile",
    "vector_quiver_field",
)
CHART_MODES = SUPPORTED_GRAMMAR_MODES

SUPPORTED_KINETICS_SUBTYPES = (
    "pulse_align",
    "galvanostatic_dqdv",
    "ragone",
)

ORIGIN_PLOT_ID_BY_MARK: Dict[str, int] = {
    "line_scatter": 202,
    "scatter": 201,
    "bar_grouped_gradient": 203,
    "bar_stacked": 213,
    "bar_stacked_100pct": 213,
    "contour_pseudocolor": 226,
    "matrix_heatmap": 105,
    "waterfall": 200,
    "deconv_envelope": 200,
    "stat_distribution": 206,
    "stat_box_jitter": 206,
    "line_band": 202,
    "bar_dot_error": 203,
    "violin_box": 206,
    "forest_ci": 201,
    "step_line": 200,
    "energy_step": 200,
    "km_step": 200,
    "ternary_scatter": 245,
    "polar_line": 192,
    "vector_quiver": 218,
}

ORIGIN_TEMPLATE_BY_MARK: Dict[str, Optional[str]] = {
    "line_scatter": None,
    "scatter": None,
    "bar_grouped_gradient": "COLUMN",
    "bar_stacked": "STACKCOLUMN",
    "bar_stacked_100pct": "StackColP",
    "contour_pseudocolor": "CONTOUR",
    "matrix_heatmap": "Heat_Map_With_Labels",
    "waterfall": None,
    "deconv_envelope": None,
    "stat_distribution": "BOX+DATA+OVERLAP",
    "stat_box_jitter": "BOX+DATA+OVERLAP",
    "line_band": None,
    "bar_dot_error": "COLUMN",
    "violin_box": "Violin",
    "forest_ci": None,
    "step_line": None,
    "energy_step": None,
    "km_step": None,
    "ternary_scatter": "Ternary",
    "polar_line": "Polar",
    "vector_quiver": "VECTXYXY",
}


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses, tuples, and numpy scalars/arrays into pure Python JSON types."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return obj.to_dict()
    if hasattr(obj, "tolist") and callable(obj.tolist):
        return _to_jsonable(obj.tolist())
    if hasattr(obj, "item") and callable(obj.item):
        return _to_jsonable(obj.item())
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def _as_float_list(seq: Optional[Sequence[Any]], field_name: str = "values") -> Optional[List[float]]:
    if seq is None:
        return None
    if hasattr(seq, "tolist") and callable(seq.tolist):
        seq = seq.tolist()
    out: List[float] = []
    for idx, val in enumerate(seq):
        try:
            fv = float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}[{idx}] must be numeric, got {val!r}") from exc
        if not math.isfinite(fv):
            raise ValueError(f"{field_name}[{idx}] must be finite, got {val!r}")
        out.append(fv)
    return out


def _as_any_list(seq: Optional[Sequence[Any]]) -> Optional[List[Any]]:
    if seq is None:
        return None
    if hasattr(seq, "tolist") and callable(seq.tolist):
        seq = seq.tolist()
    return [_to_jsonable(v) for v in seq]


def _as_2d_float_matrix(mat: Optional[Sequence[Sequence[Any]]]) -> Optional[List[List[float]]]:
    if mat is None:
        return None
    if hasattr(mat, "tolist") and callable(mat.tolist):
        mat = mat.tolist()
    rows: List[List[float]] = []
    expected_cols: Optional[int] = None
    for r_i, row in enumerate(mat):
        if hasattr(row, "tolist") and callable(row.tolist):
            row = row.tolist()
        f_row = _as_float_list(row, field_name=f"matrix_z[{r_i}]") or []
        if not f_row:
            raise ValueError(f"matrix_z[{r_i}] cannot be empty.")
        if expected_cols is None:
            expected_cols = len(f_row)
        elif len(f_row) != expected_cols:
            raise ValueError(
                f"matrix_z must be rectangular: row 0 has {expected_cols} cols, row {r_i} has {len(f_row)} cols."
            )
        rows.append(f_row)
    if not rows:
        raise ValueError("matrix_z cannot be empty.")
    return rows


# ---------------------------------------------------------------------------
# Declarative Chart Grammar Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SeriesSpec:
    name: str
    x: Optional[List[Any]] = None
    y: Optional[List[float]] = None
    y_err: Optional[List[float]] = None
    y_low: Optional[List[float]] = None
    y_high: Optional[List[float]] = None
    matrix_x: Optional[List[float]] = None
    matrix_y: Optional[List[Any]] = None
    matrix_z: Optional[List[List[float]]] = None
    role: Optional[str] = None
    color: Optional[str] = None
    gradient_top_color: Optional[str] = None
    gradient_bottom_color: Optional[str] = None
    label_color: Optional[str] = None
    line_style: str = "solid"
    line_width_pt: float = 2.8
    marker_style: str = "none"
    marker_size_pt: float = 6.0
    fill_alpha: Optional[float] = None
    show_value_labels: bool = False
    value_format: str = "{:.2f}"
    x_unit: Optional[str] = None
    y_unit: Optional[str] = None
    z_unit: Optional[str] = None
    source_ref: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.x = _as_any_list(self.x)
        self.y = _as_float_list(self.y, "y")
        self.y_err = _as_float_list(self.y_err, "y_err")
        self.y_low = _as_float_list(self.y_low, "y_low")
        self.y_high = _as_float_list(self.y_high, "y_high")
        self.matrix_x = _as_float_list(self.matrix_x, "matrix_x")
        self.matrix_y = _as_any_list(self.matrix_y)
        self.matrix_z = _as_2d_float_matrix(self.matrix_z)
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("SeriesSpec.name must be a non-empty string.")
        if self.x is not None and self.y is not None and len(self.x) != len(self.y):
            raise ValueError(
                f"Series '{self.name}': len(x)={len(self.x)} does not match len(y)={len(self.y)}."
            )
        if self.y is not None and self.y_err is not None and len(self.y_err) != len(self.y):
            raise ValueError(
                f"Series '{self.name}': len(y_err)={len(self.y_err)} does not match len(y)={len(self.y)}."
            )
        if self.y is not None and self.y_low is not None and len(self.y_low) != len(self.y):
            raise ValueError(
                f"Series '{self.name}': len(y_low)={len(self.y_low)} does not match len(y)={len(self.y)}."
            )
        if self.y is not None and self.y_high is not None and len(self.y_high) != len(self.y):
            raise ValueError(
                f"Series '{self.name}': len(y_high)={len(self.y_high)} does not match len(y)={len(self.y)}."
            )
        if self.matrix_z is not None:
            ny = len(self.matrix_z)
            nx = len(self.matrix_z[0])
            if self.matrix_x is not None and len(self.matrix_x) != nx:
                raise ValueError(
                    f"Series '{self.name}': len(matrix_x)={len(self.matrix_x)} != matrix_z cols ({nx})."
                )
            if self.matrix_y is not None and len(self.matrix_y) != ny:
                raise ValueError(
                    f"Series '{self.name}': len(matrix_y)={len(self.matrix_y)} != matrix_z rows ({ny})."
                )
        for hex_field_name in ("color", "gradient_top_color", "gradient_bottom_color", "label_color"):
            c_val = getattr(self, hex_field_name)
            if c_val is not None:
                setattr(self, hex_field_name, ot.normalize_hex(c_val))

    def to_dict(self) -> Dict[str, Any]:
        d = _to_jsonable(self.__dict__)
        if self.y_unit is not None and "unit" not in d:
            d["unit"] = self.y_unit
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SeriesSpec":
        d = copy.deepcopy(data)
        if "unit" in d and d.get("y_unit") is None:
            d["y_unit"] = d.pop("unit")
        else:
            d.pop("unit", None)
        return cls(**d)


def _normalize_axis_breaks(raw_breaks: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not raw_breaks:
        return []
    out: List[Dict[str, Any]] = []
    for idx, b in enumerate(raw_breaks):
        if not isinstance(b, dict):
            raise TypeError(f"AxisSpec.breaks[{idx}] must be a dict, got {type(b).__name__}")
        raw_from = b.get("from", b.get("start"))
        raw_to = b.get("to", b.get("end"))
        if raw_from is None or raw_to is None:
            raise ValueError(f"AxisSpec.breaks[{idx}] requires numeric 'from' and 'to' fields.")
        b_from = float(raw_from)
        b_to = float(raw_to)
        if not (math.isfinite(b_from) and math.isfinite(b_to)):
            raise ValueError(f"AxisSpec.breaks[{idx}] 'from'/'to' must be finite, got ({b_from}, {b_to})")
        if abs(b_from - b_to) <= 1e-12:
            raise ValueError(f"AxisSpec.breaks[{idx}] requires 'from' != 'to', got {b_from}")
        pos_pct = float(b.get("position_pct", b.get("position", 48.0)))
        if not (5.0 <= pos_pct <= 95.0):
            raise ValueError(f"AxisSpec.breaks[{idx}] position_pct must be in [5, 95], got {pos_pct}")
        sc_after = str(b.get("scale_after", "linear")).strip().lower()
        if sc_after == "log":
            sc_after = "log10"
        if sc_after not in ot.VALID_AXIS_SCALES:
            raise ValueError(
                f"AxisSpec.breaks[{idx}] scale_after must be one of {ot.VALID_AXIS_SCALES}, got {sc_after!r}"
            )
        inc_before = float(b["inc_before"]) if b.get("inc_before") is not None else None
        inc_after = float(b["inc_after"]) if b.get("inc_after") is not None else None
        out.append(
            {
                "from": b_from,
                "to": b_to,
                "position_pct": pos_pct,
                "scale_after": sc_after,
                "inc_before": inc_before,
                "inc_after": inc_after,
            }
        )
    return out


def _normalize_linked_top(raw_linked: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if raw_linked is None:
        return None
    if not isinstance(raw_linked, dict):
        raise TypeError(f"AxisSpec.linked_top must be a dict or None, got {type(raw_linked).__name__}")
    lbl = str(raw_linked.get("label", "")).strip()
    formula = str(raw_linked.get("formula", "1239.84193/x")).strip()
    if not formula:
        raise ValueError("AxisSpec.linked_top requires a non-empty 'formula' string (e.g. '1239.84193/x').")
    m_step = float(raw_linked["major_step"]) if raw_linked.get("major_step") is not None else None
    rich_lbl = raw_linked.get("origin_rich_label") or ot.format_origin_axis_title(lbl, bold=True)
    return {
        "label": lbl,
        "formula": formula,
        "major_step": m_step,
        "origin_rich_label": rich_lbl,
    }


@dataclass
class AxisSpec:
    which: str = "x"
    label: str = ""
    unit: Optional[str] = None
    axis_kind: str = "quantitative"
    scale: str = "linear"
    limits: Optional[Tuple[float, float]] = None
    invert: bool = False
    categories: Optional[List[str]] = None
    color: str = "#111111"
    align_zero: bool = False
    major_step: Optional[float] = None
    origin_rich_label: Optional[str] = None
    tick_policy: Dict[str, Any] = field(default_factory=dict)
    breaks: List[Dict[str, Any]] = field(default_factory=list)
    linked_top: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        w = str(self.which).strip().lower()
        if w in ("y", "left", "left_y"):
            w = "y1"
        elif w in ("right", "right_y"):
            w = "y2"
        self.which = w
        sc = str(self.scale).strip().lower()
        self.scale = "log10" if sc == "log" else sc
        self.color = ot.normalize_hex(self.color)
        if self.limits is not None:
            if len(self.limits) != 2:
                raise ValueError(f"AxisSpec.limits must have 2 elements, got {self.limits!r}")
            self.limits = (float(self.limits[0]), float(self.limits[1]))
        if self.categories is not None:
            self.categories = [str(c) for c in self.categories]
        if self.major_step is not None:
            self.major_step = float(self.major_step)
        self.breaks = _normalize_axis_breaks(self.breaks)
        self.linked_top = _normalize_linked_top(self.linked_top)
        if self.origin_rich_label is None:
            self.origin_rich_label = ot.format_origin_axis_title(self.label, bold=True)
        if not self.tick_policy:
            if self.axis_kind == "dual_y_right":
                self.tick_policy = ot.resolve_axis_tick_policy(
                    self.axis_kind, self.scale, right_axis_color=self.color
                )
            else:
                self.tick_policy = ot.resolve_axis_tick_policy(
                    self.axis_kind, self.scale, left_axis_color=self.color
                )
        self.validate()

    def validate(self) -> None:
        if self.which not in ("x", "y1", "y2", "z"):
            raise ValueError(f"AxisSpec.which must be one of ('x', 'y1', 'y2', 'z'), got {self.which!r}")
        if self.scale not in ot.VALID_AXIS_SCALES:
            raise ValueError(f"AxisSpec.scale must be one of {ot.VALID_AXIS_SCALES}, got {self.scale!r}")
        if self.axis_kind not in ot.VALID_AXIS_KINDS:
            raise ValueError(
                f"AxisSpec.axis_kind must be one of {ot.VALID_AXIS_KINDS}, got {self.axis_kind!r}"
            )
        if self.limits is not None:
            lo, hi = self.limits
            if not (math.isfinite(lo) and math.isfinite(hi)):
                raise ValueError(f"AxisSpec.limits must be finite, got {self.limits!r}")
            if self.scale == "log10" and (lo <= 0.0 or hi <= 0.0):
                raise ValueError(f"Log10 axis '{self.which}' requires strictly positive limits, got {self.limits!r}")
        for idx, b in enumerate(self.breaks):
            if b["from"] == b["to"]:
                raise ValueError(f"AxisSpec.breaks[{idx}] requires 'from' != 'to'.")
        if self.linked_top is not None and self.which != "x":
            raise ValueError(f"AxisSpec.linked_top is only supported on 'x' axis, got {self.which!r}")

    def to_dict(self) -> Dict[str, Any]:
        return _to_jsonable(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AxisSpec":
        d = copy.deepcopy(data)
        if d.get("limits") is not None:
            d["limits"] = tuple(d["limits"])
        allowed = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in allowed}
        return cls(**d)


@dataclass
class GuideSpec:
    kind: str = "vline"
    axis: str = "y1"
    value: Optional[float] = None
    start: Optional[float] = None
    end: Optional[float] = None
    anchor_pos: Optional[float] = None
    x: Optional[float] = None
    x2: Optional[float] = None
    y: Optional[float] = None
    x_end: Optional[float] = None
    y_end: Optional[float] = None
    tip_drop: Optional[float] = None
    label: str = ""
    color: str = "#3E86DE"
    line_style: str = "dashed"
    line_width_pt: float = 2.8
    font_size_pt: float = 20.0
    shoulder_y_frac: float = 0.77
    label_side: str = "right"
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        k_norm = str(self.kind).strip().lower()
        if k_norm in ("vspan_arrow", "vspan", "vertical_span"):
            k_norm = "span_v"
        elif k_norm in ("hspan_arrow", "hspan", "horizontal_span"):
            k_norm = "span_h"
        elif k_norm in ("bracket", "significance_bracket", "stat_bracket"):
            k_norm = "sig_bracket"
        elif k_norm in ("slope", "power_slope", "slope_guide"):
            k_norm = "slope_triangle"
        self.kind = k_norm
        self.color = ot.normalize_hex(self.color)
        for attr in ("value", "start", "end", "anchor_pos", "x", "x2", "y", "x_end", "y_end", "tip_drop"):
            v = getattr(self, attr)
            if v is not None:
                setattr(self, attr, float(v))
        if self.kind == "span_v":
            if self.x is None and self.anchor_pos is not None:
                self.x = self.anchor_pos
            elif self.anchor_pos is None and self.x is not None:
                self.anchor_pos = self.x
        elif self.kind in ("sig_bracket", "slope_triangle"):
            if self.x is None and self.start is not None:
                self.x = self.start
            if self.x2 is None and self.x_end is not None:
                self.x2 = self.x_end
            elif self.x2 is None and self.end is not None:
                self.x2 = self.end
            if self.x_end is None and self.x2 is not None:
                self.x_end = self.x2
        if self.meta is None:
            self.meta = {}
        self.validate()

    def validate(self) -> None:
        if self.kind not in SUPPORTED_GUIDE_KINDS:
            raise ValueError(
                f"GuideSpec.kind must be one of {SUPPORTED_GUIDE_KINDS}, got {self.kind!r}"
            )
        if self.axis not in ("y1", "y2"):
            raise ValueError(f"GuideSpec.axis must be 'y1' or 'y2', got {self.axis!r}")
        if self.kind in ("vline", "hline") and self.value is None:
            raise ValueError(f"GuideSpec(kind={self.kind!r}) requires numeric `value`.")
        if self.kind in ("span_v", "span_h") and (self.start is None or self.end is None):
            raise ValueError(f"GuideSpec(kind={self.kind!r}) requires both `start` and `end`.")
        if self.kind == "sig_bracket" and (self.value is None or self.x is None or self.x2 is None):
            raise ValueError("GuideSpec(kind='sig_bracket') requires numeric `value` (y_bar), `x` (x1), and `x2`.")
        if self.kind == "slope_triangle":
            if self.x is None or self.y is None or self.x2 is None or self.value is None:
                raise ValueError(
                    "GuideSpec(kind='slope_triangle') requires numeric `x` (x_start), `y` (y_start), `x2` (x_end), and `value` (slope)."
                )
            if abs(self.x2 - self.x) <= 1e-12:
                raise ValueError("GuideSpec(kind='slope_triangle') requires `x` != `x2`.")

    def to_dict(self) -> Dict[str, Any]:
        d = _to_jsonable(self.__dict__)
        if self.kind == "span_v" and self.start is not None and self.end is not None:
            d["y_start"] = self.start
            d["y_end"] = self.end
            d["span"] = round(abs(self.end - self.start), 6)
        elif self.kind == "span_h" and self.start is not None and self.end is not None:
            d["x_start"] = self.start
            d["x_end"] = self.end
            d["span"] = round(abs(self.end - self.start), 6)
        elif self.kind == "sig_bracket":
            d["x1"] = self.x
            d["x2"] = self.x2
            d["y_bar"] = self.value
            d["tip_drop"] = self.tip_drop
        elif self.kind == "slope_triangle":
            d["x_start"] = self.x
            d["y_start"] = self.y
            d["x_end"] = self.x2
            d["slope"] = self.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuideSpec":
        d = copy.deepcopy(data)
        raw_kind = str(d.get("kind", "vline")).strip().lower()
        is_slope = raw_kind in ("slope_triangle", "slope", "power_slope", "slope_guide")
        if d.get("x") is None and "x_start" in d and is_slope:
            d["x"] = d.pop("x_start")
        else:
            d.pop("x_start", None)
        if d.get("y") is None and "y_start" in d and is_slope:
            d["y"] = d.pop("y_start")
        elif d.get("start") is None and "y_start" in d:
            d["start"] = d.pop("y_start")
        else:
            d.pop("y_start", None)
        if d.get("end") is None and raw_kind in ("span_v", "vspan_arrow") and "y_end" in d:
            d["end"] = d.pop("y_end")
        if d.get("x") is None and "x1" in d:
            d["x"] = d.pop("x1")
        else:
            d.pop("x1", None)
        if d.get("value") is None and "y_bar" in d:
            d["value"] = d.pop("y_bar")
        else:
            d.pop("y_bar", None)
        if d.get("value") is None and "slope" in d:
            d["value"] = d.pop("slope")
        else:
            d.pop("slope", None)
        if d.get("x2") is None and (raw_kind in ("sig_bracket", "bracket", "significance_bracket", "stat_bracket") or is_slope) and "x_end" in d:
            d["x2"] = d.get("x_end")
        if "linestyle" in d and "line_style" not in d:
            d["line_style"] = d.pop("linestyle")
        allowed = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in allowed}
        return cls(**d)


@dataclass
class LayerSpec:
    layer_id: str = "layer_1"
    mark: str = "line_scatter"
    y_axis: str = "y1"
    series: List[SeriesSpec] = field(default_factory=list)
    categories: Optional[List[str]] = None
    color_scheme: str = "paired_semantic"
    palette_colors: List[str] = field(default_factory=list)
    normalize_100: bool = False
    bar_width_ratio: float = 0.62
    divider_color: Optional[str] = None
    divider_linewidth_pt: float = 0.0
    edge_color: str = "#222222"
    edge_linewidth_pt: float = 1.2
    show_value_labels: bool = False
    value_label_size_pt: float = 22.0
    show_ribbon_links: bool = False
    z_levels_count: int = 32
    hide_contour_lines: bool = True
    origin_template: Optional[str] = None
    origin_plot_type: Optional[int] = None
    style_overrides: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ya = str(self.y_axis).strip().lower()
        if ya in ("y", "left", "left_y"):
            ya = "y1"
        elif ya in ("right", "right_y"):
            ya = "y2"
        self.y_axis = ya
        self.series = [
            s if isinstance(s, SeriesSpec) else SeriesSpec.from_dict(s)
            for s in self.series
        ]
        if self.categories is not None:
            self.categories = [str(c) for c in self.categories]
        self.palette_colors = [ot.normalize_hex(c) for c in self.palette_colors]
        if self.divider_color is not None:
            self.divider_color = ot.normalize_hex(self.divider_color)
        self.edge_color = ot.normalize_hex(self.edge_color)
        if self.origin_plot_type is None and self.mark in ORIGIN_PLOT_ID_BY_MARK:
            self.origin_plot_type = ORIGIN_PLOT_ID_BY_MARK[self.mark]
        if self.origin_template is None and self.mark in ORIGIN_TEMPLATE_BY_MARK:
            self.origin_template = ORIGIN_TEMPLATE_BY_MARK[self.mark]
        if self.mark == "bar_stacked_100pct":
            self.normalize_100 = True
        self.validate()

    def validate(self) -> None:
        if self.mark not in SUPPORTED_LAYER_MARKS:
            raise ValueError(
                f"LayerSpec.mark must be one of {SUPPORTED_LAYER_MARKS}, got {self.mark!r}"
            )
        if self.y_axis not in ("y1", "y2"):
            raise ValueError(f"LayerSpec.y_axis must be 'y1' or 'y2', got {self.y_axis!r}")
        if self.color_scheme not in ot.VALID_COLOR_SCHEMES:
            raise ValueError(
                f"LayerSpec.color_scheme must be one of {ot.VALID_COLOR_SCHEMES}, got {self.color_scheme!r}"
            )
        if not self.series:
            raise ValueError(f"LayerSpec '{self.layer_id}' ({self.mark}) must contain at least one SeriesSpec.")
        for s in self.series:
            s.validate()
        if self.mark in ("bar_stacked", "bar_stacked_100pct"):
            lengths = {len(s.y) for s in self.series if s.y is not None}
            if len(lengths) > 1:
                raise ValueError(
                    f"Stacked bar layer '{self.layer_id}' has mismatched series lengths: {sorted(lengths)}"
                )
            if self.categories is not None and lengths:
                only_len = next(iter(lengths))
                if only_len != len(self.categories):
                    raise ValueError(
                        f"Stacked bar layer '{self.layer_id}': len(categories)={len(self.categories)} != series length ({only_len})"
                    )
        if self.mark == "contour_pseudocolor":
            s0 = self.series[0]
            if s0.matrix_z is None and not s0.source_ref:
                raise ValueError(
                    f"Contour layer '{self.layer_id}' requires `matrix_z` data or `source_ref`."
                )

    def to_dict(self) -> Dict[str, Any]:
        d = copy.copy(self.__dict__)
        d["series"] = [s.to_dict() for s in self.series]
        # Expose 2D matrix convenience pointers at layer level for export_multi_chart_workbook
        if self.mark in ("contour_pseudocolor", "matrix_heatmap") and self.series:
            s0 = self.series[0]
            if s0.matrix_z is not None:
                d["matrix_x"] = s0.matrix_x
                d["matrix_y"] = s0.matrix_y
                d["matrix_z"] = s0.matrix_z
                d["z_unit"] = s0.z_unit
                if s0.meta.get("state_labels"):
                    d["y_labels"] = s0.meta["state_labels"]
        return _to_jsonable(d)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LayerSpec":
        d = copy.deepcopy(data)
        for extra_k in ("matrix_x", "matrix_y", "matrix_z", "z_unit", "y_labels"):
            d.pop(extra_k, None)
        d["series"] = [SeriesSpec.from_dict(s) for s in d.get("series", [])]
        return cls(**d)


@dataclass
class InsetSpec:
    inset_id: str = "inset_1"
    mode: str = "zoom"
    bbox_pct: Tuple[float, float, float, float] = (46.0, 8.0, 46.0, 44.0)
    xlim: Optional[Tuple[float, float]] = None
    ylim: Optional[Tuple[float, float]] = None
    equal_aspect: bool = False
    show_zoom_box: bool = True
    zoom_box_color: str = "#6579BE"
    background_color: str = "#FFFFFF"
    box_linewidth_pt: float = 1.6
    x_axis: AxisSpec = field(default_factory=lambda: AxisSpec(which="x", axis_kind="inset"))
    y_axis: AxisSpec = field(default_factory=lambda: AxisSpec(which="y1", axis_kind="inset"))
    layers: List[LayerSpec] = field(default_factory=list)
    guides: List[GuideSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.mode = str(self.mode).strip().lower()
        if len(self.bbox_pct) != 4:
            raise ValueError(f"InsetSpec.bbox_pct must be (left, top, width, height), got {self.bbox_pct!r}")
        self.bbox_pct = (
            float(self.bbox_pct[0]),
            float(self.bbox_pct[1]),
            float(self.bbox_pct[2]),
            float(self.bbox_pct[3]),
        )
        if self.xlim is not None:
            self.xlim = (float(self.xlim[0]), float(self.xlim[1]))
        if self.ylim is not None:
            self.ylim = (float(self.ylim[0]), float(self.ylim[1]))
        self.zoom_box_color = ot.normalize_hex(self.zoom_box_color)
        self.background_color = ot.normalize_hex(self.background_color)
        if isinstance(self.x_axis, dict):
            self.x_axis = AxisSpec.from_dict(self.x_axis)
        if isinstance(self.y_axis, dict):
            self.y_axis = AxisSpec.from_dict(self.y_axis)
        self.layers = [
            ly if isinstance(ly, LayerSpec) else LayerSpec.from_dict(ly)
            for ly in self.layers
        ]
        self.guides = [
            gd if isinstance(gd, GuideSpec) else GuideSpec.from_dict(gd)
            for gd in self.guides
        ]
        self.validate()

    def validate(self) -> None:
        if self.mode not in ("zoom", "subchart"):
            raise ValueError(f"InsetSpec.mode must be 'zoom' or 'subchart', got {self.mode!r}")
        l_pct, t_pct, w_pct, h_pct = self.bbox_pct
        if not (0.0 <= l_pct < 100.0 and 0.0 <= t_pct < 100.0 and 0.0 < w_pct <= 100.0 and 0.0 < h_pct <= 100.0):
            raise ValueError(
                f"InsetSpec.bbox_pct must be parent-layer percentages in [0, 100], got {self.bbox_pct!r}"
            )
        if l_pct + w_pct > 102.0 or t_pct + h_pct > 102.0:
            raise ValueError(
                f"InsetSpec.bbox_pct overflows parent layer frame (>100%): {self.bbox_pct!r}"
            )
        if self.mode == "subchart" and not self.layers:
            raise ValueError(f"InsetSpec '{self.inset_id}' with mode='subchart' requires non-empty `layers`.")
        self.x_axis.validate()
        self.y_axis.validate()
        for ly in self.layers:
            ly.validate()
        for gd in self.guides:
            gd.validate()

    def to_dict(self) -> Dict[str, Any]:
        return _to_jsonable(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InsetSpec":
        d = copy.deepcopy(data)
        if d.get("bbox_pct") is not None:
            d["bbox_pct"] = tuple(d["bbox_pct"])
        if d.get("xlim") is not None:
            d["xlim"] = tuple(d["xlim"])
        if d.get("ylim") is not None:
            d["ylim"] = tuple(d["ylim"])
        return cls(**d)


@dataclass
class PanelSpec:
    panel_id: str = "panel_a"
    tag: Optional[str] = None
    row: int = 0
    col: int = 0
    row_span: int = 1
    col_span: int = 1
    coord: str = "cartesian"
    x_axis: AxisSpec = field(default_factory=lambda: AxisSpec(which="x"))
    y1_axis: AxisSpec = field(default_factory=lambda: AxisSpec(which="y1"))
    y2_axis: Optional[AxisSpec] = None
    z_axis: Optional[AxisSpec] = None
    layers: List[LayerSpec] = field(default_factory=list)
    insets: List[InsetSpec] = field(default_factory=list)
    guides: List[GuideSpec] = field(default_factory=list)
    equal_aspect: bool = False
    align_zero: bool = False
    legend_style: str = "corner_upper_left"
    box_linewidth_pt: float = 3.0
    share_x_with: Optional[str] = None
    share_y_with: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.coord = str(self.coord or "cartesian").strip().lower()
        if isinstance(self.x_axis, dict):
            self.x_axis = AxisSpec.from_dict(self.x_axis)
        if isinstance(self.y1_axis, dict):
            self.y1_axis = AxisSpec.from_dict(self.y1_axis)
        if isinstance(self.y2_axis, dict):
            self.y2_axis = AxisSpec.from_dict(self.y2_axis)
        if isinstance(self.z_axis, dict):
            self.z_axis = AxisSpec.from_dict(self.z_axis)
        self.layers = [
            ly if isinstance(ly, LayerSpec) else LayerSpec.from_dict(ly)
            for ly in self.layers
        ]
        self.insets = [
            ins if isinstance(ins, InsetSpec) else InsetSpec.from_dict(ins)
            for ins in self.insets
        ]
        self.guides = [
            gd if isinstance(gd, GuideSpec) else GuideSpec.from_dict(gd)
            for gd in self.guides
        ]
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.panel_id, str) or not self.panel_id.strip():
            raise ValueError("PanelSpec.panel_id must be a non-empty string.")
        if self.coord not in SUPPORTED_PANEL_COORDS:
            raise ValueError(
                f"PanelSpec.coord must be one of {SUPPORTED_PANEL_COORDS}, got {self.coord!r}"
            )
        if self.row < 0 or self.col < 0 or self.row_span < 1 or self.col_span < 1:
            raise ValueError(
                f"Invalid grid placement for panel '{self.panel_id}': row={self.row}, col={self.col}, "
                f"row_span={self.row_span}, col_span={self.col_span}"
            )
        if not self.layers:
            raise ValueError(f"PanelSpec '{self.panel_id}' must contain at least one LayerSpec.")
        self.x_axis.validate()
        self.y1_axis.validate()
        has_y2_layer = any(ly.y_axis == "y2" for ly in self.layers)
        if has_y2_layer and self.y2_axis is None:
            raise ValueError(
                f"PanelSpec '{self.panel_id}' has layer(s) on y_axis='y2' but `y2_axis` is None."
            )
        if self.y2_axis is not None:
            self.y2_axis.validate()
        if self.z_axis is not None:
            self.z_axis.validate()
        for ly in self.layers:
            ly.validate()
        for ins in self.insets:
            ins.validate()
        for gd in self.guides:
            gd.validate()

    def to_dict(self) -> Dict[str, Any]:
        return _to_jsonable(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PanelSpec":
        d = copy.deepcopy(data)
        allowed = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in allowed}
        return cls(**d)


@dataclass
class FigureSpec:
    title: str = "SciOrigin_Figure"
    mode: str = "chart_grammar"
    subtype: Optional[str] = None
    style_preset: str = ot.DEFAULT_STYLE_PRESET
    journal_spec: Optional[str] = None
    theme: Dict[str, Any] = field(default_factory=dict)
    nrows: int = 1
    ncols: int = 1
    width_ratios: List[float] = field(default_factory=lambda: [1.0])
    height_ratios: List[float] = field(default_factory=lambda: [1.0])
    width_mm: float = 140.0
    height_mm: float = 108.0
    panels: List[PanelSpec] = field(default_factory=list)
    output_dir: Optional[str] = None
    build_opju: bool = True
    template_override: Optional[str] = None
    summary_metrics: Dict[str, Any] = field(default_factory=dict)
    audit_notes: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.panels = [
            p if isinstance(p, PanelSpec) else PanelSpec.from_dict(p)
            for p in self.panels
        ]
        self.width_ratios = [float(r) for r in self.width_ratios]
        self.height_ratios = [float(r) for r in self.height_ratios]
        if not self.theme:
            self.theme = ot.load_theme(self.style_preset)
        if self.journal_spec:
            self.theme = ot.apply_journal_spec(self.theme, self.journal_spec)
            self.journal_spec = str(self.theme.get("journal_spec") or self.journal_spec)
            if self.journal_spec != "presentation_4_3" and "width_mm" in self.theme and "height_mm" in self.theme:
                if (self.width_mm, self.height_mm) == (140.0, 108.0):
                    self.width_mm = float(self.theme["width_mm"])
                    self.height_mm = float(self.theme["height_mm"])
        if self.meta is None:
            self.meta = {}
        self.validate()

    def validate(self) -> None:
        if self.nrows < 1 or self.ncols < 1:
            raise ValueError(f"FigureSpec grid must be >= 1x1, got {self.nrows}x{self.ncols}")
        if len(self.width_ratios) != self.ncols:
            raise ValueError(
                f"len(width_ratios)={len(self.width_ratios)} must match ncols={self.ncols}"
            )
        if len(self.height_ratios) != self.nrows:
            raise ValueError(
                f"len(height_ratios)={len(self.height_ratios)} must match nrows={self.nrows}"
            )
        if not self.panels:
            raise ValueError("FigureSpec.panels must contain at least one PanelSpec.")
        seen_ids: set[str] = set()
        for p in self.panels:
            p.validate()
            if p.panel_id in seen_ids:
                raise ValueError(f"Duplicate panel_id {p.panel_id!r} in FigureSpec.")
            seen_ids.add(p.panel_id)
            if p.row + p.row_span > self.nrows or p.col + p.col_span > self.ncols:
                raise ValueError(
                    f"Panel '{p.panel_id}' span (row={p.row}+{p.row_span}, col={p.col}+{p.col_span}) "
                    f"exceeds FigureSpec grid ({self.nrows}x{self.ncols})."
                )

    def to_dict(self) -> Dict[str, Any]:
        d = _to_jsonable(self.__dict__)
        if self.summary_metrics and "metrics" not in d:
            d["metrics"] = _to_jsonable(self.summary_metrics)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FigureSpec":
        d = copy.deepcopy(data)
        if "metrics" in d and not d.get("summary_metrics"):
            d["summary_metrics"] = d.pop("metrics")
        else:
            d.pop("metrics", None)
        allowed = set(cls.__dataclass_fields__.keys())
        d = {k: v for k, v in d.items() if k in allowed}
        return cls(**d)


# ---------------------------------------------------------------------------
# Internal Helpers for Table Binding, Normalization & Kinetics Compilation
# ---------------------------------------------------------------------------


def _extract_column_from_table(table_obj: Any, col_spec: Any) -> Optional[List[Any]]:
    """Extract a column list from a pandas DataFrame or dict-of-lists if available."""
    if table_obj is None or col_spec is None:
        return None
    # pandas DataFrame duck-typing (without importing pandas eagerly if not needed)
    if hasattr(table_obj, "iloc") and hasattr(table_obj, "columns"):
        if isinstance(col_spec, int):
            return table_obj.iloc[:, col_spec].tolist()
        col_str = str(col_spec).strip()
        if col_str in table_obj.columns:
            return table_obj[col_str].tolist()
        trimmed_map = {str(c).strip(): c for c in table_obj.columns}
        if col_str in trimmed_map:
            return table_obj[trimmed_map[col_str]].tolist()
        raise KeyError(f"Column {col_spec!r} not found in DataFrame columns {list(table_obj.columns)}")
    if isinstance(table_obj, dict):
        if col_spec in table_obj:
            val = table_obj[col_spec]
            return val.tolist() if hasattr(val, "tolist") else list(val)
    return None


def _lookup_loaded_table(loaded_tables: Optional[Dict[str, Any]], *keys: Optional[str]) -> Any:
    if not loaded_tables:
        return None
    for k in keys:
        if k and k in loaded_tables:
            return loaded_tables[k]
    return None


def _normalize_stacks_to_100pct(stacks_values: List[List[float]]) -> List[List[float]]:
    """Normalize positive row sums across stacked series to 0-100%; raise explicitly on negative or zero-sum rows."""
    n_cats = len(stacks_values[0])
    n_stacks = len(stacks_values)
    normed: List[List[float]] = [[] for _ in range(n_stacks)]
    for c_idx in range(n_cats):
        row_vals = [stacks_values[s_idx][c_idx] for s_idx in range(n_stacks)]
        if any(v < -1e-9 for v in row_vals):
            raise ValueError(
                f"100% stacked bar requires non-negative values; category index {c_idx} has {row_vals}"
            )
        clamped = [max(0.0, v) for v in row_vals]
        row_sum = sum(clamped)
        if row_sum <= 1e-12:
            raise ValueError(
                f"Zero-sum row at category index {c_idx} cannot be normalized to 100%."
            )
        for s_idx in range(n_stacks):
            normed[s_idx].append(round((clamped[s_idx] / row_sum) * 100.0, 6))
    return normed


def _build_guides_from_cfg(guides_cfg: Sequence[Dict[str, Any]], theme: Dict[str, Any]) -> List[GuideSpec]:
    out: List[GuideSpec] = []
    default_lw = float(theme.get("guide_linewidth", 2.8))
    default_fs = float(theme.get("title_annot_size", 20.0))
    default_y_frac = float(theme.get("peak_shoulder_y_frac", 0.77))
    for g in guides_cfg:
        raw_kind = str(g.get("kind", "vline")).lower()
        if raw_kind in ("vspan_arrow", "vspan", "vertical_span"):
            kind = "span_v"
        elif raw_kind in ("hspan_arrow", "hspan", "horizontal_span"):
            kind = "span_h"
        elif raw_kind in ("bracket", "significance_bracket", "stat_bracket"):
            kind = "sig_bracket"
        elif raw_kind in ("slope", "power_slope", "slope_guide", "slope_triangle"):
            kind = "slope_triangle"
        else:
            kind = raw_kind
        val = g.get("value", g.get("slope", g.get("y_bar", g.get("pos"))))
        start_v = g.get("start", g.get("y_start") if kind != "slope_triangle" else None)
        end_v = g.get("end", g.get("y_end") if kind == "span_v" else None)
        anchor_v = g.get("anchor_pos", g.get("x") if kind == "span_v" else None)
        x_val = g.get("x", g.get("x_start", g.get("x1", anchor_v if kind == "span_v" else None)))
        x2_val = g.get("x2", g.get("x_end") if kind in ("sig_bracket", "slope_triangle") else None)
        y_val = g.get("y", g.get("y_start") if kind == "slope_triangle" else None)
        ls = g.get("line_style", g.get("linestyle", "dashed" if kind in ("vline", "hline") else "solid"))
        default_col = "#111111" if kind in ("sig_bracket", "slope_triangle") else "#3E86DE"
        default_kind_lw = 1.6 if kind in ("sig_bracket", "slope_triangle") else (1.8 if kind.startswith("span") else default_lw)
        out.append(
            GuideSpec(
                kind=kind,
                axis=g.get("axis", "y1"),
                value=val,
                start=start_v,
                end=end_v,
                anchor_pos=anchor_v,
                x=x_val,
                x2=x2_val,
                y=y_val,
                x_end=g.get("x_end"),
                y_end=g.get("y_end") if kind != "span_v" else None,
                tip_drop=g.get("tip_drop"),
                label=str(g.get("label", "")),
                color=g.get("color", default_col),
                line_style=ls,
                line_width_pt=float(g.get("line_width_pt", default_kind_lw)),
                font_size_pt=float(g.get("font_size_pt", default_fs)),
                shoulder_y_frac=float(g.get("shoulder_y_frac", default_y_frac)),
                label_side=g.get("label_side", "right"),
                meta=dict(g.get("meta") or {}),
            )
        )
    return out


def _compute_inline_dq_dv(
    capacity: Sequence[float],
    voltage: Sequence[float],
    min_dv: float = 2e-3,
) -> Tuple[List[float], List[float], List[float]]:
    """Pure-Python monotonic-binned finite-difference dQ/dV fallback when raw arrays are inline."""
    q_arr = [float(v) for v in capacity]
    v_arr = [float(v) for v in voltage]
    if len(q_arr) < 4 or len(q_arr) != len(v_arr):
        raise ValueError("Inline dQ/dV computation requires matching capacity & voltage arrays of length >= 4.")
    # Keep monotonic voltage step points >= min_dv to prevent division-by-zero spikes
    kept_q = [q_arr[0]]
    kept_v = [v_arr[0]]
    direction = -1.0 if v_arr[-1] < v_arr[0] else 1.0
    for q_i, v_i in zip(q_arr[1:], v_arr[1:]):
        if (v_i - kept_v[-1]) * direction >= min_dv:
            kept_q.append(q_i)
            kept_v.append(v_i)
    if len(kept_v) < 3:
        raise ValueError("Voltage array does not span enough monotonic steps above min_dv for dQ/dV.")
    v_mid: List[float] = []
    dqdv: List[float] = []
    for i in range(len(kept_v) - 1):
        dv = kept_v[i + 1] - kept_v[i]
        dq = kept_q[i + 1] - kept_q[i]
        v_mid.append(0.5 * (kept_v[i] + kept_v[i + 1]))
        dqdv.append(dq / dv)
    # 3-point moving smooth if >= 5 points
    if len(dqdv) >= 5:
        smoothed = [dqdv[0]]
        for i in range(1, len(dqdv) - 1):
            smoothed.append(0.25 * dqdv[i - 1] + 0.5 * dqdv[i] + 0.25 * dqdv[i + 1])
        smoothed.append(dqdv[-1])
        dqdv = smoothed
    # Locate dominant local extremum by |dQ/dV|
    peak_idx = max(range(len(dqdv)), key=lambda idx: abs(dqdv[idx]))
    peaks = [round(v_mid[peak_idx], 4)]
    return v_mid, dqdv, peaks


# ---------------------------------------------------------------------------
# Mode Compilers
# ---------------------------------------------------------------------------


def _compile_bar_grouped_gradient(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    clean_prefix = bool(cfg.get("clean_sample_prefix", theme.get("clean_sample_prefix", True)))
    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")

    raw_cats = cfg.get("categories")
    if raw_cats is None and isinstance(tbl, dict) and "categories" in tbl:
        raw_cats = tbl["categories"]
    elif raw_cats is None and tbl is not None and cfg.get("x_col") is not None:
        raw_cats = _extract_column_from_table(tbl, cfg.get("x_col"))
    categories = [ot.clean_semantic_sample_name(str(c), clean_prefix) for c in raw_cats] if raw_cats is not None else None

    raw_series_list = cfg.get("series", [])
    if not raw_series_list and isinstance(tbl, dict) and "series" in tbl:
        raw_series_list = tbl["series"]
    if not raw_series_list:
        raise ValueError("Mode 'bar_grouped_gradient' requires non-empty `series`.")

    scheme = cfg.get("color_scheme", "paired_semantic")
    roles = [s.get("role") for s in raw_series_list]
    resolved_colors = ot.resolve_series_colors(len(raw_series_list), roles=roles, scheme=scheme)

    total_bars = len(raw_series_list) * (len(categories) if categories else 4)
    bar_cfg = theme.get("bar_style", {}).get("grouped_gradient", {})
    max_full_bars = int(bar_cfg.get("max_bars_for_full_label_size", 7))
    label_pt = float(
        cfg.get(
            "value_label_size_pt",
            bar_cfg.get("value_label_size_pt", 22.0)
            if total_bars <= max_full_bars
            else bar_cfg.get("dense_value_label_size_pt", 16.0),
        )
    )
    show_vals_default = bool(cfg.get("show_value_labels", True))

    compiled_series: List[SeriesSpec] = []
    for idx, s_item in enumerate(raw_series_list):
        s_tbl = _lookup_loaded_table(loaded_tables, s_item.get("table_key"), s_item.get("file")) or tbl
        vals = s_item.get("values", s_item.get("y"))
        if vals is None and s_tbl is not None and s_item.get("y_col") is not None:
            vals = _extract_column_from_table(s_tbl, s_item["y_col"])
        errs = s_item.get("errors", s_item.get("y_err"))
        if errs is None and s_tbl is not None and s_item.get("y_err_col") is not None:
            errs = _extract_column_from_table(s_tbl, s_item["y_err_col"])

        c_hex = ot.normalize_hex(s_item["color"]) if s_item.get("color") else resolved_colors[idx]
        grad_info = ot.compute_gradient_pair_and_label_color(c_hex)

        s_meta: Dict[str, Any] = dict(s_item.get("meta", {}))
        # Single-series multi-sample semantic per-bar colors (e.g. Raman ID/IG across samples)
        if len(raw_series_list) == 1 and (
            s_item.get("bar_colors") or s_item.get("bar_roles") or cfg.get("per_bar_semantic", True)
        ):
            n_bars = len(vals) if vals is not None else (len(categories) if categories is not None else 0)
            if n_bars > 0:
                if s_item.get("bar_colors"):
                    b_cols = [ot.normalize_hex(bc) for bc in s_item["bar_colors"]]
                else:
                    b_roles = s_item.get("bar_roles")
                    b_scheme = "sequential_blue_red" if n_bars > 6 and not b_roles else scheme
                    b_cols = ot.resolve_series_colors(n_bars, roles=b_roles, scheme=b_scheme)
                b_grads = [ot.compute_gradient_pair_and_label_color(bc).to_dict() for bc in b_cols]
                s_meta["origin_diagonal_columns"] = True
                s_meta["bar_colors"] = b_cols
                s_meta["bar_gradients"] = b_grads
                s_meta["bar_label_colors"] = [bg["label_hex"] for bg in b_grads]

        src_ref = None
        if cfg.get("input_file") or s_item.get("file") or s_item.get("y_col") is not None:
            src_ref = {
                "file": s_item.get("file") or cfg.get("input_file"),
                "sheet": s_item.get("sheet", cfg.get("sheet", 0)),
                "x_col": s_item.get("x_col", cfg.get("x_col", 0)),
                "y_col": s_item.get("y_col"),
                "y_err_col": s_item.get("y_err_col"),
            }

        compiled_series.append(
            SeriesSpec(
                name=ot.clean_semantic_sample_name(s_item.get("name", f"Series {idx + 1}"), clean_prefix),
                x=categories if vals is not None and categories is not None else None,
                y=vals,
                y_err=errs,
                role=s_item.get("role"),
                color=c_hex,
                gradient_top_color=grad_info.top_hex,
                gradient_bottom_color=grad_info.bottom_hex,
                label_color=grad_info.label_hex,
                show_value_labels=bool(s_item.get("show_value_labels", show_vals_default)),
                value_format=s_item.get("value_format", cfg.get("value_format", "{:.2f}")),
                y_unit=s_item.get("y_unit", cfg.get("y_unit")),
                source_ref=src_ref,
                meta=s_meta,
            )
        )

    layer = LayerSpec(
        layer_id="bars_gradient",
        mark="bar_grouped_gradient",
        y_axis="y1",
        series=compiled_series,
        categories=categories,
        color_scheme=scheme,
        palette_colors=[s.color for s in compiled_series if s.color],
        edge_color=bar_cfg.get("edge_color", "#222222"),
        edge_linewidth_pt=float(bar_cfg.get("edge_linewidth_pt", 1.2)),
        show_value_labels=show_vals_default,
        value_label_size_pt=label_pt,
        origin_template="COLUMN",
        origin_plot_type=203,
    )

    x_ax = AxisSpec(
        which="x",
        label=cfg.get("x_label", ""),
        axis_kind="categorical",
        categories=categories,
    )
    y_ax = AxisSpec(
        which="y1",
        label=cfg.get("y_label", "Value"),
        unit=cfg.get("y_unit"),
        axis_kind="quantitative",
        scale=cfg.get("y_scale", "linear"),
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    guides = _build_guides_from_cfg(cfg.get("guides", []), theme)

    panel = PanelSpec(
        panel_id="panel_main",
        x_axis=x_ax,
        y1_axis=y_ax,
        layers=[layer],
        guides=guides,
        legend_style="none" if len(compiled_series) == 1 else cfg.get("legend_style", "corner_upper_left"),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
    )

    return FigureSpec(
        title=cfg.get("title", "Grouped_Gradient_Bar"),
        mode="bar_grouped_gradient",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=dict(cfg.get("meta") or {}),
    )


def _compile_bar_stacked_layer(
    cfg_block: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
    force_100pct: bool = False,
    y_axis: str = "y1",
    layer_id: str = "bars_stacked",
) -> Tuple[LayerSpec, Optional[List[str]]]:
    clean_prefix = bool(cfg_block.get("clean_sample_prefix", theme.get("clean_sample_prefix", True)))
    tbl = _lookup_loaded_table(loaded_tables, cfg_block.get("table_key"), cfg_block.get("input_file"), "main")

    raw_cats = cfg_block.get("categories")
    if raw_cats is None and isinstance(tbl, dict) and "categories" in tbl:
        raw_cats = tbl["categories"]
    elif raw_cats is None and tbl is not None and cfg_block.get("x_col") is not None:
        raw_cats = _extract_column_from_table(tbl, cfg_block.get("x_col"))
    categories = [ot.clean_semantic_sample_name(str(c), clean_prefix) for c in raw_cats] if raw_cats is not None else None

    raw_stacks = cfg_block.get("stacks", cfg_block.get("series", []))
    if not raw_stacks and isinstance(tbl, dict) and "stacks" in tbl:
        raw_stacks = tbl["stacks"]
    if not raw_stacks:
        raise ValueError("Stacked bar mode requires non-empty `stacks` (or `series`).")

    norm_100 = bool(force_100pct or cfg_block.get("normalize_100", False))
    scheme = cfg_block.get("color_scheme", "sandwich_stack")
    roles = [st.get("role") for st in raw_stacks]
    resolved_colors = ot.resolve_series_colors(len(raw_stacks), roles=roles, scheme=scheme)

    extracted_vals: List[Optional[List[float]]] = []
    for st in raw_stacks:
        v = st.get("values", st.get("y"))
        if v is None and tbl is not None and st.get("y_col") is not None:
            v = _extract_column_from_table(tbl, st["y_col"])
        extracted_vals.append(_as_float_list(v, f"stack[{st.get('name', '?')}]") if v is not None else None)

    if norm_100 and all(v is not None for v in extracted_vals):
        typed_vals = [v for v in extracted_vals if v is not None]
        normed_matrix = _normalize_stacks_to_100pct(typed_vals)
        extracted_vals = [row for row in normed_matrix]

    stack_style = theme.get("bar_style", {}).get("stacked_flat", {})
    compiled_stacks: List[SeriesSpec] = []
    for idx, st in enumerate(raw_stacks):
        c_hex = ot.normalize_hex(st["color"]) if st.get("color") else resolved_colors[idx]
        vals = extracted_vals[idx]
        src_ref = None
        if cfg_block.get("input_file") or st.get("file") or st.get("y_col") is not None:
            src_ref = {
                "file": st.get("file") or cfg_block.get("input_file"),
                "sheet": st.get("sheet", cfg_block.get("sheet", 0)),
                "x_col": st.get("x_col", cfg_block.get("x_col", 0)),
                "y_col": st.get("y_col"),
            }
        compiled_stacks.append(
            SeriesSpec(
                name=str(st.get("name", f"Component {idx + 1}")),
                x=categories if vals is not None and categories is not None else None,
                y=vals,
                role=st.get("role"),
                color=c_hex,
                gradient_top_color=None,
                gradient_bottom_color=None,
                label_color=ot.compute_gradient_pair_and_label_color(c_hex).label_hex,
                y_unit="%" if norm_100 else st.get("y_unit", cfg_block.get("y_unit")),
                source_ref=src_ref,
            )
        )

    mark_name = "bar_stacked_100pct" if norm_100 else "bar_stacked"
    layer = LayerSpec(
        layer_id=layer_id,
        mark=mark_name,
        y_axis=y_axis,
        series=compiled_stacks,
        categories=categories,
        color_scheme=scheme,
        palette_colors=[s.color for s in compiled_stacks if s.color],
        normalize_100=norm_100,
        divider_color=stack_style.get("divider_color", "#FFFFFF"),
        divider_linewidth_pt=float(stack_style.get("divider_linewidth_pt", 0.8)),
        edge_color="#FFFFFF",
        edge_linewidth_pt=0.8,
        show_ribbon_links=bool(cfg_block.get("show_ribbon_links", cfg_block.get("ribbon_links", False))),
        origin_template="StackColP" if norm_100 else "STACKCOLUMN",
        origin_plot_type=213,
    )
    return layer, categories


def _compile_bar_stacked(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
    force_100pct: bool = False,
) -> FigureSpec:
    layer, categories = _compile_bar_stacked_layer(cfg, theme, loaded_tables, force_100pct=force_100pct)
    norm_100 = layer.normalize_100
    default_ylim = (0.0, 100.0) if norm_100 else None
    ylim = tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else default_ylim

    x_ax = AxisSpec(
        which="x",
        label=cfg.get("x_label", ""),
        axis_kind="categorical",
        categories=categories,
    )
    y_ax = AxisSpec(
        which="y1",
        label=cfg.get("y_label", "Fraction (%)" if norm_100 else "Value"),
        unit="%" if norm_100 else cfg.get("y_unit"),
        axis_kind="quantitative",
        scale=cfg.get("y_scale", "linear"),
        limits=ylim,
    )
    panel = PanelSpec(
        panel_id="panel_main",
        x_axis=x_ax,
        y1_axis=y_ax,
        layers=[layer],
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        legend_style=cfg.get("legend_style", "corner_upper_left"),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
    )
    mode_name = "bar_stacked_100pct" if force_100pct else "bar_stacked"
    return FigureSpec(
        title=cfg.get("title", "Stacked_Column_100Pct" if norm_100 else "Stacked_Column"),
        mode=mode_name,
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=dict(cfg.get("meta") or {}),
    )


def _compile_line_scatter_layer(
    block: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
    y_axis: str = "y1",
    layer_id: str = "curves_1",
    shared_x: Optional[List[Any]] = None,
    foreground_over_bars: bool = False,
) -> LayerSpec:
    clean_prefix = bool(block.get("clean_sample_prefix", theme.get("clean_sample_prefix", True)))
    tbl = _lookup_loaded_table(loaded_tables, block.get("table_key"), block.get("input_file"), "main")
    raw_series = block.get("series", block.get("curves", []))
    if not raw_series:
        raise ValueError(f"Line/scatter layer '{layer_id}' requires non-empty `series` (or `curves`).")

    # Optional physical-relevance element filter (e.g. filter C 1s dual-Y lines to ['F', 'C'])
    relevant_elements = block.get("relevant_elements")
    if relevant_elements:
        rel_tokens = {str(el).strip().lower() for el in relevant_elements}
        filtered = [
            s for s in raw_series
            if any(
                str(s.get("element", "")).strip().lower() == tok
                or str(s.get("name", "")).strip().lower().startswith(tok)
                for tok in rel_tokens
            )
        ]
        if filtered:
            raw_series = filtered

    default_scheme = (
        "sequential_blue_red"
        if len(raw_series) > 5 and block.get("sequential", True)
        else block.get("color_scheme", "paired_semantic")
    )
    if foreground_over_bars and "color_scheme" not in block:
        # High-contrast dark foreground colors over stacked bars (#A02333 wine, #111111 ink, #3E86DE blue)
        fg_defaults = ["#A02333", "#111111", "#3E86DE", "#6579BE"]
        resolved_colors = [fg_defaults[i % len(fg_defaults)] for i in range(len(raw_series))]
    else:
        roles = [s.get("role") for s in raw_series]
        resolved_colors = ot.resolve_series_colors(len(raw_series), roles=roles, scheme=default_scheme)

    default_lw = float(theme.get("curve_linewidth", 3.0))
    default_marker = "circle_solid" if foreground_over_bars else block.get("marker_style", "circle_solid")

    compiled: List[SeriesSpec] = []
    for idx, s_item in enumerate(raw_series):
        s_tbl = _lookup_loaded_table(loaded_tables, s_item.get("table_key"), s_item.get("file")) or tbl
        xv = s_item.get("x", shared_x)
        if xv is None and s_tbl is not None and (s_item.get("x_col") is not None or block.get("x_col") is not None):
            xv = _extract_column_from_table(s_tbl, s_item.get("x_col", block.get("x_col")))
        yv = s_item.get("y", s_item.get("values"))
        if yv is None and s_tbl is not None and s_item.get("y_col") is not None:
            yv = _extract_column_from_table(s_tbl, s_item["y_col"])
        yerr = s_item.get("y_err", s_item.get("errors"))
        if yerr is None and s_tbl is not None and s_item.get("y_err_col") is not None:
            yerr = _extract_column_from_table(s_tbl, s_item["y_err_col"])

        c_hex = ot.normalize_hex(s_item["color"]) if s_item.get("color") else resolved_colors[idx]
        m_style = s_item.get("marker_style", default_marker)
        l_style = s_item.get("line_style", "solid")

        src_ref = None
        if block.get("input_file") or s_item.get("file") or s_item.get("y_col") is not None:
            src_ref = {
                "file": s_item.get("file") or block.get("input_file"),
                "sheet": s_item.get("sheet", block.get("sheet", 0)),
                "x_col": s_item.get("x_col", block.get("x_col", 0)),
                "y_col": s_item.get("y_col"),
                "y_err_col": s_item.get("y_err_col"),
            }

        compiled.append(
            SeriesSpec(
                name=ot.clean_semantic_sample_name(s_item.get("name", f"Curve {idx + 1}"), clean_prefix),
                x=xv,
                y=yv,
                y_err=yerr,
                y_low=s_item.get("y_low"),
                y_high=s_item.get("y_high"),
                role=s_item.get("role"),
                color=c_hex,
                label_color=ot.compute_gradient_pair_and_label_color(c_hex).label_hex,
                line_style=l_style,
                line_width_pt=float(s_item.get("line_width_pt", default_lw)),
                marker_style=m_style,
                marker_size_pt=float(s_item.get("marker_size_pt", 7.5)),
                fill_alpha=s_item.get("fill_alpha"),
                x_unit=s_item.get("x_unit", block.get("x_unit")),
                y_unit=s_item.get("y_unit", block.get("y_unit")),
                source_ref=src_ref,
                meta=dict(s_item.get("meta", {})),
            )
        )

    has_markers = any(s.marker_style != "none" for s in compiled)
    has_lines = any(s.line_style != "none" for s in compiled)
    plot_id = 202 if (has_markers and has_lines) else (201 if has_markers else 200)

    return LayerSpec(
        layer_id=layer_id,
        mark="line_scatter",
        y_axis=y_axis,
        series=compiled,
        color_scheme=default_scheme,
        palette_colors=[s.color for s in compiled if s.color],
        origin_plot_type=plot_id,
    )


def _compute_auto_zero_aligned_limits(layer: LayerSpec, default_top_pad: float = 1.12) -> Optional[Tuple[float, float]]:
    if layer.mark == "bar_stacked_100pct":
        return (0.0, 100.0)
    if layer.mark == "bar_stacked":
        if all(s.y is not None for s in layer.series):
            n_pts = len(layer.series[0].y or [])
            totals = [sum((s.y or [0.0])[i] for s in layer.series) for i in range(n_pts)]
            if totals:
                return (0.0, max(totals) * default_top_pad)
        return None
    all_vals: List[float] = []
    for s in layer.series:
        if s.y:
            all_vals.extend(s.y)
    if not all_vals:
        return None
    min_v, max_v = min(all_vals), max(all_vals)
    if min_v >= 0.0:
        hi = max_v * default_top_pad if max_v > 0 else 1.0
        return (0.0, round(hi, 6))
    return None


def _compile_dual_y_combo(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    clean_prefix = bool(cfg.get("clean_sample_prefix", theme.get("clean_sample_prefix", True)))
    align_zero = bool(cfg.get("align_zero", True))
    shared_x = cfg.get("x", cfg.get("categories"))
    if shared_x is not None and all(isinstance(v, str) for v in shared_x):
        shared_x = [ot.clean_semantic_sample_name(v, clean_prefix) for v in shared_x]

    left_cfg = dict(cfg.get("left_y", {}))
    right_cfg = dict(cfg.get("right_y", {}))
    if not left_cfg or not right_cfg:
        raise ValueError("Mode 'dual_y_combo' requires both `left_y` and `right_y` blocks.")

    for side_cfg in (left_cfg, right_cfg):
        if "input_file" not in side_cfg and "input_file" in cfg:
            side_cfg["input_file"] = cfg["input_file"]
        if "sheet" not in side_cfg and "sheet" in cfg:
            side_cfg["sheet"] = cfg["sheet"]
        if "x_col" not in side_cfg and "x_col" in cfg:
            side_cfg["x_col"] = cfg["x_col"]
        if shared_x is not None and "categories" not in side_cfg and all(isinstance(v, str) for v in shared_x):
            side_cfg["categories"] = shared_x

    left_geom = str(left_cfg.get("geom", left_cfg.get("mark", "line_scatter"))).lower()
    right_geom = str(right_cfg.get("geom", right_cfg.get("mark", "line_scatter"))).lower()
    has_bar_bg = any("bar" in g for g in (left_geom, right_geom))

    def _build_side_layer(side_block: Dict[str, Any], y_target: str, lid: str) -> Tuple[LayerSpec, Optional[List[str]]]:
        geom = str(side_block.get("geom", side_block.get("mark", "line_scatter"))).lower()
        if geom in ("bar_stacked", "bar_stacked_100pct"):
            return _compile_bar_stacked_layer(
                side_block,
                theme,
                loaded_tables,
                force_100pct=(geom == "bar_stacked_100pct"),
                y_axis=y_target,
                layer_id=lid,
            )
        if geom == "bar_grouped_gradient":
            sub_fig = _compile_bar_grouped_gradient(
                {**side_block, "output_dir": cfg.get("output_dir")}, theme, loaded_tables
            )
            ly = sub_fig.panels[0].layers[0]
            ly.y_axis = y_target
            ly.layer_id = lid
            return ly, ly.categories
        ly_line = _compile_line_scatter_layer(
            side_block,
            theme,
            loaded_tables,
            y_axis=y_target,
            layer_id=lid,
            shared_x=shared_x,
            foreground_over_bars=has_bar_bg,
        )
        cats = [str(v) for v in shared_x] if shared_x and all(isinstance(v, str) for v in shared_x) else None
        return ly_line, cats

    left_layer, left_cats = _build_side_layer(left_cfg, "y1", "left_y1_layer")
    right_layer, right_cats = _build_side_layer(right_cfg, "y2", "right_y2_layer")

    # Render stacked/bar layers behind foreground line_scatter layers!
    # Identify which side is the stacked-bar background.
    _right_is_bar_bg = "bar" in right_layer.mark and left_layer.mark == "line_scatter"
    _left_is_bar_bg  = "bar" in left_layer.mark  and right_layer.mark == "line_scatter"
    ordered_layers = (
        [right_layer, left_layer]
        if _right_is_bar_bg
        else [left_layer, right_layer]
    )

    # Soften stacked/bar background palette lightly (8% white) so segments remain crisp and distinct
    # while foreground lines (#A02333, #111111) stand out clearly.
    _WHITE_SOFTEN = 0.08
    if _right_is_bar_bg or _left_is_bar_bg:
        _bar_layer = right_layer if _right_is_bar_bg else left_layer
        for _s in _bar_layer.series:
            if _s.color:
                _s.color = ot.mix_hex(_s.color, "#FFFFFF", _WHITE_SOFTEN)
            if _s.gradient_top_color:
                _s.gradient_top_color = ot.mix_hex(_s.gradient_top_color, "#FFFFFF", _WHITE_SOFTEN)
            if _s.gradient_bottom_color:
                _s.gradient_bottom_color = ot.mix_hex(_s.gradient_bottom_color, "#FFFFFF", _WHITE_SOFTEN)

    cats = right_cats or left_cats
    is_categorical_x = cats is not None or has_bar_bg
    x_ax = AxisSpec(
        which="x",
        label=cfg.get("x_label", ""),
        unit=cfg.get("x_unit"),
        axis_kind="categorical" if is_categorical_x else "quantitative",
        scale=cfg.get("x_scale", "linear"),
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
        categories=cats,
    )

    left_color = ot.normalize_hex(left_cfg.get("axis_color", "#111111"))
    # Bind right Y axis color to explicit right_y.axis_color, or primary semantic color of right layer
    if right_cfg.get("axis_color"):
        right_color = ot.normalize_hex(right_cfg["axis_color"])
    elif right_layer.mark in ("bar_stacked", "bar_stacked_100pct"):
        right_color = "#3E86DE"
    else:
        right_color = right_layer.series[0].color or "#D84B5C"

    y1_lims = (
        tuple(left_cfg["limits"])
        if left_cfg.get("limits") is not None
        else (_compute_auto_zero_aligned_limits(left_layer) if align_zero else None)
    )
    y2_lims = (
        tuple(right_cfg["limits"])
        if right_cfg.get("limits") is not None
        else (_compute_auto_zero_aligned_limits(right_layer) if align_zero else None)
    )
    if align_zero:
        if y1_lims is not None and y1_lims[0] > 0:
            y1_lims = (0.0, y1_lims[1])
        if y2_lims is not None and y2_lims[0] > 0:
            y2_lims = (0.0, y2_lims[1])

    y1_ax = AxisSpec(
        which="y1",
        label=left_cfg.get("label", "Left Y"),
        unit=left_cfg.get("unit"),
        axis_kind="dual_y_left",
        scale=left_cfg.get("scale", "linear"),
        limits=y1_lims,
        color=left_color,
        align_zero=align_zero,
        tick_policy=ot.resolve_axis_tick_policy(
            "dual_y_left",
            left_cfg.get("scale", "linear"),
            left_axis_color=left_color,
            right_axis_color=right_color,
        ),
    )
    y2_ax = AxisSpec(
        which="y2",
        label=right_cfg.get("label", "Right Y"),
        unit=right_cfg.get("unit"),
        axis_kind="dual_y_right",
        scale=right_cfg.get("scale", "linear"),
        limits=y2_lims,
        color=right_color,
        align_zero=align_zero,
        tick_policy=ot.resolve_axis_tick_policy(
            "dual_y_right",
            right_cfg.get("scale", "linear"),
            right_axis_color=right_color,
            left_axis_color=left_color,
        ),
    )

    panel = PanelSpec(
        panel_id="panel_dual_y",
        x_axis=x_ax,
        y1_axis=y1_ax,
        y2_axis=y2_ax,
        layers=ordered_layers,
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        align_zero=align_zero,
        legend_style=cfg.get("legend_style", "interior_top_dual"),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
    )

    return FigureSpec(
        title=cfg.get("title", "Dual_Y_Combo"),
        mode="dual_y_combo",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=dict(cfg.get("meta") or {}),
    )


def _compile_curve_with_inset(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    main_block = cfg.get("main", cfg)
    main_layer = _compile_line_scatter_layer(
        main_block,
        theme,
        loaded_tables,
        y_axis="y1",
        layer_id="main_curves",
    )
    eq_aspect = bool(main_block.get("equal_aspect", cfg.get("equal_aspect", False)))

    x_lims = tuple(main_block["x_limits"]) if main_block.get("x_limits") is not None else None
    y_lims = tuple(main_block["y_limits"]) if main_block.get("y_limits") is not None else None
    eq_step: Optional[float] = None
    if eq_aspect and x_lims is None and y_lims is None:
        xs = [float(v) for s in main_layer.series for v in (s.x or []) if isinstance(v, (int, float))]
        ys = [float(v) for s in main_layer.series for v in (s.y or [])]
        if xs and ys:
            x_lims, y_lims, eq_step = compute_isometric_4_3_bounds(xs, ys)

    y_kind = main_block.get("y_axis_kind", "quantitative")
    x_ax = AxisSpec(
        which="x",
        label=main_block.get("x_label", cfg.get("x_label", "X")),
        unit=main_block.get("x_unit"),
        axis_kind="quantitative",
        scale=main_block.get("x_scale", "linear"),
        limits=x_lims,
        major_step=main_block.get("x_step", eq_step),
        invert=bool(main_block.get("invert_x", False)),
    )
    y_ax = AxisSpec(
        which="y1",
        label=main_block.get("y_label", cfg.get("y_label", "Y")),
        unit=main_block.get("y_unit"),
        axis_kind=y_kind,
        scale=main_block.get("y_scale", "linear"),
        limits=y_lims,
        major_step=main_block.get("y_step", eq_step),
    )

    raw_insets = cfg.get("insets")
    if raw_insets is None and cfg.get("inset") is not None:
        raw_insets = [cfg["inset"]]
    if not raw_insets:
        raise ValueError("Mode 'curve_with_inset' requires `insets` (or `inset`).")

    compiled_insets: List[InsetSpec] = []
    for idx, ins_cfg in enumerate(raw_insets):
        ins_mode = str(ins_cfg.get("mode", "zoom")).lower()
        bbox = tuple(ins_cfg.get("bbox_pct", [46.0, 8.0, 46.0, 44.0]))
        ins_eq = bool(ins_cfg.get("equal_aspect", eq_aspect if ins_mode == "zoom" else False))
        ins_xlim = tuple(ins_cfg["xlim"]) if ins_cfg.get("xlim") is not None else None
        ins_ylim = tuple(ins_cfg["ylim"]) if ins_cfg.get("ylim") is not None else None

        if ins_mode == "subchart":
            sub_block = ins_cfg.get("sub_spec", ins_cfg)
            sub_layer = _compile_line_scatter_layer(
                sub_block, theme, loaded_tables, y_axis="y1", layer_id=f"inset_{idx + 1}_sub"
            )
            ins_layers = [sub_layer]
            ins_x_label = sub_block.get("x_label", ins_cfg.get("x_label", ""))
            ins_y_label = sub_block.get("y_label", ins_cfg.get("y_label", ""))
        else:
            # Zoom mode clones main curves (with slightly smaller markers); include compact axis titles on large >=40% insets
            zoom_series = [copy.deepcopy(s) for s in main_layer.series]
            for zs in zoom_series:
                zs.marker_size_pt = max(3.5, zs.marker_size_pt * 0.72)
            ins_layers = [
                LayerSpec(
                    layer_id=f"inset_{idx + 1}_zoom",
                    mark="line_scatter",
                    y_axis="y1",
                    series=zoom_series,
                    color_scheme=main_layer.color_scheme,
                    palette_colors=list(main_layer.palette_colors),
                    origin_plot_type=main_layer.origin_plot_type,
                )
            ]
            default_ins_xl = x_ax.label if bbox[2] >= 40.0 else ""
            default_ins_yl = y_ax.label if bbox[3] >= 40.0 else ""
            ins_x_label = ins_cfg.get("x_label", default_ins_xl)
            ins_y_label = ins_cfg.get("y_label", default_ins_yl)

        compiled_insets.append(
            InsetSpec(
                inset_id=ins_cfg.get("inset_id", f"inset_{idx + 1}"),
                mode=ins_mode,
                bbox_pct=bbox,
                xlim=ins_xlim,
                ylim=ins_ylim,
                equal_aspect=ins_eq,
                show_zoom_box=bool(ins_cfg.get("show_zoom_box", ins_mode == "zoom")),
                zoom_box_color=ins_cfg.get("zoom_box_color", "#6579BE"),
                background_color="#FFFFFF",
                box_linewidth_pt=float(ins_cfg.get("box_linewidth_pt", 1.6)),
                x_axis=AxisSpec(
                    which="x",
                    label=ins_x_label,
                    axis_kind="inset",
                    scale=ins_cfg.get("x_scale", x_ax.scale if ins_mode == "zoom" else "linear"),
                    limits=ins_xlim,
                ),
                y_axis=AxisSpec(
                    which="y1",
                    label=ins_y_label,
                    axis_kind="inset",
                    scale=ins_cfg.get("y_scale", y_ax.scale if ins_mode == "zoom" else "linear"),
                    limits=ins_ylim,
                ),
                layers=ins_layers,
                guides=_build_guides_from_cfg(ins_cfg.get("guides", []), theme),
            )
        )

    panel = PanelSpec(
        panel_id="panel_main",
        x_axis=x_ax,
        y1_axis=y_ax,
        layers=[main_layer],
        insets=compiled_insets,
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        equal_aspect=eq_aspect,
        legend_style=cfg.get("legend_style", "corner_upper_left"),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
    )

    return FigureSpec(
        title=cfg.get("title", "Curve_With_Inset"),
        mode="curve_with_inset",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        width_mm=140.0,
        height_mm=108.0,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=dict(cfg.get("meta") or {}),
    )


def _compile_electrochem_kinetics(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    subtype = str(cfg.get("subtype", "pulse_align")).strip().lower()
    if subtype not in SUPPORTED_KINETICS_SUBTYPES:
        raise ValueError(
            f"Unsupported electrochem_kinetics subtype {subtype!r}; expected one of {SUPPORTED_KINETICS_SUBTYPES}"
        )

    if subtype == "pulse_align":
        pulse_block = copy.deepcopy(cfg)
        raw_curves = pulse_block.get("series", pulse_block.get("curves", []))
        # Apply inline zero-time shift if t_pulse_start is specified on raw curves
        t0_global = cfg.get("t_pulse_start")
        for c_item in raw_curves:
            t0 = c_item.get("t_pulse_start", t0_global)
            if t0 is not None and c_item.get("x") is not None and not c_item.get("already_aligned", False):
                c_item["x"] = [round(float(tv) - float(t0), 6) for tv in c_item["x"]]
        pulse_block["series"] = raw_curves
        if "marker_style" not in pulse_block:
            pulse_block["marker_style"] = "none"

        layer = _compile_line_scatter_layer(
            pulse_block, theme, loaded_tables, y_axis="y1", layer_id="pulse_curves"
        )
        guides = _build_guides_from_cfg(cfg.get("guides", []), theme)
        for sp in cfg.get("span_annotations", []):
            guides.append(
                GuideSpec(
                    kind=sp.get("kind", "span_v"),
                    axis="y1",
                    start=sp["start"],
                    end=sp["end"],
                    anchor_pos=sp.get("anchor_pos", sp.get("x", 0.0)),
                    label=str(sp.get("label", "")),
                    color=sp.get("color", "#D84B5C"),
                    line_style="solid",
                    line_width_pt=1.8,
                )
            )
        # Merge precomputed pulse decomposition guides from loaded_tables if available
        pulse_tbl = _lookup_loaded_table(loaded_tables, "pulse_decomposition", "main")
        summary_metrics: Dict[str, Any] = {}
        if isinstance(pulse_tbl, dict):
            for m_key in ("v_before", "v_instant", "v_pulse_end", "v_final", "delta_v0_app", "delta_v_slow_app"):
                if m_key in pulse_tbl:
                    summary_metrics[m_key] = pulse_tbl[m_key]
            if not guides and "guides" in pulse_tbl:
                guides.extend(_build_guides_from_cfg(pulse_tbl["guides"], theme))

        panel = PanelSpec(
            panel_id="panel_pulse",
            x_axis=AxisSpec(
                which="x",
                label=cfg.get("x_label", "Time (s)"),
                unit="s",
                axis_kind="quantitative",
                scale="linear",
                limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
            ),
            y1_axis=AxisSpec(
                which="y1",
                label=cfg.get("y_label", "Voltage (V)"),
                unit="V",
                axis_kind="quantitative",
                scale="linear",
                limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
            ),
            layers=[layer],
            guides=guides,
            legend_style=cfg.get("legend_style", "corner_upper_left"),
            box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        )
        return FigureSpec(
            title=cfg.get("title", "Short_Pulse_Voltage_Alignment"),
            mode="electrochem_kinetics",
            subtype="pulse_align",
            style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
            theme=theme,
            panels=[panel],
            output_dir=cfg.get("output_dir"),
            build_opju=bool(cfg.get("build_opju", True)),
            summary_metrics=summary_metrics,
        )

    if subtype == "galvanostatic_dqdv":
        qv_block = copy.deepcopy(cfg)
        if "marker_style" not in qv_block:
            qv_block["marker_style"] = "none"
        qv_layer = _compile_line_scatter_layer(
            qv_block, theme, loaded_tables, y_axis="y1", layer_id="galvanostatic_qv"
        )

        # Build dQ/dV series from explicit dqdv_series, loaded_tables, or inline Q-V arrays
        dqdv_raw = cfg.get("dqdv_series", [])
        dqdv_tbl = _lookup_loaded_table(loaded_tables, "dq_dv", "dqdv")
        peak_guides: List[GuideSpec] = _build_guides_from_cfg(cfg.get("dqdv_guides", []), theme)
        summary_peaks: Dict[str, List[float]] = {}

        if not dqdv_raw and isinstance(dqdv_tbl, dict) and "voltage_v" in dqdv_tbl and "dq_dv" in dqdv_tbl:
            dqdv_raw = [
                {
                    "name": qv_layer.series[0].name,
                    "x": dqdv_tbl["voltage_v"],
                    "y": dqdv_tbl["dq_dv"],
                    "color": qv_layer.series[0].color,
                }
            ]
            if dqdv_tbl.get("peak_positions"):
                summary_peaks[qv_layer.series[0].name] = list(dqdv_tbl["peak_positions"])

        if not dqdv_raw:
            derived_list: List[Dict[str, Any]] = []
            for s_qv in qv_layer.series:
                if s_qv.x is not None and s_qv.y is not None and len(s_qv.x) >= 4:
                    v_mid, dqdv_vals, pks = _compute_inline_dq_dv(
                        [float(v) for v in s_qv.x], s_qv.y
                    )
                    derived_list.append(
                        {"name": s_qv.name, "x": v_mid, "y": dqdv_vals, "color": s_qv.color}
                    )
                    summary_peaks[s_qv.name] = pks
                    if pks and not peak_guides:
                        peak_guides.append(
                            GuideSpec(
                                kind="vline",
                                value=pks[0],
                                label=f"{pks[0]:.2f} V",
                                color=s_qv.color or "#D84B5C",
                                line_style="dashed",
                            )
                        )
                else:
                    derived_list.append(
                        {
                            "name": s_qv.name,
                            "color": s_qv.color,
                            "file": (s_qv.source_ref or {}).get("file"),
                            "meta": {"derive": "compute_dq_dv"},
                        }
                    )
            dqdv_raw = derived_list

        dqdv_layer = _compile_line_scatter_layer(
            {"series": dqdv_raw, "marker_style": "none"},
            theme,
            loaded_tables,
            y_axis="y1",
            layer_id="differential_dqdv",
        )

        comp_profile = theme.get("composite_print_profile", {})
        box_lw = float(comp_profile.get("box_linewidth_pt", 2.2))
        panel_qv = PanelSpec(
            panel_id="panel_a_qv",
            tag="a",
            row=0,
            col=0,
            x_axis=AxisSpec(
                which="x",
                label=cfg.get("x_label", "Specific Capacity (mAh g^-1)"),
                unit="mAh g^-1",
                axis_kind="quantitative",
            ),
            y1_axis=AxisSpec(
                which="y1",
                label=cfg.get("y_label", "Voltage (V)"),
                unit="V",
                axis_kind="quantitative",
            ),
            layers=[qv_layer],
            guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
            box_linewidth_pt=box_lw,
        )
        panel_dqdv = PanelSpec(
            panel_id="panel_b_dqdv",
            tag="b",
            row=0,
            col=1,
            x_axis=AxisSpec(
                which="x",
                label=cfg.get("dqdv_x_label", "Voltage (V)"),
                unit="V",
                axis_kind="quantitative",
            ),
            y1_axis=AxisSpec(
                which="y1",
                label=cfg.get("dqdv_y_label", "dQ/dV (mAh g^-1 V^-1)"),
                unit="mAh g^-1 V^-1",
                axis_kind="quantitative",
            ),
            layers=[dqdv_layer],
            guides=peak_guides,
            box_linewidth_pt=box_lw,
        )
        return FigureSpec(
            title=cfg.get("title", "Galvanostatic_and_dQdV"),
            mode="electrochem_kinetics",
            subtype="galvanostatic_dqdv",
            style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
            theme=theme,
            nrows=1,
            ncols=2,
            width_ratios=[1.0, 1.0],
            height_ratios=[1.0],
            width_mm=180.0,
            height_mm=86.0,
            panels=[panel_qv, panel_dqdv],
            output_dir=cfg.get("output_dir"),
            build_opju=bool(cfg.get("build_opju", True)),
            summary_metrics={"dq_dv_peaks_V": summary_peaks} if summary_peaks else {},
        )

    # subtype == "ragone" (Double-log10 Energy vs Power density)
    ragone_block = copy.deepcopy(cfg)
    if "marker_style" not in ragone_block:
        ragone_block["marker_style"] = "sphere_3d"
    layer_ragone = _compile_line_scatter_layer(
        ragone_block, theme, loaded_tables, y_axis="y1", layer_id="ragone_curves"
    )
    panel_ragone = PanelSpec(
        panel_id="panel_ragone",
        x_axis=AxisSpec(
            which="x",
            label=cfg.get("x_label", "Power Density (W kg^-1)"),
            unit="W kg^-1",
            axis_kind="quantitative",
            scale="log10",
            limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
        ),
        y1_axis=AxisSpec(
            which="y1",
            label=cfg.get("y_label", "Energy Density (Wh kg^-1)"),
            unit="Wh kg^-1",
            axis_kind="quantitative",
            scale="log10",
            limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
        ),
        layers=[layer_ragone],
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        legend_style=cfg.get("legend_style", "corner_upper_left"),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
    )
    return FigureSpec(
        title=cfg.get("title", "Ragone_Energy_Power"),
        mode="electrochem_kinetics",
        subtype="ragone",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        panels=[panel_ragone],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
    )


def _compile_contour_pseudocolor_2d(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    mat_tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "matrix", "main")
    mx = cfg.get("matrix_x", cfg.get("x_grid"))
    my = cfg.get("matrix_y", cfg.get("y_grid"))
    mz = cfg.get("matrix_z", cfg.get("z_matrix"))

    if isinstance(mat_tbl, dict):
        if mx is None:
            mx = mat_tbl.get("matrix_x", mat_tbl.get("x_grid", mat_tbl.get("x")))
        if my is None:
            my = mat_tbl.get("matrix_y", mat_tbl.get("y_grid", mat_tbl.get("y")))
        if mz is None:
            mz = mat_tbl.get("matrix_z", mat_tbl.get("z_matrix"))

    src_ref = None
    if cfg.get("input_file") or cfg.get("matrix_file"):
        src_ref = {
            "file": cfg.get("matrix_file") or cfg.get("input_file"),
            "sheet": cfg.get("sheet", 0),
            "transpose": bool(cfg.get("transpose", False)),
        }

    is_diverging = bool(cfg.get("center_zero", cfg.get("diverging", False)))
    cmap_scheme = cfg.get(
        "color_scheme",
        "diverging_blue_white_red" if is_diverging else "pseudocolor_zero_white",
    )
    cmap_stops = (
        list(cfg["color_stops"])
        if cfg.get("color_stops")
        else (
            list(ot.DIVERGING_BLUE_WHITE_RED_STOPS)
            if cmap_scheme == "diverging_blue_white_red"
            else list(ot.PSEUDOCOLOR_ZERO_WHITE_STOPS)
        )
    )

    mat_series = SeriesSpec(
        name=cfg.get("field_name", "2D_Field"),
        matrix_x=mx,
        matrix_y=my,
        matrix_z=mz,
        color=cmap_stops[-1],
        x_unit=cfg.get("x_unit"),
        y_unit=cfg.get("y_unit"),
        z_unit=cfg.get("z_unit"),
        source_ref=src_ref,
        meta={"state_labels": cfg.get("state_labels") or (mat_tbl.get("state_labels") if isinstance(mat_tbl, dict) else None)},
    )
    contour_layer = LayerSpec(
        layer_id="contour_2d",
        mark="contour_pseudocolor",
        y_axis="y1",
        series=[mat_series],
        color_scheme=cmap_scheme,
        palette_colors=cmap_stops,
        z_levels_count=int(cfg.get("z_levels_count", 32)),
        hide_contour_lines=bool(cfg.get("hide_contour_lines", True)),
        origin_template="CONTOUR",
        origin_plot_type=226,
    )

    x_scale = "log10" if cfg.get("log_x", False) else cfg.get("x_scale", "linear")
    y_scale = "log10" if cfg.get("log_y", False) else cfg.get("y_scale", "linear")
    z_ax = AxisSpec(
        which="z",
        label=cfg.get("z_label", "Intensity (a.u.)"),
        unit=cfg.get("z_unit"),
        axis_kind="quantitative",
        limits=tuple(cfg["z_limits"]) if cfg.get("z_limits") is not None else None,
    )

    side_cfg = cfg.get("side_panel")
    if not side_cfg:
        panel_2d = PanelSpec(
            panel_id="panel_contour",
            x_axis=AxisSpec(
                which="x",
                label=cfg.get("x_label", "X"),
                unit=cfg.get("x_unit"),
                axis_kind="quantitative",
                scale=x_scale,
                invert=bool(cfg.get("invert_x", False)),
                limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
            ),
            y1_axis=AxisSpec(
                which="y1",
                label=cfg.get("y_label", "State / Time"),
                unit=cfg.get("y_unit"),
                axis_kind="quantitative",
                scale=y_scale,
                categories=cfg.get("state_labels"),
                limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
            ),
            z_axis=z_ax,
            layers=[contour_layer],
            guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
            legend_style="none",
            box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        )
        return FigureSpec(
            title=cfg.get("title", "Contour_Pseudocolor_2D"),
            mode="contour_pseudocolor_2d",
            style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
            theme=theme,
            panels=[panel_2d],
            output_dir=cfg.get("output_dir"),
            build_opju=bool(cfg.get("build_opju", True)),
            template_override=cfg.get("template_override"),
        )

    # Coupled 1D side_panel + 2D contour_pseudocolor panel
    pos = str(side_cfg.get("position", side_cfg.get("pos", "left"))).lower()
    if pos not in ("left", "right"):
        raise ValueError(f"side_panel.position must be 'left' or 'right', got {pos!r}")

    side_series_cfg = side_cfg.get("series")
    if not side_series_cfg:
        side_series_cfg = [
            {
                "name": side_cfg.get("name", "Coupled Profile"),
                "x": side_cfg.get("x"),
                "y": side_cfg.get("y"),
                "file": side_cfg.get("file"),
                "x_col": side_cfg.get("x_col", 0),
                "y_col": side_cfg.get("y_col", 1),
                "color": side_cfg.get("color", "#3E86DE"),
            }
        ]
    side_layer = _compile_line_scatter_layer(
        {"series": side_series_cfg, "marker_style": side_cfg.get("marker_style", "none")},
        theme,
        loaded_tables,
        y_axis="y1",
        layer_id="side_1d_curve",
    )

    comp_lw = float(theme.get("composite_print_profile", {}).get("box_linewidth_pt", 2.2))
    side_col = 0 if pos == "left" else 1
    contour_col = 1 if pos == "left" else 0
    w_ratios = [0.32, 0.68] if pos == "left" else [0.68, 0.32]

    panel_side = PanelSpec(
        panel_id="panel_side_1d",
        tag="a" if side_col == 0 else "b",
        row=0,
        col=side_col,
        x_axis=AxisSpec(
            which="x",
            label=side_cfg.get("x_label", side_cfg.get("label", "Voltage (V)")),
            axis_kind="quantitative",
            invert=bool(side_cfg.get("invert_x", False)),
        ),
        y1_axis=AxisSpec(
            which="y1",
            label=side_cfg.get("y_label", cfg.get("y_label", "State / Time")),
            axis_kind="quantitative",
            scale=y_scale,
        ),
        layers=[side_layer],
        share_y_with="panel_contour" if side_col == 1 else None,
        legend_style="none",
        box_linewidth_pt=comp_lw,
    )
    panel_contour = PanelSpec(
        panel_id="panel_contour",
        tag="b" if contour_col == 1 else "a",
        row=0,
        col=contour_col,
        x_axis=AxisSpec(
            which="x",
            label=cfg.get("x_label", "X"),
            unit=cfg.get("x_unit"),
            axis_kind="quantitative",
            scale=x_scale,
            invert=bool(cfg.get("invert_x", False)),
        ),
        y1_axis=AxisSpec(
            which="y1",
            label=cfg.get("y_label", "State / Time"),
            unit=cfg.get("y_unit"),
            axis_kind="quantitative",
            scale=y_scale,
        ),
        z_axis=z_ax,
        layers=[contour_layer],
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        share_y_with="panel_side_1d" if contour_col == 1 else None,
        legend_style="none",
        box_linewidth_pt=comp_lw,
    )
    ordered_panels = [panel_side, panel_contour] if pos == "left" else [panel_contour, panel_side]
    return FigureSpec(
        title=cfg.get("title", "InSitu_Contour_With_SidePanel"),
        mode="contour_pseudocolor_2d",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        theme=theme,
        nrows=1,
        ncols=2,
        width_ratios=w_ratios,
        height_ratios=[1.0],
        width_mm=180.0,
        height_mm=96.0,
        panels=ordered_panels,
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=dict(cfg.get("meta") or {}),
    )


def _compile_universal_chart_grammar(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile general multi-panel / multi-layer `mode == 'chart_grammar'` configurations."""
    raw_panels = cfg.get("panels", [])
    if not raw_panels:
        raise ValueError("Mode 'chart_grammar' requires non-empty `panels` list.")

    nrows = int(cfg.get("nrows", 1))
    ncols = int(cfg.get("ncols", len(raw_panels) if nrows == 1 else 1))
    w_ratios = [float(r) for r in cfg.get("width_ratios", [1.0] * ncols)]
    h_ratios = [float(r) for r in cfg.get("height_ratios", [1.0] * nrows)]
    is_multi = len(raw_panels) > 1
    comp_lw = float(theme.get("composite_print_profile", {}).get("box_linewidth_pt", 1.8))
    default_lw = comp_lw if is_multi else float(theme.get("figure_box_linewidth", 3.0))

    compiled_panels: List[PanelSpec] = []
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    if "locale" in cfg:
        fig_meta["locale"] = str(cfg["locale"])
    for p_idx, p_cfg in enumerate(raw_panels):
        pid = p_cfg.get("panel_id", f"panel_{chr(ord('a') + p_idx)}")
        tag = p_cfg.get("tag", chr(ord("a") + p_idx) if is_multi else None)

        # Allow panel shorthand `panel_mode` to reuse any specialized compiler inside a multi-panel grid!
        if p_cfg.get("panel_mode") and not p_cfg.get("layers"):
            sub_cfg = copy.deepcopy(p_cfg)
            sub_cfg["mode"] = sub_cfg.pop("panel_mode")
            sub_fig = compile_config_to_figure_spec(sub_cfg, loaded_tables=loaded_tables)
            p_built = sub_fig.panels[0]
            p_built.panel_id = pid
            p_built.tag = tag
            p_built.row = int(p_cfg.get("row", p_idx // ncols))
            p_built.col = int(p_cfg.get("col", p_idx % ncols))
            p_built.row_span = int(p_cfg.get("row_span", 1))
            p_built.col_span = int(p_cfg.get("col_span", 1))
            p_built.box_linewidth_pt = float(p_cfg.get("box_linewidth_pt", default_lw))
            p_built.share_x_with = p_cfg.get("share_x_with")
            p_built.share_y_with = p_cfg.get("share_y_with")
            if sub_fig.meta:
                for mk, mv in sub_fig.meta.items():
                    fig_meta.setdefault(mk, mv)
            p_built.validate()
            compiled_panels.append(p_built)
            continue

        raw_layers = p_cfg.get("layers", [])
        if not raw_layers:
            raise ValueError(f"Panel '{pid}' in 'chart_grammar' must specify `layers` or `panel_mode`.")

        p_layers: List[LayerSpec] = []
        cats_found: Optional[List[str]] = None
        has_bar_bg = any("bar" in str(l_item.get("mark", "")).lower() for l_item in raw_layers)

        for l_idx, l_cfg in enumerate(raw_layers):
            mark = str(l_cfg.get("mark", "line_scatter")).lower()
            ya = l_cfg.get("y_axis", "y1")
            lid = l_cfg.get("layer_id", f"{pid}_layer_{l_idx + 1}")
            if mark in ("bar_stacked", "bar_stacked_100pct"):
                ly, l_cats = _compile_bar_stacked_layer(
                    l_cfg, theme, loaded_tables, force_100pct=(mark == "bar_stacked_100pct"), y_axis=ya, layer_id=lid
                )
                cats_found = cats_found or l_cats
                p_layers.append(ly)
            elif mark == "bar_grouped_gradient":
                sub_f = _compile_bar_grouped_gradient(l_cfg, theme, loaded_tables)
                ly = sub_f.panels[0].layers[0]
                ly.y_axis = ya
                ly.layer_id = lid
                cats_found = cats_found or ly.categories
                p_layers.append(ly)
            elif mark == "contour_pseudocolor":
                sub_c = _compile_contour_pseudocolor_2d(l_cfg, theme, loaded_tables)
                ly = sub_c.panels[0].layers[0]
                ly.y_axis = ya
                ly.layer_id = lid
                p_layers.append(ly)
            elif mark == "line_scatter":
                ly = _compile_line_scatter_layer(
                    l_cfg, theme, loaded_tables, y_axis=ya, layer_id=lid, foreground_over_bars=has_bar_bg
                )
                p_layers.append(ly)
            else:
                p_layers.append(LayerSpec.from_dict(l_cfg))

        has_y2 = any(ly.y_axis == "y2" for ly in p_layers)
        x_cfg = p_cfg.get("x_axis", {})
        y1_cfg = p_cfg.get("y1_axis", {})
        y2_cfg = p_cfg.get("y2_axis")

        x_ax = AxisSpec(
            which="x",
            label=x_cfg.get("label", p_cfg.get("x_label", "")),
            unit=x_cfg.get("unit"),
            axis_kind=x_cfg.get("axis_kind", "categorical" if cats_found or has_bar_bg else "quantitative"),
            scale=x_cfg.get("scale", "linear"),
            limits=tuple(x_cfg["limits"]) if x_cfg.get("limits") is not None else None,
            invert=bool(x_cfg.get("invert", False)),
            categories=x_cfg.get("categories", cats_found),
            breaks=x_cfg.get("breaks", p_cfg.get("x_breaks", [])),
            linked_top=x_cfg.get("linked_top", p_cfg.get("linked_top_x")),
        )
        right_col = (
            ot.normalize_hex(y2_cfg["color"])
            if isinstance(y2_cfg, dict) and y2_cfg.get("color")
            else "#3E86DE"
        )
        y1_ax = AxisSpec(
            which="y1",
            label=y1_cfg.get("label", p_cfg.get("y_label", "Y")),
            unit=y1_cfg.get("unit"),
            axis_kind=y1_cfg.get("axis_kind", "dual_y_left" if has_y2 else "quantitative"),
            scale=y1_cfg.get("scale", "linear"),
            limits=tuple(y1_cfg["limits"]) if y1_cfg.get("limits") is not None else None,
            invert=bool(y1_cfg.get("invert", False)),
            color=y1_cfg.get("color", "#111111"),
            breaks=y1_cfg.get("breaks", p_cfg.get("y_breaks", [])),
        )
        y2_ax = None
        if has_y2 or y2_cfg is not None:
            y2_d = y2_cfg or {}
            y2_ax = AxisSpec(
                which="y2",
                label=y2_d.get("label", "Right Y"),
                unit=y2_d.get("unit"),
                axis_kind="dual_y_right",
                scale=y2_d.get("scale", "linear"),
                limits=tuple(y2_d["limits"]) if y2_d.get("limits") is not None else None,
                color=right_col,
                breaks=y2_d.get("breaks", []),
            )

        insets = [InsetSpec.from_dict(ins) for ins in p_cfg.get("insets", [])]
        guides = _build_guides_from_cfg(p_cfg.get("guides", []), theme)

        compiled_panels.append(
            PanelSpec(
                panel_id=pid,
                tag=tag,
                row=int(p_cfg.get("row", p_idx // ncols)),
                col=int(p_cfg.get("col", p_idx % ncols)),
                row_span=int(p_cfg.get("row_span", 1)),
                col_span=int(p_cfg.get("col_span", 1)),
                coord=str(p_cfg.get("coord", "cartesian")),
                x_axis=x_ax,
                y1_axis=y1_ax,
                y2_axis=y2_ax,
                layers=p_layers,
                insets=insets,
                guides=guides,
                equal_aspect=bool(p_cfg.get("equal_aspect", False)),
                align_zero=bool(p_cfg.get("align_zero", has_y2)),
                legend_style=p_cfg.get("legend_style", "interior_top_dual" if has_y2 else "corner_upper_left"),
                box_linewidth_pt=float(p_cfg.get("box_linewidth_pt", default_lw)),
                share_x_with=p_cfg.get("share_x_with"),
                share_y_with=p_cfg.get("share_y_with"),
                meta=dict(p_cfg.get("meta") or {}),
            )
        )

    return FigureSpec(
        title=cfg.get("title", "Declarative_Chart_Grammar"),
        mode="chart_grammar",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        nrows=nrows,
        ncols=ncols,
        width_ratios=w_ratios,
        height_ratios=h_ratios,
        width_mm=float(cfg.get("width_mm", 180.0 if ncols > 1 else 140.0)),
        height_mm=float(cfg.get("height_mm", 90.0 * nrows if is_multi else 108.0)),
        panels=compiled_panels,
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
        meta=fig_meta,
    )


# ---------------------------------------------------------------------------
# Public Entry Points
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# New mode compilers: xy_fit_and_band, bode_dual_panel,
#                     stat_distribution (new subtype), matrix_heatmap
# ---------------------------------------------------------------------------

def _compile_xy_fit_and_band(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Scatter + scientific curve fit + 95% CI shaded band (`xy_fit_and_band` / `dose_response_4pl`).
    Supports all `curve_models.SUPPORTED_CURVE_MODELS` ('linear', 'poly2', 'poly3', 'power',
    'exp_decay', 'arrhenius', 'michaelis_menten', 'dose_response_4pl', 'langmuir') across
    `>= 1` experimental series, plus subtype='band_only' for pre-computed CI bands.
    """
    import importlib as _il

    _sc_path = str(Path(__file__).resolve().parent)
    if _sc_path not in sys.path:
        sys.path.insert(0, _sc_path)
    _cm = _il.import_module("curve_models")
    fit_curve_with_ci95 = _cm.fit_curve_with_ci95

    raw_mode = str(cfg.get("mode") or "xy_fit_and_band").strip()
    is_4pl_mode = raw_mode == "dose_response_4pl"
    model = str(
        cfg.get("model")
        or cfg.get("fit_model")
        or ("dose_response_4pl" if is_4pl_mode else "linear")
    ).strip().lower()
    if model == "4pl":
        model = "dose_response_4pl"

    title = str(cfg.get("title", "Dose_Response_4PL" if model == "dose_response_4pl" else "xy_fit"))
    style_name = str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET))
    default_xlab = "Concentration (nM)" if model == "dose_response_4pl" else "x"
    default_ylab = "Cell Viability (%)" if model == "dose_response_4pl" else "y"
    x_label = str(cfg.get("x_label", default_xlab))
    y_label = str(cfg.get("y_label", default_ylab))
    default_xscale = "log10" if model == "dose_response_4pl" else "linear"
    x_scale = str(cfg.get("x_scale", default_xscale)).strip().lower()
    if x_scale == "log":
        x_scale = "log10"
    y_scale = str(cfg.get("y_scale", "linear")).strip().lower()

    n_grid = int(cfg.get("n_grid", 200))
    ci_level = float(cfg.get("ci_level", 0.95))
    subtype = str(cfg.get("subtype", "scatter_fit"))
    output_dir = cfg.get("output_dir")
    build_opju = bool(cfg.get("build_opju", True))
    locale = str(cfg.get("locale", "en"))

    series_specs: List[SeriesSpec] = []
    panel_meta: Dict[str, Any] = {"locale": locale}
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    if "locale" in cfg or is_4pl_mode or model not in ("linear", "poly2", "power"):
        fig_meta["locale"] = locale

    guides: List[GuideSpec] = []
    color_scheme = str(cfg.get("color_scheme", "paired_semantic"))

    if subtype == "band_only":
        raw_series = cfg.get("series", [])
        n_s = len(raw_series) or 1
        b_scheme = str(cfg.get("color_scheme", "sequential_blue_red"))
        palette = ot.resolve_series_colors(n_s, scheme=b_scheme)
        color_scheme = b_scheme
        for i, s in enumerate(raw_series):
            sc = str(s.get("color", palette[i % len(palette)]))
            x_vals = _as_float_list(s.get("x"), "x")
            y_vals = _as_float_list(s.get("y_mean") or s.get("y"), "y")
            y_err = _as_float_list(s.get("y_err"), "y_err")
            y_low = _as_float_list(s.get("y_low"), "y_low")
            y_high = _as_float_list(s.get("y_high"), "y_high")
            if (y_low is None or y_high is None) and y_vals is not None and y_err is not None and len(y_err) == len(y_vals):
                y_low = [yv - ev for yv, ev in zip(y_vals, y_err)]
                y_high = [yv + ev for yv, ev in zip(y_vals, y_err)]
            series_specs.append(SeriesSpec(
                name=str(s.get("name", f"series_{i}")),
                x=x_vals,
                y=y_vals,
                y_low=y_low,
                y_high=y_high,
                color=sc,
                line_style="solid",
                line_width_pt=float(s.get("line_width_pt", theme.get("curve_linewidth", 3.0))),
                marker_style=str(s.get("marker_style", "none")),
                meta={"mark_override": "line_band"},
            ))
    else:
        raw_series_list = list(cfg.get("series") or [])
        groups_to_fit: List[Dict[str, Any]] = []
        if raw_series_list and isinstance(raw_series_list[0], dict):
            for idx, s_dict in enumerate(raw_series_list):
                sx = _as_float_list(s_dict.get("x", cfg.get("x")), f"series[{idx}].x")
                sy_raw = s_dict.get("y") if s_dict.get("y") is not None else s_dict.get("values")
                s_err = _as_float_list(s_dict.get("y_err", s_dict.get("errors")), f"series[{idx}].y_err")
                # Support replicate matrix (n_conc x n_rep or list of replicate vectors) if supplied
                if sy_raw is None and isinstance(s_dict.get("replicates"), (list, tuple)) and sx is not None:
                    reps = s_dict["replicates"]
                    if reps and isinstance(reps[0], (list, tuple)):
                        # Detect shape: len(reps) == len(sx) -> per-x replicates; else replicate curves
                        if len(reps) == len(sx):
                            per_x = [[float(v) for v in row] for row in reps]
                        else:
                            per_x = [[float(reps[r][c]) for r in range(len(reps))] for c in range(len(sx))]
                        sy = [sum(r) / len(r) for r in per_x]
                        s_err = [
                            math.sqrt(sum((v - m) ** 2 for v in r) / max(len(r) - 1, 1)) if len(r) > 1 else 0.0
                            for r, m in zip(per_x, sy)
                        ]
                        fit_x = [ xv_i for xv_i, r in zip(sx, per_x) for _ in r ]
                        fit_y = [ v for r in per_x for v in r ]
                    else:
                        sy = _as_float_list(reps, f"series[{idx}].replicates")
                        fit_x, fit_y = sx, sy
                else:
                    sy = _as_float_list(sy_raw, f"series[{idx}].y")
                    fit_x, fit_y = sx, sy
                if sx is None or sy is None:
                    raise ValueError(f"xy_fit_and_band series[{idx}] requires numeric 'x' and 'y' arrays.")
                groups_to_fit.append(
                    {
                        "name": s_dict.get("name"),
                        "scatter_name": s_dict.get("scatter_name"),
                        "fit_name": s_dict.get("fit_name"),
                        "x": sx,
                        "y": sy,
                        "fit_x": fit_x,
                        "fit_y": fit_y,
                        "y_err": s_err,
                        "color": s_dict.get("color"),
                        "role": s_dict.get("role"),
                        "marker_style": s_dict.get("marker_style"),
                        "marker_size_pt": s_dict.get("marker_size_pt"),
                        "line_width_pt": s_dict.get("line_width_pt"),
                    }
                )
        else:
            x_raw = _as_float_list(cfg.get("x"), "x")
            y_raw = _as_float_list(cfg.get("y"), "y")
            if (x_raw is None or y_raw is None) and loaded_tables:
                tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
                if tbl is not None and cfg.get("x_col") is not None and cfg.get("y_col") is not None:
                    x_raw = _as_float_list(_extract_column_from_table(tbl, cfg.get("x_col")), "x")
                    y_raw = _as_float_list(_extract_column_from_table(tbl, cfg.get("y_col")), "y")
            if x_raw is None or y_raw is None:
                raise ValueError(f"{raw_mode} requires 'x' and 'y' arrays in config (or in 'series').")
            groups_to_fit.append(
                {
                    "name": cfg.get("name"),
                    "scatter_name": cfg.get("scatter_name"),
                    "fit_name": cfg.get("fit_name"),
                    "x": x_raw,
                    "y": y_raw,
                    "fit_x": x_raw,
                    "fit_y": y_raw,
                    "y_err": _as_float_list(cfg.get("y_err"), "y_err"),
                    "color": cfg.get("color", ot.SEMANTIC_PALETTE["blue"]),
                    "role": cfg.get("role"),
                    "marker_style": cfg.get("marker_style"),
                    "marker_size_pt": cfg.get("marker_size_pt"),
                    "line_width_pt": cfg.get("line_width_pt"),
                }
            )

        n_groups = len(groups_to_fit)
        roles = [g.get("role") for g in groups_to_fit]
        has_roles = any(r is not None for r in roles)
        resolved_cols = ot.resolve_series_colors(
            n_groups,
            roles=(roles if has_roles else None),
            scheme=color_scheme,
        )

        curve_fits_list: List[Dict[str, Any]] = []
        for idx, g_item in enumerate(groups_to_fit):
            if g_item.get("color"):
                g_color = ot.normalize_hex(str(g_item["color"]))
            elif n_groups == 1 and cfg.get("color"):
                g_color = ot.normalize_hex(str(cfg["color"]))
            else:
                g_color = resolved_cols[idx % len(resolved_cols)]

            raw_nm = g_item.get("name")
            grp_name = (
                ot.clean_semantic_sample_name(str(raw_nm), bool(cfg.get("clean_sample_prefix", False)))
                if raw_nm
                else ("Experimental" if n_groups == 1 else f"Group {idx + 1}")
            )
            if n_groups == 1 and not is_4pl_mode and not raw_nm:
                scatter_name = str(g_item.get("scatter_name") or cfg.get("scatter_name") or "Experimental")
                fit_name = str(g_item.get("fit_name") or cfg.get("fit_name") or f"{model.capitalize()} Fit (95% CI)")
            else:
                scatter_name = str(g_item.get("scatter_name") or grp_name)
                default_fn = f"{scatter_name} (4PL Fit)" if model == "dose_response_4pl" else f"{scatter_name} Fit (95% CI)"
                fit_name = str(g_item.get("fit_name") or default_fn)

            fit = fit_curve_with_ci95(
                g_item["fit_x"],
                g_item["fit_y"],
                model=model,
                n_grid=n_grid,
                ci_level=ci_level,
                x_scale=x_scale,
                T_in_kelvin=cfg.get("T_in_kelvin"),
            )
            x_fit = fit["x_grid"]
            y_fit_list = fit["y_fit"]
            y_low = fit["y_low"]
            y_high = fit["y_high"]
            eq_str = fit["equation_text"]
            km = dict(fit.get("key_metrics") or {})

            if model == "dose_response_4pl" and "IC50" in km:
                ann_str = f"{grp_name}: IC50 = {km['IC50']:.3g}, R²={fit['r2']:.4f}" if n_groups > 1 else f"IC50 = {km['IC50']:.3g}  R²={fit['r2']:.4f}"
            else:
                ann_str = f"{eq_str}  R²={fit['r2']:.4f}"

            fit_record = {
                "name": grp_name,
                "color": g_color,
                "model": fit["model"],
                "params": fit["params"],
                "param_se": fit["param_se"],
                "r2": fit["r2"],
                "adj_r2": fit["adj_r2"],
                "aic": fit["aic"],
                "bic": fit["bic"],
                "rmse": fit["rmse"],
                "equation_text": eq_str,
                "origin_rich_eq": fit.get("origin_rich_eq", ""),
                "key_metrics": km,
            }
            curve_fits_list.append(fit_record)

            series_specs.append(
                SeriesSpec(
                    name=scatter_name,
                    x=g_item["x"],
                    y=g_item["y"],
                    y_err=g_item.get("y_err"),
                    role="raw",
                    color=g_color,
                    marker_style=str(g_item.get("marker_style") or cfg.get("marker_style") or "circle_solid"),
                    marker_size_pt=float(g_item.get("marker_size_pt") or cfg.get("marker_size_pt") or 7.5),
                    line_style="none",
                    meta={
                        "series_group": grp_name,
                        "group_index": idx,
                        "error_type": str(cfg.get("error_bar", "SD")) if g_item.get("y_err") else None,
                    },
                )
            )
            series_specs.append(
                SeriesSpec(
                    name=fit_name,
                    x=x_fit,
                    y=y_fit_list,
                    y_low=y_low,
                    y_high=y_high,
                    role="fit",
                    color=g_color,
                    line_style="solid",
                    line_width_pt=float(g_item.get("line_width_pt") or cfg.get("line_width_pt") or theme.get("curve_linewidth", 3.0)),
                    marker_style="none",
                    meta={
                        "mark_override": "line_band",
                        "series_group": grp_name,
                        "group_index": idx,
                        "annotation": ann_str,
                        "r2": fit["r2"],
                        "equation_str": eq_str,
                        "origin_rich_eq": fit.get("origin_rich_eq", ""),
                        "key_metrics": km,
                    },
                )
            )

        panel_meta["curve_fits"] = curve_fits_list
        fig_meta["curve_fits"] = curve_fits_list
        if len(curve_fits_list) == 1:
            cf0 = curve_fits_list[0]
            if model == "dose_response_4pl" and "IC50" in cf0["key_metrics"]:
                panel_meta["regression_equation"] = cf0["origin_rich_eq"] or f"IC50 = {cf0['key_metrics']['IC50']:.4g}"
            else:
                panel_meta["regression_equation"] = cf0["equation_text"]
            panel_meta["r_squared"] = f"{cf0['r2']:.4f}"
        else:
            if model == "dose_response_4pl":
                ic50_parts = [
                    f"{cf['name']}: IC\\-(50) = {cf['key_metrics']['IC50']:.3g}"
                    for cf in curve_fits_list
                    if "IC50" in cf.get("key_metrics", {})
                ]
                panel_meta["regression_equation"] = ";  ".join(ic50_parts)
                panel_meta["r_squared"] = f"{curve_fits_list[0]['r2']:.4f}"
            else:
                panel_meta["regression_equation"] = curve_fits_list[0]["equation_text"]
                panel_meta["r_squared"] = f"{curve_fits_list[0]['r2']:.4f}"

        # Auto-attach IC50 horizontal & vertical dashed drop-line guides for 4PL
        if model == "dose_response_4pl" and bool(cfg.get("show_ic50_guides", True)):
            valid_4pl = [cf for cf in curve_fits_list if cf.get("key_metrics", {}).get("IC50") is not None]
            if valid_4pl:
                if cfg.get("ic50_ref_y") is not None:
                    ref_y = float(cfg["ic50_ref_y"])
                else:
                    spans_50 = all(
                        min(cf["key_metrics"].get("bottom", 0.0), cf["key_metrics"].get("top", 100.0)) - 5.0
                        <= 50.0
                        <= max(cf["key_metrics"].get("bottom", 0.0), cf["key_metrics"].get("top", 100.0)) + 5.0
                        for cf in valid_4pl
                    )
                    ref_y = 50.0 if spans_50 else float(valid_4pl[0]["key_metrics"].get("mid_y", 50.0))
                guides.append(
                    GuideSpec(
                        kind="hline",
                        value=ref_y,
                        color="#666666",
                        line_style="dashed",
                        line_width_pt=1.5,
                        label=str(cfg.get("ic50_hline_label", "")),
                        meta={"guide_role": "ic50_mid_response"},
                    )
                )
                for cf in valid_4pl:
                    ic50_val = float(cf["key_metrics"]["IC50"])
                    if ic50_val > 0.0 or x_scale != "log10":
                        guides.append(
                            GuideSpec(
                                kind="vline",
                                value=ic50_val,
                                color=cf["color"],
                                line_style="dashed",
                                line_width_pt=1.6,
                                label=f"IC50 = {ic50_val:.3g}",
                                meta={
                                    "guide_role": "ic50_drop",
                                    "series": cf["name"],
                                    "ic50": ic50_val,
                                    "mid_y": float(cf["key_metrics"].get("mid_y", ref_y)),
                                    "ref_y": ref_y,
                                },
                            )
                        )

    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    layer = LayerSpec(
        layer_id="xy_fit_main",
        mark="line_band",
        series=series_specs,
        color_scheme=color_scheme,
    )
    x_axis = AxisSpec(
        which="x",
        label=x_label,
        scale=x_scale,
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=y_label,
        scale=y_scale,
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_right" if model == "dose_response_4pl" else "corner_upper_left")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=title,
        mode="dose_response_4pl" if is_4pl_mode else "xy_fit_and_band",
        subtype=subtype,
        style_preset=style_name,
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=output_dir,
        build_opju=build_opju,
        meta=fig_meta,
    )


def _compile_dose_response_4pl(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """Dedicated compiler entry point for `mode == 'dose_response_4pl'`."""
    sub_cfg = copy.deepcopy(cfg)
    sub_cfg["mode"] = "dose_response_4pl"
    sub_cfg.setdefault("model", "dose_response_4pl")
    sub_cfg.setdefault("x_scale", "log10")
    sub_cfg.setdefault("locale", "en")
    return _compile_xy_fit_and_band(sub_cfg, theme, loaded_tables)


def _compile_bode_dual_panel(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Bode plot: 2-row, 1-col panel layout.
    Top panel:    |Z| (Ohm) vs Frequency (Hz), log-log axes, X labels hidden.
    Bottom panel: -Phase (deg.) vs Frequency (Hz), log-linear axes, X labels shown.
    """
    title = str(cfg.get("title", "bode_plot"))
    style_name = str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET))
    output_dir = cfg.get("output_dir")
    build_opju = bool(cfg.get("build_opju", True))
    raw_series = cfg.get("series", [])
    n = max(len(raw_series), 1)
    roles = [s.get("role") if isinstance(s, dict) else None for s in raw_series]
    has_roles = any(r is not None for r in roles)
    default_cs = "paired_semantic" if has_roles else "sequential_blue_red"
    color_scheme = str(cfg.get("color_scheme", default_cs))
    colors = ot.resolve_series_colors(
        n,
        roles=(roles if (has_roles and len(roles) == n) else None),
        scheme=color_scheme,
    )

    top_series: List[SeriesSpec] = []
    bot_series: List[SeriesSpec] = []

    for i, s in enumerate(raw_series):
        if not isinstance(s, dict):
            continue
        col = str(s.get("color", colors[i % len(colors)]))
        name = ot.clean_semantic_sample_name(str(s.get("name", f"EIS_{i}")))
        freq = _as_float_list(
            s.get("freq") or s.get("frequency") or s.get("freq_Hz"), "freq"
        )
        z_mag = _as_float_list(
            s.get("z_mag") or s.get("Z_mag") or s.get("z_mod") or s.get("Z_mod"), "z_mag"
        )
        phase_lbl_cfg = str(cfg.get("phase_label", "-Phase (deg.)"))
        has_neg_phase_explicit = s.get("neg_phase") is not None
        phase = _as_float_list(
            s.get("neg_phase") if has_neg_phase_explicit else (s.get("phase") or s.get("phase_deg")), "phase"
        )
        if not freq and (s.get("file") or cfg.get("input_file")):
            try:
                import sys as _sys, importlib as _il
                _sc_dir = str(Path(__file__).resolve().parent)
                if _sc_dir not in _sys.path:
                    _sys.path.insert(0, _sc_dir)
                _parsers = _il.import_module("parsers")
                _pr = _parsers.parse_eis(Path(s.get("file") or cfg["input_file"]))
                freq = _as_float_list(_pr["freq_Hz"].tolist(), "freq")
                z_mag = _as_float_list(_pr["z_mod"].tolist(), "z_mag")
                phase = _as_float_list(_pr["phase_deg"].tolist(), "phase")
            except Exception:
                pass
        if phase and not has_neg_phase_explicit and phase_lbl_cfg.strip().startswith("-"):
            sorted_ph = sorted(float(pv) for pv in phase)
            med_ph = sorted_ph[len(sorted_ph) // 2]
            if med_ph < 0.0:
                phase = [-float(pv) for pv in phase]
        mk_style = str(s.get("marker_style", "circle_solid"))
        mk_sz = float(s.get("marker_size_pt", 6.2))
        lw_pt = float(s.get("line_width_pt", theme.get("curve_linewidth", 3.0)))
        if freq and z_mag:
            top_series.append(SeriesSpec(
                name=name, x=freq, y=z_mag, color=col,
                line_style="solid", line_width_pt=lw_pt,
                marker_style=mk_style, marker_size_pt=mk_sz,
            ))
        if freq and phase:
            bot_series.append(SeriesSpec(
                name=name, x=freq, y=phase, color=col,
                line_style="solid", line_width_pt=lw_pt,
                marker_style=mk_style, marker_size_pt=mk_sz,
            ))

    if not top_series:
        top_series = [SeriesSpec(name="Z_placeholder", x=[1.0], y=[1.0],
                                  color=ot.SEMANTIC_PALETTE["blue"], line_style="solid")]
    if not bot_series:
        bot_series = [SeriesSpec(name="Phase_placeholder", x=[1.0], y=[0.0],
                                  color=ot.SEMANTIC_PALETTE["blue"], line_style="solid")]

    top_layer = LayerSpec(layer_id="zmag", mark="line_scatter", series=top_series,
                           color_scheme=color_scheme)
    bot_layer = LayerSpec(layer_id="phase", mark="line_scatter", series=bot_series,
                           color_scheme=color_scheme)

    bode_bt = float(theme.get("figure_box_linewidth", 3.0))
    panel_top = PanelSpec(
        panel_id="panel_top",
        tag="a",
        row=0,
        col=0,
        x_axis=AxisSpec(which="x", label="", scale="log10",
                         tick_policy={"show_labels": False, "tick_in": True, "minor_ticks": True}),
        y1_axis=AxisSpec(which="y1", label=str(cfg.get("z_label", "|Z| (Ω)")), scale="log10",
                          tick_policy={"tick_in": True, "minor_ticks": True}),
        layers=[top_layer],
        box_linewidth_pt=bode_bt,
        meta={"bode_panel": "top"},
    )
    panel_bot = PanelSpec(
        panel_id="panel_bot",
        tag="b",
        row=1,
        col=0,
        x_axis=AxisSpec(which="x", label=str(cfg.get("x_label", "Frequency (Hz)")), scale="log10",
                         tick_policy={"tick_in": True, "minor_ticks": True}),
        y1_axis=AxisSpec(which="y1", label=str(cfg.get("phase_label", "-Phase (deg.)")), scale="linear",
                          tick_policy={"tick_in": True}),
        layers=[bot_layer],
        box_linewidth_pt=bode_bt,
        share_x_with="panel_top",
        meta={"bode_panel": "bottom"},
    )

    return FigureSpec(
        title=title,
        mode="bode_dual_panel",
        style_preset=style_name,
        theme=theme,
        nrows=2,
        ncols=1,
        height_ratios=[1.0, 1.0],
        panels=[panel_top, panel_bot],
        output_dir=output_dir,
        build_opju=build_opju,
    )


def _compile_stat_distribution_new(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Statistical distribution chart for the 'stat_distribution' grammar mode.
    Subtypes: box_jitter (default), violin_box, half_violin.
    Each series carries raw parallel-sample y array.
    """
    title = str(cfg.get("title", "stat_dist"))
    style_name = str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET))
    x_label = str(cfg.get("x_label", ""))
    y_label = str(cfg.get("y_label", ""))
    subtype = str(cfg.get("subtype", "box_jitter"))
    output_dir = cfg.get("output_dir")
    build_opju = bool(cfg.get("build_opju", True))
    group_col = cfg.get("group_col")
    value_col = cfg.get("value_col")
    sample_filter = cfg.get("sample_filter")
    label_map = cfg.get("label_map") or {}
    raw_series = list(cfg.get("series", []))

    def _extract_groups_from_df(df_obj: Any, fallback_name: str) -> None:
        import pandas as _pd
        work_df = df_obj.copy()
        if isinstance(sample_filter, dict):
            for fk, fv in sample_filter.items():
                if fk in work_df.columns:
                    allowed = {str(x).strip() for x in (fv if isinstance(fv, (list, tuple, set)) else [fv])}
                    work_df = work_df.loc[work_df[fk].astype(str).str.strip().isin(allowed)].copy()
        if group_col and value_col and group_col in work_df.columns and value_col in work_df.columns:
            if isinstance(sample_filter, (list, tuple)):
                allowed_g = [str(x).strip() for x in sample_filter]
                work_df = work_df.loc[work_df[group_col].astype(str).str.strip().isin(set(allowed_g))].copy()
            for g_name, g_df in work_df.groupby(group_col, sort=False):
                vals = _pd.to_numeric(g_df[value_col], errors="coerce").dropna().tolist()
                if vals:
                    g_str = str(g_name).strip()
                    mapped_nm = str(label_map.get(g_str, label_map.get(ot.clean_semantic_sample_name(g_str), g_str)))
                    raw_series.append({"name": mapped_nm, "y": vals})
        elif len(work_df.columns) == 1:
            vals = _pd.to_numeric(work_df.iloc[:, 0], errors="coerce").dropna().tolist()
            if vals:
                raw_series.append({"name": str(fallback_name), "y": vals})
        else:
            for col_nm in work_df.columns:
                vals = _pd.to_numeric(work_df[col_nm], errors="coerce").dropna().tolist()
                if vals:
                    c_str = str(col_nm).strip()
                    raw_series.append({"name": str(label_map.get(c_str, c_str)), "y": vals})

    if not raw_series and loaded_tables:
        for grp_name, grp_data in loaded_tables.items():
            if isinstance(grp_data, list):
                raw_series.append({"name": str(grp_name), "y": grp_data})
            elif hasattr(grp_data, "columns") and hasattr(grp_data, "iloc"):
                _extract_groups_from_df(grp_data, str(grp_name))
            elif hasattr(grp_data, "tolist"):
                raw_series.append({"name": str(grp_name), "y": grp_data.tolist()})

    if not raw_series and cfg.get("input_file"):
        try:
            import sys as _sys, importlib as _il
            _sc_dir = str(Path(__file__).resolve().parent)
            if _sc_dir not in _sys.path:
                _sys.path.insert(0, _sc_dir)
            _et = _il.import_module("electrochem_transforms")
            _df = _et.load_tabular_sheet(
                cfg["input_file"],
                sheet=cfg.get("sheet", 0),
                header_row=cfg.get("header_row", 0),
            )
            _extract_groups_from_df(_df, "group_0")
        except Exception:
            pass

    n = max(len(raw_series), 1)
    default_cs = "paired_semantic" if n <= 6 else "sequential_blue_red"
    cs = str(cfg.get("color_scheme", default_cs))
    roles = [s.get("role") if isinstance(s, dict) else None for s in raw_series]
    has_roles = any(r is not None for r in roles)
    colors = ot.resolve_series_colors(
        n,
        roles=(roles if (has_roles and len(roles) == n) else None),
        scheme=cs,
    )

    series_specs: List[SeriesSpec] = []
    for i, s in enumerate(raw_series):
        col = str(s.get("color", colors[i % len(colors)]))
        y_vals = _as_float_list(s.get("y") if s.get("y") is not None else s.get("values"), "y")
        clean_nm = ot.clean_semantic_sample_name(str(s.get("name", f"group_{i}")))
        series_specs.append(SeriesSpec(
            name=clean_nm,
            y=y_vals,
            color=col,
            meta={
                "subtype": subtype,
                "label": str(s.get("label", clean_nm)),
            },
        ))

    if not series_specs:
        series_specs = [SeriesSpec(name="placeholder", y=[0.0],
                                    color=ot.SEMANTIC_PALETTE["blue"])]

    cats = [s.name for s in series_specs]
    layer = LayerSpec(
        layer_id="stat_main",
        mark="stat_distribution",   # renderer checks mark=="stat_distribution"
        series=series_specs,
        categories=cats,
        color_scheme=cs,
        style_overrides={"subtype": subtype},
    )
    x_axis = AxisSpec(which="x", label=x_label, axis_kind="categorical", categories=cats)
    y1_axis = AxisSpec(which="y1", label=y_label)
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "none")),
    )
    return FigureSpec(
        title=title,
        mode="stat_distribution",
        subtype=subtype,
        style_preset=style_name,
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=output_dir,
        build_opju=build_opju,
    )


def _compile_matrix_heatmap_new(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    2D matrix heatmap with optional value labels.
    series[0] (or top-level cfg) carries matrix_x, matrix_y, matrix_z, x_labels, y_labels.
    """
    title = str(cfg.get("title", "matrix_heatmap"))
    style_name = str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET))
    x_label = str(cfg.get("x_label", ""))
    y_label = str(cfg.get("y_label", ""))
    output_dir = cfg.get("output_dir")
    build_opju = bool(cfg.get("build_opju", True))

    raw_cs = str(cfg.get("color_scheme") or cfg.get("colormap") or "diverging_blue_white_red").strip().lower()
    if raw_cs in ("blue_white_red", "bwr", "diverging", "coolwarm", "diverging_blue_white_red") or "diverging" in raw_cs or "blue_white_red" in raw_cs:
        color_scheme = "diverging_blue_white_red"
        palette_colors = list(ot.DIVERGING_BLUE_WHITE_RED_STOPS)
        default_center_zero = True
    elif raw_cs in ("pseudocolor_zero_white", "zero_white", "pseudocolor"):
        color_scheme = "pseudocolor_zero_white"
        palette_colors = list(ot.PSEUDOCOLOR_ZERO_WHITE_STOPS)
        default_center_zero = False
    elif raw_cs in ot.VALID_COLOR_SCHEMES:
        color_scheme = raw_cs
        palette_colors = ot.resolve_series_colors(6, scheme=color_scheme)
        default_center_zero = False
    else:
        color_scheme = "diverging_blue_white_red"
        palette_colors = list(ot.DIVERGING_BLUE_WHITE_RED_STOPS)
        default_center_zero = True

    center_zero = bool(cfg.get("center_zero", default_center_zero))
    show_value_labels = bool(cfg.get("show_value_labels", cfg.get("show_values", True)))
    value_format = str(cfg.get("value_format", ".2f")).lstrip(":").strip("{}")

    raw_series = cfg.get("series", [{}])
    s0 = raw_series[0] if raw_series and isinstance(raw_series[0], dict) else {}

    def _safe_matrix_z(val: Any) -> Optional[List[List[float]]]:
        if val is None:
            return None
        if hasattr(val, "tolist"):
            val = val.tolist()
        return _as_2d_float_matrix(val)

    matrix_x_raw = _as_any_list(s0.get("matrix_x")) or _as_any_list(cfg.get("matrix_x")) or []
    matrix_y_raw = _as_any_list(s0.get("matrix_y")) or _as_any_list(cfg.get("matrix_y")) or []
    matrix_z_raw = _safe_matrix_z(s0.get("matrix_z")) or _safe_matrix_z(cfg.get("matrix_z"))
    x_lbls_cfg = _as_any_list(s0.get("x_labels")) or _as_any_list(cfg.get("x_labels"))
    y_lbls_cfg = _as_any_list(s0.get("y_labels")) or _as_any_list(cfg.get("y_labels"))

    if cfg.get("input_file") and (matrix_z_raw is None or (x_lbls_cfg is None and y_lbls_cfg is None)):
        try:
            import sys as _sys, importlib as _il
            _sc_dir = str(Path(__file__).resolve().parent)
            if _sc_dir not in _sys.path:
                _sys.path.insert(0, _sc_dir)
            _et = _il.import_module("electrochem_transforms")
            _m_res = _et.load_2d_field_matrix(cfg)
            if matrix_z_raw is None:
                matrix_z_raw = _safe_matrix_z(_m_res.get("matrix_z"))
            if not matrix_x_raw and _m_res.get("matrix_x") is not None:
                _mx = _m_res["matrix_x"]
                matrix_x_raw = _mx.tolist() if hasattr(_mx, "tolist") else list(_mx)
            if not matrix_y_raw and _m_res.get("matrix_y") is not None:
                _my = _m_res["matrix_y"]
                matrix_y_raw = _my.tolist() if hasattr(_my, "tolist") else list(_my)
            if x_lbls_cfg is None and _m_res.get("x_labels"):
                x_lbls_cfg = list(_m_res["x_labels"])
            if y_lbls_cfg is None and _m_res.get("y_labels"):
                y_lbls_cfg = list(_m_res["y_labels"])
        except Exception:
            pass

    if matrix_z_raw is None:
        matrix_z_raw = [[0.0]]

    ny = len(matrix_z_raw)
    nx = len(matrix_z_raw[0]) if ny > 0 else 1

    def _is_num_seq(seq: List[Any]) -> bool:
        if not seq:
            return False
        try:
            for v in seq:
                if isinstance(v, bool):
                    return False
                float(v)
            return True
        except (TypeError, ValueError):
            return False

    num_mx = (
        [float(v) for v in matrix_x_raw]
        if (len(matrix_x_raw) == nx and _is_num_seq(matrix_x_raw))
        else [float(i + 1) for i in range(nx)]
    )
    num_my = (
        [float(v) for v in matrix_y_raw]
        if (len(matrix_y_raw) == ny and _is_num_seq(matrix_y_raw))
        else [float(i + 1) for i in range(ny)]
    )

    x_lbls = [
        str(v)
        for v in (
            x_lbls_cfg
            or (matrix_x_raw if (matrix_x_raw and not _is_num_seq(matrix_x_raw)) else [])
            or [str(v) for v in matrix_x_raw]
        )
    ]
    y_lbls = [
        str(v)
        for v in (
            y_lbls_cfg
            or (matrix_y_raw if (matrix_y_raw and not _is_num_seq(matrix_y_raw)) else [])
            or [str(v) for v in matrix_y_raw]
        )
    ]

    flat_z = [v for row in matrix_z_raw for v in row]
    min_z = min(flat_z) if flat_z else -1.0
    max_z = max(flat_z) if flat_z else 1.0
    if cfg.get("z_limits") is not None:
        z_lims: Optional[Tuple[float, float]] = (float(cfg["z_limits"][0]), float(cfg["z_limits"][1]))
    elif cfg.get("z_min") is not None or cfg.get("z_max") is not None:
        z_lims = (
            float(cfg.get("z_min", -1.0 if center_zero else min_z)),
            float(cfg.get("z_max", 1.0 if center_zero else max_z)),
        )
    elif center_zero:
        abs_m = max(abs(min_z), abs(max_z), 1e-6)
        z_lims = (-1.0, 1.0) if abs_m <= 1.0001 else (-abs_m, abs_m)
    else:
        z_lims = (min_z, max_z)

    series_spec = SeriesSpec(
        name=str(s0.get("name", "heatmap")),
        matrix_x=num_mx,
        matrix_y=num_my,
        matrix_z=matrix_z_raw,
        show_value_labels=show_value_labels,
        value_format="{:" + value_format + "}",
        meta={
            "matrix_x_labels": x_lbls,
            "matrix_y_labels": y_lbls,
            "x_labels": x_lbls,
            "state_labels": y_lbls,
            "color_scheme": color_scheme,
            "center_zero": center_zero,
        },
    )

    layer = LayerSpec(
        layer_id="heatmap_main",
        mark="matrix_heatmap",
        series=[series_spec],
        categories=x_lbls or None,
        color_scheme=color_scheme,
        palette_colors=palette_colors,
        show_value_labels=show_value_labels,
        value_label_size_pt=float(cfg.get("value_fontsize_pt", 20.0)),
        style_overrides={"center_zero": center_zero, "value_format": value_format},
    )
    x_axis = AxisSpec(
        which="x",
        label=x_label,
        axis_kind="categorical" if x_lbls else "quantitative",
        categories=x_lbls or None,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=y_label,
        categories=y_lbls or None,
    )
    z_axis = AxisSpec(
        which="z",
        label=str(cfg.get("z_label", "Pearson r" if center_zero else "")),
        limits=z_lims,
    )
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        z_axis=z_axis,
        layers=[layer],
        equal_aspect=bool(cfg.get("equal_aspect", True)),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style="none",
    )
    return FigureSpec(
        title=title,
        mode="matrix_heatmap",
        style_preset=style_name,
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=output_dir,
        build_opju=build_opju,
    )


ISO_4_3_STEPS: Tuple[float, ...] = (
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


def pick_iso_4_3_step(req_x_span: float, req_y_span: float) -> float:
    """Pick a clean shared `step` so `(4 * step) >= req_x_span` and `(3 * step) >= req_y_span`."""
    need = max(float(req_x_span) / 4.0, float(req_y_span) / 3.0, 1e-6)
    for st in ISO_4_3_STEPS:
        if st + 1e-9 >= need:
            return float(st)
    return float(math.ceil(need / 5000.0) * 5000.0)


def compute_isometric_4_3_bounds(
    xs: Sequence[float],
    ys: Sequence[float],
) -> Tuple[Tuple[float, float], Tuple[float, float], float]:
    """
    Compute physical 1:1 Ohm/inch bounds `(x_bounds, y_bounds, step)` inside a `4:3` (`6.40 x 4.80 in`) frame
    so `X_span : Y_span == 4 : 3` (`x_max = 4 * step`, `y_max = 3 * step` when `min >= 0`).
    """
    if not xs or not ys:
        return (0.0, 4.0), (0.0, 3.0), 1.0
    min_x, max_x = float(min(xs)), float(max(xs))
    min_y, max_y = float(min(ys)), float(max(ys))

    if min_x >= 0.0 and min_y >= 0.0:
        if max_y > 2.2 * max(max_x, 1.0):
            # Blocking-electrode low-frequency capacitive spike: frame the semicircle + Warburg transition cleanly
            cap_y = min(max_y * 1.08, max(900.0, max_x * 1.45))
            vis_xs = [float(xv) for xv, yv in zip(xs, ys) if float(yv) <= cap_y * 1.05]
            req_x = max(max(vis_xs) if vis_xs else max_x, max_x * 0.85) * 1.08
            req_y = cap_y
        else:
            req_x = max(max_x * 1.08, 1e-6)
            req_y = max(max_y * 1.08, 1e-6)
        step = pick_iso_4_3_step(req_x, req_y)
        return (0.0, round(4.0 * step, 6)), (0.0, round(3.0 * step, 6)), step

    sp_x = max((max_x - min_x) * 1.12, 1e-6)
    sp_y = max((max_y - min_y) * 1.12, 1e-6)
    step = pick_iso_4_3_step(sp_x, sp_y)
    x0 = 0.0 if min_x >= 0.0 else math.floor(min_x / step) * step
    y0 = 0.0 if min_y >= 0.0 else math.floor(min_y / step) * step
    while (x0 + 4.0 * step < max_x * 1.04) or (y0 + 3.0 * step < max_y * 1.04):
        step = pick_iso_4_3_step(4.0 * step * 1.05, 3.0 * step * 1.05)
        x0 = 0.0 if min_x >= 0.0 else math.floor(min_x / step) * step
        y0 = 0.0 if min_y >= 0.0 else math.floor(min_y / step) * step
    return (round(x0, 6), round(x0 + 4.0 * step, 6)), (round(y0, 6), round(y0 + 3.0 * step, 6)), step


def _extract_multi_group_replicates(
    cfg: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
    stat_engine_mod: Any,
) -> List[Dict[str, Any]]:
    """
    Normalize multi-group replicate inputs from `cfg['groups']` (dict or list of dicts),
    `cfg['series']`, `cfg['rows']`, `loaded_tables`, or `cfg['input_file']` into an ordered
    list of `{'name': str, 'values': List[float], 'role': Optional[str], 'color': Optional[str]}`.
    """
    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    label_map = cfg.get("label_map") or {}
    out: List[Dict[str, Any]] = []

    raw_groups = cfg.get("groups")
    if isinstance(raw_groups, dict):
        for g_key, g_vals in raw_groups.items():
            nm = str(label_map.get(g_key, ot.clean_semantic_sample_name(str(g_key), clean_prefix)))
            if isinstance(g_vals, dict):
                vals = _as_float_list(
                    g_vals.get("values") if g_vals.get("values") is not None else (g_vals.get("y") if g_vals.get("y") is not None else g_vals.get("raw_points")),
                    f"groups[{g_key!r}]",
                ) or []
                out.append({"name": nm, "values": vals, "role": g_vals.get("role"), "color": g_vals.get("color")})
            else:
                vals = _as_float_list(g_vals, f"groups[{g_key!r}]") or []
                out.append({"name": nm, "values": vals, "role": None, "color": None})
    elif isinstance(raw_groups, (list, tuple)) and raw_groups:
        for idx, item in enumerate(raw_groups):
            if isinstance(item, dict):
                raw_nm = str(item.get("name", item.get("group", f"Group {idx + 1}")))
                nm = str(label_map.get(raw_nm, ot.clean_semantic_sample_name(raw_nm, clean_prefix)))
                v_seq = (
                    item.get("values")
                    if item.get("values") is not None
                    else (item.get("y") if item.get("y") is not None else item.get("raw_points"))
                )
                vals = _as_float_list(v_seq, f"groups[{idx}]") or []
                out.append({"name": nm, "values": vals, "role": item.get("role"), "color": item.get("color")})

    if not out and isinstance(cfg.get("series"), (list, tuple)):
        for idx, s_item in enumerate(cfg["series"]):
            if isinstance(s_item, dict):
                raw_nm = str(s_item.get("name", s_item.get("group", f"Group {idx + 1}")))
                nm = str(label_map.get(raw_nm, ot.clean_semantic_sample_name(raw_nm, clean_prefix)))
                v_seq = (
                    s_item.get("values")
                    if s_item.get("values") is not None
                    else (s_item.get("y") if s_item.get("y") is not None else s_item.get("raw_points"))
                )
                vals = _as_float_list(v_seq, f"series[{idx}]") or []
                out.append({"name": nm, "values": vals, "role": s_item.get("role"), "color": s_item.get("color")})

    group_col = cfg.get("group_col")
    value_col = cfg.get("value_col")
    bio_unit_col = cfg.get("bio_unit_col")

    if not out and cfg.get("rows") is not None and group_col and value_col:
        agg = stat_engine_mod.aggregate_replicates(cfg["rows"], group_col, value_col, bio_unit_col=bio_unit_col)
        for g_key, vals in agg.items():
            nm = str(label_map.get(g_key, ot.clean_semantic_sample_name(str(g_key), clean_prefix)))
            out.append({"name": nm, "values": [float(v) for v in vals], "role": None, "color": None})

    if not out:
        tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
        if tbl is None and cfg.get("input_file"):
            import importlib as _il

            _et = _il.import_module("electrochem_transforms")
            tbl = _et.load_tabular_sheet(
                cfg["input_file"],
                sheet=cfg.get("sheet", 0),
                header_row=cfg.get("header_row", 0),
            )
        if tbl is not None:
            if group_col and value_col:
                agg = stat_engine_mod.aggregate_replicates(tbl, group_col, value_col, bio_unit_col=bio_unit_col)
                for g_key, vals in agg.items():
                    nm = str(label_map.get(g_key, ot.clean_semantic_sample_name(str(g_key), clean_prefix)))
                    out.append({"name": nm, "values": [float(v) for v in vals], "role": None, "color": None})
            elif hasattr(tbl, "columns"):
                import pandas as _pd

                for col_nm in tbl.columns:
                    vals = _pd.to_numeric(tbl[col_nm], errors="coerce").dropna().tolist()
                    if vals:
                        nm = str(label_map.get(str(col_nm), ot.clean_semantic_sample_name(str(col_nm), clean_prefix)))
                        out.append({"name": nm, "values": [float(v) for v in vals], "role": None, "color": None})

    out = [g for g in out if len(g["values"]) > 0]
    if not out:
        raise ValueError(f"Mode {cfg.get('mode')!r} requires non-empty multi-group replicate data in 'groups' or 'series'.")
    return out


def _build_sig_bracket_guides(
    brackets: Sequence[Dict[str, Any]],
    *,
    color: str = "#111111",
    line_width_pt: float = 1.6,
    font_size_pt: float = 20.0,
) -> List[GuideSpec]:
    """Convert `stat_engine.compute_sig_bracket_tiers` output dicts into `GuideSpec(kind='sig_bracket')`."""
    guides: List[GuideSpec] = []
    for br in brackets:
        guides.append(
            GuideSpec(
                kind="sig_bracket",
                axis="y1",
                value=float(br["y_bar"]),
                x=float(br["x1"]),
                x2=float(br["x2"]),
                tip_drop=float(br["tip_drop"]),
                label=str(br.get("label") or br.get("stars") or ""),
                color=color,
                line_style="solid",
                line_width_pt=line_width_pt,
                font_size_pt=font_size_pt,
                meta=dict(br),
            )
        )
    return guides


def _compile_stat_bar_dot_sig(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Compile `stat_bar_dot_sig`: mean±SD/SEM/CI95 column bars overlaid with individual replicate
    dots (`LayerSpec(mark='bar_dot_error')`) and auto-computed significance brackets (`sig_bracket`).
    """
    import importlib as _il

    _sc_path = str(Path(__file__).resolve().parent)
    if _sc_path not in sys.path:
        sys.path.insert(0, _sc_path)
    _se = _il.import_module("stat_engine")

    group_items = _extract_multi_group_replicates(cfg, loaded_tables, _se)
    group_names = [g["name"] for g in group_items]
    groups_map = {g["name"]: g["values"] for g in group_items}
    n_groups = len(group_items)

    err_type = str(cfg.get("error_bar") or cfg.get("error_type") or "SD").strip().upper()
    if err_type not in ("SD", "SEM", "CI95", "95% CI"):
        raise ValueError(f"Unsupported error_bar={err_type!r} in 'stat_bar_dot_sig'; expected 'SD', 'SEM', or 'CI95'.")

    paired = bool(cfg.get("paired", False))
    control_group = cfg.get("control_group")
    p_adjust = str(cfg.get("p_adjust", "fdr_bh"))
    alpha = float(cfg.get("alpha", 0.05))
    raw_pairs = cfg.get("pairs")
    pairs = [tuple(p) for p in raw_pairs] if raw_pairs is not None else None
    hide_ns = bool(cfg.get("hide_ns", True))
    max_brackets = int(cfg.get("max_brackets", 6))
    show_stats = bool(cfg.get("show_stats", True))
    locale = str(cfg.get("locale", "en"))

    if n_groups >= 2:
        stat_report = _se.run_group_comparisons(
            groups_map,
            paired=paired,
            control_group=control_group,
            p_adjust=p_adjust,
            alpha=alpha,
            pairs=pairs,
        )
    else:
        stat_report = {
            "omnibus_test": "none",
            "omnibus_stat": 0.0,
            "omnibus_p": 1.0,
            "parametric": True,
            "homoscedastic": True,
            "levene_p": 1.0,
            "p_adjust_method": p_adjust,
            "summary": _se.summarize_groups(groups_map),
            "comparisons": [],
        }

    summary_by_name = {row["group"]: row for row in stat_report["summary"]}
    scheme = str(cfg.get("color_scheme", "paired_semantic"))
    roles = [g.get("role") for g in group_items]
    has_roles = any(r is not None for r in roles)
    resolved_cols = ot.resolve_series_colors(
        n_groups,
        roles=(roles if has_roles else None),
        scheme=scheme,
    )

    series_specs: List[SeriesSpec] = []
    group_tops: List[float] = []
    all_raw_min = min(min(g["values"]) for g in group_items)

    for idx, g_item in enumerate(group_items):
        g_name = g_item["name"]
        vals = [float(v) for v in g_item["values"]]
        s_row = summary_by_name[g_name]
        mean_v = float(s_row["mean"])
        if err_type == "SEM":
            err_v = float(s_row["sem"])
        elif err_type in ("CI95", "95% CI"):
            err_v = float(s_row["ci95_half"])
        else:
            err_v = float(s_row["sd"])

        c_hex = ot.normalize_hex(str(g_item["color"])) if g_item.get("color") else resolved_cols[idx % len(resolved_cols)]
        grad = ot.compute_gradient_pair_and_label_color(c_hex)
        top_v = max(max(vals), mean_v + err_v)
        group_tops.append(top_v)

        series_specs.append(
            SeriesSpec(
                name=g_name,
                x=[g_name],
                y=[mean_v],
                y_err=[err_v],
                role=g_item.get("role"),
                color=c_hex,
                gradient_top_color=grad.top_hex,
                gradient_bottom_color=grad.bottom_hex,
                label_color=grad.label_hex,
                show_value_labels=bool(cfg.get("show_value_labels", False)),
                value_format=str(cfg.get("value_format", "{:.2f}")),
                y_unit=cfg.get("y_unit"),
                meta={
                    "raw_points": vals,
                    "n": int(s_row["n"]),
                    "error_type": "CI95" if err_type == "95% CI" else err_type,
                    "group_index": idx,
                    "x_pos": float(idx + 1),
                    "mean": mean_v,
                    "sd": float(s_row["sd"]),
                    "sem": float(s_row["sem"]),
                    "ci95_half": float(s_row["ci95_half"]),
                    "median": float(s_row["median"]),
                },
            )
        )

    guides: List[GuideSpec] = []
    if show_stats and stat_report.get("comparisons"):
        bracket_tiers = _se.compute_sig_bracket_tiers(
            stat_report["comparisons"],
            group_names,
            group_tops,
            hide_ns=hide_ns,
            max_brackets=max_brackets,
            data_min=min(0.0, all_raw_min),
        )
        stat_report["brackets"] = bracket_tiers
        guides.extend(
            _build_sig_bracket_guides(
                bracket_tiers,
                color=str(cfg.get("bracket_color", "#111111")),
                line_width_pt=float(cfg.get("bracket_linewidth_pt", theme.get("guide_linewidth", 1.6))),
                font_size_pt=float(cfg.get("bracket_fontsize_pt", theme.get("callout_font_size", 20.0))),
            )
        )
    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    norm_err_type = "CI95" if err_type == "95% CI" else err_type
    layer = LayerSpec(
        layer_id="bar_dot_sig_main",
        mark="bar_dot_error",
        y_axis="y1",
        series=series_specs,
        categories=group_names,
        color_scheme=scheme,
        palette_colors=[s.color for s in series_specs if s.color],
        show_value_labels=bool(cfg.get("show_value_labels", False)),
        style_overrides={
            "error_type": norm_err_type,
            "jitter_width": float(cfg.get("jitter_width", 0.13)),
        },
    )
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "")),
        axis_kind="categorical",
        categories=group_names,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Response")),
        unit=cfg.get("y_unit"),
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    panel_meta: Dict[str, Any] = {
        "stat_report": stat_report,
        "error_bar_type": norm_err_type,
        "locale": locale,
    }
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["stat_report"] = stat_report
    fig_meta["error_bar_type"] = norm_err_type
    fig_meta["locale"] = locale

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "none")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Stat_Bar_Dot_Significance")),
        mode="stat_bar_dot_sig",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "omnibus_test": stat_report["omnibus_test"],
            "omnibus_p": stat_report["omnibus_p"],
            "error_bar_type": norm_err_type,
            "n_groups": n_groups,
        },
        meta=fig_meta,
    )


def _compile_stat_violin_raincloud(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Compile `stat_violin_raincloud`: multi-group raw distributions into `LayerSpec(mark='violin_box')`
    (default `color_scheme='okabe_ito'`) + optional `sig_bracket` guides (`show_stats=True` default).
    """
    import importlib as _il

    _sc_path = str(Path(__file__).resolve().parent)
    if _sc_path not in sys.path:
        sys.path.insert(0, _sc_path)
    _se = _il.import_module("stat_engine")

    group_items = _extract_multi_group_replicates(cfg, loaded_tables, _se)
    group_names = [g["name"] for g in group_items]
    groups_map = {g["name"]: g["values"] for g in group_items}
    n_groups = len(group_items)

    subtype = str(cfg.get("subtype", "violin_box")).strip().lower()
    scheme = str(cfg.get("color_scheme", "okabe_ito"))
    show_stats = bool(cfg.get("show_stats", True))
    paired = bool(cfg.get("paired", False))
    control_group = cfg.get("control_group")
    p_adjust = str(cfg.get("p_adjust", "fdr_bh"))
    alpha = float(cfg.get("alpha", 0.05))
    raw_pairs = cfg.get("pairs")
    pairs = [tuple(p) for p in raw_pairs] if raw_pairs is not None else None
    hide_ns = bool(cfg.get("hide_ns", True))
    max_brackets = int(cfg.get("max_brackets", 6))
    locale = str(cfg.get("locale", "en"))

    if n_groups >= 2:
        stat_report = _se.run_group_comparisons(
            groups_map,
            paired=paired,
            control_group=control_group,
            p_adjust=p_adjust,
            alpha=alpha,
            pairs=pairs,
        )
    else:
        stat_report = {
            "omnibus_test": "none",
            "omnibus_stat": 0.0,
            "omnibus_p": 1.0,
            "parametric": True,
            "homoscedastic": True,
            "levene_p": 1.0,
            "p_adjust_method": p_adjust,
            "summary": _se.summarize_groups(groups_map),
            "comparisons": [],
        }

    summary_by_name = {row["group"]: row for row in stat_report["summary"]}
    roles = [g.get("role") for g in group_items]
    has_roles = any(r is not None for r in roles)
    resolved_cols = ot.resolve_series_colors(
        n_groups,
        roles=(roles if has_roles else None),
        scheme=scheme,
    )

    series_specs: List[SeriesSpec] = []
    group_tops: List[float] = []
    all_raw_min = min(min(g["values"]) for g in group_items)

    for idx, g_item in enumerate(group_items):
        g_name = g_item["name"]
        vals = [float(v) for v in g_item["values"]]
        s_row = summary_by_name[g_name]
        c_hex = ot.normalize_hex(str(g_item["color"])) if g_item.get("color") else resolved_cols[idx % len(resolved_cols)]
        # Add minor KDE upper tail clearance (0.25 * SD) so brackets sit cleanly above violin tips
        kde_top = max(vals) + 0.25 * float(s_row["sd"])
        group_tops.append(kde_top)

        series_specs.append(
            SeriesSpec(
                name=g_name,
                y=vals,
                role=g_item.get("role"),
                color=c_hex,
                y_unit=cfg.get("y_unit"),
                meta={
                    "raw_points": vals,
                    "n": int(s_row["n"]),
                    "subtype": subtype,
                    "group_index": idx,
                    "label": g_name,
                    "median": float(s_row["median"]),
                    "iqr": float(s_row["iqr"]),
                },
            )
        )

    guides: List[GuideSpec] = []
    if show_stats and stat_report.get("comparisons"):
        bracket_tiers = _se.compute_sig_bracket_tiers(
            stat_report["comparisons"],
            group_names,
            group_tops,
            hide_ns=hide_ns,
            max_brackets=max_brackets,
            data_min=all_raw_min,
        )
        stat_report["brackets"] = bracket_tiers
        guides.extend(
            _build_sig_bracket_guides(
                bracket_tiers,
                color=str(cfg.get("bracket_color", "#111111")),
                line_width_pt=float(cfg.get("bracket_linewidth_pt", theme.get("guide_linewidth", 1.6))),
                font_size_pt=float(cfg.get("bracket_fontsize_pt", theme.get("callout_font_size", 20.0))),
            )
        )
    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    layer = LayerSpec(
        layer_id="violin_main",
        mark="violin_box",
        y_axis="y1",
        series=series_specs,
        categories=group_names,
        color_scheme=scheme,
        palette_colors=[s.color for s in series_specs if s.color],
        style_overrides={"subtype": subtype},
    )
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "")),
        axis_kind="categorical",
        categories=group_names,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Distribution")),
        unit=cfg.get("y_unit"),
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    panel_meta: Dict[str, Any] = {
        "stat_report": stat_report,
        "locale": locale,
    }
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["stat_report"] = stat_report
    fig_meta["locale"] = locale

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "none")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Stat_Violin_Distribution")),
        mode="stat_violin_raincloud",
        subtype=subtype,
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "omnibus_test": stat_report["omnibus_test"],
            "omnibus_p": stat_report["omnibus_p"],
            "n_groups": n_groups,
        },
        meta=fig_meta,
    )


def _compile_volcano_plot(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Compile `volcano_plot`: partitions (`log2fc`, `pval` / `neg_log10_p`) into 3 `SeriesSpec`
    (`Down` #2B6CB0, `NS` #B8C2CC, `Up` #D84B5C) on `LayerSpec(mark='scatter')`, adds dashed
    threshold guides, and stores top hits in `panel.meta['point_callouts']`.
    """
    fc_raw = cfg.get("log2fc", cfg.get("x"))
    p_raw = cfg.get("pval", cfg.get("p_adj", cfg.get("fdr")))
    nlp_raw = cfg.get("neg_log10_p", cfg.get("y"))
    lbl_raw = cfg.get("genes", cfg.get("labels"))

    if fc_raw is None and isinstance(cfg.get("points"), (list, tuple)):
        pts = cfg["points"]
        fc_raw = [pt.get("log2fc", pt.get("x")) for pt in pts]
        if any(pt.get("neg_log10_p") is not None or pt.get("y") is not None for pt in pts):
            nlp_raw = [pt.get("neg_log10_p", pt.get("y")) for pt in pts]
        else:
            p_raw = [pt.get("pval", pt.get("p_adj", pt.get("fdr"))) for pt in pts]
        lbl_raw = [pt.get("gene", pt.get("label", pt.get("name", f"Gene_{i+1}"))) for i, pt in enumerate(pts)]

    if fc_raw is None:
        tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
        if tbl is None and cfg.get("input_file"):
            import importlib as _il

            _et = _il.import_module("electrochem_transforms")
            tbl = _et.load_tabular_sheet(
                cfg["input_file"],
                sheet=cfg.get("sheet", 0),
                header_row=cfg.get("header_row", 0),
            )
        if tbl is not None:
            fc_col = cfg.get("fc_col", cfg.get("x_col", "log2FC"))
            fc_raw = _extract_column_from_table(tbl, fc_col)
            if cfg.get("neg_log10_p_col") is not None:
                nlp_raw = _extract_column_from_table(tbl, cfg["neg_log10_p_col"])
            else:
                p_col = cfg.get("p_col", cfg.get("y_col", "pval"))
                p_raw = _extract_column_from_table(tbl, p_col)
            g_col = cfg.get("gene_col", cfg.get("label_col"))
            if g_col is not None:
                lbl_raw = _extract_column_from_table(tbl, g_col)

    fc_list = _as_float_list(fc_raw, "log2fc")
    if not fc_list:
        raise ValueError("Mode 'volcano_plot' requires non-empty 'log2fc' array.")
    n_pts = len(fc_list)

    if nlp_raw is not None:
        nlp_list = _as_float_list(nlp_raw, "neg_log10_p") or []
    elif p_raw is not None:
        p_vals = _as_float_list(p_raw, "pval") or []
        if len(p_vals) != n_pts:
            raise ValueError(f"volcano_plot: len(pval)={len(p_vals)} != len(log2fc)={n_pts}")
        nlp_list = [-math.log10(max(float(pv), 1e-300)) for pv in p_vals]
    else:
        raise ValueError("Mode 'volcano_plot' requires either 'pval' or 'neg_log10_p'.")

    if len(nlp_list) != n_pts:
        raise ValueError(f"volcano_plot: len(neg_log10_p)={len(nlp_list)} != len(log2fc)={n_pts}")

    if lbl_raw is not None:
        labels_list = [str(v) for v in (lbl_raw.tolist() if hasattr(lbl_raw, "tolist") else lbl_raw)]
        if len(labels_list) != n_pts:
            raise ValueError(f"volcano_plot: len(genes/labels)={len(labels_list)} != len(log2fc)={n_pts}")
    else:
        labels_list = [f"Gene_{i + 1}" for i in range(n_pts)]

    fc_cutoff = abs(float(cfg.get("fc_cutoff", 1.0)))
    p_cutoff = float(cfg.get("p_cutoff", 0.05))
    if p_cutoff <= 0.0 or p_cutoff >= 1.0:
        raise ValueError(f"volcano_plot: p_cutoff must be in (0, 1), got {p_cutoff}")
    y_thresh = -math.log10(max(p_cutoff, 1e-300))
    top_n_labels = max(0, int(cfg.get("top_n_labels", 6)))
    locale = str(cfg.get("locale", "en"))

    down_color = str(cfg.get("down_color", "#2B6CB0"))
    ns_color = str(cfg.get("ns_color", "#B8C2CC"))
    up_color = str(cfg.get("up_color", "#D84B5C"))

    buckets: Dict[str, Dict[str, List[Any]]] = {
        "Down": {"x": [], "y": [], "labels": []},
        "NS": {"x": [], "y": [], "labels": []},
        "Up": {"x": [], "y": [], "labels": []},
    }
    sig_candidates: List[Dict[str, Any]] = []

    for x_v, y_v, g_lbl in zip(fc_list, nlp_list, labels_list):
        if x_v <= -fc_cutoff and y_v >= y_thresh:
            buckets["Down"]["x"].append(x_v)
            buckets["Down"]["y"].append(y_v)
            buckets["Down"]["labels"].append(g_lbl)
            sig_candidates.append({"x": x_v, "y": y_v, "label": g_lbl, "color": ot.normalize_hex(down_color), "regulation": "Down"})
        elif x_v >= fc_cutoff and y_v >= y_thresh:
            buckets["Up"]["x"].append(x_v)
            buckets["Up"]["y"].append(y_v)
            buckets["Up"]["labels"].append(g_lbl)
            sig_candidates.append({"x": x_v, "y": y_v, "label": g_lbl, "color": ot.normalize_hex(up_color), "regulation": "Up"})
        else:
            buckets["NS"]["x"].append(x_v)
            buckets["NS"]["y"].append(y_v)
            buckets["NS"]["labels"].append(g_lbl)

    color_by_bucket = {"Down": down_color, "NS": ns_color, "Up": up_color}
    size_by_bucket = {
        "Down": float(cfg.get("sig_marker_size_pt", 6.5)),
        "NS": float(cfg.get("ns_marker_size_pt", 4.8)),
        "Up": float(cfg.get("sig_marker_size_pt", 6.5)),
    }

    series_specs: List[SeriesSpec] = []
    for b_name in ("Down", "NS", "Up"):
        bx = buckets[b_name]["x"]
        by = buckets[b_name]["y"]
        bl = buckets[b_name]["labels"]
        if not bx:
            continue
        series_specs.append(
            SeriesSpec(
                name=b_name,
                x=bx,
                y=by,
                color=color_by_bucket[b_name],
                line_style="none",
                marker_style="circle_solid",
                marker_size_pt=size_by_bucket[b_name],
                meta={
                    "point_labels": bl,
                    "regulation": b_name,
                    "count": len(bx),
                    "alpha_pct": int(cfg.get("point_alpha_pct", 35)),
                },
            )
        )

    # Select top_n_labels callouts (prioritizing explicit highlight_genes if supplied, else highest y * (1 + 0.15*|x|))
    highlight_req = [str(g) for g in (cfg.get("highlight_genes") or cfg.get("callout_labels") or [])]
    point_callouts: List[Dict[str, Any]] = []
    if top_n_labels > 0 and sig_candidates:
        used_lbls: set[str] = set()
        if highlight_req:
            cand_by_lbl = {c["label"]: c for c in sig_candidates}
            for hl in highlight_req:
                if hl in cand_by_lbl and hl not in used_lbls and len(point_callouts) < top_n_labels:
                    c_hit = cand_by_lbl[hl]
                    point_callouts.append({"x": c_hit["x"], "y": c_hit["y"], "label": c_hit["label"], "color": c_hit["color"]})
                    used_lbls.add(hl)
        ranked = sorted(
            sig_candidates,
            key=lambda c: (float(c["y"]) * (1.0 + 0.15 * abs(float(c["x"]))), abs(float(c["x"]))),
            reverse=True,
        )
        for c_hit in ranked:
            if len(point_callouts) >= top_n_labels:
                break
            if c_hit["label"] not in used_lbls:
                point_callouts.append({"x": c_hit["x"], "y": c_hit["y"], "label": c_hit["label"], "color": c_hit["color"]})
                used_lbls.add(c_hit["label"])

    guides: List[GuideSpec] = [
        GuideSpec(kind="vline", value=-fc_cutoff, color="#666666", line_style="dashed", line_width_pt=1.5, label=""),
        GuideSpec(kind="vline", value=fc_cutoff, color="#666666", line_style="dashed", line_width_pt=1.5, label=""),
        GuideSpec(kind="hline", value=y_thresh, color="#666666", line_style="dashed", line_width_pt=1.5, label=""),
    ]
    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    layer = LayerSpec(
        layer_id="volcano_main",
        mark="scatter",
        y_axis="y1",
        series=series_specs,
        color_scheme="paired_semantic",
        palette_colors=[s.color for s in series_specs if s.color],
    )
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "log_2 Fold Change")),
        axis_kind="quantitative",
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "-log_10(FDR)" if "fdr" in cfg else "-log_10(p-value)")),
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    volcano_summary = {
        "n_total": n_pts,
        "n_down": len(buckets["Down"]["x"]),
        "n_ns": len(buckets["NS"]["x"]),
        "n_up": len(buckets["Up"]["x"]),
        "fc_cutoff": fc_cutoff,
        "p_cutoff": p_cutoff,
    }
    panel_meta: Dict[str, Any] = {
        "point_callouts": point_callouts,
        "volcano_summary": volcano_summary,
        "locale": locale,
    }
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["volcano_summary"] = volcano_summary

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_right")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Volcano_Differential_Expression")),
        mode="volcano_plot",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics=volcano_summary,
        meta=fig_meta,
    )


def _compile_forest_ablation_plot(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Compile `forest_ablation_plot`: horizontal effect size + 95% CI plot (`LayerSpec(mark='forest_ci')`)
    with inverted categorical `y1_axis` (item 1 at top) and dashed `vline` at `null_value`.
    """
    raw_items = cfg.get("items") or cfg.get("series") or cfg.get("rows")
    if not raw_items and (loaded_tables or cfg.get("input_file")):
        tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
        if tbl is None and cfg.get("input_file"):
            import importlib as _il

            _et = _il.import_module("electrochem_transforms")
            tbl = _et.load_tabular_sheet(
                cfg["input_file"],
                sheet=cfg.get("sheet", 0),
                header_row=cfg.get("header_row", 0),
            )
        if tbl is not None and hasattr(tbl, "to_dict"):
            raw_items = tbl.to_dict(orient="records")

    if not isinstance(raw_items, (list, tuple)) or not raw_items:
        raise ValueError("Mode 'forest_ablation_plot' requires non-empty 'items' list.")

    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    null_value = float(cfg.get("null_value", 0.0))
    val_fmt = str(cfg.get("value_format", "{:.2f}"))
    if "{" not in val_fmt:
        val_fmt = "{:" + val_fmt.lstrip(":") + "}"
    locale = str(cfg.get("locale", "en"))

    K = len(raw_items)
    default_cs = "okabe_ito" if K > 6 else "paired_semantic"
    scheme = str(cfg.get("color_scheme", default_cs))
    roles = [it.get("role") if isinstance(it, dict) else None for it in raw_items]
    has_roles = any(r is not None for r in roles)
    resolved_cols = ot.resolve_series_colors(K, roles=(roles if has_roles else None), scheme=scheme)

    names: List[str] = []
    estimates: List[float] = []
    ci_lows: List[float] = []
    ci_highs: List[float] = []
    formatted_cis: List[str] = []
    item_colors: List[str] = []
    normalized_items: List[Dict[str, Any]] = []

    for idx, it in enumerate(raw_items):
        if not isinstance(it, dict):
            raise TypeError(f"forest_ablation_plot items[{idx}] must be a dict, got {type(it).__name__}")
        raw_nm = str(it.get("name", it.get("label", f"Item {idx + 1}")))
        nm = ot.clean_semantic_sample_name(raw_nm, clean_prefix)
        est_raw = it.get("estimate", it.get("mean", it.get("effect", it.get("x"))))
        if est_raw is None:
            raise ValueError(f"forest_ablation_plot items[{idx}] ({nm!r}) is missing 'estimate'.")
        est = float(est_raw)

        lo_raw = it.get("ci_low", it.get("low", it.get("lower")))
        hi_raw = it.get("ci_high", it.get("high", it.get("upper")))
        if lo_raw is None or hi_raw is None:
            half_w = float(it.get("ci95_half", it.get("ci", it.get("err", 0.0))))
            lo = est - abs(half_w)
            hi = est + abs(half_w)
        else:
            lo = float(lo_raw)
            hi = float(hi_raw)
        if lo > hi:
            lo, hi = hi, lo

        c_hex = ot.normalize_hex(str(it["color"])) if it.get("color") else resolved_cols[idx % len(resolved_cols)]
        fmt_str = f"{val_fmt.format(est)} [{val_fmt.format(lo)}, {val_fmt.format(hi)}]"

        names.append(nm)
        estimates.append(est)
        ci_lows.append(lo)
        ci_highs.append(hi)
        formatted_cis.append(fmt_str)
        item_colors.append(c_hex)
        normalized_items.append(
            {
                "name": nm,
                "y_pos": float(idx + 1),
                "estimate": est,
                "ci_low": lo,
                "ci_high": hi,
                "formatted_ci": fmt_str,
                "color": c_hex,
                "p_value": float(it["p_value"]) if it.get("p_value") is not None else None,
            }
        )

    y_positions = [float(i + 1) for i in range(K)]
    s_main = SeriesSpec(
        name=str(cfg.get("series_name", "Estimate (95% CI)")),
        x=estimates,
        y=y_positions,
        color=item_colors[0],
        line_style="none",
        marker_style="circle_solid",
        marker_size_pt=float(cfg.get("marker_size_pt", 8.5)),
        show_value_labels=bool(cfg.get("show_ci_text", True)),
        value_format=val_fmt,
        x_unit=cfg.get("x_unit"),
        meta={
            "ci_low": ci_lows,
            "ci_high": ci_highs,
            "formatted_ci": formatted_cis,
            "item_names": names,
            "item_colors": item_colors,
            "null_value": null_value,
            "error_type": "95% CI",
            "items": normalized_items,
        },
    )

    guides: List[GuideSpec] = [
        GuideSpec(
            kind="vline",
            value=null_value,
            color=str(cfg.get("null_color", "#555555")),
            line_style="dashed",
            line_width_pt=1.6,
            label=str(cfg.get("null_label", "")),
        )
    ]
    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    layer = LayerSpec(
        layer_id="forest_main",
        mark="forest_ci",
        y_axis="y1",
        series=[s_main],
        categories=names,
        color_scheme=scheme,
        palette_colors=item_colors,
        show_value_labels=bool(cfg.get("show_ci_text", True)),
        style_overrides={"error_type": "95% CI", "null_value": null_value},
    )
    x_scale = str(cfg.get("x_scale", "linear")).strip().lower()
    if x_scale == "log":
        x_scale = "log10"
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "Effect Size (95% CI)")),
        unit=cfg.get("x_unit"),
        axis_kind="quantitative",
        scale=x_scale,
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "")),
        axis_kind="categorical",
        categories=names,
        invert=True,
        limits=(0.4, float(K) + 0.6),
    )
    panel_meta: Dict[str, Any] = {
        "forest_items": normalized_items,
        "null_value": null_value,
        "error_bar_type": "95% CI",
        "locale": locale,
    }
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["error_bar_type"] = "95% CI"

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "none")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Forest_Ablation_CI")),
        mode="forest_ablation_plot",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_items": K, "null_value": null_value},
        meta=fig_meta,
    )


def _compile_free_energy_diagram(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> "FigureSpec":
    """
    Compile `free_energy_diagram`: multi-pathway reaction free-energy step profile
    (`LayerSpec(mark='energy_step')`) with horizontal plateaus `[i - 0.28, i + 0.28]`,
    dashed connectors `[i + 0.28, i + 1 - 0.28]`, categorical X `step_labels`,
    and Y label `Free Energy \\g(D)\\i(G) (eV)`.
    """
    raw_pathways = cfg.get("pathways") or cfg.get("series")
    if not isinstance(raw_pathways, (list, tuple)) or not raw_pathways:
        raise ValueError("Mode 'free_energy_diagram' requires non-empty 'pathways' list.")

    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    hw = float(cfg.get("plateau_half_width", 0.28))
    if not (0.05 <= hw <= 0.45):
        raise ValueError(f"plateau_half_width must be in [0.05, 0.45], got {hw}")
    locale = str(cfg.get("locale", "en"))

    n_pw = len(raw_pathways)
    scheme = str(cfg.get("color_scheme", "paired_semantic" if n_pw <= 6 else "okabe_ito"))
    roles = [pw.get("role") if isinstance(pw, dict) else None for pw in raw_pathways]
    has_roles = any(r is not None for r in roles)
    resolved_cols = ot.resolve_series_colors(n_pw, roles=(roles if has_roles else None), scheme=scheme)

    first_steps = raw_pathways[0].get("steps", raw_pathways[0].get("energies", raw_pathways[0].get("y", raw_pathways[0].get("values"))))
    first_floats = _as_float_list(first_steps, "pathways[0].steps")
    if not first_floats or len(first_floats) < 2:
        raise ValueError("free_energy_diagram requires at least 2 energy steps per pathway.")
    M = len(first_floats)

    raw_step_labels = cfg.get("step_labels") or cfg.get("categories") or cfg.get("reaction_steps")
    if raw_step_labels is not None:
        step_labels = [str(s) for s in raw_step_labels]
        if len(step_labels) != M:
            raise ValueError(f"len(step_labels)={len(step_labels)} must match pathway step count ({M}).")
    else:
        step_labels = [f"Step {i + 1}" for i in range(M)]

    base_lw = float(theme.get("curve_linewidth", 3.0))
    pw_series: List[SeriesSpec] = []
    ts_spline_series: List[SeriesSpec] = []
    rds_records: List[Dict[str, Any]] = []
    ts_records: List[Dict[str, Any]] = []
    guides: List[GuideSpec] = []

    all_g_vals: List[float] = []
    for pw_tmp in raw_pathways:
        if isinstance(pw_tmp, dict):
            st_tmp = pw_tmp.get("steps", pw_tmp.get("energies", pw_tmp.get("y", pw_tmp.get("values"))))
            if st_tmp is not None:
                all_g_vals.extend(_as_float_list(st_tmp, "steps") or [])
            for ts_tmp in (pw_tmp.get("ts") or pw_tmp.get("ts_barriers") or []):
                if isinstance(ts_tmp, dict) and ts_tmp.get("g_ts") is not None:
                    all_g_vals.append(float(ts_tmp["g_ts"]))
    g_span_est = max((max(all_g_vals) - min(all_g_vals)) if all_g_vals else 1.0, 0.5)

    for idx, pw in enumerate(raw_pathways):
        if not isinstance(pw, dict):
            raise TypeError(f"free_energy_diagram pathways[{idx}] must be a dict.")
        raw_nm = str(pw.get("name", f"Pathway {idx + 1}"))
        nm = ot.clean_semantic_sample_name(raw_nm, clean_prefix)
        st_seq = pw.get("steps", pw.get("energies", pw.get("y", pw.get("values"))))
        steps_v = _as_float_list(st_seq, f"pathways[{idx}].steps") or []
        if len(steps_v) != M:
            raise ValueError(
                f"free_energy_diagram pathway {nm!r} has {len(steps_v)} steps, expected {M}."
            )
        c_hex = ot.normalize_hex(str(pw["color"])) if pw.get("color") else resolved_cols[idx % len(resolved_cols)]

        # Resolve optional transition-state saddle points (`ts` / `ts_barriers`)
        raw_ts_list = pw.get("ts") if pw.get("ts") is not None else pw.get("ts_barriers")
        ts_by_step: Dict[int, Dict[str, Any]] = {}
        norm_ts_list: List[Dict[str, Any]] = []
        if isinstance(raw_ts_list, (list, tuple)) and raw_ts_list:
            zero_based = any(
                isinstance(t_it, dict)
                and isinstance(t_it.get("step_from"), int)
                and int(t_it["step_from"]) == 0
                for t_it in raw_ts_list
            )
            for t_i, t_it in enumerate(raw_ts_list):
                if not isinstance(t_it, dict):
                    raise TypeError(f"pathways[{idx}].ts[{t_i}] must be a dict.")
                sf_raw = t_it.get("step_from")
                st_raw = t_it.get("step_to")
                if isinstance(sf_raw, str) and sf_raw in step_labels:
                    s_from_idx = step_labels.index(sf_raw)
                elif sf_raw is not None:
                    s_from_idx = int(sf_raw) if zero_based else int(sf_raw) - 1
                else:
                    raise ValueError(f"pathways[{idx}].ts[{t_i}] requires 'step_from'.")
                if isinstance(st_raw, str) and st_raw in step_labels:
                    s_to_idx = step_labels.index(st_raw)
                elif st_raw is not None:
                    s_to_idx = int(st_raw) if zero_based else int(st_raw) - 1
                else:
                    s_to_idx = s_from_idx + 1
                if not (0 <= s_from_idx < M - 1 and s_to_idx == s_from_idx + 1):
                    raise ValueError(
                        f"pathways[{idx}].ts[{t_i}] must connect adjacent steps in 1..{M}, got ({sf_raw} -> {st_raw})."
                    )
                g_ts_val = float(t_it["g_ts"])
                ts_lbl = str(t_it.get("label", "")).strip()
                x_r = float(s_from_idx + 1) + hw
                x_l = float(s_to_idx + 1) - hw
                x_m = 0.5 * (x_r + x_l)
                g_a = float(steps_v[s_from_idx])
                g_b = float(steps_v[s_to_idx])
                spline_x = [
                    round(x_r, 6),
                    round(x_r + 0.25 * (x_l - x_r), 6),
                    round(x_m, 6),
                    round(x_r + 0.75 * (x_l - x_r), 6),
                    round(x_l, 6),
                ]
                spline_y = [
                    round(g_a, 6),
                    round(0.5 * (g_a + g_ts_val), 6),
                    round(g_ts_val, 6),
                    round(0.5 * (g_ts_val + g_b), 6),
                    round(g_b, 6),
                ]
                ts_rec = {
                    "pathway": nm,
                    "step_from": s_from_idx + 1,
                    "step_to": s_to_idx + 1,
                    "step_from_label": step_labels[s_from_idx],
                    "step_to_label": step_labels[s_to_idx],
                    "g_ts": g_ts_val,
                    "ea_forward": round(g_ts_val - g_a, 6),
                    "label": ts_lbl,
                    "spline_x": spline_x,
                    "spline_y": spline_y,
                }
                ts_by_step[s_from_idx] = ts_rec
                norm_ts_list.append(ts_rec)
                ts_records.append(ts_rec)
                ts_spline_series.append(
                    SeriesSpec(
                        name=f"{nm}_{ts_lbl or f'TS{s_from_idx + 1}'}",
                        x=spline_x,
                        y=spline_y,
                        color=c_hex,
                        line_style=str(t_it.get("line_style", "solid")),
                        line_width_pt=float(t_it.get("line_width_pt", max(1.1, round(base_lw * 0.85, 2)))),
                        marker_style="none",
                        y_unit=str(cfg.get("y_unit", "eV")),
                        meta={
                            "line_connect": "spline",
                            "skip_legend": True,
                            "is_ts_barrier": True,
                            "ts_label": ts_lbl,
                            "g_ts": g_ts_val,
                            "ea_forward": round(g_ts_val - g_a, 6),
                        },
                    )
                )
                if ts_lbl and bool(t_it.get("show_label", True)):
                    guides.append(
                        GuideSpec(
                            kind="peak_tag",
                            x=x_m,
                            y=g_ts_val + 0.045 * g_span_est,
                            value=x_m,
                            label=ts_lbl,
                            color=c_hex,
                        )
                    )

        # 1-based Origin categorical X coordinates: step k sits at x = k + 1.0
        x_centers = [float(k + 1) for k in range(M)]
        plateau_segments = [
            ([float(k + 1) - hw, float(k + 1) + hw], [float(g_val), float(g_val)])
            for k, g_val in enumerate(steps_v)
        ]
        connector_segments = [
            ([float(k + 1) + hw, float(k + 2) - hw], [float(steps_v[k]), float(steps_v[k + 1])])
            for k in range(M - 1)
            if k not in ts_by_step
        ]

        deltas = [float(steps_v[k + 1] - steps_v[k]) for k in range(M - 1)]
        rds_step_idx = max(range(len(deltas)), key=lambda k: deltas[k])
        rds_info = {
            "pathway": nm,
            "step_from_idx": rds_step_idx,
            "step_to_idx": rds_step_idx + 1,
            "step_from": step_labels[rds_step_idx],
            "step_to": step_labels[rds_step_idx + 1],
            "g_from": float(steps_v[rds_step_idx]),
            "g_to": float(steps_v[rds_step_idx + 1]),
            "delta_g_max": float(deltas[rds_step_idx]),
            "color": c_hex,
        }
        rds_records.append(rds_info)

        pw_series.append(
            SeriesSpec(
                name=nm,
                x=x_centers,
                y=steps_v,
                role=pw.get("role"),
                color=c_hex,
                line_style="solid",
                line_width_pt=float(pw.get("line_width_pt", round(base_lw * 1.35, 2))),
                marker_style="none",
                y_unit=str(cfg.get("y_unit", "eV")),
                meta={
                    "steps": steps_v,
                    "step_labels": step_labels,
                    "plateau_half_width": hw,
                    "plateau_segments": plateau_segments,
                    "connector_segments": connector_segments,
                    "step_deltas": deltas,
                    "rds": rds_info,
                    "ts_barriers": norm_ts_list,
                },
            )
        )

    rds_cfg = cfg.get("rds_highlight")
    if rds_cfg:
        # Optional span_v annotation on the primary or specified pathway if requested
        if isinstance(rds_cfg, dict) and rds_cfg.get("draw_span", False):
            target_pw = str(rds_cfg.get("pathway", rds_records[0]["pathway"]))
            rec = next((r for r in rds_records if r["pathway"] == target_pw), rds_records[0])
            guides.append(
                GuideSpec(
                    kind="span_v",
                    start=rec["g_from"],
                    end=rec["g_to"],
                    anchor_pos=float(rec["step_to_idx"] + 1),
                    label=f"\\g(D)\\i(G)\\-(RDS) = {rec['delta_g_max']:.2f} eV",
                    color=rec["color"],
                    line_width_pt=1.6,
                )
            )

    if bool(cfg.get("show_zero_line", False)):
        guides.append(GuideSpec(kind="hline", value=0.0, color="#888888", line_style="dashed", line_width_pt=1.4, label=""))
    if cfg.get("guides"):
        guides.extend(_build_guides_from_cfg(cfg["guides"], theme))

    layer = LayerSpec(
        layer_id="energy_step_main",
        mark="energy_step",
        y_axis="y1",
        series=pw_series,
        categories=step_labels,
        color_scheme=scheme,
        palette_colors=[s.color for s in pw_series if s.color],
        style_overrides={"plateau_half_width": hw, "rds_highlight": bool(rds_cfg)},
    )
    panel_layers: List[LayerSpec] = []
    if ts_spline_series:
        panel_layers.append(
            LayerSpec(
                layer_id="energy_ts_splines",
                mark="line_scatter",
                y_axis="y1",
                series=ts_spline_series,
                color_scheme=scheme,
                palette_colors=[s.color for s in ts_spline_series if s.color],
                origin_plot_type=200,
            )
        )
    panel_layers.append(layer)

    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "Reaction Coordinate")),
        axis_kind="categorical",
        categories=step_labels,
        limits=(1.0 - hw - 0.25, float(M) + hw + 0.25),
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Free Energy \\g(D)\\i(G) (eV)")),
        unit=str(cfg.get("y_unit", "eV")),
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    panel_meta: Dict[str, Any] = {
        "step_labels": step_labels,
        "plateau_half_width": hw,
        "rds_highlights": rds_records if rds_cfg else [],
        "rds_summary": rds_records,
        "ts_summary": ts_records,
        "locale": locale,
    }
    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["rds_summary"] = rds_records
    if ts_records:
        fig_meta["ts_summary"] = ts_records

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=panel_layers,
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_left" if n_pw >= 2 else "none")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Reaction_Free_Energy_Diagram")),
        mode="free_energy_diagram",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "n_pathways": n_pw,
            "n_steps": M,
            "rds_by_pathway": {r["pathway"]: round(r["delta_g_max"], 4) for r in rds_records},
            "n_ts_barriers": len(ts_records),
        },
        meta=fig_meta,
    )


# ---------------------------------------------------------------------------
# Phase 2/3 Cross-Science Compilers (Survival, ROC/PR, NMR, Broken-Axis,
# Dual-X Optical, Ternary, Polar/Radar, Multi-Track Depth, Vector Quiver)
# ---------------------------------------------------------------------------


def _compile_kaplan_meier_plot(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `kaplan_meier_plot`: clinical/reliability Kaplan-Meier step curves + Greenwood CI + censor ticks + Number-at-risk."""
    import stat_engine as se

    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    raw_groups = cfg.get("groups") or cfg.get("arms") or cfg.get("series")
    if not raw_groups and tbl is not None:
        t_col = cfg.get("time_col", "time")
        e_col = cfg.get("event_col", cfg.get("status_col", "event"))
        g_col = cfg.get("group_col", cfg.get("arm_col"))
        t_all = _extract_column_from_table(tbl, t_col) or []
        e_all = _extract_column_from_table(tbl, e_col) or []
        if g_col is not None:
            g_all = [str(v) for v in (_extract_column_from_table(tbl, g_col) or [])]
            seen_g: List[str] = []
            for gv in g_all:
                if gv not in seen_g:
                    seen_g.append(gv)
            raw_groups = [
                {
                    "name": gn,
                    "time": [t_all[i] for i in range(len(t_all)) if g_all[i] == gn],
                    "event": [e_all[i] for i in range(len(e_all)) if g_all[i] == gn],
                }
                for gn in seen_g
            ]
        else:
            raw_groups = [{"name": str(cfg.get("arm_name", "Cohort")), "time": t_all, "event": e_all}]

    if not isinstance(raw_groups, (list, tuple)) or not raw_groups:
        raise ValueError("Mode 'kaplan_meier_plot' requires non-empty 'groups' / 'arms' list.")

    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    locale = str(cfg.get("locale", "en"))
    show_ci = bool(cfg.get("show_ci", True))
    show_censor = bool(cfg.get("show_censor", True))
    show_risk_table = bool(cfg.get("show_risk_table", True))
    y_scale_pct = bool(cfg.get("y_scale_pct", False))
    conf_level = float(cfg.get("conf_level", cfg.get("ci_level", 0.95)))

    n_arms = len(raw_groups)
    scheme = str(cfg.get("color_scheme", "paired_semantic" if n_arms <= 6 else "okabe_ito"))
    roles = [g.get("role") if isinstance(g, dict) else None for g in raw_groups]
    resolved_cols = ot.resolve_series_colors(n_arms, roles=(roles if any(roles) else None), scheme=scheme)

    norm_groups: List[Dict[str, Any]] = []
    for idx, g_item in enumerate(raw_groups):
        if not isinstance(g_item, dict):
            raise TypeError(f"kaplan_meier_plot groups[{idx}] must be a dict.")
        nm = ot.clean_semantic_sample_name(str(g_item.get("name", f"Arm {idx + 1}")), clean_prefix)
        c_hex = ot.normalize_hex(str(g_item["color"])) if g_item.get("color") else resolved_cols[idx % len(resolved_cols)]
        norm_groups.append(
            {
                "name": nm,
                "time": g_item.get("time", g_item.get("x")),
                "event": g_item.get("event", g_item.get("status", g_item.get("censor_event"))),
                "role": g_item.get("role"),
                "color": c_hex,
            }
        )

    km_res = se.kaplan_meier_survival(norm_groups, risk_times=cfg.get("risk_times"), conf_level=conf_level)
    y_mult = 100.0 if y_scale_pct else 1.0
    base_lw = float(theme.get("curve_linewidth", 3.0))

    km_series: List[SeriesSpec] = []
    max_time_obs = 0.0
    for idx, arm_res in enumerate(km_res["arms"]):
        arm_nm = str(arm_res.get("name", norm_groups[idx]["name"]))
        c_hex = ot.normalize_hex(str(arm_res.get("color") or norm_groups[idx]["color"]))
        step_t = [float(v) for v in arm_res["time"]]
        step_s = [float(v) * y_mult for v in arm_res["survival"]]
        if step_t:
            max_time_obs = max(max_time_obs, max(step_t))
        ci_lo = [float(v) * y_mult for v in arm_res["ci_low"]] if (show_ci and arm_res.get("ci_low") is not None) else None
        ci_hi = [float(v) * y_mult for v in arm_res["ci_high"]] if (show_ci and arm_res.get("ci_high") is not None) else None
        cens_t = [float(v) for v in (arm_res.get("censored_time") or [])] if show_censor else []
        cens_s = [float(v) * y_mult for v in (arm_res.get("censored_surv") or [])] if show_censor else []
        med_t = float(arm_res["median_survival"]) if arm_res.get("median_survival") is not None else None

        km_series.append(
            SeriesSpec(
                name=arm_nm,
                x=step_t,
                y=step_s,
                y_low=ci_lo,
                y_high=ci_hi,
                role=arm_res.get("role"),
                color=c_hex,
                line_style="solid",
                line_width_pt=base_lw,
                marker_style="none",
                fill_alpha=float(cfg.get("ci_alpha", 0.22)) if show_ci else None,
                x_unit=cfg.get("x_unit"),
                y_unit="%" if y_scale_pct else None,
                meta={
                    "line_connect": "step_horz",
                    "censored_x": cens_t,
                    "censored_y": cens_s,
                    "median_survival": med_t,
                    "n_total": arm_res.get("n_total", arm_res.get("n")),
                    "n_events": arm_res.get("n_events"),
                    "n_censored": arm_res.get("n_censored"),
                },
            )
        )

    risk_tbl = copy.deepcopy(km_res.get("at_risk_table")) if km_res.get("at_risk_table") else None
    rt_step: Optional[float] = None
    x_hi_default = max(1.0, max_time_obs)
    if risk_tbl and isinstance(risk_tbl.get("times"), list) and len(risk_tbl["times"]) >= 2:
        rt_times = [float(v) for v in risk_tbl["times"]]
        if rt_times[1] > rt_times[0]:
            rt_step = round(rt_times[1] - rt_times[0], 8)
        x_hi_default = max(x_hi_default, max(rt_times))
        for r_idx, r_row in enumerate(risk_tbl.get("rows") or []):
            if isinstance(r_row, dict) and r_idx < len(km_series):
                r_row.setdefault("color", km_series[r_idx].color)

    summary_lines: List[str] = []
    lr = km_res.get("logrank")
    if isinstance(lr, dict) and lr.get("p_value") is not None:
        pv = float(lr["p_value"])
        p_txt = "< 0.0001" if pv < 1e-4 else f"= {pv:.4f}" if pv < 0.01 else f"= {pv:.3f}"
        summary_lines.append(f"Log-rank p {p_txt}")
    hr = km_res.get("hazard_ratio")
    if isinstance(hr, dict) and hr.get("hr") is not None:
        hr_v = float(hr["hr"])
        hr_lo = hr.get("hr_ci_low", hr.get("ci_low"))
        hr_hi = hr.get("hr_ci_high", hr.get("ci_high"))
        if hr_lo is not None and hr_hi is not None:
            summary_lines.append(f"HR = {hr_v:.2f} (95% CI: {float(hr_lo):.2f}-{float(hr_hi):.2f})")
        else:
            summary_lines.append(f"HR = {hr_v:.2f}")

    guides = _build_guides_from_cfg(cfg.get("guides", []), theme)
    if bool(cfg.get("show_median_guides", False)):
        guides.append(
            GuideSpec(
                kind="hline",
                value=50.0 if y_scale_pct else 0.5,
                color="#888888",
                line_style="dashed",
                line_width_pt=max(0.8, round(base_lw * 0.48, 2)),
            )
        )

    layer = LayerSpec(
        layer_id="km_main",
        mark="km_step",
        y_axis="y1",
        series=km_series,
        color_scheme=scheme,
        palette_colors=[s.color for s in km_series if s.color],
        origin_plot_type=200,
    )
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "Time (months)")),
        unit=cfg.get("x_unit"),
        axis_kind="quantitative",
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else (0.0, x_hi_default),
        major_step=float(cfg["x_major_step"]) if cfg.get("x_major_step") is not None else rt_step,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Survival (%)" if y_scale_pct else "Survival Probability")),
        unit="%" if y_scale_pct else None,
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else (0.0, 105.0 if y_scale_pct else 1.05),
        major_step=20.0 if y_scale_pct else 0.2,
    )

    panel_meta: Dict[str, Any] = {
        "km_summary_lines": summary_lines,
        "logrank": lr,
        "hazard_ratio": hr,
        "y_scale_pct": y_scale_pct,
        "locale": locale,
    }
    if show_risk_table and risk_tbl:
        panel_meta["at_risk_table"] = risk_tbl

    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["statistical_tests"] = list(km_res.get("stat_rows") or [])
    if show_risk_table and risk_tbl:
        fig_meta["at_risk_table"] = risk_tbl

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_right")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=str(cfg.get("title", "Kaplan_Meier_Survival")),
        mode="kaplan_meier_plot",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "n_arms": n_arms,
            "logrank_p": lr.get("p_value") if isinstance(lr, dict) else None,
            "hr": hr.get("hr") if isinstance(hr, dict) else None,
            "median_survival": {s.name: s.meta.get("median_survival") for s in km_series},
        },
        meta=fig_meta,
    )


def _compile_roc_pr_curve(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `roc_pr_curve`: multi-model ROC (AUROC ± Hanley-McNeil CI + Youden point) or Precision-Recall curves."""
    import stat_engine as se

    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    raw_models = cfg.get("models") or cfg.get("series")
    if not raw_models and tbl is not None:
        yt_col = cfg.get("y_true_col", "y_true")
        ys_cols = cfg.get("y_score_cols") or ([cfg["y_score_col"]] if cfg.get("y_score_col") else ["y_score"])
        yt_vals = _extract_column_from_table(tbl, yt_col)
        raw_models = [
            {"name": str(sc), "y_true": yt_vals, "y_score": _extract_column_from_table(tbl, sc)}
            for sc in ys_cols
        ]
    if not isinstance(raw_models, (list, tuple)) or not raw_models:
        raise ValueError("Mode 'roc_pr_curve' requires non-empty 'models' / 'series' list.")

    curve_kind = str(cfg.get("curve_kind") or cfg.get("subtype") or "roc").strip().lower()
    if curve_kind not in ("roc", "pr"):
        raise ValueError(f"roc_pr_curve curve_kind must be 'roc' or 'pr', got {curve_kind!r}")
    show_opt = bool(cfg.get("show_optimal_point", True))
    conf_level = float(cfg.get("conf_level", cfg.get("ci_level", 0.95)))
    locale = str(cfg.get("locale", "en"))
    clean_prefix = bool(cfg.get("clean_sample_prefix", False))

    n_models = len(raw_models)
    scheme = str(cfg.get("color_scheme", "paired_semantic" if n_models <= 6 else "okabe_ito"))
    roles = [m.get("role") if isinstance(m, dict) else None for m in raw_models]
    resolved_cols = ot.resolve_series_colors(n_models, roles=(roles if any(roles) else None), scheme=scheme)

    norm_models: List[Dict[str, Any]] = []
    for idx, m_item in enumerate(raw_models):
        if not isinstance(m_item, dict):
            raise TypeError(f"roc_pr_curve models[{idx}] must be a dict.")
        m_copy = dict(m_item)
        m_copy["name"] = ot.clean_semantic_sample_name(str(m_item.get("name", f"Model {idx + 1}")), clean_prefix)
        m_copy["color"] = ot.normalize_hex(str(m_item["color"])) if m_item.get("color") else resolved_cols[idx % len(resolved_cols)]
        norm_models.append(m_copy)

    roc_res = se.compute_roc_pr_curves(norm_models, conf_level=conf_level)
    curves_list = roc_res.get("curves") or []
    base_lw = float(theme.get("curve_linewidth", 3.0))

    series_specs: List[SeriesSpec] = []
    best_opt: Optional[Tuple[float, float, str, str]] = None
    best_auc = -1.0

    for idx, c_rec in enumerate(curves_list):
        m_nm = str(c_rec.get("name", norm_models[idx]["name"]))
        c_hex = ot.normalize_hex(str(c_rec.get("color") or norm_models[idx]["color"]))
        auroc = float(c_rec.get("auroc", 0.0))
        ci_lo = c_rec.get("ci_low")
        ci_hi = c_rec.get("ci_high")
        auprc = c_rec.get("auprc")

        if curve_kind == "pr":
            xv = _as_float_list(c_rec.get("recall") or c_rec.get("fpr"), f"models[{idx}].recall") or [0.0, 1.0]
            yv = _as_float_list(c_rec.get("precision") or c_rec.get("tpr"), f"models[{idx}].precision") or [1.0, 0.5]
            metric_val = float(auprc) if auprc is not None else auroc
            disp_nm = f"{m_nm} (AUPRC = {metric_val:.3f})"
        else:
            xv = _as_float_list(c_rec.get("fpr"), f"models[{idx}].fpr") or [0.0, 1.0]
            yv = _as_float_list(c_rec.get("tpr"), f"models[{idx}].tpr") or [0.0, 1.0]
            disp_nm = f"{m_nm} (AUC = {auroc:.3f})"
            opt_d = c_rec.get("optimal_point") or c_rec.get("youden")
            if isinstance(opt_d, dict) and opt_d.get("fpr") is not None and opt_d.get("tpr") is not None:
                if auroc > best_auc:
                    best_auc = auroc
                    best_opt = (float(opt_d["fpr"]), float(opt_d["tpr"]), c_hex, m_nm)

        series_specs.append(
            SeriesSpec(
                name=disp_nm,
                x=xv,
                y=yv,
                color=c_hex,
                role=norm_models[idx].get("role"),
                line_style="solid",
                line_width_pt=base_lw,
                marker_style="none",
                meta={
                    "model_name": m_nm,
                    "curve_kind": curve_kind,
                    "auroc": auroc,
                    "ci_low": ci_lo,
                    "ci_high": ci_hi,
                    "auprc": auprc,
                    "optimal_point": c_rec.get("optimal_point") or c_rec.get("youden"),
                },
            )
        )

    # Diagonal chance line (ROC) or prevalence baseline (PR)
    if curve_kind == "roc":
        series_specs.append(
            SeriesSpec(
                name="Chance",
                x=[0.0, 1.0],
                y=[0.0, 1.0],
                color="#888888",
                line_style="dashed",
                line_width_pt=max(0.8, round(base_lw * 0.52, 2)),
                marker_style="none",
                meta={"skip_legend": True, "is_chance_line": True},
            )
        )
        if show_opt and best_opt is not None:
            opt_fpr, opt_tpr, opt_col, opt_nm = best_opt
            series_specs.append(
                SeriesSpec(
                    name=f"{opt_nm} Cutoff",
                    x=[opt_fpr],
                    y=[opt_tpr],
                    color=opt_col,
                    line_style="none",
                    marker_style="circle_open",
                    marker_size_pt=float(theme.get("origin_native", {}).get("marker_size_pt", 7.5)) * 1.15,
                    meta={"skip_legend": True, "is_optimal_point": True},
                )
            )
    else:
        pos_rate = float(curves_list[0].get("pos_rate") or 0.5) if curves_list else 0.5
        series_specs.append(
            SeriesSpec(
                name="Baseline",
                x=[0.0, 1.0],
                y=[pos_rate, pos_rate],
                color="#888888",
                line_style="dashed",
                line_width_pt=max(0.8, round(base_lw * 0.52, 2)),
                marker_style="none",
                meta={"skip_legend": True, "is_chance_line": True},
            )
        )

    layer = LayerSpec(
        layer_id="roc_pr_main",
        mark="line_scatter",
        y_axis="y1",
        series=series_specs,
        color_scheme=scheme,
        palette_colors=[s.color for s in series_specs if s.color],
        origin_plot_type=202 if (show_opt and best_opt is not None) else 200,
    )
    default_xlab = "Recall (Sensitivity)" if curve_kind == "pr" else "False Positive Rate (1 - Specificity)"
    default_ylab = "Precision (PPV)" if curve_kind == "pr" else "True Positive Rate (Sensitivity)"
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", default_xlab)),
        axis_kind="quantitative",
        limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else (0.0, 1.0),
        major_step=0.2,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", default_ylab)),
        axis_kind="quantitative",
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else (0.0, 1.05),
        major_step=0.2,
    )

    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["statistical_tests"] = list(roc_res.get("stat_rows") or [])
    fig_meta["roc_curves"] = curves_list

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        equal_aspect=bool(cfg.get("equal_aspect", False)),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_lower_right" if curve_kind == "roc" else "corner_lower_left")),
        meta={"curve_kind": curve_kind, "roc_curves": curves_list, "locale": locale},
    )
    return FigureSpec(
        title=str(cfg.get("title", "Precision_Recall_Curve" if curve_kind == "pr" else "ROC_Curve_Comparison")),
        mode="roc_pr_curve",
        subtype=curve_kind,
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "n_models": n_models,
            "curve_kind": curve_kind,
            "auroc_by_model": {str(c.get("name")): round(float(c.get("auroc", 0.0)), 4) for c in curves_list},
        },
        meta=fig_meta,
    )


def _compile_nmr_spectrum(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `nmr_spectrum`: inverted chemical-shift δ (ppm) spectrum + elevated step-integral curves + multiplet peak callouts."""
    import numpy as _np

    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    raw_series = cfg.get("series") or cfg.get("spectra")
    if not raw_series and tbl is not None:
        raw_series = [
            {
                "name": str(cfg.get("name", "1H NMR")),
                "x": _extract_column_from_table(tbl, cfg.get("x_col", 0)),
                "y": _extract_column_from_table(tbl, cfg.get("y_col", 1)),
                "integrals": cfg.get("integrals", []),
            }
        ]
    if not isinstance(raw_series, (list, tuple)) or not raw_series:
        raise ValueError("Mode 'nmr_spectrum' requires non-empty 'series' list.")

    locale = str(cfg.get("locale", "en"))
    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    n_spec = len(raw_series)
    scheme = str(cfg.get("color_scheme", "paired_semantic"))
    roles = [s.get("role") if isinstance(s, dict) else None for s in raw_series]
    resolved_cols = ot.resolve_series_colors(n_spec, roles=(roles if any(roles) else None), scheme=scheme)
    base_lw = float(theme.get("curve_linewidth", 3.0))

    compiled_series: List[SeriesSpec] = []
    integral_series: List[SeriesSpec] = []
    integral_records: List[Dict[str, Any]] = []
    guides: List[GuideSpec] = _build_guides_from_cfg(cfg.get("guides", []), theme)

    global_xmin = float("inf")
    global_xmax = float("-inf")
    global_ymin = float("inf")
    global_ymax = float("-inf")
    primary_x_arr: Optional[_np.ndarray] = None
    primary_y_arr: Optional[_np.ndarray] = None

    for idx, s_item in enumerate(raw_series):
        if not isinstance(s_item, dict):
            raise TypeError(f"nmr_spectrum series[{idx}] must be a dict.")
        nm = ot.clean_semantic_sample_name(str(s_item.get("name", f"Spectrum {idx + 1}")), clean_prefix)
        xv = _as_float_list(s_item.get("x"), f"series[{idx}].x")
        yv = _as_float_list(s_item.get("y", s_item.get("values")), f"series[{idx}].y")
        if not xv or not yv or len(xv) != len(yv):
            raise ValueError(f"nmr_spectrum series {nm!r} requires matching non-empty x and y arrays.")
        c_hex = ot.normalize_hex(str(s_item["color"])) if s_item.get("color") else (
            "#111111" if n_spec == 1 and not s_item.get("role") else resolved_cols[idx % len(resolved_cols)]
        )

        x_arr = _np.asarray(xv, dtype=float)
        y_arr = _np.asarray(yv, dtype=float)
        if primary_x_arr is None:
            primary_x_arr, primary_y_arr = x_arr, y_arr
        global_xmin = min(global_xmin, float(_np.min(x_arr)))
        global_xmax = max(global_xmax, float(_np.max(x_arr)))
        global_ymin = min(global_ymin, float(_np.min(y_arr)))
        global_ymax = max(global_ymax, float(_np.max(y_arr)))

        compiled_series.append(
            SeriesSpec(
                name=nm,
                x=xv,
                y=yv,
                color=c_hex,
                role=s_item.get("role"),
                line_style=str(s_item.get("line_style", "solid")),
                line_width_pt=float(s_item.get("line_width_pt", max(0.85, round(base_lw * 0.72, 2)))),
                marker_style="none",
                x_unit="ppm",
                y_unit="a.u.",
            )
        )

        # Step-integral windows (`integrals` on series or top-level `cfg["integrals"]` for series 0)
        int_windows = s_item.get("integrals") or (cfg.get("integrals") if idx == 0 else None) or []
        if int_windows:
            base_lvl = float(_np.percentile(y_arr, 10))
            max_pk = max(float(_np.max(y_arr)) - base_lvl, 1e-9)
            int_col = ot.normalize_hex(str(s_item.get("integral_color", "#D84B5C" if c_hex == "#111111" else "#A02333")))
            for w_idx, win in enumerate(int_windows):
                if not isinstance(win, dict) or not win.get("ppm_range"):
                    continue
                r0, r1 = float(win["ppm_range"][0]), float(win["ppm_range"][1])
                lo_p, hi_p = min(r0, r1), max(r0, r1)
                mask = (x_arr >= lo_p) & (x_arr <= hi_p)
                if int(_np.sum(mask)) < 2:
                    # Synthesize clean 12-point step across [hi_p -> lo_p] if sparse synthetic spectrum
                    xw = _np.linspace(hi_p, lo_p, 12)
                    yw = _np.interp(xw, _np.sort(x_arr), y_arr[_np.argsort(x_arr)])
                else:
                    xw_raw = x_arr[mask]
                    yw_raw = y_arr[mask]
                    desc_ord = _np.argsort(-xw_raw)  # downfield (hi_p) -> upfield (lo_p)
                    xw = xw_raw[desc_ord]
                    yw = yw_raw[desc_ord]
                y_net = _np.maximum(0.0, yw - base_lvl)
                dx_pos = _np.abs(_np.diff(xw))
                trap_steps = 0.5 * (y_net[:-1] + y_net[1:]) * dx_pos
                cum = _np.concatenate([[0.0], _np.cumsum(trap_steps)])
                raw_area = float(cum[-1])
                cum_norm = (cum / raw_area) if raw_area > 1e-12 else _np.linspace(0.0, 1.0, len(xw))
                y_elev = base_lvl + (0.42 + (0.78 - 0.42) * cum_norm) * max_pk
                int_lbl = str(win.get("label", f"Int {w_idx + 1}")).strip()
                integral_series.append(
                    SeriesSpec(
                        name=f"Integral {int_lbl}",
                        x=[round(float(v), 6) for v in xw],
                        y=[round(float(v), 6) for v in y_elev],
                        color=int_col,
                        line_style="solid",
                        line_width_pt=max(0.75, round(base_lw * 0.58, 2)),
                        marker_style="none",
                        meta={
                            "is_nmr_integral": True,
                            "skip_legend": True,
                            "ppm_range": [lo_p, hi_p],
                            "integral_label": int_lbl,
                            "raw_area": round(raw_area, 6),
                        },
                    )
                )
                integral_records.append(
                    {"spectrum": nm, "ppm_low": lo_p, "ppm_high": hi_p, "label": int_lbl, "raw_area": round(raw_area, 6)}
                )
                if int_lbl:
                    guides.append(
                        GuideSpec(
                            kind="text",
                            x=lo_p,
                            y=float(y_elev[-1]) + 0.045 * max_pk,
                            value=lo_p,
                            label=int_lbl,
                            color=int_col,
                        )
                    )

    y_span = max(global_ymax - global_ymin, 1e-6)
    for pk in (cfg.get("peaks") or []):
        if isinstance(pk, dict) and pk.get("ppm") is not None:
            ppm_v = float(pk["ppm"])
            pk_lbl = str(pk.get("label", f"{ppm_v:.2f}")).strip()
            if primary_x_arr is not None and primary_y_arr is not None:
                near_mask = _np.abs(primary_x_arr - ppm_v) <= max(0.08, 0.015 * max(global_xmax - global_xmin, 1.0))
                local_top = float(_np.max(primary_y_arr[near_mask])) if _np.any(near_mask) else global_ymax * 0.82
            else:
                local_top = global_ymax * 0.82
            guides.append(
                GuideSpec(
                    kind="peak_tag",
                    x=ppm_v,
                    y=min(global_ymax + 0.18 * y_span, local_top + 0.06 * y_span),
                    value=ppm_v,
                    label=pk_lbl,
                    color=str(pk.get("color", "#222222")),
                )
            )

    all_series = compiled_series + integral_series
    layer = LayerSpec(
        layer_id="nmr_main",
        mark="line_scatter",
        y_axis="y1",
        series=all_series,
        color_scheme=scheme,
        palette_colors=[s.color for s in all_series if s.color],
        origin_plot_type=200,
    )
    x_pad = 0.03 * max(global_xmax - global_xmin, 0.5)
    x_lims = tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else (global_xmin - x_pad, global_xmax + x_pad)
    y_lims = tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else (
        global_ymin - 0.05 * y_span,
        global_ymax + 0.24 * y_span,
    )
    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "Chemical Shift \\g(d) (ppm)")),
        unit="ppm",
        axis_kind="quantitative",
        invert=bool(cfg.get("invert_x", True)),
        limits=x_lims,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Intensity (a.u.)")),
        axis_kind="intensity_arbitrary",
        limits=y_lims,
    )

    fig_meta: Dict[str, Any] = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    if integral_records:
        fig_meta["nmr_integrals"] = integral_records

    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        guides=guides,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_left" if n_spec >= 2 else "none")),
        meta={"nmr_integrals": integral_records, "locale": locale},
    )
    return FigureSpec(
        title=str(cfg.get("title", "NMR_Chemical_Shift_Spectrum")),
        mode="nmr_spectrum",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_spectra": n_spec, "n_integrals": len(integral_records)},
        meta=fig_meta,
    )


def _compile_broken_axis_plot(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `broken_axis_plot`: `line_scatter` or `bar_grouped_gradient` with native Origin `AxisSpec.breaks`."""
    x_breaks = cfg.get("x_breaks") or []
    y_breaks = cfg.get("y_breaks") or []
    if not x_breaks and not y_breaks:
        raise ValueError("Mode 'broken_axis_plot' requires non-empty 'x_breaks' and/or 'y_breaks'.")

    geom = str(cfg.get("geom") or cfg.get("subtype") or "").strip().lower()
    is_bar = geom in ("bar", "bar_grouped_gradient", "column") or (
        bool(cfg.get("categories"))
        and all(isinstance(s, dict) and s.get("x") is None for s in (cfg.get("series") or []))
    )

    if is_bar:
        fig = _compile_bar_grouped_gradient(cfg, theme, loaded_tables)
    else:
        ly = _compile_line_scatter_layer(cfg, theme, loaded_tables, y_axis="y1", layer_id="broken_curves")
        x_scale = "log10" if cfg.get("log_x", False) else str(cfg.get("x_scale", "linear"))
        y_scale = "log10" if cfg.get("log_y", False) else str(cfg.get("y_scale", "linear"))
        panel = PanelSpec(
            panel_id="panel_main",
            tag=str(cfg.get("tag", "a")),
            x_axis=AxisSpec(
                which="x",
                label=str(cfg.get("x_label", "X")),
                unit=cfg.get("x_unit"),
                axis_kind="quantitative",
                scale=x_scale,
                invert=bool(cfg.get("invert_x", False)),
                limits=tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else None,
                breaks=x_breaks,
            ),
            y1_axis=AxisSpec(
                which="y1",
                label=str(cfg.get("y_label", "Y")),
                unit=cfg.get("y_unit"),
                axis_kind=str(cfg.get("y_axis_kind", "quantitative")),
                scale=y_scale,
                invert=bool(cfg.get("invert_y", False)),
                limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
                breaks=y_breaks,
            ),
            layers=[ly],
            guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
            box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
            legend_style=str(cfg.get("legend_style", "corner_upper_left" if len(ly.series) >= 2 else "none")),
            meta={"locale": str(cfg.get("locale", "en"))},
        )
        fig = FigureSpec(
            title=str(cfg.get("title", "Broken_Axis_Plot")),
            mode="broken_axis_plot",
            subtype="line_scatter",
            style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
            journal_spec=cfg.get("journal_spec"),
            theme=theme,
            panels=[panel],
            output_dir=cfg.get("output_dir"),
            build_opju=bool(cfg.get("build_opju", True)),
            meta=dict(cfg.get("meta") or {}),
        )

    fig.mode = "broken_axis_plot"
    fig.journal_spec = cfg.get("journal_spec") or fig.journal_spec
    p0 = fig.panels[0]
    if x_breaks:
        p0.x_axis.breaks = _normalize_axis_breaks(x_breaks)
    if y_breaks:
        p0.y1_axis.breaks = _normalize_axis_breaks(y_breaks)
    p0.validate()
    return fig


def _compile_dual_x_optical_spectrum(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `dual_x_optical_spectrum`: optical/Arrhenius curves with nonlinear formula-linked top X axis (`1239.84193/x`)."""
    block = copy.deepcopy(cfg)
    block.setdefault("marker_style", "none")
    ly = _compile_line_scatter_layer(block, theme, loaded_tables, y_axis="y1", layer_id="optical_curves")

    linked_cfg = cfg.get("linked_top_x") or cfg.get("linked_top") or {
        "label": "Photon Energy (eV)",
        "formula": "1239.84193/x",
    }
    linked_norm = _normalize_linked_top(linked_cfg)

    all_x: List[float] = []
    for s in ly.series:
        for xv in (s.x or []):
            if isinstance(xv, (int, float)) and math.isfinite(float(xv)):
                all_x.append(float(xv))
    if cfg.get("x_limits") is not None:
        x_lims: Optional[Tuple[float, float]] = (float(cfg["x_limits"][0]), float(cfg["x_limits"][1]))
    elif all_x:
        x_lo, x_hi = min(all_x), max(all_x)
        # Keep reciprocal top-axis domain strictly away from zero
        if linked_norm and "/x" in linked_norm["formula"].lower() and x_lo <= 0.0:
            raise ValueError(
                f"dual_x_optical_spectrum with reciprocal formula {linked_norm['formula']!r} requires strictly positive X values, got min(x)={x_lo}."
            )
        x_lims = (x_lo, x_hi)
    else:
        x_lims = None

    x_axis = AxisSpec(
        which="x",
        label=str(cfg.get("x_label", "Wavelength \\g(l) (nm)")),
        unit=cfg.get("x_unit", "nm"),
        axis_kind="quantitative",
        scale=str(cfg.get("x_scale", "linear")),
        invert=bool(cfg.get("invert_x", False)),
        limits=x_lims,
        linked_top=linked_norm,
    )
    y1_axis = AxisSpec(
        which="y1",
        label=str(cfg.get("y_label", "Absorbance (a.u.)")),
        unit=cfg.get("y_unit"),
        axis_kind=str(cfg.get("y_axis_kind", "quantitative")),
        scale=str(cfg.get("y_scale", "linear")),
        limits=tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else None,
    )
    locale = str(cfg.get("locale", "en"))
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[ly],
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_right" if len(ly.series) >= 2 else "none")),
        meta={"linked_top_x": linked_norm, "locale": locale},
    )
    fig_meta = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["linked_top_x"] = linked_norm
    return FigureSpec(
        title=str(cfg.get("title", "Dual_X_Optical_Spectrum")),
        mode="dual_x_optical_spectrum",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_series": len(ly.series), "top_x_formula": linked_norm["formula"] if linked_norm else ""},
        meta=fig_meta,
    )


def _compile_ternary_diagram(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `ternary_diagram`: 3-component `(A + B + C = 100%)` phase/geochemical ternary diagram (`type=245`)."""
    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    raw_series = cfg.get("series")
    if not raw_series and tbl is not None:
        raw_series = [
            {
                "name": str(cfg.get("name", "Compositions")),
                "a": _extract_column_from_table(tbl, cfg.get("a_col", 0)),
                "b": _extract_column_from_table(tbl, cfg.get("b_col", 1)),
                "c": _extract_column_from_table(tbl, cfg.get("c_col", 2)),
            }
        ]
    if not isinstance(raw_series, (list, tuple)) or not raw_series:
        raise ValueError("Mode 'ternary_diagram' requires non-empty 'series' list with (a, b, c) arrays.")

    raw_comp_lbls = cfg.get("component_labels") or cfg.get("axes_labels") or [
        "Component A (%)",
        "Component B (%)",
        "Component C (%)",
    ]
    if len(raw_comp_lbls) != 3:
        raise ValueError(f"ternary_diagram component_labels must have 3 labels, got {len(raw_comp_lbls)}.")
    comp_labels = [str(lbl) for lbl in raw_comp_lbls]

    locale = str(cfg.get("locale", "en"))
    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    n_ser = len(raw_series)
    scheme = str(cfg.get("color_scheme", "paired_semantic" if n_ser <= 6 else "okabe_ito"))
    roles = [s.get("role") if isinstance(s, dict) else None for s in raw_series]
    resolved_cols = ot.resolve_series_colors(n_ser, roles=(roles if any(roles) else None), scheme=scheme)
    base_lw = float(theme.get("curve_linewidth", 3.0))
    base_mk = float(theme.get("origin_native", {}).get("marker_size_pt", 7.5))

    t_series: List[SeriesSpec] = []
    for idx, s_item in enumerate(raw_series):
        if not isinstance(s_item, dict):
            raise TypeError(f"ternary_diagram series[{idx}] must be a dict.")
        nm = ot.clean_semantic_sample_name(str(s_item.get("name", f"Phase {idx + 1}")), clean_prefix)
        av = _as_float_list(s_item.get("a", s_item.get("x")), f"series[{idx}].a") or []
        bv = _as_float_list(s_item.get("b", s_item.get("y")), f"series[{idx}].b") or []
        cv = _as_float_list(s_item.get("c", s_item.get("z")), f"series[{idx}].c") or []
        if not (len(av) == len(bv) == len(cv) and len(av) >= 1):
            raise ValueError(f"ternary_diagram series {nm!r} requires non-empty equal-length (a, b, c) arrays.")

        a_norm: List[float] = []
        b_norm: List[float] = []
        c_norm: List[float] = []
        for p_i, (ai, bi, ci) in enumerate(zip(av, bv, cv)):
            if ai < -1e-9 or bi < -1e-9 or ci < -1e-9:
                raise ValueError(f"ternary_diagram series {nm!r} point {p_i} has negative composition ({ai}, {bi}, {ci}).")
            a_c, b_c, c_c = max(0.0, ai), max(0.0, bi), max(0.0, ci)
            tot = a_c + b_c + c_c
            if tot <= 1e-12:
                raise ValueError(f"ternary_diagram series {nm!r} point {p_i} sums to zero.")
            a_norm.append(round(100.0 * a_c / tot, 6))
            b_norm.append(round(100.0 * b_c / tot, 6))
            c_norm.append(round(100.0 * c_c / tot, 6))

        c_hex = ot.normalize_hex(str(s_item["color"])) if s_item.get("color") else resolved_cols[idx % len(resolved_cols)]
        mk_raw = str(s_item.get("marker_style", "circle_solid"))
        if mk_raw == "circle":
            mk_raw = "circle_solid"
        elif mk_raw == "open_circle":
            mk_raw = "circle_open"
        l_style = str(s_item.get("line_style", "none"))

        t_series.append(
            SeriesSpec(
                name=nm,
                x=a_norm,
                y=b_norm,
                role=s_item.get("role"),
                color=c_hex,
                line_style=l_style,
                line_width_pt=float(s_item.get("line_width_pt", base_lw)),
                marker_style=mk_raw,
                marker_size_pt=float(s_item.get("marker_size_pt", base_mk)),
                x_unit="%",
                y_unit="%",
                z_unit="%",
                meta={
                    "ternary_a": a_norm,
                    "ternary_b": b_norm,
                    "ternary_c": c_norm,
                    "component_labels": comp_labels,
                },
            )
        )

    layer = LayerSpec(
        layer_id="ternary_main",
        mark="ternary_scatter",
        y_axis="y1",
        series=t_series,
        color_scheme=scheme,
        palette_colors=[s.color for s in t_series if s.color],
        origin_template="Ternary",
        origin_plot_type=245,
    )
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        coord="ternary",
        x_axis=AxisSpec(which="x", label=comp_labels[0], unit="%", limits=(0.0, 100.0)),
        y1_axis=AxisSpec(which="y1", label=comp_labels[1], unit="%", limits=(0.0, 100.0)),
        z_axis=AxisSpec(which="z", label=comp_labels[2], unit="%", limits=(0.0, 100.0)),
        layers=[layer],
        equal_aspect=True,
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_right")),
        meta={"component_labels": comp_labels, "locale": locale},
    )
    fig_meta = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["component_labels"] = comp_labels
    return FigureSpec(
        title=str(cfg.get("title", "Ternary_Phase_Diagram")),
        mode="ternary_diagram",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_series": n_ser, "component_labels": comp_labels},
        meta=fig_meta,
    )


def _compile_polar_radar_plot(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `polar_radar_plot`: radiation/anisotropy `'polar'` (`0..360°`) or multi-spoke ML/sensor `'radar'`."""
    raw_cats = cfg.get("categories") or cfg.get("spokes") or cfg.get("metrics")
    subtype = str(cfg.get("subtype") or ("radar" if raw_cats else "polar")).strip().lower()
    if subtype not in ("polar", "radar"):
        raise ValueError(f"polar_radar_plot subtype must be 'polar' or 'radar', got {subtype!r}")

    raw_series = cfg.get("series") or cfg.get("models")
    if not isinstance(raw_series, (list, tuple)) or not raw_series:
        raise ValueError("Mode 'polar_radar_plot' requires non-empty 'series' list.")

    locale = str(cfg.get("locale", "en"))
    clean_prefix = bool(cfg.get("clean_sample_prefix", False))
    n_ser = len(raw_series)
    scheme = str(cfg.get("color_scheme", "paired_semantic" if n_ser <= 6 else "okabe_ito"))
    roles = [s.get("role") if isinstance(s, dict) else None for s in raw_series]
    resolved_cols = ot.resolve_series_colors(n_ser, roles=(roles if any(roles) else None), scheme=scheme)
    base_lw = float(theme.get("curve_linewidth", 3.0))
    base_mk = float(theme.get("origin_native", {}).get("marker_size_pt", 7.5))

    compiled: List[SeriesSpec] = []
    max_r = 0.0
    min_r = 0.0

    if subtype == "radar":
        if not raw_cats or len(raw_cats) < 3:
            raise ValueError("polar_radar_plot with subtype='radar' requires >= 3 'categories' (spoke names).")
        cats = [str(c) for c in raw_cats]
        for idx, s_item in enumerate(raw_series):
            if not isinstance(s_item, dict):
                raise TypeError(f"polar_radar_plot series[{idx}] must be a dict.")
            nm = ot.clean_semantic_sample_name(str(s_item.get("name", f"Model {idx + 1}")), clean_prefix)
            yv = _as_float_list(s_item.get("y", s_item.get("values", s_item.get("r"))), f"series[{idx}].y") or []
            if len(yv) != len(cats):
                raise ValueError(f"Radar series {nm!r} length ({len(yv)}) must match categories ({len(cats)}).")
            max_r = max(max_r, max(yv))
            min_r = min(min_r, min(yv))
            c_hex = ot.normalize_hex(str(s_item["color"])) if s_item.get("color") else resolved_cols[idx % len(resolved_cols)]
            compiled.append(
                SeriesSpec(
                    name=nm,
                    x=list(cats),
                    y=yv,
                    role=s_item.get("role"),
                    color=c_hex,
                    line_style="solid",
                    line_width_pt=float(s_item.get("line_width_pt", base_lw)),
                    marker_style=str(s_item.get("marker_style", "circle_solid")),
                    marker_size_pt=float(s_item.get("marker_size_pt", base_mk)),
                    fill_alpha=float(s_item.get("fill_alpha", cfg.get("fill_alpha", 0.18))),
                    meta={"coord": "radar", "categories": list(cats)},
                )
            )
        r_top = 1.0 if max_r <= 1.05 else (100.0 if 50.0 < max_r <= 105.0 else round(max_r * 1.12, 4))
        r_lims = tuple(cfg["r_limits"]) if cfg.get("r_limits") is not None else (min(0.0, min_r), r_top)
        layer = LayerSpec(
            layer_id="radar_main",
            mark="polar_line",
            y_axis="y1",
            series=compiled,
            categories=cats,
            color_scheme=scheme,
            palette_colors=[s.color for s in compiled if s.color],
            origin_template="Polar",
            origin_plot_type=192,
        )
        panel = PanelSpec(
            panel_id="panel_main",
            tag=str(cfg.get("tag", "a")),
            coord="radar",
            x_axis=AxisSpec(which="x", label="", axis_kind="categorical", categories=cats),
            y1_axis=AxisSpec(which="y1", label=str(cfg.get("y_label", "Score")), limits=r_lims),
            layers=[layer],
            equal_aspect=True,
            box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
            legend_style=str(cfg.get("legend_style", "corner_upper_right")),
            meta={"categories": cats, "radar_max": r_lims[1], "locale": locale},
        )
    else:
        is_rad = str(cfg.get("angle_unit", "deg")).strip().lower().startswith("rad")
        for idx, s_item in enumerate(raw_series):
            if not isinstance(s_item, dict):
                raise TypeError(f"polar_radar_plot series[{idx}] must be a dict.")
            nm = ot.clean_semantic_sample_name(str(s_item.get("name", f"Pattern {idx + 1}")), clean_prefix)
            th_raw = _as_float_list(s_item.get("theta", s_item.get("angle", s_item.get("x"))), f"series[{idx}].theta") or []
            rv = _as_float_list(s_item.get("r", s_item.get("y", s_item.get("values"))), f"series[{idx}].r") or []
            if not th_raw or len(th_raw) != len(rv):
                raise ValueError(f"Polar series {nm!r} requires matching non-empty theta and r arrays.")
            th_deg = [round(v * 180.0 / math.pi, 6) for v in th_raw] if is_rad else th_raw
            max_r = max(max_r, max(rv))
            min_r = min(min_r, min(rv))
            c_hex = ot.normalize_hex(str(s_item["color"])) if s_item.get("color") else resolved_cols[idx % len(resolved_cols)]
            compiled.append(
                SeriesSpec(
                    name=nm,
                    x=th_deg,
                    y=rv,
                    role=s_item.get("role"),
                    color=c_hex,
                    line_style=str(s_item.get("line_style", "solid")),
                    line_width_pt=float(s_item.get("line_width_pt", base_lw)),
                    marker_style=str(s_item.get("marker_style", "none")),
                    marker_size_pt=float(s_item.get("marker_size_pt", base_mk)),
                    x_unit="deg",
                    y_unit=cfg.get("r_unit", cfg.get("y_unit")),
                    meta={"coord": "polar", "theta_deg": th_deg},
                )
            )
        r_lims = tuple(cfg["r_limits"]) if cfg.get("r_limits") is not None else (
            min(0.0, min_r),
            max(1.0, round(max_r * 1.12, 4)),
        )
        layer = LayerSpec(
            layer_id="polar_main",
            mark="polar_line",
            y_axis="y1",
            series=compiled,
            color_scheme=scheme,
            palette_colors=[s.color for s in compiled if s.color],
            origin_template="Polar",
            origin_plot_type=192,
        )
        panel = PanelSpec(
            panel_id="panel_main",
            tag=str(cfg.get("tag", "a")),
            coord="polar",
            x_axis=AxisSpec(which="x", label=str(cfg.get("x_label", "Angle (deg)")), unit="deg", limits=(0.0, 360.0), major_step=45.0),
            y1_axis=AxisSpec(which="y1", label=str(cfg.get("y_label", cfg.get("r_label", "Amplitude"))), limits=r_lims),
            layers=[layer],
            equal_aspect=True,
            box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
            legend_style=str(cfg.get("legend_style", "corner_upper_right")),
            meta={"locale": locale},
        )

    fig_meta = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    return FigureSpec(
        title=str(cfg.get("title", "Radar_Comparison" if subtype == "radar" else "Polar_Angular_Plot")),
        mode="polar_radar_plot",
        subtype=subtype,
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_series": n_ser, "coord": subtype},
        meta=fig_meta,
    )


def _compile_multi_track_profile(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `multi_track_profile`: K side-by-side ocean/borehole/ice-core vertical tracks sharing Depth/Age Y axis."""
    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    raw_tracks = cfg.get("tracks") or cfg.get("panels")
    if not raw_tracks and tbl is not None and cfg.get("track_cols"):
        d_vals = _extract_column_from_table(tbl, cfg.get("depth_col", 0))
        raw_tracks = [
            {"name": str(tc), "x_label": str(tc), "x": _extract_column_from_table(tbl, tc), "depth": d_vals}
            for tc in cfg["track_cols"]
        ]
    if not isinstance(raw_tracks, (list, tuple)) or not raw_tracks:
        raise ValueError("Mode 'multi_track_profile' requires non-empty 'tracks' list.")

    K = len(raw_tracks)
    depth_label = str(cfg.get("depth_label", cfg.get("y_label", "Depth (m)")))
    depth_unit = cfg.get("depth_unit", cfg.get("y_unit"))
    depth_invert = bool(cfg.get("depth_invert", cfg.get("invert_y", True)))
    locale = str(cfg.get("locale", "en"))

    norm_horizons: List[Dict[str, Any]] = []
    for h_idx, hz in enumerate(cfg.get("horizons") or []):
        if isinstance(hz, dict) and hz.get("depth_start") is not None and hz.get("depth_end") is not None:
            norm_horizons.append(
                {
                    "depth_start": float(hz["depth_start"]),
                    "depth_end": float(hz["depth_end"]),
                    "label": str(hz.get("label", f"Horizon {h_idx + 1}")),
                    "color": ot.normalize_hex(str(hz.get("color", "#DCE8F5"))),
                }
            )

    scheme = str(cfg.get("color_scheme", "okabe_ito" if K > 4 else "paired_semantic"))
    track_cols = ot.resolve_series_colors(K, scheme=scheme)
    base_lw = float(theme.get("curve_linewidth", 3.0))
    comp_lw = float(theme.get("composite_print_profile", {}).get("box_linewidth_pt", min(2.0, float(theme.get("figure_box_linewidth", 3.0)))))

    all_depths: List[float] = []
    parsed_tracks: List[Tuple[Dict[str, Any], List[SeriesSpec]]] = []

    for idx, tr in enumerate(raw_tracks):
        if not isinstance(tr, dict):
            raise TypeError(f"multi_track_profile tracks[{idx}] must be a dict.")
        tr_nm = str(tr.get("name", f"Track {idx + 1}"))
        tr_c = ot.normalize_hex(str(tr["color"])) if tr.get("color") else track_cols[idx % len(track_cols)]

        sub_series_raw = tr.get("series")
        if not sub_series_raw:
            sub_series_raw = [
                {
                    "name": tr_nm,
                    "x": tr.get("x", tr.get("values")),
                    "depth": tr.get("depth", tr.get("y", cfg.get("depth"))),
                    "color": tr_c,
                    "line_style": tr.get("line_style", "solid"),
                    "marker_style": tr.get("marker_style", "circle_solid"),
                }
            ]

        tr_specs: List[SeriesSpec] = []
        for s_i, s_it in enumerate(sub_series_raw):
            xv = _as_float_list(s_it.get("x", s_it.get("values")), f"tracks[{idx}].x") or []
            dv = _as_float_list(s_it.get("depth", s_it.get("y", tr.get("depth", cfg.get("depth")))), f"tracks[{idx}].depth") or []
            if not xv or len(xv) != len(dv):
                raise ValueError(f"Track {tr_nm!r} requires matching non-empty 'x' and 'depth' arrays.")
            all_depths.extend(dv)
            sc_hex = ot.normalize_hex(str(s_it["color"])) if s_it.get("color") else tr_c
            tr_specs.append(
                SeriesSpec(
                    name=str(s_it.get("name", tr_nm)),
                    x=xv,
                    y=dv,
                    y_err=_as_float_list(s_it.get("y_err"), f"tracks[{idx}].y_err"),
                    color=sc_hex,
                    line_style=str(s_it.get("line_style", "solid")),
                    line_width_pt=float(s_it.get("line_width_pt", max(0.85, round(base_lw * 0.85, 2)))),
                    marker_style=str(s_it.get("marker_style", "circle_solid" if len(xv) <= 18 else "none")),
                    marker_size_pt=float(s_it.get("marker_size_pt", float(theme.get("origin_native", {}).get("marker_size_pt", 6.5)) * 0.82)),
                    x_unit=tr.get("x_unit"),
                    y_unit=depth_unit,
                    meta={"track_index": idx, "track_name": tr_nm, "depth_label": depth_label},
                )
            )
        parsed_tracks.append((tr, tr_specs))

    raw_d_lims = cfg.get("depth_limits") or cfg.get("y_limits")
    if raw_d_lims is not None:
        d_min, d_max = float(raw_d_lims[0]), float(raw_d_lims[1])
    else:
        d_lo, d_hi = min(all_depths), max(all_depths)
        d_pad = 0.03 * max(d_hi - d_lo, 1.0)
        d_min = 0.0 if (d_lo >= 0.0 and d_lo <= 0.08 * max(d_hi, 1.0)) else (d_lo - d_pad)
        d_max = d_hi + d_pad

    panels: List[PanelSpec] = []
    for idx, (tr, tr_specs) in enumerate(parsed_tracks):
        tr_nm = str(tr.get("name", f"Track {idx + 1}"))
        has_mk = any(s.marker_style != "none" for s in tr_specs)
        has_ln = any(s.line_style != "none" for s in tr_specs)
        pid_plot = 202 if (has_mk and has_ln) else (201 if has_mk else 200)
        ly = LayerSpec(
            layer_id=f"track_layer_{idx + 1}",
            mark="line_scatter",
            y_axis="y1",
            series=tr_specs,
            color_scheme=scheme,
            palette_colors=[s.color for s in tr_specs if s.color],
            origin_plot_type=pid_plot,
        )
        tr_xlims = tuple(tr["x_limits"]) if tr.get("x_limits") is not None else None
        panels.append(
            PanelSpec(
                panel_id=f"track_{idx + 1}",
                tag=chr(ord("a") + idx),
                row=0,
                col=idx,
                x_axis=AxisSpec(
                    which="x",
                    label=str(tr.get("x_label", tr_nm)),
                    unit=tr.get("x_unit"),
                    axis_kind="quantitative",
                    scale=str(tr.get("x_scale", "linear")),
                    limits=tr_xlims,
                ),
                y1_axis=AxisSpec(
                    which="y1",
                    label=depth_label if idx == 0 else "",
                    unit=depth_unit,
                    axis_kind="quantitative",
                    invert=depth_invert,
                    limits=(d_min, d_max),
                ),
                layers=[ly],
                guides=_build_guides_from_cfg(tr.get("guides", []), theme),
                share_y_with="track_1" if idx > 0 else None,
                box_linewidth_pt=comp_lw,
                legend_style=str(tr.get("legend_style", "corner_upper_right" if len(tr_specs) > 1 else "none")),
                meta={
                    "multi_track": True,
                    "track_index": idx,
                    "n_tracks": K,
                    "track_name": tr_nm,
                    "depth_label": depth_label,
                    "horizons": norm_horizons,
                    "locale": locale,
                },
            )
        )

    w_ratios = [float(r) for r in cfg.get("width_ratios", [1.0] * K)]
    fig_meta = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    fig_meta["horizons"] = norm_horizons
    fig_meta["depth_limits"] = [d_min, d_max]
    fig_meta["depth_invert"] = depth_invert
    fig_meta["depth_label"] = depth_label

    return FigureSpec(
        title=str(cfg.get("title", "Multi_Track_Stratigraphic_Profile")),
        mode="multi_track_profile",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        nrows=1,
        ncols=K,
        width_ratios=w_ratios,
        height_ratios=[1.0],
        panels=panels,
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={"n_tracks": K, "depth_range": [round(d_min, 4), round(d_max, 4)], "n_horizons": len(norm_horizons)},
        meta=fig_meta,
    )


def _compile_vector_quiver_field(
    cfg: Dict[str, Any],
    theme: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]],
) -> FigureSpec:
    """Compile `vector_quiver_field`: 2D `(x, y, u, v)` quiver arrows (`type=218`) + optional background scalar contour."""
    import numpy as _np

    tbl = _lookup_loaded_table(loaded_tables, cfg.get("table_key"), cfg.get("input_file"), "main")
    v_src = cfg.get("vectors") if isinstance(cfg.get("vectors"), dict) else (
        cfg["series"][0] if isinstance(cfg.get("series"), list) and cfg["series"] and isinstance(cfg["series"][0], dict) else cfg
    )

    x_raw = v_src.get("x") if v_src.get("x") is not None else (_extract_column_from_table(tbl, cfg.get("x_col", "x")) if tbl is not None else None)
    y_raw = v_src.get("y") if v_src.get("y") is not None else (_extract_column_from_table(tbl, cfg.get("y_col", "y")) if tbl is not None else None)
    u_raw = v_src.get("u") if v_src.get("u") is not None else (_extract_column_from_table(tbl, cfg.get("u_col", "u")) if tbl is not None and cfg.get("u_col") else None)
    v_raw = v_src.get("v") if v_src.get("v") is not None else (_extract_column_from_table(tbl, cfg.get("v_col", "v")) if tbl is not None and cfg.get("v_col") else None)
    xe_raw = v_src.get("x_end", v_src.get("x2"))
    ye_raw = v_src.get("y_end", v_src.get("y2"))

    if x_raw is None or y_raw is None:
        raise ValueError("Mode 'vector_quiver_field' requires 'x' and 'y' vector coordinates.")

    x_arr = _np.asarray(x_raw, dtype=float).ravel()
    y_arr = _np.asarray(y_raw, dtype=float).ravel()
    if len(x_arr) == 0 or len(x_arr) != len(y_arr):
        raise ValueError("vector_quiver_field requires equal-length non-empty 'x' and 'y' arrays.")

    has_explicit_ends = xe_raw is not None and ye_raw is not None
    if has_explicit_ends:
        xe_arr = _np.asarray(xe_raw, dtype=float).ravel()
        ye_arr = _np.asarray(ye_raw, dtype=float).ravel()
        if len(xe_arr) != len(x_arr) or len(ye_arr) != len(y_arr):
            raise ValueError("vector_quiver_field 'x_end'/'y_end' must match length of 'x'/'y'.")
        u_arr = _np.asarray(u_raw, dtype=float).ravel() if u_raw is not None else (xe_arr - x_arr)
        v_arr = _np.asarray(v_raw, dtype=float).ravel() if v_raw is not None else (ye_arr - y_arr)
        arrow_scale = 1.0
    elif u_raw is not None and v_raw is not None:
        u_arr = _np.asarray(u_raw, dtype=float).ravel()
        v_arr = _np.asarray(v_raw, dtype=float).ravel()
        if len(u_arr) != len(x_arr) or len(v_arr) != len(y_arr):
            raise ValueError("vector_quiver_field 'u'/'v' must match length of 'x'/'y'.")
        mag_tmp = _np.hypot(u_arr, v_arr)
        p95_mag = float(_np.percentile(mag_tmp, 95)) if len(mag_tmp) > 0 else 1.0
        if cfg.get("arrow_scale") is not None:
            arrow_scale = float(cfg["arrow_scale"])
        elif bool(cfg.get("raw_displacement", False)):
            arrow_scale = 1.0
        else:
            ux = _np.unique(_np.round(x_arr, 8))
            uy = _np.unique(_np.round(y_arr, 8))
            dx_g = float(_np.median(_np.diff(ux))) if len(ux) >= 2 else max(1e-3, 0.1 * float(_np.ptp(x_arr) or 1.0))
            dy_g = float(_np.median(_np.diff(uy))) if len(uy) >= 2 else max(1e-3, 0.1 * float(_np.ptp(y_arr) or 1.0))
            arrow_scale = (0.78 * min(dx_g, dy_g) / p95_mag) if p95_mag > 1e-12 else 1.0
        xe_arr = x_arr + arrow_scale * u_arr
        ye_arr = y_arr + arrow_scale * v_arr
    else:
        raise ValueError("Mode 'vector_quiver_field' requires either ('u', 'v') or ('x_end', 'y_end').")

    mag_arr = _np.hypot(u_arr, v_arr)

    mx = cfg.get("matrix_x", cfg.get("x_grid"))
    my = cfg.get("matrix_y", cfg.get("y_grid"))
    mz = cfg.get("matrix_z", cfg.get("z_matrix"))
    compute_bg = bool(cfg.get("compute_magnitude_bg", False))

    if mz is None and compute_bg:
        ux = _np.unique(_np.round(x_arr, 8))
        uy = _np.unique(_np.round(y_arr, 8))
        if len(ux) >= 2 and len(uy) >= 2 and len(ux) * len(uy) == len(x_arr):
            z_grid = _np.zeros((len(uy), len(ux)), dtype=float)
            ix_map = {float(v): i for i, v in enumerate(ux)}
            iy_map = {float(v): j for j, v in enumerate(uy)}
            for xi, yi, mi in zip(_np.round(x_arr, 8), _np.round(y_arr, 8), mag_arr):
                z_grid[iy_map[float(yi)], ix_map[float(xi)]] = float(mi)
            mx = [float(v) for v in ux]
            my = [float(v) for v in uy]
            mz = z_grid.tolist()
        elif len(x_arr) >= 4:
            gx = _np.linspace(float(_np.min(x_arr)), float(_np.max(x_arr)), 24)
            gy = _np.linspace(float(_np.min(y_arr)), float(_np.max(y_arr)), 24)
            gxx, gyy = _np.meshgrid(gx, gy)
            # Smooth inverse-distance weighting onto 24x24 grid (zero NaN risk on convex hull corners)
            dx2 = (gxx[..., None] - x_arr[None, None, :]) ** 2 + (gyy[..., None] - y_arr[None, None, :]) ** 2
            wts = 1.0 / _np.maximum(dx2, 1e-12)
            z_grid = _np.sum(wts * mag_arr[None, None, :], axis=-1) / _np.sum(wts, axis=-1)
            mx = [round(float(v), 6) for v in gx]
            my = [round(float(v), 6) for v in gy]
            mz = [[round(float(v), 6) for v in row] for row in z_grid]

    layers: List[LayerSpec] = []
    z_axis: Optional[AxisSpec] = None
    has_bg = mz is not None
    if has_bg:
        bg_scheme = str(cfg.get("color_scheme", "viridis" if compute_bg else "pseudocolor_zero_white"))
        bg_stops = list(cfg["color_stops"]) if cfg.get("color_stops") else ot.get_scheme_color_stops(bg_scheme)
        mat_s = SeriesSpec(
            name=str(cfg.get("field_name", "Scalar_Background")),
            matrix_x=mx,
            matrix_y=my,
            matrix_z=mz,
            color=bg_stops[-1],
            x_unit=cfg.get("x_unit"),
            y_unit=cfg.get("y_unit"),
            z_unit=cfg.get("z_unit"),
        )
        layers.append(
            LayerSpec(
                layer_id="field_bg_contour",
                mark="contour_pseudocolor",
                y_axis="y1",
                series=[mat_s],
                color_scheme=bg_scheme,
                palette_colors=bg_stops,
                z_levels_count=int(cfg.get("z_levels_count", 32)),
                hide_contour_lines=bool(cfg.get("hide_contour_lines", True)),
                origin_template="CONTOUR",
                origin_plot_type=226,
            )
        )
        z_axis = AxisSpec(
            which="z",
            label=str(cfg.get("z_label", "Velocity Magnitude")),
            unit=cfg.get("z_unit"),
            axis_kind="quantitative",
        )

    default_vec_col = "#FFFFFF" if (has_bg and str(cfg.get("color_scheme", "")) in ("viridis", "magma", "cividis")) else "#111111"
    vec_col = ot.normalize_hex(str(v_src.get("color", cfg.get("vector_color", default_vec_col))))
    base_lw = float(theme.get("curve_linewidth", 3.0))

    quiver_s = SeriesSpec(
        name=str(v_src.get("name", cfg.get("vector_name", "Vector Field"))),
        x=[round(float(v), 6) for v in x_arr],
        y=[round(float(v), 6) for v in y_arr],
        color=vec_col,
        line_style="solid",
        line_width_pt=float(v_src.get("line_width_pt", cfg.get("vector_linewidth_pt", max(0.7, round(base_lw * 0.62, 2))))),
        marker_style="none",
        x_unit=cfg.get("x_unit"),
        y_unit=cfg.get("y_unit"),
        meta={
            "u": [round(float(v), 6) for v in u_arr],
            "v": [round(float(v), 6) for v in v_arr],
            "x_end": [round(float(v), 6) for v in xe_arr],
            "y_end": [round(float(v), 6) for v in ye_arr],
            "magnitude": [round(float(v), 6) for v in mag_arr],
            "arrow_scale": round(float(arrow_scale), 6),
        },
    )
    layers.append(
        LayerSpec(
            layer_id="quiver_main",
            mark="vector_quiver",
            y_axis="y1",
            series=[quiver_s],
            color_scheme="paired_semantic",
            palette_colors=[vec_col],
            origin_template="VECTXYXY",
            origin_plot_type=218,
        )
    )

    all_bx = _np.concatenate([x_arr, xe_arr])
    all_by = _np.concatenate([y_arr, ye_arr])
    x_pad = 0.06 * max(float(_np.ptp(all_bx)), 1e-3)
    y_pad = 0.06 * max(float(_np.ptp(all_by)), 1e-3)
    x_lims = tuple(cfg["x_limits"]) if cfg.get("x_limits") is not None else (
        float(_np.min(all_bx)) - x_pad,
        float(_np.max(all_bx)) + x_pad,
    )
    y_lims = tuple(cfg["y_limits"]) if cfg.get("y_limits") is not None else (
        float(_np.min(all_by)) - y_pad,
        float(_np.max(all_by)) + y_pad,
    )

    locale = str(cfg.get("locale", "en"))
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=AxisSpec(which="x", label=str(cfg.get("x_label", "X")), unit=cfg.get("x_unit"), limits=x_lims),
        y1_axis=AxisSpec(which="y1", label=str(cfg.get("y_label", "Y")), unit=cfg.get("y_unit"), limits=y_lims),
        z_axis=z_axis,
        layers=layers,
        guides=_build_guides_from_cfg(cfg.get("guides", []), theme),
        equal_aspect=bool(cfg.get("equal_aspect", True)),
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style="none",
        meta={"has_scalar_bg": has_bg, "locale": locale},
    )
    fig_meta = dict(cfg.get("meta") or {})
    fig_meta["locale"] = locale
    return FigureSpec(
        title=str(cfg.get("title", "Vector_Quiver_Field")),
        mode="vector_quiver_field",
        style_preset=str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)),
        journal_spec=cfg.get("journal_spec"),
        theme=theme,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        summary_metrics={
            "n_vectors": int(len(x_arr)),
            "max_magnitude": round(float(_np.max(mag_arr)), 4),
            "has_scalar_bg": has_bg,
        },
        meta=fig_meta,
    )


_COMPILE_MODE_ALIASES: Dict[str, str] = {
    "fit_band": "xy_fit_and_band",
    "bode": "bode_dual_panel",
    "stat_dist": "stat_distribution",
    "heatmap": "matrix_heatmap",
    "bar_dot_sig": "stat_bar_dot_sig",
    "violin": "stat_violin_raincloud",
    "raincloud": "stat_violin_raincloud",
    "volcano": "volcano_plot",
    "forest": "forest_ablation_plot",
    "ablation": "forest_ablation_plot",
    "free_energy": "free_energy_diagram",
    "ic50": "dose_response_4pl",
    "4pl": "dose_response_4pl",
    "km": "kaplan_meier_plot",
    "kaplan_meier": "kaplan_meier_plot",
    "survival": "kaplan_meier_plot",
    "roc": "roc_pr_curve",
    "pr_curve": "roc_pr_curve",
    "nmr": "nmr_spectrum",
    "broken_axis": "broken_axis_plot",
    "dual_x": "dual_x_optical_spectrum",
    "optical_dual_x": "dual_x_optical_spectrum",
    "ternary": "ternary_diagram",
    "polar": "polar_radar_plot",
    "radar": "polar_radar_plot",
    "multi_track": "multi_track_profile",
    "stratigraphic_profile": "multi_track_profile",
    "quiver": "vector_quiver_field",
    "vector_field": "vector_quiver_field",
}


def compile_config_to_figure_spec(
    cfg: Dict[str, Any],
    loaded_tables: Optional[Dict[str, Any]] = None,
) -> FigureSpec:
    """
    Compile a declarative `task_config` dictionary (and optional pre-loaded tables)
    into a validated `FigureSpec` dataclass instance.
    """
    if not isinstance(cfg, dict):
        raise TypeError(f"cfg must be a dict, got {type(cfg).__name__}")
    raw_mode = str(cfg.get("mode", "")).strip()
    if not raw_mode:
        raise ValueError("Configuration dictionary is missing required `mode` field.")
    mode = _COMPILE_MODE_ALIASES.get(raw_mode, raw_mode)
    if raw_mode == "radar" and not cfg.get("subtype"):
        cfg = copy.deepcopy(cfg)
        cfg["subtype"] = "radar"
    elif raw_mode == "pr_curve" and not cfg.get("curve_kind"):
        cfg = copy.deepcopy(cfg)
        cfg["curve_kind"] = "pr"

    style_name = cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)
    theme = ot.load_theme(style_name)
    j_spec = cfg.get("journal_spec")
    if j_spec:
        theme = ot.apply_journal_spec(theme, j_spec)

    fig_spec: Optional[FigureSpec] = None
    if mode == "bar_grouped_gradient":
        fig_spec = _compile_bar_grouped_gradient(cfg, theme, loaded_tables)
    elif mode == "bar_stacked":
        fig_spec = _compile_bar_stacked(cfg, theme, loaded_tables, force_100pct=False)
    elif mode == "bar_stacked_100pct":
        fig_spec = _compile_bar_stacked(cfg, theme, loaded_tables, force_100pct=True)
    elif mode == "dual_y_combo":
        fig_spec = _compile_dual_y_combo(cfg, theme, loaded_tables)
    elif mode == "curve_with_inset":
        fig_spec = _compile_curve_with_inset(cfg, theme, loaded_tables)
    elif mode == "electrochem_kinetics":
        fig_spec = _compile_electrochem_kinetics(cfg, theme, loaded_tables)
    elif mode == "contour_pseudocolor_2d":
        fig_spec = _compile_contour_pseudocolor_2d(cfg, theme, loaded_tables)
    elif mode == "chart_grammar":
        fig_spec = _compile_universal_chart_grammar(cfg, theme, loaded_tables)
    elif mode == "xy_fit_and_band":
        fig_spec = _compile_xy_fit_and_band(cfg, theme, loaded_tables)
    elif mode == "bode_dual_panel":
        fig_spec = _compile_bode_dual_panel(cfg, theme, loaded_tables)
    elif mode == "stat_distribution":
        fig_spec = _compile_stat_distribution_new(cfg, theme, loaded_tables)
    elif mode == "matrix_heatmap":
        fig_spec = _compile_matrix_heatmap_new(cfg, theme, loaded_tables)
    elif mode == "stat_bar_dot_sig":
        fig_spec = _compile_stat_bar_dot_sig(cfg, theme, loaded_tables)
    elif mode == "stat_violin_raincloud":
        fig_spec = _compile_stat_violin_raincloud(cfg, theme, loaded_tables)
    elif mode == "volcano_plot":
        fig_spec = _compile_volcano_plot(cfg, theme, loaded_tables)
    elif mode == "forest_ablation_plot":
        fig_spec = _compile_forest_ablation_plot(cfg, theme, loaded_tables)
    elif mode == "free_energy_diagram":
        fig_spec = _compile_free_energy_diagram(cfg, theme, loaded_tables)
    elif mode == "dose_response_4pl":
        fig_spec = _compile_dose_response_4pl(cfg, theme, loaded_tables)
    elif mode == "kaplan_meier_plot":
        fig_spec = _compile_kaplan_meier_plot(cfg, theme, loaded_tables)
    elif mode == "roc_pr_curve":
        fig_spec = _compile_roc_pr_curve(cfg, theme, loaded_tables)
    elif mode == "nmr_spectrum":
        fig_spec = _compile_nmr_spectrum(cfg, theme, loaded_tables)
    elif mode == "broken_axis_plot":
        fig_spec = _compile_broken_axis_plot(cfg, theme, loaded_tables)
    elif mode == "dual_x_optical_spectrum":
        fig_spec = _compile_dual_x_optical_spectrum(cfg, theme, loaded_tables)
    elif mode == "ternary_diagram":
        fig_spec = _compile_ternary_diagram(cfg, theme, loaded_tables)
    elif mode == "polar_radar_plot":
        fig_spec = _compile_polar_radar_plot(cfg, theme, loaded_tables)
    elif mode == "multi_track_profile":
        fig_spec = _compile_multi_track_profile(cfg, theme, loaded_tables)
    elif mode == "vector_quiver_field":
        fig_spec = _compile_vector_quiver_field(cfg, theme, loaded_tables)

    if fig_spec is None:
        raise ValueError(
            f"Unsupported chart grammar mode {raw_mode!r}; expected one of {SUPPORTED_GRAMMAR_MODES}"
        )

    if j_spec:
        fig_spec.journal_spec = str(theme.get("journal_spec") or j_spec)
        fig_spec.theme = theme
        if fig_spec.journal_spec != "presentation_4_3" and "width_mm" in theme and "height_mm" in theme:
            if "width_mm" not in cfg and "height_mm" not in cfg:
                fig_spec.width_mm = float(theme["width_mm"])
                fig_spec.height_mm = float(theme["height_mm"])

    # Allow top-level `x_breaks`, `y_breaks`, and `linked_top_x` across any single-panel mode
    if fig_spec.panels:
        p0 = fig_spec.panels[0]
        if cfg.get("x_breaks") and not p0.x_axis.breaks:
            p0.x_axis.breaks = _normalize_axis_breaks(cfg["x_breaks"])
        if cfg.get("y_breaks") and not p0.y1_axis.breaks:
            p0.y1_axis.breaks = _normalize_axis_breaks(cfg["y_breaks"])
        if cfg.get("linked_top_x") and p0.x_axis.linked_top is None:
            p0.x_axis.linked_top = _normalize_linked_top(cfg["linked_top_x"])
        p0.validate()

    if cfg.get("export_pdf") is not None:
        fig_spec.meta["export_pdf"] = bool(cfg["export_pdf"])
    if "locale" in cfg and "locale" not in fig_spec.meta:
        fig_spec.meta["locale"] = str(cfg["locale"])
    return fig_spec


# Convenient public alias
compile_figure_spec = compile_config_to_figure_spec


_MODE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "bar_grouped_gradient": {
        "mode": "bar_grouped_gradient",
        "style_preset": "style_publication_minimal",
        "title": "Raman_ID_IG_Gradient_Bar",
        "output_dir": "path/to/new_output_folder",
        "x_label": "",
        "y_label": "I_D / I_G",
        "color_scheme": "paired_semantic",
        "show_value_labels": True,
        "categories": ["Pristine", "1 C 60s", "100 C 2s", "225 C 2s"],
        "series": [
            {
                "name": "I_D / I_G",
                "values": [0.94, 1.05, 1.18, 1.29],
                "y_err": [0.02, 0.03, 0.02, 0.03],
                "bar_roles": ["pristine", "control", "pulse", "pulse_strong"],
            }
        ],
    },
    "bar_stacked": {
        "mode": "bar_stacked",
        "style_preset": "style_publication_minimal",
        "title": "Pulse_Vdrop_Component_Stack",
        "output_dir": "path/to/new_output_folder",
        "x_label": "",
        "y_label": "Voltage Drop (V)",
        "color_scheme": "sandwich_stack",
        "normalize_100": False,
        "categories": ["100 C", "150 C", "200 C", "225 C"],
        "stacks": [
            {"name": "Delta E_0", "role": "inert", "values": [0.08, 0.11, 0.14, 0.16]},
            {"name": "Delta E_slow", "role": "control", "values": [0.12, 0.16, 0.21, 0.24]},
            {"name": "Delta V_slow,pol", "role": "pulse", "values": [0.19, 0.27, 0.35, 0.42]},
            {"name": "Delta V_0,pol", "role": "pulse_strong", "values": [0.31, 0.46, 0.62, 0.74]},
        ],
    },
    "bar_stacked_100pct": {
        "mode": "bar_stacked_100pct",
        "style_preset": "style_publication_minimal",
        "title": "XPS_C1s_Functional_Groups_100Pct",
        "output_dir": "path/to/new_output_folder",
        "x_label": "",
        "y_label": "Area Fraction (%)",
        "color_scheme": "sandwich_stack",
        "categories": ["Pristine", "1 C 60s", "100 C 2s", "Discharged"],
        "stacks": [
            {"name": "C-C / C=C", "role": "inert", "values": [28.4, 34.1, 41.5, 58.2]},
            {"name": "C-CF", "role": "baseline", "values": [14.2, 13.8, 12.6, 10.4]},
            {"name": "Semi-ionic C-F", "role": "control", "values": [24.6, 22.5, 19.8, 13.9]},
            {"name": "Covalent C-F", "role": "pulse", "values": [26.8, 24.2, 21.1, 13.5]},
            {"name": "-CF2 / -CF3", "role": "pulse_strong", "values": [6.0, 5.4, 5.0, 4.0]},
        ],
    },
    "dual_y_combo": {
        "mode": "dual_y_combo",
        "style_preset": "style_publication_minimal",
        "title": "XPS_Elemental_Line_and_Group_Stack_DualY",
        "output_dir": "path/to/new_output_folder",
        "align_zero": True,
        "categories": ["Pristine", "1 C 60s", "100 C 2s", "Discharged"],
        "left_y": {
            "label": "Elemental Content (at.%)",
            "unit": "at.%",
            "geom": "line_scatter",
            "relevant_elements": ["F", "C"],
            "series": [
                {"name": "F (at.%)", "element": "F", "y": [51.2, 46.8, 41.3, 24.5], "color": "#A02333"},
                {"name": "C (at.%)", "element": "C", "y": [46.5, 50.1, 54.9, 69.8], "color": "#111111"},
            ],
        },
        "right_y": {
            "label": "C 1s Fraction (%)",
            "unit": "%",
            "geom": "bar_stacked_100pct",
            "axis_color": "#3E86DE",
            "stacks": [
                {"name": "C-C / C=C", "role": "inert", "values": [28.4, 34.1, 41.5, 58.2]},
                {"name": "Semi-ionic C-F", "role": "control", "values": [38.8, 36.3, 32.4, 24.3]},
                {"name": "Covalent C-F_x", "role": "pulse", "values": [32.8, 29.6, 26.1, 17.5]},
            ],
        },
    },
    "curve_with_inset": {
        "mode": "curve_with_inset",
        "style_preset": "style_publication_minimal",
        "title": "EIS_Nyquist_With_HF_Inset",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Z' (Ohm)",
        "y_label": "-Z'' (Ohm)",
        "equal_aspect": True,
        "series": [
            {"name": "1 C 60s", "role": "control", "x": [2.1, 4.5, 9.8, 22.0, 48.0], "y": [0.2, 3.8, 7.2, 12.5, 28.0]},
            {"name": "100 C 2s Pulse", "role": "pulse", "x": [1.8, 3.2, 6.1, 14.0, 31.0], "y": [0.15, 2.4, 4.3, 8.2, 19.5]},
        ],
        "insets": [
            {
                "inset_id": "hf_zoom",
                "mode": "zoom",
                "bbox_pct": [51.0, 44.0, 42.0, 42.0],
                "xlim": [0.0, 16.0],
                "ylim": [0.0, 12.0],
                "equal_aspect": True,
                "show_zoom_box": True,
            }
        ],
    },
    "electrochem_kinetics": {
        "mode": "electrochem_kinetics",
        "subtype": "pulse_align",
        "style_preset": "style_publication_minimal",
        "title": "High_Rate_Short_Pulse_Alignment",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Time (s)",
        "y_label": "Voltage (V)",
        "series": [
            {"name": "100 C 2s", "role": "control", "x": [-0.5, 0.0, 0.02, 1.0, 2.0, 3.0], "y": [2.82, 2.82, 2.38, 2.24, 2.18, 2.66]},
            {"name": "225 C 2s", "role": "pulse_strong", "x": [-0.5, 0.0, 0.02, 1.0, 2.0, 3.0], "y": [2.82, 2.82, 1.96, 1.74, 1.62, 2.54]},
        ],
        "guides": [
            {"kind": "hline", "value": 2.82, "label": "V_before", "color": "#6579BE"},
        ],
        "span_annotations": [
            {"kind": "span_v", "start": 2.82, "end": 1.96, "anchor_pos": 0.15, "label": "Delta V_0,app", "color": "#A02333"},
        ],
    },
    "electrochem_kinetics:galvanostatic_dqdv": {
        "mode": "electrochem_kinetics",
        "subtype": "galvanostatic_dqdv",
        "style_preset": "style_publication_minimal",
        "title": "Galvanostatic_Discharge_and_dQdV",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Specific Capacity (mAh g^-1)",
        "y_label": "Voltage (V)",
        "series": [
            {
                "name": "Sample 1 (0.1 C)",
                "role": "control",
                "x": [0.0, 80.0, 220.0, 480.0, 720.0, 840.0],
                "y": [3.10, 2.68, 2.58, 2.54, 2.42, 1.50],
            }
        ],
    },
    "electrochem_kinetics:ragone": {
        "mode": "electrochem_kinetics",
        "subtype": "ragone",
        "style_preset": "style_publication_minimal",
        "title": "Ragone_Power_vs_Energy_Demo",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Power Density (W kg^-1)",
        "y_label": "Energy Density (Wh kg^-1)",
        "series": [
            {"name": "Sample 1", "role": "control", "x": [180.0, 900.0, 4500.0, 18000.0], "y": [2050.0, 1820.0, 1340.0, 620.0]},
            {"name": "Sample 2", "role": "pulse_strong", "x": [210.0, 1100.0, 6200.0, 42000.0], "y": [2180.0, 2040.0, 1790.0, 1360.0]},
        ],
    },
    "contour_pseudocolor_2d": {
        "mode": "contour_pseudocolor_2d",
        "style_preset": "style_publication_minimal",
        "title": "InSitu_DRT_Pseudocolor_Cloud",
        "output_dir": "path/to/new_output_folder",
        "x_label": "log_10(\\tau / s)",
        "y_label": "Pulse Step",
        "z_label": "\\gamma(\\tau) (Ohm)",
        "color_scheme": "pseudocolor_zero_white",
        "matrix_x": [-5.0, -4.0, -3.0, -2.0, -1.0],
        "matrix_y": [1, 2, 3, 4],
        "matrix_z": [
            [0.0, 1.2, 4.8, 1.5, 0.1],
            [0.0, 1.5, 5.6, 2.1, 0.2],
            [0.0, 1.9, 6.8, 2.9, 0.3],
            [0.0, 2.4, 8.1, 3.6, 0.4],
        ],
        "side_panel": {
            "position": "left",
            "x_label": "Voltage (V)",
            "y_label": "Pulse Step",
            "x": [2.75, 2.58, 2.39, 2.15],
            "y": [1, 2, 3, 4],
        },
    },
    "chart_grammar": {
        "mode": "chart_grammar",
        "style_preset": "style_publication_minimal",
        "title": "Multi_Panel_Declarative_Figure",
        "output_dir": "path/to/new_output_folder",
        "nrows": 1,
        "ncols": 2,
        "width_ratios": [1.0, 1.0],
        "panels": [
            {
                "panel_id": "panel_a",
                "tag": "a",
                "panel_mode": "bar_grouped_gradient",
                "y_label": "I_D / I_G",
                "categories": ["Pristine", "1 C 60s", "100 C 2s"],
                "series": [{"name": "I_D / I_G", "values": [0.94, 1.05, 1.18], "y_err": [0.02, 0.02, 0.03]}],
            },
            {
                "panel_id": "panel_b",
                "tag": "b",
                "panel_mode": "bar_stacked_100pct",
                "y_label": "C 1s Fraction (%)",
                "categories": ["Pristine", "1 C 60s", "100 C 2s"],
                "stacks": [
                    {"name": "C-C", "role": "inert", "values": [28.4, 34.1, 41.5]},
                    {"name": "Semi-ionic C-F", "role": "control", "values": [38.8, 36.3, 32.4]},
                    {"name": "Covalent C-F", "role": "pulse", "values": [32.8, 29.6, 26.1]},
                ],
            },
        ],
    },
    "xy_fit_and_band": {
        "mode": "xy_fit_and_band",
        "style_preset": "style_publication_minimal",
        "title": "Capacity_vs_Rate_LinearFit",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Current Rate (mA g⁻¹)",
        "y_label": "Capacity (mAh g⁻¹)",
        "model": "linear",
        "color": "#3E86DE",
        "band_alpha": 0.20,
        "subtype": "scatter_fit",
        "x": [0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
        "y": [310.0, 298.0, 275.0, 251.0, 220.0, 183.0],
    },
    "bode_dual_panel": {
        "mode": "bode_dual_panel",
        "style_preset": "style_publication_minimal",
        "title": "EIS_Bode_Plot",
        "output_dir": "path/to/new_output_folder",
        "color_scheme": "sequential_blue_red",
        "series": [
            {
                "name": "Fresh",
                "freq": [100000.0, 10000.0, 1000.0, 100.0, 10.0, 1.0, 0.1],
                "z_mag": [1.5, 2.1, 5.3, 18.4, 62.1, 145.0, 310.0],
                "phase": [2.1, 5.8, 22.4, 48.6, 71.2, 83.4, 88.1],
            }
        ],
    },
    "stat_distribution": {
        "mode": "stat_distribution",
        "style_preset": "style_publication_minimal",
        "title": "Capacity_Distribution_Groups",
        "output_dir": "path/to/new_output_folder",
        "x_label": "",
        "y_label": "Capacity (mAh g⁻¹)",
        "subtype": "box_jitter",
        "color_scheme": "sequential_blue_red",
        "series": [
            {"name": "Pristine", "y": [302.0, 308.0, 311.0, 305.0, 299.0]},
            {"name": "1C 60s",   "y": [285.0, 291.0, 295.0, 288.0, 280.0]},
            {"name": "100C 2s",  "y": [260.0, 268.0, 272.0, 264.0, 255.0]},
        ],
    },
    "matrix_heatmap": {
        "mode": "matrix_heatmap",
        "style_preset": "style_publication_minimal",
        "title": "Correlation_Matrix",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Condition",
        "y_label": "Parameter",
        "color_scheme": "diverging_blue_white_red",
        "center_zero": True,
        "show_value_labels": True,
        "value_format": ".2f",
        "series": [
            {
                "name": "corr_matrix",
                "matrix_x": ["Pristine", "1C 60s", "100C 2s"],
                "matrix_y": ["Capacity", "ID/IG", "CF_frac"],
                "matrix_z": [
                    [1.00, -0.82, -0.91],
                    [-0.82, 1.00,  0.74],
                    [-0.91, 0.74,  1.00],
                ],
            }
        ],
    },
    "stat_bar_dot_sig": {
        "mode": "stat_bar_dot_sig",
        "style_preset": "style_publication_minimal",
        "title": "Bio_Treatment_Bar_Dot_Significance",
        "output_dir": "path/to/new_output_folder",
        "y_label": "Relative Expression (a.u.)",
        "error_bar": "SD",
        "p_adjust": "fdr_bh",
        "locale": "en",
        "groups": {
            "Control": [1.02, 0.96, 1.05, 0.99, 1.01, 0.98],
            "Low Dose": [1.42, 1.35, 1.51, 1.48, 1.39, 1.44],
            "High Dose": [2.15, 2.28, 2.04, 2.19, 2.31, 2.12],
        },
    },
    "stat_violin_raincloud": {
        "mode": "stat_violin_raincloud",
        "style_preset": "style_arial_clean",
        "title": "Cell_Cluster_Violin_OkabeIto",
        "output_dir": "path/to/new_output_folder",
        "y_label": "Fluorescence Intensity (a.u.)",
        "color_scheme": "okabe_ito",
        "show_stats": True,
        "locale": "en",
        "groups": {
            "Cluster 1": [12.1, 13.4, 11.8, 12.9, 14.0, 12.5, 13.1, 11.9],
            "Cluster 2": [18.5, 19.2, 17.6, 20.1, 18.9, 19.5, 18.0, 19.8],
            "Cluster 3": [15.2, 14.8, 16.1, 15.6, 14.5, 15.9, 16.4, 15.0],
        },
    },
    "volcano_plot": {
        "mode": "volcano_plot",
        "style_preset": "style_arial_clean",
        "title": "Transcriptome_Volcano_Plot",
        "output_dir": "path/to/new_output_folder",
        "x_label": "log_2 Fold Change",
        "y_label": "-log_10(FDR)",
        "fc_cutoff": 1.0,
        "p_cutoff": 0.01,
        "top_n_labels": 6,
        "locale": "en",
        "genes": ["Gene A1", "Gene B2", "Gene C3", "Gene D4"],
        "log2fc": [-2.4, -0.3, 0.4, 2.8],
        "pval": [1.2e-6, 0.42, 0.18, 3.5e-8],
    },
    "forest_ablation_plot": {
        "mode": "forest_ablation_plot",
        "style_preset": "style_arial_clean",
        "title": "Model_Ablation_Forest_CI",
        "output_dir": "path/to/new_output_folder",
        "x_label": "\\g(D)AUROC (95% CI)",
        "null_value": 0.0,
        "locale": "en",
        "items": [
            {"name": "Full Model", "estimate": 0.000, "ci_low": -0.008, "ci_high": 0.008},
            {"name": "w/o Attention", "estimate": -0.042, "ci_low": -0.056, "ci_high": -0.028},
            {"name": "w/o Pretrain", "estimate": -0.078, "ci_low": -0.095, "ci_high": -0.061},
        ],
    },
    "free_energy_diagram": {
        "mode": "free_energy_diagram",
        "style_preset": "style_publication_minimal",
        "title": "OER_Free_Energy_Profile",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Reaction Coordinate",
        "y_label": "Free Energy \\g(D)\\i(G) (eV)",
        "step_labels": ["*", "*OH", "*O", "*OOH", "O_2"],
        "locale": "en",
        "pathways": [
            {"name": "Catalyst 1", "role": "control", "steps": [0.00, 0.92, 2.38, 3.65, 4.92]},
            {"name": "Catalyst 2", "role": "pulse", "steps": [0.00, 1.15, 2.52, 3.80, 4.92]},
        ],
    },
    "dose_response_4pl": {
        "mode": "dose_response_4pl",
        "style_preset": "style_publication_minimal",
        "title": "Inhibitor_Dose_Response_4PL",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Concentration (nM)",
        "y_label": "Cell Viability (%)",
        "locale": "en",
        "series": [
            {
                "name": "Compound 1",
                "role": "pulse",
                "x": [0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 1000.0, 10000.0],
                "y": [98.5, 95.2, 86.4, 64.1, 35.8, 14.2, 5.8, 4.9],
            },
            {
                "name": "Compound 2",
                "role": "control",
                "x": [0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 1000.0, 10000.0],
                "y": [99.1, 98.4, 96.8, 93.1, 85.0, 68.5, 22.4, 7.6],
            },
        ],
    },
    "kaplan_meier_plot": {
        "mode": "kaplan_meier_plot",
        "style_preset": "style_arial_clean",
        "title": "Clinical_Survival_Kaplan_Meier",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Time (months)",
        "y_label": "Survival Probability",
        "show_ci": True,
        "show_censor": True,
        "show_risk_table": True,
        "locale": "en",
        "groups": [
            {
                "name": "Targeted Therapy",
                "role": "pulse",
                "time": [3.0, 6.0, 8.5, 11.0, 14.0, 17.5, 20.0, 22.0, 24.0, 24.0],
                "event": [1, 0, 1, 0, 1, 0, 0, 1, 0, 0],
            },
            {
                "name": "Standard Care",
                "role": "control",
                "time": [1.5, 3.5, 5.0, 6.5, 8.0, 9.5, 12.0, 15.0, 18.0, 24.0],
                "event": [1, 1, 1, 0, 1, 1, 1, 1, 0, 1],
            },
        ],
    },
    "roc_pr_curve": {
        "mode": "roc_pr_curve",
        "curve_kind": "roc",
        "style_preset": "style_arial_clean",
        "title": "Classifier_ROC_Comparison",
        "output_dir": "path/to/new_output_folder",
        "show_optimal_point": True,
        "locale": "en",
        "models": [
            {
                "name": "Multimodal GNN",
                "role": "pulse",
                "y_true": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
                "y_score": [0.08, 0.15, 0.24, 0.38, 0.52, 0.48, 0.71, 0.84, 0.91, 0.96],
            },
            {
                "name": "Linear Baseline",
                "role": "control",
                "y_true": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
                "y_score": [0.12, 0.29, 0.44, 0.61, 0.68, 0.35, 0.55, 0.64, 0.79, 0.88],
            },
        ],
    },
    "nmr_spectrum": {
        "mode": "nmr_spectrum",
        "style_preset": "style_publication_minimal",
        "title": "Proton_NMR_400MHz_Spectrum",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Chemical Shift \\g(d) (ppm)",
        "y_label": "Intensity (a.u.)",
        "locale": "en",
        "series": [
            {
                "name": "1H NMR (400 MHz)",
                "x": [8.0, 7.32, 7.26, 7.20, 4.20, 4.12, 4.04, 1.35, 1.26, 1.17, 0.5],
                "y": [0.01, 0.32, 0.95, 0.31, 0.25, 0.68, 0.24, 0.38, 0.88, 0.36, 0.01],
                "integrals": [
                    {"ppm_range": [7.15, 7.38], "label": "2H"},
                    {"ppm_range": [4.00, 4.25], "label": "2H"},
                    {"ppm_range": [1.12, 1.40], "label": "3H"},
                ],
            }
        ],
        "peaks": [
            {"ppm": 7.26, "label": "Ar-H (m)"},
            {"ppm": 4.12, "label": "-OCH_2- (q)"},
            {"ppm": 1.26, "label": "-CH_3 (t)"},
        ],
    },
    "broken_axis_plot": {
        "mode": "broken_axis_plot",
        "style_preset": "style_publication_minimal",
        "title": "Bimodal_Time_Regime_Broken_X",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Reaction Time (s)",
        "y_label": "Conversion (%)",
        "x_limits": [0.0, 3600.0],
        "x_breaks": [{"from": 12.0, "to": 1200.0, "position_pct": 48.0}],
        "locale": "en",
        "series": [
            {
                "name": "Catalyst A",
                "role": "pulse",
                "x": [0.5, 2.0, 5.0, 10.0, 1400.0, 2200.0, 3400.0],
                "y": [12.0, 34.0, 58.0, 71.0, 86.0, 93.0, 97.5],
            },
            {
                "name": "Control",
                "role": "control",
                "x": [0.5, 2.0, 5.0, 10.0, 1400.0, 2200.0, 3400.0],
                "y": [4.0, 11.0, 21.0, 29.0, 48.0, 59.0, 66.0],
            },
        ],
    },
    "dual_x_optical_spectrum": {
        "mode": "dual_x_optical_spectrum",
        "style_preset": "style_publication_minimal",
        "title": "UV_Vis_Dual_Wavelength_Energy",
        "output_dir": "path/to/new_output_folder",
        "x_label": "Wavelength \\g(l) (nm)",
        "y_label": "Absorbance (a.u.)",
        "linked_top_x": {"label": "Photon Energy (eV)", "formula": "1239.84193/x"},
        "locale": "en",
        "series": [
            {
                "name": "Perovskite Film",
                "role": "pulse",
                "x": [350.0, 420.0, 500.0, 600.0, 720.0, 780.0, 850.0],
                "y": [1.85, 1.52, 1.18, 0.89, 0.64, 0.12, 0.03],
            }
        ],
    },
    "ternary_diagram": {
        "mode": "ternary_diagram",
        "style_preset": "style_publication_minimal",
        "title": "Ternary_Composition_Phase_Map",
        "output_dir": "path/to/new_output_folder",
        "component_labels": ["Component A (wt%)", "Component B (wt%)", "Component C (wt%)"],
        "locale": "en",
        "series": [
            {
                "name": "Single Phase",
                "role": "control",
                "a": [70.0, 62.0, 55.0, 48.0],
                "b": [15.0, 22.0, 25.0, 32.0],
                "c": [15.0, 16.0, 20.0, 20.0],
                "marker_style": "circle",
            },
            {
                "name": "Two Phase",
                "role": "pulse",
                "a": [25.0, 20.0, 15.0],
                "b": [45.0, 50.0, 55.0],
                "c": [30.0, 30.0, 30.0],
                "marker_style": "open_circle",
            },
        ],
    },
    "polar_radar_plot": {
        "mode": "polar_radar_plot",
        "subtype": "polar",
        "style_preset": "style_publication_minimal",
        "title": "Radiation_Anisotropy_Polar_Pattern",
        "output_dir": "path/to/new_output_folder",
        "y_label": "Normalized Gain",
        "locale": "en",
        "series": [
            {
                "name": "TE Mode",
                "role": "pulse",
                "theta": [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0, 360.0],
                "r": [0.95, 0.68, 0.22, 0.65, 0.94, 0.66, 0.21, 0.69, 0.95],
            }
        ],
    },
    "polar_radar_plot:radar": {
        "mode": "polar_radar_plot",
        "subtype": "radar",
        "style_preset": "style_arial_clean",
        "title": "Benchmark_Multi_Metric_Radar",
        "output_dir": "path/to/new_output_folder",
        "categories": ["Accuracy", "Speed", "Memory", "Robustness", "Calibration", "Transfer"],
        "locale": "en",
        "series": [
            {"name": "Proposed Model", "role": "pulse", "y": [0.94, 0.86, 0.82, 0.91, 0.89, 0.88]},
            {"name": "Baseline Model", "role": "control", "y": [0.81, 0.78, 0.74, 0.72, 0.76, 0.69]},
        ],
    },
    "multi_track_profile": {
        "mode": "multi_track_profile",
        "style_preset": "style_arial_clean",
        "title": "Water_Column_Multi_Track_Profile",
        "output_dir": "path/to/new_output_folder",
        "depth_label": "Depth (m)",
        "depth_invert": True,
        "locale": "en",
        "horizons": [{"depth_start": 25.0, "depth_end": 42.0, "label": "Thermocline"}],
        "tracks": [
            {
                "name": "Temperature",
                "x_label": "Temp. (degC)",
                "color": "#D84B5C",
                "x": [24.2, 23.8, 19.5, 14.2, 10.8, 8.9],
                "depth": [0.0, 15.0, 30.0, 45.0, 75.0, 100.0],
            },
            {
                "name": "Salinity",
                "x_label": "Salinity (PSU)",
                "color": "#2B6CB0",
                "x": [34.1, 34.2, 34.6, 34.9, 35.1, 35.2],
                "depth": [0.0, 15.0, 30.0, 45.0, 75.0, 100.0],
            },
            {
                "name": "Dissolved O2",
                "x_label": "DO (mg L^-1)",
                "color": "#009E73",
                "x": [7.8, 7.6, 6.1, 4.8, 4.2, 3.9],
                "depth": [0.0, 15.0, 30.0, 45.0, 75.0, 100.0],
            },
        ],
    },
    "vector_quiver_field": {
        "mode": "vector_quiver_field",
        "style_preset": "style_publication_minimal",
        "title": "Vortex_Velocity_Quiver_Map",
        "output_dir": "path/to/new_output_folder",
        "x_label": "x (mm)",
        "y_label": "y (mm)",
        "z_label": "|V| (m s^-1)",
        "color_scheme": "viridis",
        "compute_magnitude_bg": True,
        "locale": "en",
        "x": [-1.0, 0.0, 1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 1.0],
        "y": [-1.0, -1.0, -1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
        "u": [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, -1.0, -1.0, -1.0],
        "v": [-1.0, 0.0, 1.0, -1.0, 0.0, 1.0, -1.0, 0.0, 1.0],
    },
}


def generate_mode_template(mode: str) -> Dict[str, Any]:
    """
    Return a standard JSON-ready configuration template dictionary for `init-template`
    across all Chart Grammar modes (including cross-science modes and kinetics subtypes).
    """
    key = str(mode or "").strip()
    subtype_aliases = {
        "pulse_align": "electrochem_kinetics",
        "electrochem_kinetics:pulse_align": "electrochem_kinetics",
        "galvanostatic_dqdv": "electrochem_kinetics:galvanostatic_dqdv",
        "ragone": "electrochem_kinetics:ragone",
        # Mode aliases
        "fit_band": "xy_fit_and_band",
        "bode": "bode_dual_panel",
        "stat_dist": "stat_distribution",
        "heatmap": "matrix_heatmap",
        "bar_dot_sig": "stat_bar_dot_sig",
        "violin": "stat_violin_raincloud",
        "raincloud": "stat_violin_raincloud",
        "volcano": "volcano_plot",
        "forest": "forest_ablation_plot",
        "ablation": "forest_ablation_plot",
        "free_energy": "free_energy_diagram",
        "ic50": "dose_response_4pl",
        "4pl": "dose_response_4pl",
        "km": "kaplan_meier_plot",
        "kaplan_meier": "kaplan_meier_plot",
        "survival": "kaplan_meier_plot",
        "roc": "roc_pr_curve",
        "pr_curve": "roc_pr_curve",
        "nmr": "nmr_spectrum",
        "broken_axis": "broken_axis_plot",
        "dual_x": "dual_x_optical_spectrum",
        "optical_dual_x": "dual_x_optical_spectrum",
        "ternary": "ternary_diagram",
        "polar": "polar_radar_plot",
        "radar": "polar_radar_plot:radar",
        "multi_track": "multi_track_profile",
        "stratigraphic_profile": "multi_track_profile",
        "quiver": "vector_quiver_field",
        "vector_field": "vector_quiver_field",
    }
    lookup = subtype_aliases.get(key, key)
    if lookup not in _MODE_TEMPLATES:
        raise ValueError(
            f"Unknown chart grammar template mode {mode!r}; supported: {list(_MODE_TEMPLATES.keys())}"
        )
    return copy.deepcopy(_MODE_TEMPLATES[lookup])
