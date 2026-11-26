"""
Chemical Spectroscopy & Catalysis Domain Pack (`chem_catalysis`).

Provides:
- Standard IUPAC JCAMP-DX `.jdx` / `.dx` spectroscopy reader (`##TITLE`, `##XUNITS`,
  `##YUNITS`, `##FIRSTX`, `##LASTX`, `##DELTAX`, `##XFACTOR`, `##YFACTOR`,
  `##XYDATA=(X++(Y..Y))` and `(XY..XY)` / `##XYPOINTS` / `##PEAKTABLE`).
- NMR chemical shift (`ppm` + `intensity` / `integral`) and free-energy pathway table sniffer.
- Free-energy pathway reaction-coordinate monotonicity, step-count consistency, and
  transition-state (`TS`) barrier sanity validator.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


PACK_ID = "chem_catalysis"
DISPLAY_NAME_ZH = "化学谱学与催化反应机理"
DISPLAY_NAME_EN = "Chemical Spectroscopy & Catalysis"
MODALITIES = (
    "jcamp_dx",
    "nmr_spectrum",
    "free_energy_pathway",
    "arrhenius_kinetics",
)
EXTENSIONS = (
    ".jdx",
    ".dx",
    ".jcamp",
    ".csv",
    ".tsv",
    ".xlsx",
)
RECOMMENDED_MODES = (
    "nmr_spectrum",
    "free_energy_diagram",
    "linear_regression_ci",
    "ftir",
    "waterfall",
)

_NUM_TOKEN_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?")
_NMR_X_COLS = {"ppm", "chemical_shift", "delta_ppm", "shift_ppm", "f1_ppm"}
_NMR_Y_COLS = {"intensity", "rel_intensity", "integral", "area", "signal"}
_FED_STEP_COLS = {"reaction_coordinate", "step", "intermediate", "state", "ads_state"}
_FED_G_COLS = {"delta_g", "free_energy", "free_energy_ev", "g_ev", "dg_ev"}


def _norm_ldr_key(raw_key: str) -> str:
    return re.sub(r"[\s_\-]+", "", raw_key.strip().upper())


def _extract_floats(line: str) -> List[float]:
    cleaned = line.replace("D", "E").replace("d", "e")
    return [float(tok) for tok in _NUM_TOKEN_RE.findall(cleaned)]


def parse_jcamp_dx(filepath: str | Path) -> Dict[str, Any]:
    """
    Parse standard IUPAC JCAMP-DX `.jdx` / `.dx` spectrum files supporting both
    `(X++(Y..Y))` compressed/tabular abscissa rows and `(XY..XY)` point/peak tables.
    """
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"JCAMP-DX file not found: {p}")

    raw_bytes = p.read_bytes()
    text: Optional[str] = None
    for enc in ("utf-8-sig", "utf-8", "latin1"):
        try:
            text = raw_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw_bytes.decode("latin1", errors="ignore")

    headers: Dict[str, str] = {}
    data_mode: Optional[str] = None
    x_yy_rows: List[Tuple[float, List[float]]] = []
    xy_pair_nums: List[float] = []

    for raw_line in text.splitlines():
        line = raw_line.split("$$", 1)[0].strip()
        if not line:
            continue

        if line.startswith("##"):
            body = line[2:]
            if "=" in body:
                k_raw, v_raw = body.split("=", 1)
                key = _norm_ldr_key(k_raw)
                val = v_raw.strip()
            else:
                key = _norm_ldr_key(body)
                val = ""

            if key == "END":
                data_mode = None
                continue

            headers[key] = val
            val_up = val.upper().replace(" ", "")
            if key == "XYDATA":
                if "X++(Y..Y)" in val_up:
                    data_mode = "x_yy"
                else:
                    data_mode = "xy_pairs"
            elif key in ("XYPOINTS", "PEAKTABLE"):
                data_mode = "xy_pairs"
            else:
                data_mode = None
            continue

        if data_mode == "x_yy":
            nums = _extract_floats(line)
            if len(nums) >= 2:
                x_yy_rows.append((nums[0], nums[1:]))
        elif data_mode == "xy_pairs":
            nums = _extract_floats(line)
            if nums:
                xy_pair_nums.extend(nums)

    xfactor = float(headers.get("XFACTOR", "1.0") or 1.0)
    yfactor = float(headers.get("YFACTOR", "1.0") or 1.0)
    first_x = float(headers["FIRSTX"]) if "FIRSTX" in headers and headers["FIRSTX"] else None
    last_x = float(headers["LASTX"]) if "LASTX" in headers and headers["LASTX"] else None
    n_pts_hdr = int(float(headers["NPOINTS"])) if "NPOINTS" in headers and headers["NPOINTS"] else None
    deltax_hdr = float(headers["DELTAX"]) if "DELTAX" in headers and headers["DELTAX"] else None

    if x_yy_rows:
        if first_x is not None and last_x is not None and n_pts_hdr is not None and n_pts_hdr > 1:
            dx_default = (last_x - first_x) / float(n_pts_hdr - 1)
        elif deltax_hdr is not None:
            dx_default = deltax_hdr
        elif len(x_yy_rows) >= 2 and len(x_yy_rows[0][1]) > 0:
            dx_default = ((x_yy_rows[1][0] - x_yy_rows[0][0]) * xfactor) / float(len(x_yy_rows[0][1]))
        else:
            dx_default = 1.0 * xfactor

        xs: List[float] = []
        ys: List[float] = []
        n_rows = len(x_yy_rows)
        for r_idx, (x_raw, y_list) in enumerate(x_yy_rows):
            x0 = x_raw * xfactor
            m_y = len(y_list)
            if r_idx + 1 < n_rows and m_y > 0:
                x_next = x_yy_rows[r_idx + 1][0] * xfactor
                dx_row = (x_next - x0) / float(m_y)
            else:
                dx_row = dx_default
            for j, y_raw in enumerate(y_list):
                xs.append(x0 + float(j) * dx_row)
                ys.append(y_raw * yfactor)

        x_arr = np.asarray(xs, dtype=float)
        y_arr = np.asarray(ys, dtype=float)
    elif len(xy_pair_nums) >= 2:
        n_even = (len(xy_pair_nums) // 2) * 2
        arr2 = np.asarray(xy_pair_nums[:n_even], dtype=float).reshape(-1, 2)
        x_arr = arr2[:, 0] * xfactor
        y_arr = arr2[:, 1] * yfactor
    else:
        raise ValueError(f"No valid numeric spectrum data found in JCAMP-DX file {p.name}.")

    title = headers.get("TITLE", p.stem)
    datatype = headers.get("DATATYPE", "SPECTRUM")
    xunits = headers.get("XUNITS", "")
    yunits = headers.get("YUNITS", "ARBITRARY UNITS")
    obs_freq = float(headers["OBSERVEFREQUENCY"]) if headers.get("OBSERVEFREQUENCY") else None

    dt_up = datatype.upper()
    xu_up = xunits.upper()
    if "NMR" in dt_up or "PPM" in xu_up:
        modality = "nmr_spectrum"
        rec_mode = "nmr_spectrum"
        if "HZ" in xu_up and obs_freq and obs_freq > 0.0:
            x_arr = x_arr / obs_freq
            xunits = "PPM"
    elif "INFRARED" in dt_up or "IR" in dt_up or "1/CM" in xu_up:
        modality = "ftir"
        rec_mode = "waterfall"
    elif "RAMAN" in dt_up:
        modality = "raman"
        rec_mode = "deconv"
    elif "UV" in dt_up or "NM" in xu_up:
        modality = "uv_vis"
        rec_mode = "dual_x_optical_spectrum"
    else:
        modality = "jcamp_dx"
        rec_mode = "waterfall"

    return {
        "pack_id": PACK_ID,
        "modality": modality,
        "recommended_mode": rec_mode,
        "file": str(p),
        "title": title,
        "data_type": datatype,
        "x_units": xunits,
        "y_units": yunits,
        "observe_frequency_mhz": obs_freq,
        "x": x_arr,
        "y": y_arr,
        "n_points": int(x_arr.size),
        "x_range": [float(np.min(x_arr)), float(np.max(x_arr))],
        "y_range": [float(np.min(y_arr)), float(np.max(y_arr))],
        "headers": headers,
    }


def _read_cols_fast(p: Path) -> Optional[List[str]]:
    ext = p.suffix.lower()
    try:
        if ext == ".csv":
            df0 = pd.read_csv(p, nrows=3)
        elif ext in (".tsv", ".txt"):
            df0 = pd.read_csv(p, sep="\t", nrows=3)
        elif ext == ".xlsx":
            df0 = pd.read_excel(p, nrows=3)
        else:
            return None
    except Exception:
        return None
    return [str(c).strip() for c in df0.columns]


def sniff_chem_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Sniff JCAMP-DX files (`.jdx`/`.dx`) or NMR / free-energy pathway tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext in (".jdx", ".dx", ".jcamp"):
        return {
            "pack_id": PACK_ID,
            "modality": "jcamp_dx",
            "recommended_mode": "nmr_spectrum",
            "extension": ext,
            "confidence": "high",
        }

    if ext in (".csv", ".tsv", ".xlsx") and p.exists() and p.is_file():
        cols = _read_cols_fast(p)
        if not cols:
            return None
        low_map = {c.lower().strip(): c for c in cols}
        low_set = set(low_map.keys())

        if (low_set & _NMR_X_COLS) and (low_set & _NMR_Y_COLS):
            return {
                "pack_id": PACK_ID,
                "modality": "nmr_spectrum",
                "recommended_mode": "nmr_spectrum",
                "extension": ext,
                "confidence": "high",
            }
        if (low_set & _FED_STEP_COLS) and (low_set & _FED_G_COLS):
            return {
                "pack_id": PACK_ID,
                "modality": "free_energy_pathway",
                "recommended_mode": "free_energy_diagram",
                "extension": ext,
                "confidence": "high",
            }

    return None


def parse_chem_file(filepath: str | Path) -> Dict[str, Any]:
    """Parse `.jdx`/`.dx` JCAMP-DX files or chemical NMR / free-energy tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext in (".jdx", ".dx", ".jcamp"):
        return parse_jcamp_dx(p)

    if not p.exists():
        raise FileNotFoundError(f"Chemistry file not found: {p}")
    sniff = sniff_chem_file(p)
    if ext == ".csv":
        df = pd.read_csv(p)
    elif ext in (".tsv", ".txt"):
        df = pd.read_csv(p, sep="\t")
    elif ext == ".xlsx":
        df = pd.read_excel(p)
    else:
        raise ValueError(f"Unsupported chem_catalysis file extension: {ext!r} ({p.name})")

    return {
        "pack_id": PACK_ID,
        "modality": sniff["modality"] if sniff else "chem_table",
        "recommended_mode": sniff["recommended_mode"] if sniff else "free_energy_diagram",
        "file": str(p),
        "n_rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "head_preview": df.head(5).to_dict(orient="records"),
    }


