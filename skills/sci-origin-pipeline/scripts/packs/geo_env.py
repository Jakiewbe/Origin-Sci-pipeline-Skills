"""
Earth, Ocean, Atmospheric & Environmental Science Domain Pack (`geo_env`).

Provides:
- `normalize_ternary_closure`: simplex non-negativity check and exact closure
  `A + B + C = scale` (default `100.0%`) for geochemistry, soil texture, and phase diagrams.
- Multi-track depth / paleo-age stratigraphic core table sniffer (`depth_m` / `age_ka`).
- 2D `(x, y, u, v)` Eulerian vector / wind / ocean current field table sniffer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


PACK_ID = "geo_env"
DISPLAY_NAME_ZH = "地球科学、海洋大气与环境工程"
DISPLAY_NAME_EN = "Earth, Ocean, Atmospheric & Environmental Science"
MODALITIES = (
    "ternary_composition",
    "depth_age_profile",
    "vector_field_2d",
)
EXTENSIONS = (
    ".csv",
    ".tsv",
    ".xlsx",
)
RECOMMENDED_MODES = (
    "ternary_diagram",
    "multi_track_profile",
    "vector_quiver_field",
    "contour_2d",
)

_DEPTH_AGE_COLS = {
    "depth_m", "depth_cm", "depth", "core_depth", "water_depth_m",
    "age_ka", "age_bp", "age_kyr", "age_ma",
}
_TERNARY_SETS = (
    {"a", "b", "c"},
    {"comp_a", "comp_b", "comp_c"},
    {"sand", "silt", "clay"},
    {"sio2", "al2o3", "mgo"},
    {"sio2", "feot", "mgo"},
    {"q", "f", "l"},
    {"ca", "mg", "na_k"},
)


def normalize_ternary_closure(
    a: Sequence[float],
    b: Sequence[float],
    c: Sequence[float],
    scale: float = 100.0,
) -> Dict[str, Any]:
    """
    Validate 3-component simplex coordinates (`a >= 0`, `b >= 0`, `c >= 0`, `a + b + c > 0`)
    and normalize each composition row to close strictly to ``scale`` (default `100.0`).
    """
    if float(scale) <= 0.0:
        raise ValueError(f"Ternary closure scale must be > 0, got {scale!r}.")

    a_arr = np.asarray(a, dtype=float).ravel()
    b_arr = np.asarray(b, dtype=float).ravel()
    c_arr = np.asarray(c, dtype=float).ravel()

    if not (a_arr.size == b_arr.size == c_arr.size):
        raise ValueError(
            f"Ternary component lengths must match: len(a)={a_arr.size}, len(b)={b_arr.size}, len(c)={c_arr.size}."
        )
    if a_arr.size == 0:
        raise ValueError("Ternary component arrays cannot be empty.")
    if not (np.all(np.isfinite(a_arr)) and np.all(np.isfinite(b_arr)) and np.all(np.isfinite(c_arr))):
        raise ValueError("Ternary component arrays contain NaN or infinite values.")

    tol_neg = -1e-12
    if np.any(a_arr < tol_neg) or np.any(b_arr < tol_neg) or np.any(c_arr < tol_neg):
        raise ValueError("Ternary components must be non-negative (found value < 0).")

    a_clean = np.maximum(a_arr, 0.0)
    b_clean = np.maximum(b_arr, 0.0)
    c_clean = np.maximum(c_arr, 0.0)

    totals = a_clean + b_clean + c_clean
    if np.any(totals <= 0.0):
        raise ValueError("Ternary composition row has zero total (a + b + c == 0); simplex closure is undefined.")

    sc = float(scale)
    a_norm = (a_clean / totals) * sc
    b_norm = (b_clean / totals) * sc
    c_norm = (c_clean / totals) * sc
    max_resid = float(np.max(np.abs((a_norm + b_norm + c_norm) - sc)))

    return {
        "a": a_norm,
        "b": b_norm,
        "c": c_norm,
        "raw_totals": totals,
        "scale": sc,
        "max_closure_residual": max_resid,
    }


def sniff_geo_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Sniff multi-track depth/age tables, 2D `(x, y, u, v)` vector grids, or ternary composition tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext not in (".csv", ".tsv", ".xlsx") or not p.exists() or not p.is_file():
        return None

    try:
        df0 = pd.read_excel(p, nrows=4) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","), nrows=4)
    except Exception:
        return None

    cols = [str(c).strip() for c in df0.columns]
    low_map = {c.lower(): c for c in cols}
    low_set = set(low_map.keys())

    has_xy = ({"x", "y"} <= low_set) or ({"lon", "lat"} <= low_set) or ({"longitude", "latitude"} <= low_set)
    has_uv = ({"u", "v"} <= low_set) or ({"vx", "vy"} <= low_set) or ({"x_end", "y_end"} <= low_set)
    if has_xy and has_uv:
        return {
            "pack_id": PACK_ID,
            "modality": "vector_field_2d",
            "recommended_mode": "vector_quiver_field",
            "extension": ext,
            "confidence": "high",
        }

    depth_hits = low_set & _DEPTH_AGE_COLS
    if depth_hits and len(cols) >= 3:
        d_col = low_map[sorted(depth_hits)[0]]
        return {
            "pack_id": PACK_ID,
            "modality": "depth_age_profile",
            "recommended_mode": "multi_track_profile",
            "extension": ext,
            "confidence": "high",
            "matched_columns": {
                "depth_col": d_col,
                "track_cols": [c for c in cols if c != d_col],
            },
        }

    for t_set in _TERNARY_SETS:
        if t_set <= low_set:
            return {
                "pack_id": PACK_ID,
                "modality": "ternary_composition",
                "recommended_mode": "ternary_diagram",
                "extension": ext,
                "confidence": "medium",
            }

    return None


def parse_geo_file(filepath: str | Path) -> Dict[str, Any]:
    """Parse earth/environmental ternary, multi-track depth, or 2D vector field tables."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Geo/environmental data file not found: {p}")

    ext = p.suffix.lower()
    sniff = sniff_geo_file(p)
    df = pd.read_excel(p) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","))

    return {
        "pack_id": PACK_ID,
        "modality": sniff["modality"] if sniff else "geo_table",
        "recommended_mode": sniff["recommended_mode"] if sniff else "multi_track_profile",
        "file": str(p),
        "n_rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "matched_columns": sniff.get("matched_columns", {}) if sniff else {},
        "head_preview": df.head(5).to_dict(orient="records"),
    }


