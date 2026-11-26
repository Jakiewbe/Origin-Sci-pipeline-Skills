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
)

SUPPORTED_GUIDE_KINDS = (
    "vline",
    "hline",
    "span_v",
    "span_h",
    "peak_tag",
    "trend_arrow",
    "text",
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
)

SUPPORTED_KINETICS_SUBTYPES = (
    "pulse_align",
    "galvanostatic_dqdv",
    "ragone",
)

ORIGIN_PLOT_ID_BY_MARK: Dict[str, int] = {
    "line_scatter": 202,
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
}

ORIGIN_TEMPLATE_BY_MARK: Dict[str, Optional[str]] = {
    "line_scatter": None,
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

    def to_dict(self) -> Dict[str, Any]:
        return _to_jsonable(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AxisSpec":
        d = copy.deepcopy(data)
        if d.get("limits") is not None:
            d["limits"] = tuple(d["limits"])
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
    y: Optional[float] = None
    x_end: Optional[float] = None
    y_end: Optional[float] = None
    label: str = ""
    color: str = "#3E86DE"
    line_style: str = "dashed"
    line_width_pt: float = 2.8
    font_size_pt: float = 20.0
    shoulder_y_frac: float = 0.77
    label_side: str = "right"

    def __post_init__(self) -> None:
        k_norm = str(self.kind).strip().lower()
        if k_norm in ("vspan_arrow", "vspan", "vertical_span"):
            k_norm = "span_v"
        elif k_norm in ("hspan_arrow", "hspan", "horizontal_span"):
            k_norm = "span_h"
        self.kind = k_norm
        self.color = ot.normalize_hex(self.color)
        for attr in ("value", "start", "end", "anchor_pos", "x", "y", "x_end", "y_end"):
            v = getattr(self, attr)
            if v is not None:
                setattr(self, attr, float(v))
        if self.kind == "span_v":
            if self.x is None and self.anchor_pos is not None:
                self.x = self.anchor_pos
            elif self.anchor_pos is None and self.x is not None:
                self.anchor_pos = self.x
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
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuideSpec":
        d = copy.deepcopy(data)
        if d.get("start") is None and "y_start" in d:
            d["start"] = d.pop("y_start")
        else:
            d.pop("y_start", None)
        if d.get("end") is None and d.get("kind") in ("span_v", "vspan_arrow") and "y_end" in d:
            d["end"] = d.pop("y_end")
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
        return cls(**copy.deepcopy(data))


@dataclass
class FigureSpec:
    title: str = "SciOrigin_Figure"
    mode: str = "chart_grammar"
    subtype: Optional[str] = None
    style_preset: str = ot.DEFAULT_STYLE_PRESET
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

    def __post_init__(self) -> None:
        self.panels = [
            p if isinstance(p, PanelSpec) else PanelSpec.from_dict(p)
            for p in self.panels
        ]
        self.width_ratios = [float(r) for r in self.width_ratios]
        self.height_ratios = [float(r) for r in self.height_ratios]
        if not self.theme:
            self.theme = ot.load_theme(self.style_preset)
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
        else:
            kind = raw_kind
        val = g.get("value", g.get("pos"))
        start_v = g.get("start", g.get("y_start"))
        end_v = g.get("end", g.get("y_end") if kind == "span_v" else None)
        anchor_v = g.get("anchor_pos", g.get("x") if kind == "span_v" else None)
        ls = g.get("line_style", g.get("linestyle", "dashed" if kind in ("vline", "hline") else "solid"))
        out.append(
            GuideSpec(
                kind=kind,
                axis=g.get("axis", "y1"),
                value=val,
                start=start_v,
                end=end_v,
                anchor_pos=anchor_v,
                x=g.get("x", anchor_v if kind == "span_v" else None),
                y=g.get("y"),
                x_end=g.get("x_end"),
                y_end=g.get("y_end") if kind != "span_v" else None,
                label=str(g.get("label", "")),
                color=g.get("color", "#3E86DE"),
                line_style=ls,
                line_width_pt=float(g.get("line_width_pt", 1.8 if kind.startswith("span") else default_lw)),
                font_size_pt=float(g.get("font_size_pt", default_fs)),
                shoulder_y_frac=float(g.get("shoulder_y_frac", default_y_frac)),
                label_side=g.get("label_side", "right"),
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
            max_x_v, max_y_v = max(xs), max(ys)
            raw_sp = max(max_x_v, max_y_v)
            if max_y_v > 2.2 * max(max_x_v, 1.0):
                span = min(raw_sp * 1.06, max(1200.0, max_x_v * 2.35))
            else:
                span = raw_sp * 1.12
            eq_step = 500.0 if span > 1200.0 else (200.0 if span > 500.0 else (50.0 if span > 120.0 else 10.0))
            span = math.ceil(span / eq_step) * eq_step
            if min(min(xs), min(ys)) >= 0.0:
                x_lims = (0.0, round(span, 6))
                y_lims = (0.0, round(span, 6))

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
        width_mm=120.0 if eq_aspect else 140.0,
        height_mm=120.0 if eq_aspect else 108.0,
        panels=[panel],
        output_dir=cfg.get("output_dir"),
        build_opju=bool(cfg.get("build_opju", True)),
        template_override=cfg.get("template_override"),
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
            color=y1_cfg.get("color", "#111111"),
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
            )
        )

    return FigureSpec(
        title=cfg.get("title", "Declarative_Chart_Grammar"),
        mode="chart_grammar",
        style_preset=cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET),
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
    Scatter + regression fit curve + 95% CI shaded band (xy_fit_and_band mode).
    Two subtypes:
      - "scatter_fit"  (default): scatter points + fitted line + CI band
      - "band_only": multi-series mean lines with y_low/y_high half-transparent bands
    """
    import sys as _sys, importlib as _il
    _et_path = str(Path(__file__).resolve().parent)
    if _et_path not in _sys.path:
        _sys.path.insert(0, _et_path)
    _et = _il.import_module("electrochem_transforms")
    fit_xy_with_ci95 = _et.fit_xy_with_ci95

    title = str(cfg.get("title", "xy_fit"))
    style_name = str(cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET))
    x_label = str(cfg.get("x_label", "x"))
    y_label = str(cfg.get("y_label", "y"))
    model = str(cfg.get("model") or cfg.get("fit_model") or "linear")
    n_grid = int(cfg.get("n_grid", 200))
    ci_level = float(cfg.get("ci_level", 0.95))
    color = str(cfg.get("color", ot.SEMANTIC_PALETTE["blue"]))
    subtype = str(cfg.get("subtype", "scatter_fit"))
    output_dir = cfg.get("output_dir")
    build_opju = bool(cfg.get("build_opju", True))

    series_specs: List[SeriesSpec] = []
    panel_meta: Dict[str, Any] = {}

    if subtype == "band_only":
        raw_series = cfg.get("series", [])
        n_s = len(raw_series) or 1
        palette = ot.resolve_series_colors(n_s, scheme=cfg.get("color_scheme", "sequential_blue_red"))
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
        x_raw = _as_float_list(cfg.get("x"), "x")
        y_raw = _as_float_list(cfg.get("y"), "y")
        raw_series = cfg.get("series", [])
        if (x_raw is None or y_raw is None) and raw_series and isinstance(raw_series[0], dict):
            s0 = raw_series[0]
            x_raw = _as_float_list(s0.get("x"), "x")
            y_raw = _as_float_list(s0.get("y"), "y")
            if s0.get("color"):
                color = str(s0["color"])
        if x_raw is None or y_raw is None:
            raise ValueError("xy_fit_and_band requires 'x' and 'y' arrays in config (or in series[0])")
        scatter_name = str(cfg.get("scatter_name", "Experimental"))
        fit_name = str(cfg.get("fit_name", f"{model.capitalize()} Fit (95% CI)"))
        series_specs.append(SeriesSpec(
            name=scatter_name,
            x=x_raw,
            y=y_raw,
            role="raw",
            color=color,
            marker_style=str(cfg.get("marker_style", "circle_solid")),
            marker_size_pt=float(cfg.get("marker_size_pt", 7.5)),
            line_style="none",
        ))
        fit = fit_xy_with_ci95(x_raw, y_raw, model=model, n_grid=n_grid, ci_level=ci_level)
        x_fit = fit["x_fit"]
        y_fit_list = fit["y_fit"]
        y_low = fit["y_low"]
        y_high = fit["y_high"]
        annotation = fit["equation_str"] + f"  R²={fit['r2']:.4f}"
        panel_meta["regression_equation"] = fit["equation_str"]
        panel_meta["r_squared"] = f"{fit['r2']:.4f}"
        series_specs.append(SeriesSpec(
            name=fit_name,
            x=x_fit,
            y=y_fit_list,
            y_low=y_low,
            y_high=y_high,
            role="fit",
            color=color,
            line_style="solid",
            line_width_pt=float(cfg.get("line_width_pt", theme.get("curve_linewidth", 3.0))),
            marker_style="none",
            meta={
                "mark_override": "line_band",
                "annotation": annotation,
                "r2": fit["r2"],
                "equation_str": fit["equation_str"],
            },
        ))

    layer = LayerSpec(
        layer_id="xy_fit_main",
        mark="line_band",
        series=series_specs,
        color_scheme="paired_semantic",
    )
    x_axis = AxisSpec(which="x", label=x_label, scale=str(cfg.get("x_scale", "linear")))
    y1_axis = AxisSpec(which="y1", label=y_label, scale=str(cfg.get("y_scale", "linear")))
    panel = PanelSpec(
        panel_id="panel_main",
        tag=str(cfg.get("tag", "a")),
        x_axis=x_axis,
        y1_axis=y1_axis,
        layers=[layer],
        box_linewidth_pt=float(theme.get("figure_box_linewidth", 3.0)),
        legend_style=str(cfg.get("legend_style", "corner_upper_left")),
        meta=panel_meta,
    )
    return FigureSpec(
        title=title,
        mode="xy_fit_and_band",
        subtype=subtype,
        style_preset=style_name,
        theme=theme,
        nrows=1,
        ncols=1,
        panels=[panel],
        output_dir=output_dir,
        build_opju=build_opju,
    )


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
    mode = str(cfg.get("mode", "")).strip()
    if not mode:
        raise ValueError("Configuration dictionary is missing required `mode` field.")

    style_name = cfg.get("style_preset", ot.DEFAULT_STYLE_PRESET)
    theme = ot.load_theme(style_name)

    if mode == "bar_grouped_gradient":
        return _compile_bar_grouped_gradient(cfg, theme, loaded_tables)
    if mode == "bar_stacked":
        return _compile_bar_stacked(cfg, theme, loaded_tables, force_100pct=False)
    if mode == "bar_stacked_100pct":
        return _compile_bar_stacked(cfg, theme, loaded_tables, force_100pct=True)
    if mode == "dual_y_combo":
        return _compile_dual_y_combo(cfg, theme, loaded_tables)
    if mode == "curve_with_inset":
        return _compile_curve_with_inset(cfg, theme, loaded_tables)
    if mode == "electrochem_kinetics":
        return _compile_electrochem_kinetics(cfg, theme, loaded_tables)
    if mode == "contour_pseudocolor_2d":
        return _compile_contour_pseudocolor_2d(cfg, theme, loaded_tables)
    if mode == "chart_grammar":
        return _compile_universal_chart_grammar(cfg, theme, loaded_tables)
    if mode == "xy_fit_and_band":
        return _compile_xy_fit_and_band(cfg, theme, loaded_tables)
    if mode == "bode_dual_panel":
        return _compile_bode_dual_panel(cfg, theme, loaded_tables)
    if mode == "stat_distribution":
        return _compile_stat_distribution_new(cfg, theme, loaded_tables)
    if mode == "matrix_heatmap":
        return _compile_matrix_heatmap_new(cfg, theme, loaded_tables)

    raise ValueError(
        f"Unsupported chart grammar mode {mode!r}; expected one of {SUPPORTED_GRAMMAR_MODES}"
    )


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
                "bbox_pct": [44.0, 8.0, 46.0, 46.0],
                "xlim": [0.0, 12.0],
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
}


def generate_mode_template(mode: str) -> Dict[str, Any]:
    """
    Return a standard JSON-ready configuration template dictionary for `init-template`
    across all first-batch Chart Grammar modes (and `electrochem_kinetics` subtypes).
    """
    key = str(mode or "").strip()
    subtype_aliases = {
        "pulse_align": "electrochem_kinetics",
        "electrochem_kinetics:pulse_align": "electrochem_kinetics",
        "galvanostatic_dqdv": "electrochem_kinetics:galvanostatic_dqdv",
        "ragone": "electrochem_kinetics:ragone",
        # New mode aliases
        "fit_band": "xy_fit_and_band",
        "bode": "bode_dual_panel",
        "stat_dist": "stat_distribution",
        "heatmap": "matrix_heatmap",
    }
    lookup = subtype_aliases.get(key, key)
    if lookup not in _MODE_TEMPLATES:
        raise ValueError(
            f"Unknown chart grammar template mode {mode!r}; supported: {list(_MODE_TEMPLATES.keys())}"
        )
    return copy.deepcopy(_MODE_TEMPLATES[lookup])
