from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter

from parsers import (
    _load_xls_sheets_via_xlrd_or_bridge,
    _read_text_auto,
    parse_ftir,
    parse_xps_avantage,
    parse_xrd,
    parse_xy_text,
)


_SAMPLE_COLON_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,8}\s*[:：]\s*")
_SAMPLE_BATCH_PREFIX_RE = re.compile(r"^batch\d+[_-]\s*", re.IGNORECASE)


def _dedup_stripped_columns(raw_cols: Sequence[Any]) -> List[str]:
    """Strip leading/trailing whitespace from column names while keeping names unique."""
    cleaned: List[str] = []
    seen: Dict[str, int] = {}
    for idx, c in enumerate(raw_cols):
        if c is None or (isinstance(c, float) and np.isnan(c)):
            base = f"Unnamed: {idx}"
        else:
            s = str(c).strip()
            base = s if s else f"Unnamed: {idx}"
        if base in seen:
            seen[base] += 1
            cleaned.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 0
            cleaned.append(base)
    return cleaned


def _drop_empty_unnamed_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop columns that are both auto-named `Unnamed:*` and 100% NaN/empty."""
    keep_cols: List[Any] = []
    for col in df.columns:
        col_str = str(col)
        if col_str.startswith("Unnamed:"):
            s = df[col]
            is_all_empty = bool(s.isna().all() or s.astype(str).str.strip().replace("nan", "").eq("").all())
            if is_all_empty:
                continue
        keep_cols.append(col)
    return df.loc[:, keep_cols]


def load_tabular_sheet(
    file_path: str | Path,
    sheet: int | str = 0,
    header_row: Optional[int] = 0,
) -> pd.DataFrame:
    """
    Robustly load `.xlsx` / `.xlsm` / `.xls` / `.csv` / `.tsv` / `.txt` into a clean DataFrame
    with leading/trailing whitespace stripped from column names.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Tabular file not found: {p}")

    ext = p.suffix.lower()

    if ext in (".xlsx", ".xlsm"):
        import openpyxl

        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            sheet_names = list(wb.sheetnames)
        finally:
            wb.close()

        if isinstance(sheet, int):
            if sheet < 0 or sheet >= len(sheet_names):
                raise IndexError(f"Sheet index {sheet} out of range for {p.name} (sheets: {sheet_names})")
            target_sheet: int | str = sheet_names[sheet]
        else:
            s_req = str(sheet).strip()
            if sheet in sheet_names:
                target_sheet = sheet
            elif s_req in sheet_names:
                target_sheet = s_req
            else:
                matched = next((sn for sn in sheet_names if sn.strip().lower() == s_req.lower()), None)
                if matched is None:
                    raise KeyError(f"Sheet '{sheet}' not found in {p.name}; available sheets: {sheet_names}")
                target_sheet = matched

        df = pd.read_excel(p, sheet_name=target_sheet, header=header_row, engine="openpyxl")

    elif ext == ".xls":
        try:
            df = pd.read_excel(p, sheet_name=sheet, header=header_row)
        except ImportError:
            sheets_map = _load_xls_sheets_via_xlrd_or_bridge(p)
            sheet_names = list(sheets_map.keys())
            if isinstance(sheet, int):
                if sheet < 0 or sheet >= len(sheet_names):
                    raise IndexError(f"Sheet index {sheet} out of range for {p.name} (sheets: {sheet_names})")
                rows = sheets_map[sheet_names[sheet]]
            else:
                s_req = str(sheet).strip()
                matched = next(
                    (sn for sn in sheet_names if sn == sheet or sn.strip().lower() == s_req.lower()),
                    None,
                )
                if matched is None:
                    raise KeyError(f"Sheet '{sheet}' not found in {p.name}; available sheets: {sheet_names}")
                rows = sheets_map[matched]

            if not rows:
                return pd.DataFrame()
            if header_row is None:
                df = pd.DataFrame(rows)
            else:
                if header_row < 0 or header_row >= len(rows):
                    raise IndexError(f"header_row={header_row} out of range for {p.name} (nrows={len(rows)})")
                hdr = _dedup_stripped_columns(rows[header_row])
                body = rows[header_row + 1 :]
                df = pd.DataFrame(body, columns=hdr)
                df.replace("", np.nan, inplace=True)

    elif ext == ".csv":
        txt = _read_text_auto(p)
        df = pd.read_csv(io.StringIO(txt), header=header_row, low_memory=False)

    elif ext == ".tsv":
        txt = _read_text_auto(p)
        df = pd.read_csv(io.StringIO(txt), sep="\t", header=header_row, low_memory=False)

    elif ext in (".txt", ".dat"):
        txt = _read_text_auto(p)
        first_nonempty = next((ln for ln in txt.splitlines() if ln.strip()), "")
        sep = "\t" if "\t" in first_nonempty else r"\s+|,|;"
        eng = "c" if sep == "\t" else "python"
        df = pd.read_csv(io.StringIO(txt), sep=sep, header=header_row, engine=eng)

    else:
        raise ValueError(f"Unsupported tabular file extension '{ext}' for {p}")

    df = df.dropna(how="all").reset_index(drop=True)
    if header_row is not None and len(df.columns) > 0:
        df.columns = _dedup_stripped_columns(list(df.columns))
        df = _drop_empty_unnamed_columns(df)

    return df


def _resolve_col_name(df: pd.DataFrame, col_ref: int | str) -> Any:
    """Resolve column reference by integer positional index or exact/stripped string name."""
    if isinstance(col_ref, (int, np.integer)) and not isinstance(col_ref, bool):
        idx = int(col_ref)
        if idx < 0 or idx >= len(df.columns):
            raise IndexError(f"Column index {idx} out of bounds for DataFrame with {len(df.columns)} columns.")
        return df.columns[idx]

    target = str(col_ref).strip()
    if col_ref in df.columns:
        return col_ref
    if target in df.columns:
        return target
    for c in df.columns:
        if str(c).strip().lower() == target.lower():
            return c
    raise KeyError(f"Column '{col_ref}' not found in DataFrame columns: {list(df.columns)}")


def _clean_category_label(raw_label: Any, clean_sample_prefix: bool = True) -> str:
    s = str(raw_label).strip()
    if not clean_sample_prefix:
        return s
    s = _SAMPLE_BATCH_PREFIX_RE.sub("", s)
    s = _SAMPLE_COLON_PREFIX_RE.sub("", s)
    return s.strip()