def validate_geo_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ternary closure non-negativity, depth monotonicity, and vector field dimensions."""
    findings: List[Dict[str, str]] = []

    series_list = payload.get("series") if isinstance(payload.get("series"), list) else []
    if all(k in payload for k in ("a", "b", "c")):
        series_list = [payload]

    for idx, s in enumerate(series_list):
        if isinstance(s, dict) and all(k in s for k in ("a", "b", "c")):
            s_name = str(s.get("name") or f"Ternary_{idx + 1}")
            try:
                res = normalize_ternary_closure(s["a"], s["b"], s["c"])
                if np.max(np.abs(res["raw_totals"] - 100.0)) > 2.0 and np.max(np.abs(res["raw_totals"] - 1.0)) > 0.02:
                    findings.append(
                        {
                            "level": "INFO_TERNARY_RENORMALIZED",
                            "region": s_name,
                            "detail": (
                                f"Ternary series '{s_name}' raw component sums ranged in "
                                f"[{float(np.min(res['raw_totals'])):.2f}, {float(np.max(res['raw_totals'])):.2f}] "
                                "and were normalized to 100%."
                            ),
                        }
                    )
            except ValueError as exc:
                findings.append(
                    {
                        "level": "ERROR_TERNARY_INVALID",
                        "region": s_name,
                        "detail": str(exc),
                    }
                )

    tracks = payload.get("tracks")
    if isinstance(tracks, list):
        for idx, tr in enumerate(tracks):
            if isinstance(tr, dict) and tr.get("depth") is not None:
                d_arr = np.asarray(tr["depth"], dtype=float).ravel()
                if d_arr.size >= 2 and np.any(np.diff(d_arr) < 0.0):
                    findings.append(
                        {
                            "level": "WARN_UNSORTED_DEPTH_PROFILE",
                            "region": str(tr.get("name") or f"Track_{idx + 1}"),
                            "detail": "Depth/age values are not monotonically non-decreasing; check core log sorting.",
                        }
                    )

    has_err = any(str(f.get("level", "")).startswith("ERROR") for f in findings)
    status = "ERROR" if has_err else ("WARN" if findings else "PASS")
    return {
        "pack_id": PACK_ID,
        "status": status,
        "findings": findings,
    }


__all__ = [
    "PACK_ID",
    "DISPLAY_NAME_ZH",
    "DISPLAY_NAME_EN",
    "MODALITIES",
    "EXTENSIONS",
    "RECOMMENDED_MODES",
    "normalize_ternary_closure",
    "sniff_geo_file",
    "parse_geo_file",
    "validate_geo_payload",
]
