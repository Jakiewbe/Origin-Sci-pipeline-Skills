"""
Cross-discipline statistical inference, replicate aggregation, multiple-testing
correction, and significance bracket layout engine for SciOrigin pipelines.

Dependencies: Python standard library, numpy, scipy.stats (pandas optional).
Strictly zero dependency on originpro or matplotlib.
"""

from __future__ import annotations

import math
import warnings
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy import stats


def p_to_stars(p: float) -> str:
    """Map a p-value to standard publication significance stars."""
    if p is None:
        return "ns"
    try:
        pval = float(p)
    except (TypeError, ValueError):
        return "ns"
    if not math.isfinite(pval) or pval >= 0.05:
        return "ns"
    if pval < 1e-4:
        return "****"
    if pval < 1e-3:
        return "***"
    if pval < 1e-2:
        return "**"
    return "*"


def adjust_pvalues(pvals: Sequence[float], method: str = "fdr_bh") -> List[float]:
    """
    Adjust a sequence of p-values for multiple hypothesis testing.

    Supported methods:
    - "fdr_bh": Benjamini-Hochberg false discovery rate control
    - "holm": Holm-Bonferroni step-down family-wise error rate control
    - "bonferroni": Single-step Bonferroni correction
    - "none": Unadjusted p-values clipped to [0, 1]
    """
    norm_method = str(method or "none").strip().lower()
    alias_map = {
        "bh": "fdr_bh",
        "fdr": "fdr_bh",
        "benjamini_hochberg": "fdr_bh",
        "benjamini-hochberg": "fdr_bh",
        "holm-bonferroni": "holm",
        "holm_bonferroni": "holm",
        "bonf": "bonferroni",
        "unadjusted": "none",
        "raw": "none",
    }
    norm_method = alias_map.get(norm_method, norm_method)
    if norm_method not in ("fdr_bh", "holm", "bonferroni", "none"):
        raise ValueError(
            f"Unsupported p-value adjustment method {method!r}; "
            "expected one of ('fdr_bh', 'holm', 'bonferroni', 'none')."
        )

    n_total = len(pvals)
    if n_total == 0:
        return []

    arr = np.asarray(pvals, dtype=float).ravel()
    finite_mask = np.isfinite(arr)
    out = np.full(n_total, np.nan, dtype=float)
    if not np.any(finite_mask):
        return [float(x) for x in out]

    p_fin = np.clip(arr[finite_mask], 0.0, 1.0)
    m = int(p_fin.size)

    if norm_method == "none" or m == 1:
        adj_fin = p_fin
    elif norm_method == "bonferroni":
        adj_fin = np.minimum(1.0, p_fin * float(m))
    elif norm_method == "holm":
        order = np.argsort(p_fin, kind="mergesort")
        p_sorted = p_fin[order]
        multipliers = float(m) - np.arange(m, dtype=float)
        step_down = np.maximum.accumulate(p_sorted * multipliers)
        adj_sorted = np.clip(step_down, 0.0, 1.0)
        adj_fin = np.empty(m, dtype=float)
        adj_fin[order] = adj_sorted
    else:  # "fdr_bh"
        order = np.argsort(p_fin, kind="mergesort")
        p_sorted = p_fin[order]
        ranks = np.arange(1, m + 1, dtype=float)
        bh_raw = p_sorted * (float(m) / ranks)
        adj_sorted = np.minimum.accumulate(bh_raw[::-1])[::-1]
        adj_sorted = np.clip(adj_sorted, 0.0, 1.0)
        adj_fin = np.empty(m, dtype=float)
        adj_fin[order] = adj_sorted

    out[finite_mask] = adj_fin
    return [float(x) for x in out]


def _is_missing_scalar(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    try:
        # Handles numpy/pandas NA scalars without requiring pandas import
        if isinstance(val, (np.floating, np.number)) and np.isnan(val):
            return True
    except TypeError:
        pass
    if type(val).__name__ in ("NAType", "NaTType"):
        return True
    return False


def _iter_table_records(
    rows_or_df: Any,
    required_cols: Sequence[str],
) -> List[Dict[str, Any]]:
    """Normalize a pandas DataFrame, list of dicts, or dict of columns into row dicts."""
    if rows_or_df is None:
        raise ValueError("rows_or_df cannot be None.")

    # Duck-type pandas.DataFrame
    if hasattr(rows_or_df, "columns") and hasattr(rows_or_df, "to_dict"):
        cols = list(rows_or_df.columns)
        for col in required_cols:
            if col not in cols:
                raise KeyError(f"Column {col!r} not found in DataFrame columns {cols!r}.")
        return list(rows_or_df[list(required_cols)].to_dict(orient="records"))

    # Column-oriented mapping: {"group": [...], "value": [...]}
    if isinstance(rows_or_df, Mapping):
        for col in required_cols:
            if col not in rows_or_df:
                raise KeyError(f"Column {col!r} not found in mapping keys {list(rows_or_df.keys())!r}.")
        col_seqs = {col: list(rows_or_df[col]) for col in required_cols}
        lengths = {len(v) for v in col_seqs.values()}
        if len(lengths) > 1:
            raise ValueError(f"Column sequences in rows_or_df have mismatched lengths: {lengths}.")
        n_rows = next(iter(lengths), 0)
        return [{col: col_seqs[col][i] for col in required_cols} for i in range(n_rows)]

    # Row-oriented sequence of mappings
    records: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows_or_df):
        if not isinstance(row, Mapping):
            raise TypeError(f"Expected row {idx} to be a mapping, got {type(row).__name__}.")
        for col in required_cols:
            if col not in row:
                raise KeyError(f"Column {col!r} missing in row {idx}.")
        records.append({col: row[col] for col in required_cols})
    return records


def aggregate_replicates(
    rows_or_df: Any,
    group_col: str,
    value_col: str,
    bio_unit_col: Optional[str] = None,
) -> Dict[str, List[float]]:
    """
    Extract per-group numeric replicate lists while preserving group appearance order.

    When ``bio_unit_col`` is provided, technical replicates within each
    ``(group, bio_unit)`` pair are averaged first so downstream statistical tests
    operate strictly on independent biological replicates (preventing pseudoreplication).
    """
    req_cols = [group_col, value_col]
    if bio_unit_col is not None:
        req_cols.append(bio_unit_col)

    records = _iter_table_records(rows_or_df, req_cols)

    if bio_unit_col is None:
        grouped: Dict[str, List[float]] = {}
        for row in records:
            g_raw = row[group_col]
            v_raw = row[value_col]
            if _is_missing_scalar(g_raw) or _is_missing_scalar(v_raw):
                continue
            try:
                val = float(v_raw)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(val):
                continue
            g_name = str(g_raw)
            grouped.setdefault(g_name, []).append(val)
        return grouped

    bio_buckets: Dict[str, Dict[str, List[float]]] = {}
    for row in records:
        g_raw = row[group_col]
        b_raw = row[bio_unit_col]
        v_raw = row[value_col]
        if _is_missing_scalar(g_raw) or _is_missing_scalar(b_raw) or _is_missing_scalar(v_raw):
            continue
        try:
            val = float(v_raw)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(val):
            continue
        g_name = str(g_raw)
        b_name = str(b_raw)
        unit_map = bio_buckets.setdefault(g_name, {})
        unit_map.setdefault(b_name, []).append(val)

    aggregated: Dict[str, List[float]] = {}
    for g_name, unit_map in bio_buckets.items():
        aggregated[g_name] = [
            float(np.mean(np.asarray(tech_vals, dtype=float)))
            for tech_vals in unit_map.values()
            if len(tech_vals) > 0
        ]
    return aggregated