def extract_table_series(
    df: pd.DataFrame,
    x_col: int | str,
    series_specs: Sequence[Union[Dict[str, Any], str, int]],
    sample_filter: Optional[Union[Dict[str, Any], Sequence[Any], Callable[[pd.Series], bool]]] = None,
    label_map: Optional[Dict[str, str]] = None,
    normalize_100: bool = False,
    clean_sample_prefix: bool = True,
) -> Dict[str, Any]:
    """
    Extract categorical labels (`categories`) and multi-series numeric values + optional errors (`y_err`)
    from a wide summary sheet or multi-replicate long table.

    - Supports `x_col` and series columns by name or integer index.
    - Strips redundant prefixes (`A: `, `B: `, `batch1_`) when `clean_sample_prefix=True`.
    - Auto-aggregates replicate rows per category into Mean ± SD (`ddof=1`) when duplicate category rows exist.
    - Safely normalizes non-negative row compositions to `0–100%` when `normalize_100=True`, raising `ValueError`
      explicitly on negative entries or zero-sum rows.
    """
    if df is None or df.empty:
        raise ValueError("Input DataFrame is empty.")
    if not series_specs:
        raise ValueError("series_specs must contain at least one series specification.")

    work = df.copy()
    x_name = _resolve_col_name(work, x_col)

    # Filter out blank category rows
    valid_x = work[x_name].notna() & (work[x_name].astype(str).str.strip() != "")
    work = work.loc[valid_x].copy()

    # Apply optional sample_filter
    ordered_cat_whitelist: Optional[List[str]] = None
    if sample_filter is not None:
        if callable(sample_filter):
            mask = work.apply(sample_filter, axis=1)
            work = work.loc[mask].copy()
        elif isinstance(sample_filter, dict):
            for fk, fv in sample_filter.items():
                fcol = _resolve_col_name(work, fk)
                col_str = work[fcol].astype(str).str.strip()
                if isinstance(fv, (list, tuple, set)):
                    allowed = {str(item).strip() for item in fv}
                    work = work.loc[work[fcol].isin(fv) | col_str.isin(allowed)].copy()
                else:
                    work = work.loc[(work[fcol] == fv) | (col_str == str(fv).strip())].copy()
        elif isinstance(sample_filter, (list, tuple, set)):
            raw_strs = work[x_name].astype(str).str.strip()
            clean_strs = raw_strs.map(lambda v: _clean_category_label(v, clean_sample_prefix=clean_sample_prefix))
            allowed_list = [str(item).strip() for item in sample_filter]
            allowed_set = set(allowed_list)
            work = work.loc[raw_strs.isin(allowed_set) | clean_strs.isin(allowed_set)].copy()
            if isinstance(sample_filter, (list, tuple)):
                ordered_cat_whitelist = allowed_list
        else:
            raise TypeError(f"Unsupported sample_filter type: {type(sample_filter)}")

    if work.empty:
        raise ValueError("No rows left after applying sample_filter.")

    # Normalize series_specs to canonical dicts
    parsed_specs: List[Dict[str, Any]] = []
    for sp in series_specs:
        if isinstance(sp, (str, int, np.integer)) and not isinstance(sp, bool):
            col_resolved = _resolve_col_name(work, sp)
            parsed_specs.append(
                {
                    "name": str(col_resolved).strip(),
                    "y_col": col_resolved,
                    "err_col": None,
                    "role": None,
                    "axis": "y1",
                    "unit": None,
                    "scale": 1.0,
                }
            )
        elif isinstance(sp, dict):
            y_ref = sp.get("y_col", sp.get("col", sp.get("column", sp.get("value_col"))))
            if y_ref is None:
                raise KeyError(f"Series spec dict missing 'y_col' / 'col': {sp}")
            col_resolved = _resolve_col_name(work, y_ref)
            err_ref = sp.get("y_err", sp.get("err_col", sp.get("error_col")))
            err_resolved = _resolve_col_name(work, err_ref) if err_ref is not None else None
            parsed_specs.append(
                {
                    "name": str(sp.get("name") or sp.get("label") or col_resolved).strip(),
                    "y_col": col_resolved,
                    "err_col": err_resolved,
                    "role": sp.get("role"),
                    "axis": str(sp.get("axis", "y1")),
                    "unit": sp.get("unit"),
                    "scale": float(sp.get("scale", sp.get("multiplier", 1.0))),
                }
            )
        else:
            raise TypeError(f"Unsupported item in series_specs: {sp!r}")

    raw_cat_col = work[x_name].astype(str).str.strip()
    work["_raw_cat_key_"] = raw_cat_col

    # Optional explicit category ordering when sample_filter was passed as a list/tuple
    if ordered_cat_whitelist is not None:
        order_lookup = {k: i for i, k in enumerate(ordered_cat_whitelist)}

        def _cat_rank(val: str) -> int:
            if val in order_lookup:
                return order_lookup[val]
            cleaned_v = _clean_category_label(val, clean_sample_prefix=clean_sample_prefix)
            return order_lookup.get(cleaned_v, len(order_lookup))

        work["_cat_sort_rank_"] = work["_raw_cat_key_"].map(_cat_rank)
        work = work.sort_values("_cat_sort_rank_", kind="mergesort").drop(columns=["_cat_sort_rank_"])

    unique_raw_cats = list(dict.fromkeys(work["_raw_cat_key_"].tolist()))
    has_replicates = len(work) > len(unique_raw_cats)

    n_cats = len(unique_raw_cats)
    n_series = len(parsed_specs)
    values_mat = np.zeros((n_cats, n_series), dtype=float)
    errors_list: List[Optional[np.ndarray]] = [None] * n_series
    n_replicates: List[int] = []

    if has_replicates:
        grouped = work.groupby("_raw_cat_key_", sort=False)
        for c_idx, cat_key in enumerate(unique_raw_cats):
            grp = grouped.get_group(cat_key)
            n_rep = len(grp)
            n_replicates.append(int(n_rep))
            for s_idx, psp in enumerate(parsed_specs):
                vals = pd.to_numeric(grp[psp["y_col"]], errors="coerce").to_numpy(dtype=float) * psp["scale"]
                finite_vals = vals[np.isfinite(vals)]
                if len(finite_vals) == 0:
                    raise ValueError(
                        f"All replicate values are non-numeric/NaN for category '{cat_key}', column '{psp['y_col']}'."
                    )
                values_mat[c_idx, s_idx] = float(np.mean(finite_vals))
                if errors_list[s_idx] is None:
                    errors_list[s_idx] = np.zeros(n_cats, dtype=float)
                if psp["err_col"] is not None:
                    errs = pd.to_numeric(grp[psp["err_col"]], errors="coerce").to_numpy(dtype=float) * abs(psp["scale"])
                    f_errs = errs[np.isfinite(errs)]
                    if len(f_errs) > 0:
                        errors_list[s_idx][c_idx] = float(np.sqrt(np.mean(f_errs**2)))
                    else:
                        errors_list[s_idx][c_idx] = float(np.std(finite_vals, ddof=1)) if len(finite_vals) > 1 else 0.0
                else:
                    errors_list[s_idx][c_idx] = float(np.std(finite_vals, ddof=1)) if len(finite_vals) > 1 else 0.0
    else:
        n_replicates = [1] * n_cats
        for s_idx, psp in enumerate(parsed_specs):
            vals = pd.to_numeric(work[psp["y_col"]], errors="coerce").to_numpy(dtype=float) * psp["scale"]
            if not np.all(np.isfinite(vals)):
                bad_idx = int(np.where(~np.isfinite(vals))[0][0])
                raise ValueError(
                    f"Non-numeric or NaN value at category '{unique_raw_cats[bad_idx]}' in column '{psp['y_col']}'."
                )
            values_mat[:, s_idx] = vals
            if psp["err_col"] is not None:
                errs = pd.to_numeric(work[psp["err_col"]], errors="coerce").to_numpy(dtype=float) * abs(psp["scale"])
                errs = np.where(np.isfinite(errs), errs, 0.0)
                errors_list[s_idx] = errs

    # Build final display categories
    categories: List[str] = []
    for raw_c in unique_raw_cats:
        cleaned_c = _clean_category_label(raw_c, clean_sample_prefix=clean_sample_prefix)
        if label_map:
            if raw_c in label_map:
                categories.append(str(label_map[raw_c]))
                continue
            if cleaned_c in label_map:
                categories.append(str(label_map[cleaned_c]))
                continue
        categories.append(cleaned_c)

    # Optional 0-100% row-wise positive normalization
    if normalize_100:
        if not np.all(np.isfinite(values_mat)):
            raise ValueError("Cannot apply normalize_100=True: matrix contains NaN or infinite values.")
        if np.any(values_mat < -1e-9):
            neg_r, neg_c = np.argwhere(values_mat < -1e-9)[0]
            raise ValueError(
                f"Cannot apply normalize_100=True: negative value ({values_mat[neg_r, neg_c]:.6g}) "
                f"at category '{categories[int(neg_r)]}', series '{parsed_specs[int(neg_c)]['name']}'."
            )
        values_mat = np.maximum(values_mat, 0.0)
        row_sums = np.sum(values_mat, axis=1)
        zero_rows = np.where((~np.isfinite(row_sums)) | (row_sums <= 0.0))[0]
        if len(zero_rows) > 0:
            bad_cats = [categories[int(i)] for i in zero_rows]
            raise ValueError(
                f"Cannot apply normalize_100=True: zero-sum row(s) encountered for categories {bad_cats}."
            )
        scale_factors = 100.0 / row_sums
        values_mat = values_mat * scale_factors[:, None]
        for s_idx in range(n_series):
            if errors_list[s_idx] is not None:
                errors_list[s_idx] = errors_list[s_idx] * scale_factors

    # Assemble output series & tidy DataFrame
    out_series: List[Dict[str, Any]] = []
    out_cols: Dict[str, Any] = {str(x_name): categories}
    if has_replicates:
        out_cols["n_replicates"] = n_replicates

    for s_idx, psp in enumerate(parsed_specs):
        s_name = psp["name"]
        s_vals = values_mat[:, s_idx].copy()
        s_errs = errors_list[s_idx].copy() if errors_list[s_idx] is not None else None
        s_unit = "%" if (normalize_100 and psp["unit"] is None) else psp["unit"]
        out_series.append(
            {
                "name": s_name,
                "col_name": str(psp["y_col"]),
                "values": s_vals,
                "errors": s_errs,
                "role": psp["role"],
                "axis": psp["axis"],
                "unit": s_unit,
            }
        )
        out_cols[s_name] = s_vals
        if s_errs is not None:
            out_cols[f"{s_name}_SD"] = s_errs

    return {
        "categories": categories,
        "raw_categories": unique_raw_cats,
        "x_col_name": str(x_name),
        "series": out_series,
        "normalize_100": bool(normalize_100),
        "aggregated_from_replicates": bool(has_replicates),
        "n_replicates": n_replicates,
        "table_df": pd.DataFrame(out_cols),
    }


