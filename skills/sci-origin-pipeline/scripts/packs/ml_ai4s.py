"""
Machine Learning, AI4Science & Model Benchmarks Domain Pack (`ml_ai4s`).

Provides:
- `parse_jsonl_metrics`: parses ML training `.jsonl` logs (`step`/`epoch`, scalar metrics
  across random `seed`s/`run`s -> aggregated `mean ± SD` learning curves).
- Ablation CI table (`variant`/`model` + `mean` + `ci_low`/`ci_high`) sniffer.
- Binary classification ROC score table (`y_true` + `y_score`) sniffer.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


PACK_ID = "ml_ai4s"
DISPLAY_NAME_ZH = "机器学习、AI4Science 与模型评测"
DISPLAY_NAME_EN = "Machine Learning, AI4Science & Benchmarks"
MODALITIES = (
    "training_jsonl",
    "ablation_ci",
    "roc_scores",
    "radar_benchmark",
)
EXTENSIONS = (
    ".jsonl",
    ".csv",
    ".tsv",
    ".xlsx",
)
RECOMMENDED_MODES = (
    "roc_pr_curve",
    "forest_ablation_plot",
    "polar_radar_plot",
    "line_with_band",
)

_STEP_KEYS = ("step", "global_step", "iter", "iteration", "epoch")
_SEED_KEYS = ("seed", "run", "run_id", "fold", "trial")
_GROUP_KEYS = ("model", "variant", "method", "config")

_ABLATION_NAME_COLS = {"variant", "model", "ablation", "method", "setting"}
_ABLATION_MEAN_COLS = {"mean", "effect", "delta", "score", "estimate", "metric"}
_ABLATION_CI_PAIRS = ({"ci_low", "ci_high"}, {"lower", "upper"}, {"ci_lower", "ci_upper"})

_ROC_TRUE_COLS = {"y_true", "label", "target", "ground_truth", "is_positive"}
_ROC_SCORE_COLS = {"y_score", "score", "prob", "y_prob", "pred_prob", "logit"}


def _is_numeric_scalar(val: Any) -> bool:
    if isinstance(val, bool) or val is None:
        return False
    if isinstance(val, (int, float, np.number)):
        return math.isfinite(float(val))
    return False


def _aggregate_step_buckets(buckets: Dict[float, List[float]]) -> Dict[str, np.ndarray]:
    xs = sorted(buckets.keys())
    means: List[float] = []
    sds: List[float] = []
    sems: List[float] = []
    mins: List[float] = []
    maxs: List[float] = []
    ns: List[int] = []

    for x_v in xs:
        arr = np.asarray(buckets[x_v], dtype=float)
        n = int(arr.size)
        m_v = float(np.mean(arr))
        sd_v = float(np.std(arr, ddof=1)) if n >= 2 else 0.0
        sem_v = float(sd_v / math.sqrt(float(n))) if n >= 2 else 0.0
        means.append(m_v)
        sds.append(sd_v)
        sems.append(sem_v)
        mins.append(float(np.min(arr)))
        maxs.append(float(np.max(arr)))
        ns.append(n)

    return {
        "x": np.asarray(xs, dtype=float),
        "mean": np.asarray(means, dtype=float),
        "sd": np.asarray(sds, dtype=float),
        "sem": np.asarray(sems, dtype=float),
        "min": np.asarray(mins, dtype=float),
        "max": np.asarray(maxs, dtype=float),
        "n": np.asarray(ns, dtype=int),
    }


def parse_jsonl_metrics(filepath: str | Path) -> Dict[str, Any]:
    """
    Parse ML training `.jsonl` metric logs across steps/epochs and random seeds into
    Origin-ready `mean ± SD` curve arrays.
    """
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"JSONL metrics file not found: {p}")

    records: List[Dict[str, Any]] = []
    for line_no, raw_line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        s = raw_line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON on line {line_no} of {p.name}: {exc}") from exc
        if isinstance(obj, dict):
            records.append(obj)

    if not records:
        raise ValueError(f"JSONL file {p.name} contains 0 JSON object records.")

    x_key = "step"
    for cand in _STEP_KEYS:
        if any(_is_numeric_scalar(r.get(cand)) for r in records):
            x_key = cand
            break

    seed_key: Optional[str] = None
    for cand in _SEED_KEYS:
        if any(cand in r and r[cand] is not None for r in records):
            seed_key = cand
            break

    group_key: Optional[str] = None
    for cand in _GROUP_KEYS:
        vals = {str(r[cand]) for r in records if cand in r and r[cand] is not None}
        if len(vals) >= 1:
            group_key = cand
            break

    excluded_keys = set(_STEP_KEYS) | set(_SEED_KEYS) | set(_GROUP_KEYS) | {"timestamp", "wall_time", "lr_schedule"}
    metric_buckets: Dict[str, Dict[float, List[float]]] = {}
    group_metric_buckets: Dict[str, Dict[str, Dict[float, List[float]]]] = {}
    unique_seeds: List[str] = []

    for idx, rec in enumerate(records):
        x_val = float(rec[x_key]) if _is_numeric_scalar(rec.get(x_key)) else float(idx)
        s_id = str(rec[seed_key]) if (seed_key and rec.get(seed_key) is not None) else "0"
        if s_id not in unique_seeds:
            unique_seeds.append(s_id)
        g_name = str(rec[group_key]) if (group_key and rec.get(group_key) is not None) else "default"

        for k, v in rec.items():
            if k in excluded_keys or not _is_numeric_scalar(v):
                continue
            vf = float(v)
            metric_buckets.setdefault(k, {}).setdefault(x_val, []).append(vf)
            group_metric_buckets.setdefault(g_name, {}).setdefault(k, {}).setdefault(x_val, []).append(vf)

    if not metric_buckets:
        raise ValueError(f"No finite scalar metrics found in JSONL log {p.name}.")

    metrics_out = {m_name: _aggregate_step_buckets(b_map) for m_name, b_map in metric_buckets.items()}
    groups_out = {
        g_name: {m_name: _aggregate_step_buckets(b_map) for m_name, b_map in m_dict.items()}
        for g_name, m_dict in group_metric_buckets.items()
    }

    return {
        "pack_id": PACK_ID,
        "modality": "training_jsonl",
        "recommended_mode": "line_with_band",
        "file": str(p),
        "x_key": x_key,
        "seed_key": seed_key,
        "group_key": group_key,
        "n_records": len(records),
        "n_seeds": len(unique_seeds),
        "seeds": unique_seeds,
        "metric_names": list(metrics_out.keys()),
        "metrics": metrics_out,
        "groups": groups_out,
    }


def sniff_ml_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Sniff `.jsonl` ML training logs, ablation CI tables, or ROC score tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext == ".jsonl":
        return {
            "pack_id": PACK_ID,
            "modality": "training_jsonl",
            "recommended_mode": "line_with_band",
            "extension": ext,
            "confidence": "high",
        }

    if ext in (".csv", ".tsv", ".xlsx") and p.exists() and p.is_file():
        try:
            df0 = pd.read_excel(p, nrows=3) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","), nrows=3)
        except Exception:
            return None
        low_set = {str(c).strip().lower() for c in df0.columns}

        if (low_set & _ROC_TRUE_COLS) and (low_set & _ROC_SCORE_COLS):
            return {
                "pack_id": PACK_ID,
                "modality": "roc_scores",
                "recommended_mode": "roc_pr_curve",
                "extension": ext,
                "confidence": "high",
            }

        has_ci = any(pair <= low_set for pair in _ABLATION_CI_PAIRS) or bool(low_set & {"ci95", "se", "sd"})
        if (low_set & _ABLATION_NAME_COLS) and (low_set & _ABLATION_MEAN_COLS) and has_ci:
            return {
                "pack_id": PACK_ID,
                "modality": "ablation_ci",
                "recommended_mode": "forest_ablation_plot",
                "extension": ext,
                "confidence": "high",
            }

    return None


def parse_ml_file(filepath: str | Path) -> Dict[str, Any]:
    """Parse `.jsonl` ML logs or ablation/ROC benchmark tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext == ".jsonl":
        return parse_jsonl_metrics(p)

    if not p.exists():
        raise FileNotFoundError(f"ML benchmark file not found: {p}")
    sniff = sniff_ml_file(p)
    df = pd.read_excel(p) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","))
    return {
        "pack_id": PACK_ID,
        "modality": sniff["modality"] if sniff else "ml_table",
        "recommended_mode": sniff["recommended_mode"] if sniff else "forest_ablation_plot",
        "file": str(p),
        "n_rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "head_preview": df.head(5).to_dict(orient="records"),
    }