def _clean_numeric_array(vals: Sequence[float], group_name: str) -> np.ndarray:
    arr = np.asarray(vals, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError(f"Group {group_name!r} contains 0 finite numeric values.")
    return arr


def _shapiro_normality(arr: np.ndarray, alpha: float = 0.05) -> Tuple[Optional[float], bool]:
    n = int(arr.size)
    if n < 3:
        return None, False
    if n > 5000:
        return None, True
    if float(np.ptp(arr)) <= 0.0:
        return None, False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = stats.shapiro(arr)
    p_val = float(res.pvalue)
    if not math.isfinite(p_val):
        return None, False
    return p_val, bool(p_val >= alpha)


def summarize_groups(
    groups: Dict[str, Sequence[float]],
    *,
    alpha: float = 0.05,
) -> List[Dict[str, Any]]:
    """
    Compute parametric, non-parametric, and Shapiro-Wilk normality summaries
    for each group in appearance order.
    """
    summaries: List[Dict[str, Any]] = []
    for name, vals in groups.items():
        arr = _clean_numeric_array(vals, str(name))
        n = int(arr.size)
        mean_v = float(np.mean(arr))
        if n >= 2:
            sd_v = float(np.std(arr, ddof=1))
            sem_v = float(sd_v / math.sqrt(float(n)))
            t_crit = float(stats.t.ppf(1.0 - 0.5 * alpha, df=n - 1))
            ci95_half = float(t_crit * sem_v)
        else:
            sd_v = 0.0
            sem_v = 0.0
            ci95_half = 0.0

        median_v = float(np.median(arr))
        q25_v = float(np.percentile(arr, 25.0))
        q75_v = float(np.percentile(arr, 75.0))
        iqr_v = float(q75_v - q25_v)
        min_v = float(np.min(arr))
        max_v = float(np.max(arr))
        shapiro_p, is_normal = _shapiro_normality(arr, alpha=alpha)

        summaries.append(
            {
                "group": str(name),
                "n": n,
                "mean": mean_v,
                "sd": sd_v,
                "sem": sem_v,
                "ci95_half": ci95_half,
                "median": median_v,
                "q25": q25_v,
                "q75": q75_v,
                "iqr": iqr_v,
                "min": min_v,
                "max": max_v,
                "shapiro_p": shapiro_p,
                "is_normal": bool(is_normal),
            }
        )
    return summaries


def _cohens_d_unpaired(a: np.ndarray, b: np.ndarray, equal_var: bool = True) -> float:
    n1, n2 = int(a.size), int(b.size)
    diff = float(np.mean(a) - np.mean(b))
    if n1 < 2 or n2 < 2:
        return 0.0
    v1 = float(np.var(a, ddof=1))
    v2 = float(np.var(b, ddof=1))
    if equal_var:
        denom_df = n1 + n2 - 2
        s_pool = math.sqrt(max(((n1 - 1) * v1 + (n2 - 1) * v2) / max(denom_df, 1), 0.0))
    else:
        s_pool = math.sqrt(max(0.5 * (v1 + v2), 0.0))
    if s_pool <= 1e-15:
        return 0.0
    return float(diff / s_pool)


def _welch_df(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    n1, n2 = int(a.size), int(b.size)
    if n1 < 2 or n2 < 2:
        return None
    s1_n = float(np.var(a, ddof=1)) / float(n1)
    s2_n = float(np.var(b, ddof=1)) / float(n2)
    num = (s1_n + s2_n) ** 2
    den = (s1_n ** 2) / float(n1 - 1) + (s2_n ** 2) / float(n2 - 1)
    if den <= 1e-30:
        return float(n1 + n2 - 2)
    return float(num / den)


def _rank_biserial_unpaired(u_stat: float, n1: int, n2: int) -> float:
    denom = float(n1 * n2)
    if denom <= 0.0:
        return 0.0
    # U1 counts pairs where a > b (+0.5 ties), so (2*U1)/(n1*n2) - 1 is positive when a > b
    return float((2.0 * float(u_stat)) / denom - 1.0)


def _paired_comparison(
    a_raw: Sequence[float],
    b_raw: Sequence[float],
    g1: str,
    g2: str,
    alpha: float,
) -> Tuple[str, float, Optional[float], float, float, str, bool]:
    a_arr = np.asarray(a_raw, dtype=float).ravel()
    b_arr = np.asarray(b_raw, dtype=float).ravel()
    if a_arr.size != b_arr.size:
        raise ValueError(
            f"Paired comparison requires equal sample lengths for {g1!r} ({a_arr.size}) "
            f"and {g2!r} ({b_arr.size})."
        )
    valid = np.isfinite(a_arr) & np.isfinite(b_arr)
    a = a_arr[valid]
    b = b_arr[valid]
    n = int(a.size)
    if n < 2:
        raise ValueError(f"Paired comparison between {g1!r} and {g2!r} requires >= 2 valid pairs.")

    diff = a - b
    _, diff_normal = _shapiro_normality(diff, alpha=alpha)

    if diff_normal:
        if float(np.ptp(diff)) <= 0.0:
            stat_v = 0.0
            p_raw = 1.0 if abs(float(diff[0])) <= 1e-15 else 0.0
            dz = 0.0
        else:
            res = stats.ttest_rel(a, b)
            stat_v = float(res.statistic) if math.isfinite(float(res.statistic)) else 0.0
            p_raw = float(res.pvalue) if math.isfinite(float(res.pvalue)) else 1.0
            sd_d = float(np.std(diff, ddof=1))
            dz = float(np.mean(diff) / sd_d) if sd_d > 1e-15 else 0.0
        return ("Paired t-test", stat_v, float(n - 1), float(np.clip(p_raw, 0.0, 1.0)), dz, "cohens_dz", True)

    nz_diff = diff[np.abs(diff) > 0.0]
    if nz_diff.size == 0:
        return ("Wilcoxon signed-rank", 0.0, None, 1.0, 0.0, "rank_biserial_r", False)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = stats.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
    w_stat = float(res.statistic)
    p_raw = float(res.pvalue) if math.isfinite(float(res.pvalue)) else 1.0

    n_eff = int(nz_diff.size)
    total_ranks = 0.5 * float(n_eff * (n_eff + 1))
    ranks = stats.rankdata(np.abs(nz_diff))
    w_plus = float(np.sum(ranks[nz_diff > 0.0]))
    w_minus = float(np.sum(ranks[nz_diff < 0.0]))
    r_rb = float((w_plus - w_minus) / total_ranks) if total_ranks > 0.0 else 0.0
    return (
        "Wilcoxon signed-rank",
        w_stat,
        None,
        float(np.clip(p_raw, 0.0, 1.0)),
        r_rb,
        "rank_biserial_r",
        False,
    )


def _resolve_Requested_Pairs(
    group_names: Sequence[str],
    control_group: Optional[str],
    pairs: Optional[Sequence[Tuple[str, str]]],
) -> List[Tuple[str, str, int, int]]:
    name_to_idx = {name: idx for idx, name in enumerate(group_names)}
    resolved: List[Tuple[str, str, int, int]] = []

    if pairs is not None:
        for pair in pairs:
            if len(pair) != 2:
                raise ValueError(f"Each pair must be a 2-tuple (group1, group2), got {pair!r}.")
            g1, g2 = str(pair[0]), str(pair[1])
            if g1 not in name_to_idx:
                raise KeyError(f"Group {g1!r} in pairs not found in groups {list(group_names)!r}.")
            if g2 not in name_to_idx:
                raise KeyError(f"Group {g2!r} in pairs not found in groups {list(group_names)!r}.")
            if g1 == g2:
                continue
            resolved.append((g1, g2, name_to_idx[g1], name_to_idx[g2]))
        return resolved

    if control_group is not None:
        ctrl = str(control_group)
        if ctrl not in name_to_idx:
            raise KeyError(f"control_group {ctrl!r} not found in groups {list(group_names)!r}.")
        c_idx = name_to_idx[ctrl]
        for idx, g_name in enumerate(group_names):
            if idx != c_idx:
                resolved.append((ctrl, g_name, c_idx, idx))
        return resolved

    k = len(group_names)
    for i in range(k):
        for j in range(i + 1, k):
            resolved.append((group_names[i], group_names[j], i, j))
    return resolved


def run_group_comparisons(
    groups: Dict[str, Sequence[float]],
    *,
    paired: bool = False,
    control_group: Optional[str] = None,
    p_adjust: str = "fdr_bh",
    alpha: float = 0.05,
    pairs: Optional[Sequence[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """
    Automated multi-group statistical comparison engine with assumption checking.

    - Checks per-group Shapiro-Wilk normality (3 <= n <= 5000) and Brown-Forsythe / Levene
      homoscedasticity.
    - Routes 2-group and >=3-group designs (paired or unpaired) to the appropriate
      parametric or non-parametric omnibus and post-hoc pairwise tests.
    """
    if len(groups) < 2:
        raise ValueError(f"run_group_comparisons requires >= 2 groups, got {len(groups)}.")

    group_names = [str(k) for k in groups.keys()]
    raw_seqs = [groups[k] for k in groups.keys()]
    arrays = [_clean_numeric_array(vals, name) for name, vals in zip(group_names, raw_seqs)]
    k_groups = len(group_names)

    summary = summarize_groups(
        {name: arr for name, arr in zip(group_names, arrays)},
        alpha=alpha,
    )
    all_normal = all(bool(item["is_normal"]) for item in summary)

    homoscedastic = False
    levene_p: Optional[float] = None
    if not paired and all(arr.size >= 2 for arr in arrays):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lev_res = stats.levene(*arrays, center="median")
        if math.isfinite(float(lev_res.pvalue)):
            levene_p = float(lev_res.pvalue)
            homoscedastic = bool(levene_p >= alpha)

    requested_pairs = _resolve_Requested_Pairs(group_names, control_group, pairs)

    # ---- 2-group comparison ----
    if k_groups == 2:
        g1, g2, i1, i2 = requested_pairs[0] if requested_pairs else (group_names[0], group_names[1], 0, 1)
        if paired:
            test_name, stat_v, df_v, p_raw, eff_v, eff_type, is_param = _paired_comparison(
                raw_seqs[i1], raw_seqs[i2], g1, g2, alpha
            )
            p_adj_method_used = "none"
        else:
            a, b = arrays[i1], arrays[i2]
            if all_normal and homoscedastic:
                res = stats.ttest_ind(a, b, equal_var=True)
                test_name = "Student t-test"
                stat_v = float(res.statistic) if math.isfinite(float(res.statistic)) else 0.0
                p_raw = float(res.pvalue) if math.isfinite(float(res.pvalue)) else 1.0
                df_v = float(a.size + b.size - 2)
                eff_v = _cohens_d_unpaired(a, b, equal_var=True)
                eff_type = "cohens_d"
                is_param = True
            elif all_normal and not homoscedastic:
                res = stats.ttest_ind(a, b, equal_var=False)
                test_name = "Welch t-test"
                stat_v = float(res.statistic) if math.isfinite(float(res.statistic)) else 0.0
                p_raw = float(res.pvalue) if math.isfinite(float(res.pvalue)) else 1.0
                df_v = float(res.df) if hasattr(res, "df") and math.isfinite(float(res.df)) else _welch_df(a, b)
                eff_v = _cohens_d_unpaired(a, b, equal_var=False)
                eff_type = "cohens_d"
                is_param = True
            else:
                res = stats.mannwhitneyu(a, b, alternative="two-sided")
                test_name = "Mann-Whitney U"
                stat_v = float(res.statistic)
                p_raw = float(res.pvalue) if math.isfinite(float(res.pvalue)) else 1.0
                df_v = None
                eff_v = _rank_biserial_unpaired(stat_v, int(a.size), int(b.size))
                eff_type = "rank_biserial_r"
                is_param = False
            p_adj_method_used = str(p_adjust)

        p_raw = float(np.clip(p_raw, 0.0, 1.0))
        p_adj = float(adjust_pvalues([p_raw], method=p_adjust)[0]) if requested_pairs else p_raw
        comp_list = (
            [
                {
                    "group1": g1,
                    "group2": g2,
                    "idx1": int(i1),
                    "idx2": int(i2),
                    "test": test_name,
                    "statistic": float(stat_v),
                    "df": float(df_v) if df_v is not None else None,
                    "p_raw": p_raw,
                    "p_adj": p_adj,
                    "stars": p_to_stars(p_adj),
                    "significant": bool(p_adj < alpha),
                    "effect_size": float(eff_v),
                    "effect_type": eff_type,
                }
            ]
            if requested_pairs
            else []
        )
        return {
            "omnibus_test": test_name,
            "omnibus_stat": float(stat_v),
            "omnibus_p": p_raw,
            "parametric": bool(is_param),
            "homoscedastic": bool(homoscedastic) if not paired else True,
            "levene_p": levene_p,
            "p_adjust_method": p_adj_method_used,
            "summary": summary,
            "comparisons": comp_list,
        }

    # ---- >= 3 groups ----
    if paired:
        lengths = { np.asarray(s, dtype=float).size for s in raw_seqs }
        if len(lengths) > 1:
            raise ValueError(f"Paired multi-group comparison requires equal lengths, got {lengths}.")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fr_res = stats.friedmanchisquare(*arrays)
        omnibus_test = "Friedman test"
        omnibus_stat = float(fr_res.statistic) if math.isfinite(float(fr_res.statistic)) else 0.0
        omnibus_p = float(np.clip(fr_res.pvalue, 0.0, 1.0)) if math.isfinite(float(fr_res.pvalue)) else 1.0

        raw_records: List[Dict[str, Any]] = []
        all_pair_param = True
        for g1, g2, i1, i2 in requested_pairs:
            t_name, st_v, df_v, p_r, ef_v, ef_t, is_p = _paired_comparison(
                raw_seqs[i1], raw_seqs[i2], g1, g2, alpha
            )
            all_pair_param = all_pair_param and is_p
            raw_records.append(
                {
                    "group1": g1,
                    "group2": g2,
                    "idx1": int(i1),
                    "idx2": int(i2),
                    "test": t_name,
                    "statistic": float(st_v),
                    "df": float(df_v) if df_v is not None else None,
                    "p_raw": float(p_r),
                    "effect_size": float(ef_v),
                    "effect_type": ef_t,
                }
            )
        p_adjs = adjust_pvalues([r["p_raw"] for r in raw_records], method=p_adjust)
        for rec, p_a in zip(raw_records, p_adjs):
            rec["p_adj"] = float(p_a)
            rec["stars"] = p_to_stars(p_a)
            rec["significant"] = bool(p_a < alpha)
        return {
            "omnibus_test": omnibus_test,
            "omnibus_stat": omnibus_stat,
            "omnibus_p": omnibus_p,
            "parametric": bool(all_pair_param),
            "homoscedastic": True,
            "levene_p": None,
            "p_adjust_method": str(p_adjust),
            "summary": summary,
            "comparisons": raw_records,
        }

    # Unpaired >= 3 groups
    if all_normal:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            f_res = stats.f_oneway(*arrays)
        omnibus_test = "One-way ANOVA"
        omnibus_stat = float(f_res.statistic) if math.isfinite(float(f_res.statistic)) else 0.0
        omnibus_p = float(np.clip(f_res.pvalue, 0.0, 1.0)) if math.isfinite(float(f_res.pvalue)) else 1.0
        parametric = True
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kw_res = stats.kruskal(*arrays)
        omnibus_test = "Kruskal-Wallis"
        omnibus_stat = float(kw_res.statistic) if math.isfinite(float(kw_res.statistic)) else 0.0
        omnibus_p = float(np.clip(kw_res.pvalue, 0.0, 1.0)) if math.isfinite(float(kw_res.pvalue)) else 1.0
        parametric = False

    use_tukey = bool(
        all_normal
        and homoscedastic
        and pairs is None
        and control_group is None
        and hasattr(stats, "tukey_hsd")
    )

    if use_tukey:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tukey_res = stats.tukey_hsd(*arrays)

        n_total = sum(int(arr.size) for arr in arrays)
        df_resid = max(n_total - k_groups, 1)
        ss_within = sum(float(np.sum((arr - np.mean(arr)) ** 2)) for arr in arrays)
        mse = ss_within / float(df_resid)

        comparisons: List[Dict[str, Any]] = []
        for g1, g2, i1, i2 in requested_pairs:
            a, b = arrays[i1], arrays[i2]
            stat_v = float(tukey_res.statistic[i1, i2])
            p_adj_v = float(np.clip(tukey_res.pvalue[i1, i2], 0.0, 1.0))
            se_diff = math.sqrt(max(mse * (1.0 / float(a.size) + 1.0 / float(b.size)), 0.0))
            if se_diff > 1e-15:
                t_unadj = abs(float(np.mean(a) - np.mean(b))) / se_diff
                p_raw_v = float(np.clip(2.0 * stats.t.sf(t_unadj, df=df_resid), 0.0, 1.0))
            else:
                p_raw_v = p_adj_v

            comparisons.append(
                {
                    "group1": g1,
                    "group2": g2,
                    "idx1": int(i1),
                    "idx2": int(i2),
                    "test": "Tukey HSD",
                    "statistic": stat_v,
                    "df": float(df_resid),
                    "p_raw": p_raw_v,
                    "p_adj": p_adj_v,
                    "stars": p_to_stars(p_adj_v),
                    "significant": bool(p_adj_v < alpha),
                    "effect_size": _cohens_d_unpaired(a, b, equal_var=True),
                    "effect_type": "cohens_d",
                }
            )
        return {
            "omnibus_test": omnibus_test,
            "omnibus_stat": omnibus_stat,
            "omnibus_p": omnibus_p,
            "parametric": True,
            "homoscedastic": True,
            "levene_p": levene_p,
            "p_adjust_method": "tukey_hsd",
            "summary": summary,
            "comparisons": comparisons,
        }

    raw_comps: List[Dict[str, Any]] = []
    for g1, g2, i1, i2 in requested_pairs:
        a, b = arrays[i1], arrays[i2]
        if all_normal:
            eq_var = bool(homoscedastic)
            res = stats.ttest_ind(a, b, equal_var=eq_var)
            t_name = "Student t-test" if eq_var else "Welch t-test"
            st_v = float(res.statistic) if math.isfinite(float(res.statistic)) else 0.0
            p_r = float(np.clip(res.pvalue, 0.0, 1.0)) if math.isfinite(float(res.pvalue)) else 1.0
            if eq_var:
                df_val: Optional[float] = float(a.size + b.size - 2)
            else:
                df_val = float(res.df) if hasattr(res, "df") and math.isfinite(float(res.df)) else _welch_df(a, b)
            ef_v = _cohens_d_unpaired(a, b, equal_var=eq_var)
            ef_t = "cohens_d"
        else:
            res = stats.mannwhitneyu(a, b, alternative="two-sided")
            t_name = "Mann-Whitney U"
            st_v = float(res.statistic)
            p_r = float(np.clip(res.pvalue, 0.0, 1.0)) if math.isfinite(float(res.pvalue)) else 1.0
            df_val = None
            ef_v = _rank_biserial_unpaired(st_v, int(a.size), int(b.size))
            ef_t = "rank_biserial_r"

        raw_comps.append(
            {
                "group1": g1,
                "group2": g2,
                "idx1": int(i1),
                "idx2": int(i2),
                "test": t_name,
                "statistic": st_v,
                "df": df_val,
                "p_raw": p_r,
                "effect_size": ef_v,
                "effect_type": ef_t,
            }
        )

    adj_list = adjust_pvalues([c["p_raw"] for c in raw_comps], method=p_adjust)
    for comp, p_a in zip(raw_comps, adj_list):
        comp["p_adj"] = float(p_a)
        comp["stars"] = p_to_stars(p_a)
        comp["significant"] = bool(p_a < alpha)

    return {
        "omnibus_test": omnibus_test,
        "omnibus_stat": omnibus_stat,
        "omnibus_p": omnibus_p,
        "parametric": parametric,
        "homoscedastic": bool(homoscedastic),
        "levene_p": levene_p,
        "p_adjust_method": str(p_adjust),
        "summary": summary,
        "comparisons": raw_comps,
    }


def compute_sig_bracket_tiers(
    comparisons: Sequence[Dict[str, Any]],
    group_names: Sequence[str],
    group_tops: Sequence[float],
    *,
    hide_ns: bool = True,
    max_brackets: int = 6,
    base_pad_frac: float = 0.06,
    tier_step_frac: float = 0.085,
    data_min: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Assign non-overlapping horizontal bracket tiers and 1-based Origin categorical
    X coordinates for pairwise significance annotations.

    - Filters out non-significant comparisons when ``hide_ns=True``.
    - Retains up to ``max_brackets`` most significant comparisons when crowded.
    - Orders narrowest span ``abs(idx2 - idx1)`` first, greedily assigns non-overlapping
      tier indices ``0, 1, 2, ...``, and guarantees each bracket clears both all spanned
      bars/violins and any overlapping lower-tier brackets.
    """
    n_groups = len(group_names)
    if n_groups == 0 or len(comparisons) == 0 or max_brackets <= 0:
        return []
    if len(group_tops) != n_groups:
        raise ValueError(
            f"group_tops length ({len(group_tops)}) must match group_names length ({n_groups})."
        )

    name_to_idx = {str(name): idx for idx, name in enumerate(group_names)}
    tops = [float(t) for t in group_tops]
    top_max = max(tops)
    top_min = min(tops)

    if data_min is not None:
        raw_span = top_max - float(data_min)
    elif top_min >= 0.0 and top_max > 0.0:
        raw_span = top_max
    else:
        raw_span = top_max - top_min
    data_span = float(raw_span) if raw_span > 1e-12 else max(abs(top_max), 1.0)

    base_pad = float(base_pad_frac) * data_span
    tier_step = float(tier_step_frac) * data_span
    tip_drop = float(0.028 * data_span)

    candidates: List[Dict[str, Any]] = []
    for comp in comparisons:
        p_raw = float(comp.get("p_raw", 1.0))
        p_adj = float(comp.get("p_adj", p_raw))
        sig_flag = bool(comp.get("significant", p_adj < 0.05))
        if hide_ns and not sig_flag:
            continue

        g1 = str(comp["group1"])
        g2 = str(comp["group2"])
        i1 = int(comp["idx1"]) if "idx1" in comp and comp["idx1"] is not None else name_to_idx[g1]
        i2 = int(comp["idx2"]) if "idx2" in comp and comp["idx2"] is not None else name_to_idx[g2]
        if i1 == i2 or not (0 <= i1 < n_groups) or not (0 <= i2 < n_groups):
            continue

        lo_idx, hi_idx = (i1, i2) if i1 < i2 else (i2, i1)
        stars = str(comp.get("stars") or p_to_stars(p_adj))
        candidates.append(
            {
                "group1": str(group_names[lo_idx]),
                "group2": str(group_names[hi_idx]),
                "lo_idx": lo_idx,
                "hi_idx": hi_idx,
                "span": hi_idx - lo_idx,
                "p_adj": p_adj,
                "p_raw": p_raw,
                "stars": stars,
            }
        )

    if not candidates:
        return []

    if len(candidates) > max_brackets:
        candidates.sort(key=lambda item: (item["p_adj"], item["span"], item["lo_idx"]))
        candidates = candidates[:max_brackets]

    # Narrowest span first, left-to-right
    candidates.sort(key=lambda item: (item["span"], item["lo_idx"], item["p_adj"]))

    tier_intervals: List[List[Tuple[int, int]]] = []
    placed: List[Dict[str, Any]] = []

    for item in candidates:
        lo_idx = int(item["lo_idx"])
        hi_idx = int(item["hi_idx"])

        assigned_tier: Optional[int] = None
        for t_idx, intervals in enumerate(tier_intervals):
            # Closed-interval check prevents vertical tick collisions at shared group indices
            if all(hi_idx < b_lo or lo_idx > b_hi for b_lo, b_hi in intervals):
                assigned_tier = t_idx
                intervals.append((lo_idx, hi_idx))
                break
        if assigned_tier is None:
            assigned_tier = len(tier_intervals)
            tier_intervals.append([(lo_idx, hi_idx)])

        spanned_bar_top = max(tops[lo_idx : hi_idx + 1])
        floor_bars = spanned_bar_top + base_pad + float(assigned_tier) * 0.0 if assigned_tier == 0 else spanned_bar_top + base_pad
        overlapping_lower = [
            prev["y_bar"] + tier_step
            for prev in placed
            if not (hi_idx < prev["_lo"] or lo_idx > prev["_hi"])
        ]
        y_bar = max([floor_bars] + overlapping_lower)

        x1 = float(lo_idx + 1.0)
        x2 = float(hi_idx + 1.0)
        stars = str(item["stars"])

        placed.append(
            {
                "group1": item["group1"],
                "group2": item["group2"],
                "x1": x1,
                "x2": x2,
                "y_bar": float(y_bar),
                "tip_drop": float(tip_drop),
                "tier": int(assigned_tier),
                "stars": stars,
                "p_adj": float(item["p_adj"]),
                "p_raw": float(item["p_raw"]),
                "label": stars,
                "_lo": lo_idx,
                "_hi": hi_idx,
            }
        )

    for rec in placed:
        rec.pop("_lo", None)
        rec.pop("_hi", None)

    return placed


def _trapz_1d(y: np.ndarray, x: np.ndarray) -> float:
    trapz_fn = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(trapz_fn(y, x))


def _auto_risk_times(max_time: float) -> List[float]:
    """Select 5-6 evenly spaced, publication-clean risk-table time points covering [0, max_time]."""
    if not math.isfinite(max_time) or max_time <= 0.0:
        return [0.0, 1.0, 2.0, 3.0, 4.0]

    if max_time >= 12.0 and abs(max_time - round(max_time)) <= 1e-6:
        m_int = int(round(max_time))
        for cal_step in (3, 6, 12, 24):
            if m_int % cal_step == 0:
                k = m_int // cal_step
                if 4 <= k <= 5:
                    return [float(i * cal_step) for i in range(k + 1)]

    raw_step = max_time / 5.0
    exp10 = 10.0 ** math.floor(math.log10(raw_step))
    best_times: Optional[List[float]] = None
    best_overhang = float("inf")

    for scale in (0.1, 1.0, 10.0):
        base = exp10 * scale
        for mant in (1.0, 2.0, 2.5, 4.0, 5.0, 8.0, 10.0):
            step = mant * base
            if step <= 0.0:
                continue
            for k in (4, 5):
                top = step * float(k)
                if top + 1e-12 >= max_time:
                    overhang = top - max_time
                    if overhang < best_overhang - 1e-12:
                        best_overhang = overhang
                        best_times = [round(float(i) * step, 10) for i in range(k + 1)]

    if best_times is not None:
        best_times[0] = 0.0
        return best_times

    step_fb = max_time / 4.0
    return [round(float(i) * step_fb, 10) for i in range(5)]


def kaplan_meier_survival(
    groups: Sequence[Dict[str, Any]],
    risk_times: Optional[Sequence[float]] = None,
    conf_level: float = 0.95,
) -> Dict[str, Any]:
    """
    Compute Product-Limit Kaplan-Meier survival curves with Greenwood log-log (cloglog)
    confidence intervals, censored observation coordinates, median survival, multi-arm
    Mantel-Cox Log-Rank test, 2-arm Pike/Peto Hazard Ratio, and Number-at-Risk table.
    """
    if not groups or len(groups) == 0:
        raise ValueError("kaplan_meier_survival requires at least 1 group.")
    if not (0.0 < float(conf_level) < 1.0):
        raise ValueError(f"conf_level must be in (0, 1), got {conf_level!r}.")

    alpha = 1.0 - float(conf_level)
    z_crit = float(stats.norm.ppf(1.0 - 0.5 * alpha))

    cleaned_arms: List[Dict[str, Any]] = []
    max_all_time = 0.0

    for idx, g in enumerate(groups):
        if not isinstance(g, Mapping):
            raise TypeError(f"Group {idx} must be a mapping, got {type(g).__name__}.")
        name = str(g.get("name") or f"Arm {idx + 1}")
        t_seq = g.get("time")
        e_seq = g.get("event")
        if t_seq is None or e_seq is None:
            raise KeyError(f"Group {name!r} must provide 'time' and 'event' sequences.")

        t_raw = np.asarray(t_seq, dtype=float).ravel()
        e_raw = np.asarray(e_seq, dtype=float).ravel()
        if t_raw.size != e_raw.size:
            raise ValueError(
                f"Group {name!r} has mismatched 'time' ({t_raw.size}) and 'event' ({e_raw.size}) lengths."
            )

        valid = np.isfinite(t_raw) & np.isfinite(e_raw)
        t_arr = t_raw[valid]
        e_arr_f = e_raw[valid]
        if t_arr.size == 0:
            raise ValueError(f"Group {name!r} has 0 finite observations.")
        if np.any(t_arr < 0.0):
            raise ValueError(f"Group {name!r} contains negative survival time(s).")
        if not np.all(np.isin(e_arr_f, [0.0, 1.0])):
            raise ValueError(f"Group {name!r} 'event' values must be binary 0 (censored) or 1 (event).")

        e_arr = e_arr_f.astype(int)
        order = np.argsort(t_arr, kind="mergesort")
        t_arr = t_arr[order]
        e_arr = e_arr[order]

        max_arm_t = float(np.max(t_arr))
        if max_arm_t > max_all_time:
            max_all_time = max_arm_t

        cleaned_arms.append(
            {
                "name": name,
                "role": g.get("role"),
                "color": g.get("color"),
                "t": t_arr,
                "e": e_arr,
            }
        )

    arm_outputs: List[Dict[str, Any]] = []
    for arm in cleaned_arms:
        t_arr = arm["t"]
        e_arr = arm["e"]
        n_total = int(t_arr.size)
        n_events = int(np.sum(e_arr == 1))
        n_censored = int(n_total - n_events)

        event_times = np.unique(t_arr[e_arr == 1])
        step_time: List[float] = [0.0]
        survival: List[float] = [1.0]
        ci_low: List[float] = [1.0]
        ci_high: List[float] = [1.0]
        se_list: List[float] = [0.0]

        ev_t_eval: List[float] = []
        ev_s_eval: List[float] = []

        s_cur = 1.0
        v_logs = 0.0

        for tj_val in event_times:
            tj = float(tj_val)
            n_j = int(np.sum(t_arr >= tj))
            d_j = int(np.sum((t_arr == tj) & (e_arr == 1)))
            if n_j <= 0 or d_j <= 0:
                continue

            s_cur = s_cur * (1.0 - float(d_j) / float(n_j))
            if n_j > d_j:
                v_logs += float(d_j) / float(n_j * (n_j - d_j))

            if s_cur >= 1.0:
                c_lo, c_hi, se_s = 1.0, 1.0, 0.0
            elif s_cur <= 0.0 or n_j == d_j:
                s_cur = 0.0
                c_lo, c_hi, se_s = 0.0, 0.0, 0.0
            else:
                se_s = float(s_cur * math.sqrt(max(v_logs, 0.0)))
                if v_logs <= 0.0:
                    c_lo, c_hi = float(s_cur), float(s_cur)
                else:
                    se_theta = math.sqrt(v_logs) / abs(math.log(s_cur))
                    exp_pos = math.exp(min(z_crit * se_theta, 500.0))
                    exp_neg = math.exp(max(-z_crit * se_theta, -500.0))
                    c_lo = float(np.clip(s_cur ** exp_pos, 0.0, 1.0))
                    c_hi = float(np.clip(s_cur ** exp_neg, 0.0, 1.0))

            if tj == 0.0 and len(step_time) == 1 and step_time[0] == 0.0:
                step_time.append(0.0)
            else:
                step_time.append(tj)
            survival.append(float(s_cur))
            ci_low.append(float(c_lo))
            ci_high.append(float(c_hi))
            se_list.append(float(se_s))

            ev_t_eval.append(tj)
            ev_s_eval.append(float(s_cur))

        max_arm_t = float(np.max(t_arr))
        if max_arm_t > step_time[-1]:
            step_time.append(max_arm_t)
            survival.append(survival[-1])
            ci_low.append(ci_low[-1])
            ci_high.append(ci_high[-1])
            se_list.append(se_list[-1])

        ev_t_np = np.asarray(ev_t_eval, dtype=float)
        cens_t_arr = t_arr[e_arr == 0]
        cens_time_out: List[float] = []
        cens_surv_out: List[float] = []
        for tc in cens_t_arr:
            tc_f = float(tc)
            if ev_t_np.size == 0:
                sc_f = 1.0
            else:
                pos = int(np.searchsorted(ev_t_np, tc_f, side="right")) - 1
                sc_f = 1.0 if pos < 0 else float(ev_s_eval[pos])
            cens_time_out.append(tc_f)
            cens_surv_out.append(sc_f)

        median_surv: Optional[float] = None
        for tj, sj in zip(ev_t_eval, ev_s_eval):
            if sj <= 0.5 + 1e-15:
                median_surv = float(tj)
                break

        arm_outputs.append(
            {
                "name": arm["name"],
                "role": arm["role"],
                "color": arm["color"],
                "n": n_total,
                "n_total": n_total,
                "n_events": n_events,
                "n_censored": n_censored,
                "time": step_time,
                "survival": survival,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "se": se_list,
                "censored_time": cens_time_out,
                "censored_surv": cens_surv_out,
                "median_survival": median_surv,
            }
        )

    n_groups = len(cleaned_arms)
    hazard_ratio_out: Optional[Dict[str, Any]] = None
    stat_rows: List[Dict[str, Any]] = []

    if n_groups >= 2:
        pooled_ev_list = [arm["t"][arm["e"] == 1] for arm in cleaned_arms if np.any(arm["e"] == 1)]
        pooled_times = np.unique(np.concatenate(pooled_ev_list)) if pooled_ev_list else np.asarray([], dtype=float)

        obs_vec = np.zeros(n_groups, dtype=float)
        exp_vec = np.zeros(n_groups, dtype=float)
        cov_mat = np.zeros((n_groups, n_groups), dtype=float)

        for tau_val in pooled_times:
            tau = float(tau_val)
            n_g = np.asarray([np.sum(arm["t"] >= tau) for arm in cleaned_arms], dtype=float)
            d_g = np.asarray(
                [np.sum((arm["t"] == tau) & (arm["e"] == 1)) for arm in cleaned_arms],
                dtype=float,
            )
            n_tot_t = float(np.sum(n_g))
            d_tot_t = float(np.sum(d_g))
            if n_tot_t <= 0.0 or d_tot_t <= 0.0:
                continue

            e_g = d_tot_t * (n_g / n_tot_t)
            obs_vec += d_g
            exp_vec += e_g

            if n_tot_t > 1.0:
                factor = (d_tot_t * (n_tot_t - d_tot_t)) / ((n_tot_t ** 2) * (n_tot_t - 1.0))
                cov_t = -factor * np.outer(n_g, n_g)
                diag_vals = factor * n_g * (n_tot_t - n_g)
                np.fill_diagonal(cov_t, diag_vals)
                cov_mat += cov_t

        df_lr = n_groups - 1
        u_sub = (obs_vec - exp_vec)[:df_lr]
        v_sub = cov_mat[:df_lr, :df_lr]
        if pooled_times.size == 0 or float(np.max(np.abs(v_sub))) <= 1e-15:
            chi2_val = 0.0
            p_lr = 1.0
        else:
            v_inv = np.linalg.pinv(v_sub, rcond=1e-12)
            chi2_val = max(0.0, float(u_sub @ v_inv @ u_sub))
            p_lr = float(np.clip(stats.chi2.sf(chi2_val, df=df_lr), 0.0, 1.0))

        logrank_out: Dict[str, Any] = {
            "chi2": chi2_val,
            "df": int(df_lr),
            "p_value": p_lr,
            "stars": p_to_stars(p_lr),
            "observed": [float(x) for x in obs_vec],
            "expected": [float(x) for x in exp_vec],
        }

        if n_groups == 2:
            arm0_name = cleaned_arms[0]["name"]
            arm1_name = cleaned_arms[1]["name"]
            o0, o1 = float(obs_vec[0]), float(obs_vec[1])
            e0, e1 = float(exp_vec[0]), float(exp_vec[1])
            v00 = float(cov_mat[0, 0])

            if o0 > 0.0 and o1 > 0.0 and e0 > 0.0 and e1 > 0.0:
                hr_val = float((o0 / e0) / (o1 / e1))
                se_log_hr = math.sqrt(1.0 / e0 + 1.0 / e1)
                log_hr = math.log(hr_val)
                hr_lo = float(math.exp(log_hr - z_crit * se_log_hr))
                hr_hi = float(math.exp(log_hr + z_crit * se_log_hr))
                hr_method = "Pike Mantel-Haenszel"
            elif v00 > 1e-12:
                log_hr = float((o0 - e0) / v00)
                se_log_hr = 1.0 / math.sqrt(v00)
                hr_val = float(math.exp(log_hr))
                hr_lo = float(math.exp(log_hr - z_crit * se_log_hr))
                hr_hi = float(math.exp(log_hr + z_crit * se_log_hr))
                hr_method = "Peto one-step"
            else:
                hr_val = 1.0
                hr_lo = None
                hr_hi = None
                hr_method = "Undefined (zero events)"

            hazard_ratio_out = {
                "hr_comparison": f"{arm0_name} vs {arm1_name}",
                "hr": hr_val,
                "hr_ci_low": hr_lo,
                "hr_ci_high": hr_hi,
                "conf_level": float(conf_level),
                "method": hr_method,
            }

            stat_rows.append(
                {
                    "Panel": "Figure",
                    "Group_1": arm0_name,
                    "Group_2": arm1_name,
                    "Test_Method": "Mantel-Cox Log-Rank",
                    "Statistic": chi2_val,
                    "df": int(df_lr),
                    "p_raw": p_lr,
                    "p_adj": p_lr,
                    "p_adjust_method": "none",
                    "Significance": p_to_stars(p_lr),
                    "Significant": bool(p_lr < alpha),
                    "Effect_Size": hr_val,
                    "Effect_Type": "Hazard_Ratio",
                    "CI_Low": hr_lo,
                    "CI_High": hr_hi,
                    "Omnibus_Test": "Mantel-Cox Log-Rank",
                    "Omnibus_Statistic": chi2_val,
                    "Omnibus_p": p_lr,
                }
            )
        else:
            stat_rows.append(
                {
                    "Panel": "Figure",
                    "Group_1": "All_Arms",
                    "Group_2": "All_Arms",
                    "Test_Method": "Mantel-Cox Log-Rank",
                    "Statistic": chi2_val,
                    "df": int(df_lr),
                    "p_raw": p_lr,
                    "p_adj": p_lr,
                    "p_adjust_method": "none",
                    "Significance": p_to_stars(p_lr),
                    "Significant": bool(p_lr < alpha),
                    "Effect_Size": None,
                    "Effect_Type": "",
                    "CI_Low": None,
                    "CI_High": None,
                    "Omnibus_Test": "Mantel-Cox Log-Rank",
                    "Omnibus_Statistic": chi2_val,
                    "Omnibus_p": p_lr,
                }
            )
    else:
        logrank_out = {
            "chi2": None,
            "df": 0,
            "p_value": None,
            "stars": "ns",
            "observed": [float(arm_outputs[0]["n_events"])],
            "expected": [float(arm_outputs[0]["n_events"])],
        }

    if risk_times is not None:
        r_times = sorted({float(t) for t in risk_times if math.isfinite(float(t)) and float(t) >= 0.0})
        if not r_times:
            r_times = _auto_risk_times(max_all_time)
    else:
        r_times = _auto_risk_times(max_all_time)

    risk_rows: List[Dict[str, Any]] = []
    for arm in cleaned_arms:
        counts = [int(np.sum(arm["t"] >= tr)) for tr in r_times]
        risk_rows.append({"name": arm["name"], "counts": counts})

    return {
        "arms": arm_outputs,
        "logrank": logrank_out,
        "hazard_ratio": hazard_ratio_out,
        "at_risk_table": {
            "times": r_times,
            "rows": risk_rows,
        },
        "stat_rows": stat_rows,
    }


def _hanley_mcneil_ci(
    auroc: float,
    n_pos: int,
    n_neg: int,
    conf_level: float = 0.95,
) -> Tuple[float, float, float, float, float]:
    """Return (se_auc, ci_low, ci_high, z_vs_chance, p_vs_chance) via Hanley & McNeil (1982)."""
    auc_c = float(np.clip(auroc, 0.0, 1.0))
    np_f = float(max(int(n_pos), 1))
    nn_f = float(max(int(n_neg), 1))

    q1 = auc_c / (2.0 - auc_c)
    q2 = (2.0 * auc_c * auc_c) / (1.0 + auc_c)
    var_auc = (
        auc_c * (1.0 - auc_c)
        + (np_f - 1.0) * (q1 - auc_c * auc_c)
        + (nn_f - 1.0) * (q2 - auc_c * auc_c)
    ) / (np_f * nn_f)
    se_auc = math.sqrt(max(var_auc, 0.0))

    alpha = 1.0 - float(conf_level)
    z_crit = float(stats.norm.ppf(1.0 - 0.5 * alpha))
    ci_low = float(np.clip(auc_c - z_crit * se_auc, 0.0, 1.0))
    ci_high = float(np.clip(auc_c + z_crit * se_auc, 0.0, 1.0))

    se_null = math.sqrt((np_f + nn_f + 1.0) / (12.0 * np_f * nn_f))
    z_stat = float((auc_c - 0.5) / se_null) if se_null > 0.0 else 0.0
    p_val = float(np.clip(2.0 * stats.norm.sf(abs(z_stat)), 0.0, 1.0))
    return se_auc, ci_low, ci_high, z_stat, p_val


def compute_roc_pr_curves(
    models: Sequence[Dict[str, Any]],
    conf_level: float = 0.95,
) -> Dict[str, Any]:
    """
    Compute exact unique-threshold ROC and Precision-Recall curves, trapezoidal AUROC/AUPRC,
    Hanley-McNeil (1982) analytic confidence intervals, and Youden's optimal operating point.
    """
    if not models or len(models) == 0:
        raise ValueError("compute_roc_pr_curves requires at least 1 model entry.")
    if not (0.0 < float(conf_level) < 1.0):
        raise ValueError(f"conf_level must be in (0, 1), got {conf_level!r}.")

    alpha = 1.0 - float(conf_level)
    curves: List[Dict[str, Any]] = []
    raw_stat_items: List[Dict[str, Any]] = []

    for idx, cfg in enumerate(models):
        if not isinstance(cfg, Mapping):
            raise TypeError(f"Model {idx} must be a mapping, got {type(cfg).__name__}.")
        name = str(cfg.get("name") or f"Model {idx + 1}")
        color = cfg.get("color")

        if cfg.get("y_true") is not None and cfg.get("y_score") is not None:
            yt_raw = np.asarray(cfg["y_true"], dtype=float).ravel()
            ys_raw = np.asarray(cfg["y_score"], dtype=float).ravel()
            if yt_raw.size != ys_raw.size:
                raise ValueError(
                    f"Model {name!r} has mismatched 'y_true' ({yt_raw.size}) and 'y_score' ({ys_raw.size}) lengths."
                )
            valid = np.isfinite(yt_raw) & np.isfinite(ys_raw)
            yt_f = yt_raw[valid]
            ys = ys_raw[valid]
            if yt_f.size < 2:
                raise ValueError(f"Model {name!r} requires at least 2 finite observations.")
            if not np.all(np.isin(yt_f, [0.0, 1.0])):
                raise ValueError(f"Model {name!r} 'y_true' must contain binary labels in {{0, 1}}.")

            yt = yt_f.astype(int)
            n_pos = int(np.sum(yt == 1))
            n_neg = int(np.sum(yt == 0))
            if n_pos == 0 or n_neg == 0:
                raise ValueError(
                    f"Model {name!r} has single-class 'y_true' degeneracy (n_pos={n_pos}, n_neg={n_neg}); "
                    "ROC requires both positive and negative samples."
                )

            order = np.argsort(-ys, kind="mergesort")
            ys_sorted = ys[order]
            yt_sorted = yt[order]

            distinct_idx = np.where(np.diff(ys_sorted) != 0.0)[0]
            thresh_idxs = np.r_[distinct_idx, yt_sorted.size - 1]

            tps = np.cumsum(yt_sorted, dtype=float)[thresh_idxs]
            fps = (1.0 + thresh_idxs.astype(float)) - tps
            thresh_vals = ys_sorted[thresh_idxs]

            fpr_arr = np.r_[0.0, fps / float(n_neg)]
            tpr_arr = np.r_[0.0, tps / float(n_pos)]
            thresholds_arr = np.r_[float(ys_sorted[0]) + 1.0, thresh_vals]

            auroc = float(np.clip(_trapz_1d(tpr_arr, fpr_arr), 0.0, 1.0))
            se_auc, ci_lo, ci_hi, z_stat, p_val = _hanley_mcneil_ci(auroc, n_pos, n_neg, conf_level=conf_level)

            j_arr = tpr_arr - fpr_arr
            if j_arr.size > 2:
                best_rel = int(np.argmax(j_arr[1:]))
                best_idx = best_rel + 1
            else:
                best_idx = int(np.argmax(j_arr))

            youden_dict: Dict[str, Any] = {
                "fpr": float(fpr_arr[best_idx]),
                "tpr": float(tpr_arr[best_idx]),
                "threshold": float(thresholds_arr[best_idx]),
                "youden_j": float(j_arr[best_idx]),
            }

            prec_core = tps / np.maximum(tps + fps, 1.0)
            rec_core = tps / float(n_pos)
            recall_arr = np.r_[0.0, rec_core]
            precision_arr = np.r_[1.0, prec_core]
            auprc = float(np.clip(_trapz_1d(precision_arr, recall_arr), 0.0, 1.0))
            pos_rate = float(n_pos / float(n_pos + n_neg))

            curves.append(
                {
                    "name": name,
                    "color": color,
                    "fpr": [float(x) for x in fpr_arr],
                    "tpr": [float(x) for x in tpr_arr],
                    "thresholds": [float(x) for x in thresholds_arr],
                    "auroc": auroc,
                    "se_auc": se_auc,
                    "ci_low": ci_lo,
                    "ci_high": ci_hi,
                    "youden": youden_dict,
                    "optimal_point": dict(youden_dict),
                    "recall": [float(x) for x in recall_arr],
                    "precision": [float(x) for x in precision_arr],
                    "auprc": auprc,
                    "pos_rate": pos_rate,
                    "n_pos": n_pos,
                    "n_neg": n_neg,
                    "p_value": p_val,
                }
            )
            raw_stat_items.append(
                {
                    "name": name,
                    "z_stat": z_stat,
                    "p_raw": p_val,
                    "auroc": auroc,
                    "ci_low": ci_lo,
                    "ci_high": ci_hi,
                }
            )

        elif cfg.get("fpr") is not None and cfg.get("tpr") is not None:
            fpr_in = np.asarray(cfg["fpr"], dtype=float).ravel()
            tpr_in = np.asarray(cfg["tpr"], dtype=float).ravel()
            if fpr_in.size != tpr_in.size or fpr_in.size < 2:
                raise ValueError(f"Precomputed ROC model {name!r} requires matching fpr/tpr of length >= 2.")
            valid = np.isfinite(fpr_in) & np.isfinite(tpr_in)
            fpr_c = np.clip(fpr_in[valid], 0.0, 1.0)
            tpr_c = np.clip(tpr_in[valid], 0.0, 1.0)
            order = np.lexsort((tpr_c, fpr_c))
            fpr_c = fpr_c[order]
            tpr_c = tpr_c[order]

            if fpr_c[0] > 0.0 or tpr_c[0] > 0.0:
                fpr_c = np.r_[0.0, fpr_c]
                tpr_c = np.r_[0.0, tpr_c]
            if fpr_c[-1] < 1.0 or tpr_c[-1] < 1.0:
                fpr_c = np.r_[fpr_c, 1.0]
                tpr_c = np.r_[tpr_c, 1.0]

            n_pos = int(cfg.get("n_pos", 100))
            n_neg = int(cfg.get("n_neg", 100))
            if n_pos <= 0 or n_neg <= 0:
                raise ValueError(f"Precomputed ROC model {name!r} requires positive n_pos and n_neg.")

            auroc = float(np.clip(_trapz_1d(tpr_c, fpr_c), 0.0, 1.0))
            se_auc, ci_lo, ci_hi, z_stat, p_val = _hanley_mcneil_ci(auroc, n_pos, n_neg, conf_level=conf_level)

            j_arr = tpr_c - fpr_c
            best_idx = int(np.argmax(j_arr))
            youden_dict = {
                "fpr": float(fpr_c[best_idx]),
                "tpr": float(tpr_c[best_idx]),
                "threshold": None,
                "youden_j": float(j_arr[best_idx]),
            }

            rec_in = cfg.get("recall")
            prec_in = cfg.get("precision")
            if rec_in is not None and prec_in is not None:
                rec_arr = np.clip(np.asarray(rec_in, dtype=float).ravel(), 0.0, 1.0)
                prec_arr = np.clip(np.asarray(prec_in, dtype=float).ravel(), 0.0, 1.0)
                rec_order = np.argsort(rec_arr, kind="mergesort")
                rec_arr = rec_arr[rec_order]
                prec_arr = prec_arr[rec_order]
                auprc_val: Optional[float] = float(np.clip(_trapz_1d(prec_arr, rec_arr), 0.0, 1.0))
                rec_list: Optional[List[float]] = [float(x) for x in rec_arr]
                prec_list: Optional[List[float]] = [float(x) for x in prec_arr]
            else:
                auprc_val = float(cfg["auprc"]) if cfg.get("auprc") is not None else None
                rec_list = None
                prec_list = None

            pos_rate = float(n_pos / float(n_pos + n_neg))
            curves.append(
                {
                    "name": name,
                    "color": color,
                    "fpr": [float(x) for x in fpr_c],
                    "tpr": [float(x) for x in tpr_c],
                    "thresholds": None,
                    "auroc": auroc,
                    "se_auc": se_auc,
                    "ci_low": ci_lo,
                    "ci_high": ci_hi,
                    "youden": youden_dict,
                    "optimal_point": dict(youden_dict),
                    "recall": rec_list,
                    "precision": prec_list,
                    "auprc": auprc_val,
                    "pos_rate": pos_rate,
                    "n_pos": n_pos,
                    "n_neg": n_neg,
                    "p_value": p_val,
                }
            )
            raw_stat_items.append(
                {
                    "name": name,
                    "z_stat": z_stat,
                    "p_raw": p_val,
                    "auroc": auroc,
                    "ci_low": ci_lo,
                    "ci_high": ci_hi,
                }
            )
        else:
            raise KeyError(
                f"Model {name!r} must supply either ('y_true', 'y_score') or precomputed ('fpr', 'tpr')."
            )

    padj_method = "fdr_bh" if len(raw_stat_items) > 1 else "none"
    p_adj_list = adjust_pvalues([it["p_raw"] for it in raw_stat_items], method=padj_method)
    stat_rows: List[Dict[str, Any]] = []
    for it, p_adj in zip(raw_stat_items, p_adj_list):
        stat_rows.append(
            {
                "Panel": "Figure",
                "Group_1": it["name"],
                "Group_2": "Chance (0.5)",
                "Test_Method": "Hanley-McNeil AUROC",
                "Statistic": it["z_stat"],
                "df": None,
                "p_raw": it["p_raw"],
                "p_adj": p_adj,
                "p_adjust_method": padj_method,
                "Significance": p_to_stars(p_adj),
                "Significant": bool(p_adj < alpha),
                "Effect_Size": it["auroc"],
                "Effect_Type": "AUROC",
                "CI_Low": it["ci_low"],
                "CI_High": it["ci_high"],
                "Omnibus_Test": "none",
                "Omnibus_Statistic": None,
                "Omnibus_p": None,
            }
        )

    return {
        "curves": curves,
        "stat_rows": stat_rows,
    }


def bland_altman_stats(
    method_a: Sequence[float],
    method_b: Sequence[float],
    sd_mult: float = 1.96,
) -> Dict[str, Any]:
    """
    Compute Bland-Altman method-comparison agreement metrics: pairwise means, differences (A - B),
    mean bias, SD of differences, Limits of Agreement (bias ± sd_mult * SD), and paired t-test p_bias.
    """
    a_raw = np.asarray(method_a, dtype=float).ravel()
    b_raw = np.asarray(method_b, dtype=float).ravel()
    if a_raw.size != b_raw.size:
        raise ValueError(
            f"bland_altman_stats requires equal lengths for method_a ({a_raw.size}) and method_b ({b_raw.size})."
        )
    valid = np.isfinite(a_raw) & np.isfinite(b_raw)
    a = a_raw[valid]
    b = b_raw[valid]
    if a.size < 2:
        raise ValueError("bland_altman_stats requires at least 2 finite paired observations.")

    means = 0.5 * (a + b)
    diffs = a - b
    bias = float(np.mean(diffs))
    sd_diff = float(np.std(diffs, ddof=1))
    mult = float(sd_mult)
    loa_low = float(bias - mult * sd_diff)
    loa_high = float(bias + mult * sd_diff)

    if float(np.ptp(diffs)) <= 0.0:
        p_bias = 1.0 if abs(bias) <= 1e-15 else 0.0
    else:
        res = stats.ttest_rel(a, b)
        p_bias = float(np.clip(res.pvalue, 0.0, 1.0)) if math.isfinite(float(res.pvalue)) else 1.0

    return {
        "n": int(a.size),
        "means": [float(x) for x in means],
        "diffs": [float(x) for x in diffs],
        "bias": bias,
        "sd_diff": sd_diff,
        "sd_mult": mult,
        "loa_low": loa_low,
        "loa_high": loa_high,
        "p_bias": p_bias,
    }


__all__ = [
    "p_to_stars",
    "adjust_pvalues",
    "aggregate_replicates",
    "summarize_groups",
    "run_group_comparisons",
    "compute_sig_bracket_tiers",
    "kaplan_meier_survival",
    "compute_roc_pr_curves",
    "bland_altman_stats",
]