def compute_dq_dv(
    voltage: Sequence[float] | np.ndarray,
    capacity: Sequence[float] | np.ndarray,
    smooth_window: int = 11,
    polyorder: int = 2,
    min_dv: float = 1e-3,
) -> Dict[str, Any]:
    """
    Robustly compute differential capacity `dQ/dV` for galvanostatic charge/discharge curves:
    1. Bin/deduplicate voltage steps smaller than `min_dv` to suppress `dV -> 0` ADC quantization spikes.
    2. Interpolate `Q(V)` onto a monotonic uniform voltage grid (`dv_step >= min_dv`).
    3. Differentiate via Savitzky-Golay filter (`deriv=1`) and locate prominent plateau peak voltages.
    """
    v_in = np.asarray(voltage, dtype=float).ravel()
    q_in = np.asarray(capacity, dtype=float).ravel()
    if len(v_in) != len(q_in):
        raise ValueError(f"voltage ({len(v_in)}) and capacity ({len(q_in)}) must have identical length.")

    valid = np.isfinite(v_in) & np.isfinite(q_in)
    v_raw = v_in[valid]
    q_raw = q_in[valid]
    if len(v_raw) < 5:
        raise ValueError(f"Insufficient finite (voltage, capacity) points ({len(v_raw)}) for dQ/dV.")
    if min_dv <= 0:
        raise ValueError(f"min_dv must be positive, got {min_dv}.")

    v_min = float(np.min(v_raw))
    v_max = float(np.max(v_raw))
    v_span = v_max - v_min
    if v_span < max(float(min_dv) * 3.0, 1e-5):
        raise ValueError(
            f"Voltage span ({v_span:.6g} V) is too narrow relative to min_dv ({min_dv:.6g} V) to compute dQ/dV."
        )

    sweep_direction = "charge" if float(v_raw[-1] - v_raw[0]) >= 0.0 else "discharge"

    # Bin along voltage with width `min_dv` to merge constant-voltage / ADC-jitter duplicates cleanly
    bin_idx = np.floor((v_raw - v_min) / float(min_dv)).astype(np.int64)
    df_vq = pd.DataFrame({"bin": bin_idx, "v": v_raw, "q": q_raw})
    agg_vq = df_vq.groupby("bin", sort=True)[["v", "q"]].mean().reset_index(drop=True)
    v_binned = agg_vq["v"].to_numpy(dtype=float)
    q_binned = agg_vq["q"].to_numpy(dtype=float)

    # Ensure strict ascending V and spacing >= min_dv on binned anchors
    order = np.argsort(v_binned)
    v_binned = v_binned[order]
    q_binned = q_binned[order]

    keep_idx = [0]
    for k in range(1, len(v_binned)):
        if v_binned[k] - v_binned[keep_idx[-1]] >= 0.5 * float(min_dv):
            keep_idx.append(k)
    v_mono = v_binned[keep_idx]
    q_mono = q_binned[keep_idx]

    if len(v_mono) < 5:
        raise ValueError(f"Fewer than 5 distinct monotonic voltage bins ({len(v_mono)}) at min_dv={min_dv} V.")

    # Uniform voltage grid with step >= min_dv and never denser than distinct binned anchors
    max_bins_by_min_dv = int(np.floor((v_mono[-1] - v_mono[0]) / float(min_dv))) + 1
    n_grid = min(len(v_mono), max_bins_by_min_dv)
    n_grid = max(n_grid, 5)
    v_grid = np.linspace(float(v_mono[0]), float(v_mono[-1]), n_grid)
    dv_step = float(v_grid[1] - v_grid[0])
    q_grid = np.interp(v_grid, v_mono, q_mono)

    # Validate Savitzky-Golay window & polyorder
    poly = max(1, int(polyorder))
    win = max(int(smooth_window), poly + 2)
    if win % 2 == 0:
        win += 1
    if win > n_grid:
        win = n_grid if (n_grid % 2 == 1) else (n_grid - 1)
    if win <= poly:
        poly = max(1, win - 2)

    dq_dv = savgol_filter(q_grid, window_length=win, polyorder=poly, deriv=1, delta=dv_step, mode="interp")
    abs_dq_dv = np.abs(dq_dv)

    # Peak detection across both anodic (+dQ/dV) and cathodic (-dQ/dV) peaks
    max_mag = float(np.max(abs_dq_dv)) if len(abs_dq_dv) else 0.0
    peaks_detail: List[Dict[str, Any]] = []
    if max_mag > 0:
        min_dist = max(1, int(round(0.015 / max(dv_step, 1e-6))))  # >= ~15 mV separation
        prom_thresh = 0.08 * max_mag

        pos_pks, pos_props = find_peaks(dq_dv, height=prom_thresh, prominence=prom_thresh, distance=min_dist)
        for pk_i, prom in zip(pos_pks, pos_props["prominences"]):
            peaks_detail.append(
                {
                    "voltage_v": float(v_grid[pk_i]),
                    "dq_dv": float(dq_dv[pk_i]),
                    "polarity": "anodic",
                    "prominence": float(prom),
                }
            )

        neg_pks, neg_props = find_peaks(-dq_dv, height=prom_thresh, prominence=prom_thresh, distance=min_dist)
        for pk_i, prom in zip(neg_pks, neg_props["prominences"]):
            peaks_detail.append(
                {
                    "voltage_v": float(v_grid[pk_i]),
                    "dq_dv": float(dq_dv[pk_i]),
                    "polarity": "cathodic",
                    "prominence": float(prom),
                }
            )

        peaks_detail.sort(key=lambda d: d["prominence"], reverse=True)

    peak_positions = [round(d["voltage_v"], 5) for d in peaks_detail]

    return {
        "voltage_v": v_grid,
        "dq_dv": dq_dv,
        "abs_dq_dv": abs_dq_dv,
        "q_interp": q_grid,
        "peak_positions": peak_positions,
        "peaks_detail": peaks_detail,
        "sweep_direction": sweep_direction,
        "dv_step_v": dv_step,
        "smooth_window_used": win,
    }