def validate_ml_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Audit ML ROC single-class degeneracy, single-seed training curves, and CI bounds."""
    scripts_dir = str(Path(__file__).resolve().parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib

    val_mod = importlib.import_module("validator")
    findings: List[Dict[str, str]] = list(val_mod.audit_survival_and_roc(payload))

    if payload.get("modality") == "training_jsonl" and int(payload.get("n_seeds", 1)) < 2:
        findings.append(
            {
                "level": "INFO_SINGLE_SEED_CURVE",
                "region": "ML_Training_Log",
                "detail": "Training log contains only 1 random seed; SD band is 0 (log >= 3 seeds for variance bands).",
            }
        )

    for idx, row in enumerate(payload.get("items") or payload.get("rows") or []):
        if isinstance(row, dict) and row.get("ci_low") is not None and row.get("ci_high") is not None:
            lo, hi = float(row["ci_low"]), float(row["ci_high"])
            if lo > hi:
                findings.append(
                    {
                        "level": "ERROR_INVERTED_CI_BOUNDS",
                        "region": str(row.get("name") or f"Row_{idx + 1}"),
                        "detail": f"ci_low ({lo}) exceeds ci_high ({hi}).",
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
    "parse_jsonl_metrics",
    "sniff_ml_file",
    "parse_ml_file",
    "validate_ml_payload",
]