def validate_free_energy_pathway(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Validate free-energy diagram reaction coordinate monotonicity, pathway step-length
    consistency across catalysts, and transition-state (`ts`) saddle barrier heights.
    """
    findings: List[Dict[str, str]] = []
    pathways = payload.get("pathways") or payload.get("series") or []
    if isinstance(payload, dict) and ("energies" in payload or "delta_g" in payload) and not pathways:
        pathways = [payload]

    if not isinstance(pathways, list) or not pathways:
        return findings

    step_labels = payload.get("step_labels") or payload.get("steps")
    expected_len = len(step_labels) if isinstance(step_labels, list) and len(step_labels) > 0 else None
    seen_lengths: Dict[str, int] = {}

    for idx, pw in enumerate(pathways):
        if not isinstance(pw, dict):
            continue
        pw_name = str(pw.get("name") or f"Pathway_{idx + 1}")
        g_vals = pw.get("energies") if pw.get("energies") is not None else pw.get("y")
        if g_vals is None:
            g_vals = pw.get("delta_g")
        if g_vals is None:
            continue

        g_arr = np.asarray(g_vals, dtype=float).ravel()
        if not np.all(np.isfinite(g_arr)) or g_arr.size < 2:
            findings.append(
                {
                    "level": "ERROR_INVALID_PATHWAY_ENERGIES",
                    "region": pw_name,
                    "detail": f"Pathway '{pw_name}' requires >= 2 finite free-energy values.",
                }
            )
            continue

        rc = pw.get("reaction_coord") if pw.get("reaction_coord") is not None else pw.get("x")
        if rc is not None:
            rc_arr = np.asarray(rc, dtype=float).ravel()
            if rc_arr.size != g_arr.size:
                findings.append(
                    {
                        "level": "ERROR_PATHWAY_STEP_MISMATCH",
                        "region": pw_name,
                        "detail": (
                            f"Pathway '{pw_name}' reaction_coord length ({rc_arr.size}) does not match "
                            f"energies length ({g_arr.size})."
                        ),
                    }
                )
            elif np.any(np.diff(rc_arr) <= 0.0):
                findings.append(
                    {
                        "level": "ERROR_NON_MONOTONIC_REACTION_COORD",
                        "region": pw_name,
                        "detail": f"Pathway '{pw_name}' reaction coordinates must be strictly increasing.",
                    }
                )
        else:
            seen_lengths[pw_name] = int(g_arr.size)

        if expected_len is not None and int(g_arr.size) != expected_len:
            findings.append(
                {
                    "level": "ERROR_PATHWAY_STEP_MISMATCH",
                    "region": pw_name,
                    "detail": (
                        f"Pathway '{pw_name}' has {g_arr.size} energy steps, expected {expected_len} "
                        "to match step_labels."
                    ),
                }
            )

        ts_list = pw.get("ts") or []
        if isinstance(ts_list, list):
            for ts_item in ts_list:
                if not isinstance(ts_item, dict):
                    continue
                s_from = int(ts_item.get("step_from", -1))
                s_to = int(ts_item.get("step_to", -1))
                g_ts = ts_item.get("g_ts")
                if not (0 <= s_from < g_arr.size and 0 <= s_to < g_arr.size and s_to == s_from + 1):
                    findings.append(
                        {
                            "level": "ERROR_INVALID_TS_STEP_INDEX",
                            "region": pw_name,
                            "detail": (
                                f"Transition state on '{pw_name}' has invalid adjacent step indices "
                                f"({s_from} -> {s_to}) for {g_arr.size} steps."
                            ),
                        }
                    )
                elif g_ts is not None and math.isfinite(float(g_ts)):
                    g_max_adj = max(float(g_arr[s_from]), float(g_arr[s_to]))
                    if float(g_ts) < g_max_adj - 1e-9:
                        findings.append(
                            {
                                "level": "WARN_SUBMERGED_TS_BARRIER",
                                "region": pw_name,
                                "detail": (
                                    f"Transition state '{ts_item.get('label', 'TS')}' on '{pw_name}' has "
                                    f"G_TS = {float(g_ts):.3f} eV below adjacent intermediate ({g_max_adj:.3f} eV)."
                                ),
                            }
                        )

    if len(set(seen_lengths.values())) > 1:
        detail_str = ", ".join(f"{k}:{v}" for k, v in seen_lengths.items())
        findings.append(
            {
                "level": "ERROR_PATHWAY_STEP_MISMATCH",
                "region": "Free_Energy_Pathways",
                "detail": f"Inconsistent step counts across pathways without explicit reaction coordinates ({detail_str}).",
            }
        )

    return findings


def validate_chem_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate chemical spectroscopy or free-energy pathway payloads."""
    findings = validate_free_energy_pathway(payload)
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
    "parse_jcamp_dx",
    "validate_free_energy_pathway",
    "sniff_chem_file",
    "parse_chem_file",
    "validate_chem_payload",
]