def align_and_decompose_pulse(
    time_s: Sequence[float] | np.ndarray,
    voltage_v: Sequence[float] | np.ndarray,
    t_pulse_start: Optional[float] = None,
    t_pulse_end: Optional[float] = None,
    pre_window_s: float = 1.0,
) -> Dict[str, Any]:
    """
    Zero-align short high-rate pulse transient (`t_aligned = time_s - t_pulse_start`) and decompose
    apparent ohmic/instantaneous drop (`delta_v0_app`) vs intra-pulse slow polarization (`delta_v_slow_app`),
    returning scalar metrics plus Chart-Grammar-ready horizontal dashed guides and double-ended span annotations.
    """
    t_in = np.asarray(time_s, dtype=float).ravel()
    v_in = np.asarray(voltage_v, dtype=float).ravel()
    if len(t_in) != len(v_in):
        raise ValueError(f"time_s ({len(t_in)}) and voltage_v ({len(v_in)}) must have identical length.")

    valid = np.isfinite(t_in) & np.isfinite(v_in)
    t = t_in[valid]
    v = v_in[valid]
    if len(t) < 4:
        raise ValueError(f"Insufficient finite (time_s, voltage_v) points ({len(t)}) for pulse decomposition.")

    order = np.argsort(t, kind="mergesort")
    t = t[order]
    v = v[order]

    dt = np.diff(t)
    pos_dts = dt[dt > 1e-6]
    dt_floor = max(0.5 * float(np.median(pos_dts)) if len(pos_dts) > 0 else 1e-3, 1e-6)
    dt_safe = np.maximum(dt, dt_floor)
    dv = np.diff(v)
    dv_dt = dv / dt_safe

    # 1. Locate & verify pulse onset (`idx_before` & `t_start`)
    if t_pulse_start is None:
        idx_drop = int(np.argmin(dv_dt))
        total_v_range = float(np.max(v) - np.min(v))
        med_abs_rate = float(np.median(np.abs(dv_dt))) + 1e-9
        # Verify genuine negative voltage drop edge
        post_drop_amp = float(v[idx_drop] - np.min(v[idx_drop + 1 :]))
        if dv[idx_drop] >= 0.0 or post_drop_amp < max(1e-3, 0.02 * total_v_range):
            raise ValueError(
                "Auto-detection failed to find a valid negative pulse onset edge in voltage_v."
            )
        if abs(dv_dt[idx_drop]) < 2.0 * med_abs_rate and len(dv_dt) > 10:
            raise ValueError(
                f"Steepest negative dV/dt ({dv_dt[idx_drop]:.4g} V/s) is indistinguishable from baseline slope "
                f"(median |dV/dt|={med_abs_rate:.4g} V/s); pass explicit t_pulse_start."
            )
        idx_before = idx_drop
        t_start = float(t[idx_before])
    else:
        t_start = float(t_pulse_start)
        if t_start < float(t[0]) - 1e-6 or t_start > float(t[-1]) + 1e-6:
            raise ValueError(
                f"t_pulse_start={t_start} lies outside time_s range [{t[0]:.4g}, {t[-1]:.4g}]."
            )
        le_idxs = np.where(t <= t_start + 1e-9)[0]
        if len(le_idxs) == 0:
            idx_before = 0
        else:
            cand = int(le_idxs[-1])
            # If the sample at t_start already experienced the steep drop relative to cand-1, step back 1 sample
            if cand > 0 and (v[cand - 1] - v[cand]) > 0.25 * max(float(v[0] - np.min(v)), 1e-6):
                idx_before = cand - 1
            else:
                idx_before = cand
        # Find local steepest drop near idx_before for instant-edge tracking
        win_lo = max(0, idx_before - 1)
        win_hi = min(len(dv_dt), idx_before + 5)
        idx_drop = win_lo + int(np.argmin(dv_dt[win_lo:win_hi])) if win_hi > win_lo else max(0, len(dv_dt) - 1)

    if idx_before >= len(v) - 1:
        raise ValueError("Pulse start occurs at the very last sample; no loaded pulse points available.")

    # 2. Walk across instantaneous ohmic vertical edge (handles both ~20Hz single-step & >=1kHz multi-ms edge)
    peak_neg_slope = float(dv_dt[idx_drop])
    idx_instant = idx_before + 1
    if peak_neg_slope < 0:
        while (
            idx_instant < len(v) - 1
            and (t[idx_instant + 1] - t_start) <= 0.10
            and dv_dt[idx_instant] <= 0.20 * peak_neg_slope
        ):
            idx_instant += 1

    # 3. Locate `idx_pulse_end` (end of loaded pulse prior to rest/background recovery)
    if t_pulse_end is not None:
        t_end_req = float(t_pulse_end)
        if t_end_req <= t_start:
            raise ValueError(f"t_pulse_end ({t_end_req}) must be greater than t_pulse_start ({t_start}).")
        end_cands = np.where(t <= t_end_req + 1e-9)[0]
        idx_pulse_end = int(end_cands[-1]) if len(end_cands) > 0 else len(v) - 1
        # Guard if exact t_end_req sample already jumped up into recovery
        if idx_pulse_end > idx_instant and (v[idx_pulse_end] - v[idx_pulse_end - 1]) > 0.15 * max(
            float(v[idx_before] - np.min(v[idx_instant : idx_pulse_end + 1])), 1e-6
        ):
            idx_pulse_end -= 1
    else:
        rem_dv_dt = dv_dt[idx_instant:]
        min_v_after = float(np.min(v[idx_instant:]))
        total_drop_est = max(float(v[idx_before] - min_v_after), 1e-6)
        if len(rem_dv_dt) > 0:
            rel_rec = int(np.argmax(rem_dv_dt))
            cand_end = idx_instant + rel_rec
            rec_jump = float(v[min(len(v) - 1, cand_end + 2)] - v[cand_end])
            if dv[cand_end] > 0.02 * total_drop_est or rec_jump > 0.05 * total_drop_est:
                idx_pulse_end = cand_end
            else:
                idx_pulse_end = idx_instant + int(np.argmin(v[idx_instant:]))
        else:
            idx_pulse_end = len(v) - 1

    idx_pulse_end = max(idx_instant, min(idx_pulse_end, len(v) - 1))

    # 4. Compute aligned time, windowed slice, and characteristic voltage decomposition
    t_aligned = t - t_start
    pre_w = max(0.0, float(pre_window_s))
    win_mask = t_aligned >= (-pre_w - 1e-9)

    v_before = float(v[idx_before])
    v_instant = float(v[idx_instant])
    v_pulse_end = float(v[idx_pulse_end])
    v_final = float(v[-1])

    delta_v0_app = float(v_before - v_instant)
    delta_v_slow_app = float(v_instant - v_pulse_end)
    delta_v_total_app = float(v_before - v_pulse_end)
    has_recovery = bool(idx_pulse_end < len(v) - 1 and (v_final - v_pulse_end) > 1e-3)
    delta_v_rec_app = float(v_final - v_pulse_end)

    t_inst_aligned = float(t_aligned[idx_instant])
    t_end_aligned = float(t_aligned[idx_pulse_end])

    # 5. Build Chart-Grammar-ready horizontal dashed guides & double-headed span annotations
    horizontal_guides: List[Dict[str, Any]] = [
        {
            "kind": "hline",
            "orientation": "horizontal",
            "value": v_before,
            "y": v_before,
            "label": "V_before",
            "display_label": f"V_before ({v_before:.3f} V)",
            "linestyle": "dashed",
            "role": "baseline",
            "color": "#111111",
        },
        {
            "kind": "hline",
            "orientation": "horizontal",
            "value": v_instant,
            "y": v_instant,
            "label": "V_instant",
            "display_label": f"V_instant ({v_instant:.3f} V)",
            "linestyle": "dashed",
            "role": "control",
            "color": "#3E86DE",
        },
        {
            "kind": "hline",
            "orientation": "horizontal",
            "value": v_pulse_end,
            "y": v_pulse_end,
            "label": "V_pulse_end",
            "display_label": f"V_pulse_end ({v_pulse_end:.3f} V)",
            "linestyle": "dashed",
            "role": "pulse",
            "color": "#A02333",
        },
    ]
    if has_recovery:
        horizontal_guides.append(
            {
                "kind": "hline",
                "orientation": "horizontal",
                "value": v_final,
                "y": v_final,
                "label": "V_final",
                "display_label": f"V_final ({v_final:.3f} V)",
                "linestyle": "dashed",
                "role": "recovery",
                "color": "#6579BE",
            }
        )

    t_span_vis = max(t_end_aligned, 1.0)
    x_v0_arrow = min(max(0.11, t_inst_aligned + 0.10), 0.18 * t_span_vis)
    x_vslow_arrow = max(x_v0_arrow + 0.85, t_end_aligned - 0.16)

    span_annotations: List[Dict[str, Any]] = [
        {
            "kind": "vspan_arrow",
            "name": "delta_v0_app",
            "label": f"ΔV0,app = {delta_v0_app:.3f} V",
            "origin_label": "\\g(D)V\\-(0,app)",
            "x": x_v0_arrow,
            "y_start": v_instant,
            "y_end": v_before,
            "y_low": min(v_instant, v_before),
            "y_high": max(v_instant, v_before),
            "delta_v": delta_v0_app,
            "role": "control",
            "color": "#2B6CB0",
            "arrow_style": "double_headed_bar",
        },
        {
            "kind": "vspan_arrow",
            "name": "delta_v_slow_app",
            "label": f"ΔVslow,app = {delta_v_slow_app:.3f} V",
            "origin_label": "\\g(D)V\\-(slow,app)",
            "x": x_vslow_arrow,
            "y_start": v_pulse_end,
            "y_end": v_instant,
            "y_low": min(v_pulse_end, v_instant),
            "y_high": max(v_pulse_end, v_instant),
            "delta_v": delta_v_slow_app,
            "role": "pulse",
            "color": "#A02333",
            "arrow_style": "double_headed_bar",
        },
    ]

    return {
        "t_aligned": t_aligned,
        "voltage_v": v,
        "t_windowed": t_aligned[win_mask],
        "v_windowed": v[win_mask],
        "t_pulse_start": t_start,
        "t_pulse_end": float(t[idx_pulse_end]),
        "t_instant_aligned": t_inst_aligned,
        "t_pulse_duration_s": t_end_aligned,
        "v_before": v_before,
        "v_instant": v_instant,
        "v_pulse_end": v_pulse_end,
        "v_final": v_final,
        "delta_v0_app": delta_v0_app,
        "delta_v_slow_app": delta_v_slow_app,
        "delta_v_total_app": delta_v_total_app,
        "delta_v_rec_app": delta_v_rec_app,
        "slow_negative_flag": bool(delta_v_slow_app < 0.0),
        "has_recovery": has_recovery,
        "horizontal_guides": horizontal_guides,
        "span_annotations": span_annotations,
        "guides": horizontal_guides + span_annotations,
    }


def _try_parse_numeric_headers(labels: Sequence[str]) -> Optional[np.ndarray]:
    """Return float array if every header string can be parsed as a finite float, else None."""
    vals: List[float] = []
    for lbl in labels:
        s = str(lbl).strip()
        try:
            fv = float(s)
            if not np.isfinite(fv):
                return None
            vals.append(fv)
        except ValueError:
            return None
    return np.asarray(vals, dtype=float) if vals else None


def _impute_matrix_nans_along_x(z_mat: np.ndarray, x_grid: np.ndarray, fill_tail: float = 0.0) -> Tuple[np.ndarray, int]:
    """Interpolate interior NaNs along x for each y-row and fill leading/trailing NaNs with `fill_tail`."""
    nan_mask = ~np.isfinite(z_mat)
    n_nans = int(np.sum(nan_mask))
    if n_nans == 0:
        return z_mat, 0

    out = z_mat.copy()
    for r_i in range(out.shape[0]):
        row = out[r_i]
        finite = np.isfinite(row)
        if not np.any(finite):
            raise ValueError(f"Row {r_i} in 2D matrix contains 100% NaN values.")
        if not np.all(finite):
            valid_x = x_grid[finite]
            valid_z = row[finite]
            # Interpolate inside valid [valid_x[0], valid_x[-1]], fill outside with fill_tail
            interp_row = np.interp(x_grid, valid_x, valid_z, left=fill_tail, right=fill_tail)
            out[r_i] = interp_row
    return out, n_nans


def _load_single_1d_curve(item: Dict[str, Any], default_modality: str = "XY") -> Tuple[str, np.ndarray, np.ndarray, Optional[float]]:
    """Load or extract a single `(name, x, y, optional_y_val)` curve for Mode B 1D->2D stacking."""
    name = str(item.get("name") or item.get("label") or Path(str(item.get("file") or item.get("path") or "Curve")).stem)
    y_val_raw = item.get("y_val", item.get("state_value", item.get("voltage", item.get("time"))))
    y_val = float(y_val_raw) if y_val_raw is not None else None

    if "x" in item and ("y" in item or "intensity" in item):
        x_arr = np.asarray(item["x"], dtype=float).ravel()
        y_arr = np.asarray(item.get("y", item.get("intensity")), dtype=float).ravel()
    else:
        fpath = item.get("file") or item.get("path")
        if not fpath:
            raise KeyError(f"1D curve spec must provide either ('x', 'y') arrays or 'file'/'path': {item}")
        modality = str(item.get("modality", default_modality)).strip().upper()
        if modality == "XRD":
            parsed = parse_xrd(fpath)
            x_arr, y_arr = parsed["x"], parsed["y"]
        elif modality == "FTIR":
            parsed = parse_ftir(fpath)
            x_arr, y_arr = parsed["x"], parsed["y"]
        elif modality == "XPS":
            parsed = parse_xps_avantage(fpath, region_hint=str(item.get("region", "C1s")))
            x_arr, y_arr = parsed["x"], parsed["y"]
        elif str(fpath).lower().endswith((".xlsx", ".xlsm", ".xls", ".csv", ".tsv")) and (
            "x_col" in item or "y_col" in item
        ):
            df_c = load_tabular_sheet(fpath, sheet=item.get("sheet", 0), header_row=item.get("header_row", 0))
            xc = _resolve_col_name(df_c, item.get("x_col", 0))
            yc = _resolve_col_name(df_c, item.get("y_col", 1))
            x_arr = pd.to_numeric(df_c[xc], errors="coerce").to_numpy(dtype=float)
            y_arr = pd.to_numeric(df_c[yc], errors="coerce").to_numpy(dtype=float)
        else:
            parsed = parse_xy_text(
                fpath,
                despike=bool(item.get("despike", False)),
                x_col=int(item.get("x_col", 0)),
                y_col=int(item.get("y_col", 1)),
            )
            x_arr, y_arr = parsed["x"], parsed["y"]

    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_arr, y_arr = x_arr[valid], y_arr[valid]
    if len(x_arr) < 3:
        raise ValueError(f"Curve '{name}' has fewer than 3 finite points.")
    order = np.argsort(x_arr)
    x_sorted, y_sorted = x_arr[order], y_arr[order]
    # Average exact duplicate X coordinates if any
    if np.any(np.diff(x_sorted) == 0):
        df_tmp = pd.DataFrame({"x": x_sorted, "y": y_sorted}).groupby("x", sort=True)["y"].mean().reset_index()
        x_sorted = df_tmp["x"].to_numpy(dtype=float)
        y_sorted = df_tmp["y"].to_numpy(dtype=float)

    return name, x_sorted, y_sorted, y_val


def load_2d_field_matrix(config_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Load or assemble a 2D pseudocolor/contour matrix `(ny, nx)` aligned with Origin
    `MSheet.from_np(z_matrix)` + `ms.xymap = (x1, x2, y1, y2)`:

    - **Mode A (`wide_matrix`)**: Wide matrix sheet (e.g., `drt_matrix.xlsx` -> `drt_cloud_density`).
      Col 0 is `x` (or `y` when `transpose=True`), remaining column headers are parsed as numeric `y`
      or discrete state indices `1..N` + `y_labels`. Automatically skips leading non-numeric unit/sub-header
      rows (such as `('logtau', 'gamma_tau', ...)`).
    - **Mode B (`stack_1d`)**: Multiple 1D curves `(x_i, intensity_i)` (in-situ XRD/Raman/FTIR/DRT lines)
      linearly interpolated onto a common `x_grid` to form a `(ny, nx)` `float` matrix.
    """
    if not isinstance(config_dict, dict):
        raise TypeError(f"config_dict must be a dict, got {type(config_dict)}")

    explicit_mode = str(config_dict.get("mode", "")).strip().lower()
    has_1d_list = any(k in config_dict for k in ("curves", "series", "files"))

    if explicit_mode in ("stack_1d", "1d_stack", "from_curves") or (not explicit_mode and has_1d_list):
        raw_items = config_dict.get("curves") or config_dict.get("series") or config_dict.get("files")
        if not raw_items or len(raw_items) < 2:
            raise ValueError("Mode B (stack_1d) requires at least 2 curves/files to build a 2D matrix.")

        default_mod = str(config_dict.get("modality", "XY"))
        norm_mode = str(config_dict.get("normalize", "none")).strip().lower()
        loaded_curves: List[Tuple[str, np.ndarray, np.ndarray, Optional[float]]] = []
        for item in raw_items:
            spec_item = {"file": item} if isinstance(item, (str, Path)) else dict(item)
            nm, xv, yv, y_pos = _load_single_1d_curve(spec_item, default_modality=default_mod)
            if norm_mode == "minmax":
                span = float(np.max(yv) - np.min(yv))
                yv = (yv - float(np.min(yv))) / (span if span > 1e-12 else 1.0)
            elif norm_mode == "max":
                mx = float(np.max(np.abs(yv)))
                yv = yv / (mx if mx > 1e-12 else 1.0)
            elif norm_mode == "area":
                area = float(np.trapezoid(np.abs(yv), xv)) if hasattr(np, "trapezoid") else float(np.trapz(np.abs(yv), xv))
                yv = yv / (area if area > 1e-12 else 1.0)
            loaded_curves.append((nm, xv, yv, y_pos))

        # Construct common monotonic x_grid
        if "x_grid" in config_dict and config_dict["x_grid"] is not None:
            x_grid = np.sort(np.asarray(config_dict["x_grid"], dtype=float).ravel())
        else:
            if "x_range" in config_dict and config_dict["x_range"] is not None:
                x_lo, x_hi = float(config_dict["x_range"][0]), float(config_dict["x_range"][1])
                if x_lo > x_hi:
                    x_lo, x_hi = x_hi, x_lo
            else:
                domain_mode = str(config_dict.get("grid_domain", "intersection")).strip().lower()
                if domain_mode == "union":
                    x_lo = min(float(c[1][0]) for c in loaded_curves)
                    x_hi = max(float(c[1][-1]) for c in loaded_curves)
                else:
                    x_lo = max(float(c[1][0]) for c in loaded_curves)
                    x_hi = min(float(c[1][-1]) for c in loaded_curves)
                    if x_lo >= x_hi:
                        x_lo = min(float(c[1][0]) for c in loaded_curves)
                        x_hi = max(float(c[1][-1]) for c in loaded_curves)

            default_nx = max(len(c[1]) for c in loaded_curves)
            n_x = int(config_dict.get("n_x", min(max(default_nx, 100), 4000)))
            x_grid = np.linspace(x_lo, x_hi, n_x)

        ny = len(loaded_curves)
        nx = len(x_grid)
        z_matrix = np.zeros((ny, nx), dtype=float)
        y_labels: List[str] = []
        y_vals_explicit: List[Optional[float]] = []

        fill_outside = config_dict.get("fill_outside", 0.0)
        for j, (nm, xv, yv, y_pos) in enumerate(loaded_curves):
            y_labels.append(nm)
            y_vals_explicit.append(y_pos)
            if fill_outside == "edge":
                z_matrix[j, :] = np.interp(x_grid, xv, yv)
            else:
                fv = float(fill_outside)
                z_matrix[j, :] = np.interp(x_grid, xv, yv, left=fv, right=fv)

        if "y_values" in config_dict and config_dict["y_values"] is not None:
            y_grid = np.asarray(config_dict["y_values"], dtype=float).ravel()
            if len(y_grid) != ny:
                raise ValueError(f"Length of y_values ({len(y_grid)}) does not match curve count ({ny}).")
            y_is_cat = False
        elif all(v is not None for v in y_vals_explicit):
            y_grid = np.asarray([float(v) for v in y_vals_explicit], dtype=float)
            y_is_cat = False
        else:
            parsed_hdr_y = _try_parse_numeric_headers(y_labels)
            if parsed_hdr_y is not None:
                y_grid = parsed_hdr_y
                y_is_cat = False
            else:
                y_grid = np.arange(1, ny + 1, dtype=float)
                y_is_cat = True

        # Ensure ascending y_grid for Origin xymap consistency
        if len(y_grid) > 1 and y_grid[-1] < y_grid[0]:
            y_order = np.argsort(y_grid)
            y_grid = y_grid[y_order]
            z_matrix = z_matrix[y_order, :]
            y_labels = [y_labels[i] for i in y_order]

        x_label = str(config_dict.get("x_label", "X"))
        y_label = str(config_dict.get("y_label", "State"))
        z_label = str(config_dict.get("z_label", "Intensity (a.u.)"))

        return {
            "mode": "stack_1d",
            "x_grid": x_grid,
            "y_grid": y_grid,
            "z_matrix": z_matrix,
            "matrix_x": x_grid,
            "matrix_y": y_grid,
            "matrix_z": z_matrix,
            "shape": (int(ny), int(nx)),
            "xymap": (float(x_grid[0]), float(x_grid[-1]), float(y_grid[0]), float(y_grid[-1])),
            "x_label": x_label,
            "y_label": y_label,
            "z_label": z_label,
            "x_is_categorical": False,
            "y_is_categorical": y_is_cat,
            "x_labels": None,
            "y_labels": y_labels if y_is_cat else [str(lbl) for lbl in y_labels],
            "z_min": float(np.min(z_matrix)),
            "z_max": float(np.max(z_matrix)),
            "nan_imputed_count": 0,
        }

    # Mode A: Wide Matrix Sheet (e.g., drt_matrix.xlsx -> drt_cloud_density)
    if "df" in config_dict and isinstance(config_dict["df"], pd.DataFrame):
        df = config_dict["df"].copy()
    else:
        fpath = config_dict.get("file_path", config_dict.get("input_file", config_dict.get("path")))
        if not fpath:
            raise KeyError("Mode A (wide_matrix) requires 'file_path' (or 'input_file'/'path') or 'df' in config_dict.")
        sheet = config_dict.get("sheet", 0)
        header_row = config_dict.get("header_row", 0)
        df = load_tabular_sheet(fpath, sheet=sheet, header_row=header_row)

    if df.shape[1] < 3 or df.shape[0] < 2:
        raise ValueError(f"Wide matrix sheet must have >=2 rows and >=3 columns, got shape={df.shape}.")

    # Strip leading metadata/sub-header rows (e.g. Row 1 `('logtau', 'gamma_tau', ...)` in drt_cloud_density)
    col0_unit_hint: Optional[str] = None
    body_unit_hint: Optional[str] = None
    start_row = 0
    while start_row < len(df):
        r_series = df.iloc[start_row]
        r_nums = pd.to_numeric(r_series, errors="coerce")
        if int(r_nums.notna().sum()) == 0:
            c0_str = str(r_series.iloc[0] or "").strip()
            c1_str = str(r_series.iloc[1] or "").strip()
            if c0_str and c0_str.lower() != "nan":
                col0_unit_hint = c0_str
            if c1_str and c1_str.lower() != "nan":
                body_unit_hint = c1_str
            start_row += 1
        else:
            break

    df_num = df.iloc[start_row:].reset_index(drop=True)
    if len(df_num) < 2:
        raise ValueError("Insufficient numeric rows in wide matrix sheet after skipping sub-headers.")

    col0_header = str(df_num.columns[0]).strip()
    other_headers = [str(c).strip() for c in df_num.columns[1:]]

    # Parse column 0 (either numeric axis or discrete labels)
    col0_vals = pd.to_numeric(df_num.iloc[:, 0], errors="coerce").to_numpy(dtype=float)
    if np.all(np.isfinite(col0_vals)):
        col0_axis = col0_vals
        col0_is_cat = False
        col0_labels: Optional[List[str]] = None
    else:
        col0_labels = [str(v).strip() for v in df_num.iloc[:, 0].tolist()]
        col0_axis = np.arange(1, len(col0_labels) + 1, dtype=float)
        col0_is_cat = True

    # Parse headers 1..K (either numeric axis or discrete state indices 1..K + state labels)
    parsed_hdr_nums = _try_parse_numeric_headers(other_headers)
    if parsed_hdr_nums is not None:
        hdr_axis = parsed_hdr_nums
        hdr_is_cat = False
    else:
        hdr_axis = np.arange(1, len(other_headers) + 1, dtype=float)
        hdr_is_cat = True

    raw_body = df_num.iloc[:, 1:].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    transpose = bool(config_dict.get("transpose", False))

    if not transpose:
        # Default (e.g., drt_cloud_density): col 0 = x (`nx` rows), headers = y (`ny` cols) -> z_matrix is `(ny, nx)`
        x_grid = col0_axis
        x_is_cat = col0_is_cat
        x_labels = col0_labels
        y_grid = hdr_axis
        y_is_cat = hdr_is_cat
        y_labels_out: Optional[List[str]] = other_headers
        z_matrix = raw_body.T.copy()
        default_x_lbl = col0_unit_hint or (col0_header if not col0_header.startswith("Unnamed:") else "X")
        default_y_lbl = "State"
    else:
        # Transposed: col 0 = y (`ny` rows), headers = x (`nx` cols) -> z_matrix is `(ny, nx)`
        y_grid = col0_axis
        y_is_cat = col0_is_cat
        y_labels_out = col0_labels
        x_grid = hdr_axis
        x_is_cat = hdr_is_cat
        x_labels = other_headers
        z_matrix = raw_body.copy()
        default_x_lbl = "State" if x_is_cat else "X"
        default_y_lbl = col0_unit_hint or (col0_header if not col0_header.startswith("Unnamed:") else "Y")

    # Sort x_grid and y_grid ascending so Origin MSheet.xymap=(x1,x2,y1,y2) maps monotonically
    if len(x_grid) > 1 and not np.all(np.diff(x_grid) >= 0):
        x_ord = np.argsort(x_grid)
        x_grid = x_grid[x_ord]
        z_matrix = z_matrix[:, x_ord]
        if x_labels is not None:
            x_labels = [x_labels[i] for i in x_ord]

    if len(y_grid) > 1 and not np.all(np.diff(y_grid) >= 0):
        y_ord = np.argsort(y_grid)
        y_grid = y_grid[y_ord]
        z_matrix = z_matrix[y_ord, :]
        if y_labels_out is not None:
            y_labels_out = [y_labels_out[i] for i in y_ord]

    nan_fill = float(config_dict.get("fill_nan", 0.0))
    z_matrix, nan_count = _impute_matrix_nans_along_x(z_matrix, x_grid, fill_tail=nan_fill)

    ny, nx = z_matrix.shape
    x_label = str(config_dict.get("x_label", default_x_lbl))
    y_label = str(config_dict.get("y_label", default_y_lbl))
    z_label = str(config_dict.get("z_label", body_unit_hint or "Intensity"))

    return {
        "mode": "wide_matrix",
        "x_grid": x_grid,
        "y_grid": y_grid,
        "z_matrix": z_matrix,
        "matrix_x": x_grid,
        "matrix_y": y_grid,
        "matrix_z": z_matrix,
        "shape": (int(ny), int(nx)),
        "xymap": (float(x_grid[0]), float(x_grid[-1]), float(y_grid[0]), float(y_grid[-1])),
        "x_label": x_label,
        "y_label": y_label,
        "z_label": z_label,
        "x_is_categorical": x_is_cat,
        "y_is_categorical": y_is_cat,
        "x_labels": x_labels,
        "y_labels": y_labels_out,
        "z_min": float(np.min(z_matrix)),
        "z_max": float(np.max(z_matrix)),
        "nan_imputed_count": nan_count,
    }


# ---------------------------------------------------------------------------
# Regression fit with 95% confidence band — zero extra third-party deps
# ---------------------------------------------------------------------------

def _t_critical_95(df: int) -> float:
    """
    Two-tailed t critical value at the 95% confidence level.
    Uses a lookup table for small df and linear interpolation for intermediate;
    falls back to 1.96 (normal approximation) for large df.
    No scipy.stats dependency.
    """
    if df <= 0:
        return 12.706  # df == 1 worst case
    _TABLE = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000, 120: 1.980,
    }
    if df in _TABLE:
        return _TABLE[df]
    if df >= 500:
        return 1.96
    keys = sorted(_TABLE)
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= df <= hi:
            t = (df - lo) / (hi - lo)
            return _TABLE[lo] + t * (_TABLE[hi] - _TABLE[lo])
    return 1.96


def fit_xy_with_ci95(
    x,
    y,
    model: str = "linear",
    n_grid: int = 200,
    ci_level: float = 0.95,
) -> dict:
    """
    Fit x/y data and return a 95% confidence band using analytic t-distribution SE.

    Parameters
    ----------
    x, y : array-like  — input data (finite values only are used)
    model : {"linear", "power", "poly2"}
    n_grid : int — number of evenly-spaced evaluation points for fit curve

    Returns
    -------
    dict with keys:
        x_fit, y_fit, y_low, y_high  — fit curve and 95% CI band (lists)
        r2 : float — coefficient of determination on the transformed space
        slope : float — first-order coefficient (slope for linear/poly2, exponent for power)
        intercept : float — constant term (y-intercept or amplitude for power)
        equation_str : str — human-readable equation

    Notes
    -----
    Uses only numpy (already imported) and stdlib math — zero additional
    third-party package dependencies.
    """
    x_arr = np.asarray(x, dtype=float).ravel()
    y_arr = np.asarray(y, dtype=float).ravel()
    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_v, y_v = x_arr[valid], y_arr[valid]
    n = int(np.sum(valid))
    if n < 3:
        raise ValueError(
            f"fit_xy_with_ci95 requires >= 3 finite data points, got {n}"
        )

    # ---- power model: log-log linear regression ----
    if model == "power":
        if np.any(x_v <= 0) or np.any(y_v <= 0):
            raise ValueError(
                "fit_xy_with_ci95: power model requires all x > 0 and y > 0"
            )
        lx = np.log(x_v)
        ly = np.log(y_v)
        X = np.column_stack([lx, np.ones(n)])
        coeffs, *_ = np.linalg.lstsq(X, ly, rcond=None)
        exp_coeff = float(coeffs[0])
        amplitude = float(np.exp(float(coeffs[1])))
        y_pred_log = X @ coeffs
        ss_res = float(np.sum((ly - y_pred_log) ** 2))
        ss_tot = float(np.sum((ly - float(np.mean(ly))) ** 2))
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        x_grid = np.linspace(float(np.min(x_v)), float(np.max(x_v)), n_grid)
        lx_grid = np.log(x_grid)
        X_grid = np.column_stack([lx_grid, np.ones(n_grid)])
        yfit_log = X_grid @ coeffs

        df = n - 2
        se2 = ss_res / max(df, 1)
        XtX_inv = np.linalg.pinv(X.T @ X)
        h = np.einsum("ij,jk,ik->i", X_grid, XtX_inv, X_grid)
        t_crit = _t_critical_95(df)
        hw = t_crit * np.sqrt(se2 * h)

        eq = f"y = {amplitude:.4g} * x^{exp_coeff:.4g}"
        return {
            "x_fit": x_grid.tolist(),
            "y_fit": np.exp(yfit_log).tolist(),
            "y_low": np.exp(yfit_log - hw).tolist(),
            "y_high": np.exp(yfit_log + hw).tolist(),
            "r2": r2,
            "slope": exp_coeff,
            "intercept": amplitude,
            "equation_str": eq,
        }

    # ---- poly2 model: quadratic regression ----
    if model == "poly2":
        X = np.column_stack([x_v ** 2, x_v, np.ones(n)])
        coeffs, *_ = np.linalg.lstsq(X, y_v, rcond=None)
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
        y_pred = X @ coeffs
        ss_res = float(np.sum((y_v - y_pred) ** 2))
        ss_tot = float(np.sum((y_v - float(np.mean(y_v))) ** 2))
        r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

        x_grid = np.linspace(float(np.min(x_v)), float(np.max(x_v)), n_grid)
        X_grid = np.column_stack([x_grid ** 2, x_grid, np.ones(n_grid)])
        yfit = X_grid @ coeffs

        df = n - 3
        se2 = ss_res / max(df, 1)
        XtX_inv = np.linalg.pinv(X.T @ X)
        h = np.einsum("ij,jk,ik->i", X_grid, XtX_inv, X_grid)
        t_crit = _t_critical_95(df)
        hw = t_crit * np.sqrt(se2 * h)

        sign_b = "+" if b >= 0 else "-"
        sign_c = "+" if c >= 0 else "-"
        eq = f"y = {a:.4g}x² {sign_b} {abs(b):.4g}x {sign_c} {abs(c):.4g}"
        return {
            "x_fit": x_grid.tolist(),
            "y_fit": yfit.tolist(),
            "y_low": (yfit - hw).tolist(),
            "y_high": (yfit + hw).tolist(),
            "r2": r2,
            "slope": b,
            "intercept": c,
            "equation_str": eq,
        }

    # ---- default: linear model ----
    X = np.column_stack([x_v, np.ones(n)])
    coeffs, *_ = np.linalg.lstsq(X, y_v, rcond=None)
    slope = float(coeffs[0])
    intercept = float(coeffs[1])
    y_pred = X @ coeffs
    ss_res = float(np.sum((y_v - y_pred) ** 2))
    ss_tot = float(np.sum((y_v - float(np.mean(y_v))) ** 2))
    r2 = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    x_grid = np.linspace(float(np.min(x_v)), float(np.max(x_v)), n_grid)
    X_grid = np.column_stack([x_grid, np.ones(n_grid)])
    yfit = X_grid @ coeffs

    df = n - 2
    se2 = ss_res / max(df, 1)
    XtX_inv = np.linalg.pinv(X.T @ X)
    h = np.einsum("ij,jk,ik->i", X_grid, XtX_inv, X_grid)
    t_crit = _t_critical_95(df)
    hw = t_crit * np.sqrt(se2 * h)

    sign_str = "+" if intercept >= 0 else "-"
    eq = f"y = {slope:.4g}x {sign_str} {abs(intercept):.4g}"
    return {
        "x_fit": x_grid.tolist(),
        "y_fit": yfit.tolist(),
        "y_low": (yfit - hw).tolist(),
        "y_high": (yfit + hw).tolist(),
        "r2": r2,
        "slope": slope,
        "intercept": intercept,
        "equation_str": eq,
    }
