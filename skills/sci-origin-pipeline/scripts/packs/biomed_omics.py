"""
Biomedicine, Clinical Survival & Multi-Omics Domain Pack (`biomed_omics`).

Provides:
- Clinical survival (`time` + `event`/`status`), Volcano DEG (`log2fc` + `pval`/`padj`),
  and Dose-Response (`conc` + `viability`) tabular column sniffers & readers.
- ISAC Flow Cytometry Standard `.fcs` (`FCS2.0` / `FCS3.0` / `FCS3.1` / `FCS3.2`) ASCII
  header & parameter channel parser (`$PAR`, `$TOT`, `$P1N..$PkN`).
- Lightweight `.mzML` mass-spectrometry and `.h5ad` AnnData container metadata inspectors.
- `audit_survival_and_roc` statistical degeneracy & event-count validator.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


PACK_ID = "biomed_omics"
DISPLAY_NAME_ZH = "生物医学、临床统计与多组学"
DISPLAY_NAME_EN = "Biomedicine, Clinical Survival & Multi-Omics"
MODALITIES = (
    "survival_km",
    "volcano_deg",
    "dose_response",
    "roc_diagnostic",
    "flow_cytometry_fcs",
    "mass_spec_mzml",
    "single_cell_h5ad",
)
EXTENSIONS = (
    ".fcs",
    ".mzml",
    ".h5ad",
    ".csv",
    ".tsv",
    ".xlsx",
)
RECOMMENDED_MODES = (
    "kaplan_meier_plot",
    "volcano_plot",
    "dose_response_4pl",
    "roc_pr_curve",
    "stat_bar_dot_sig",
    "stat_violin_raincloud",
)

_SURV_TIME_COLS = {
    "time", "os_time", "pfs_time", "dfs_time", "efs_time", "survival_time",
    "followup_time", "follow_up_time", "futime", "months", "time_months", "time_days",
}
_SURV_EVENT_COLS = {
    "event", "status", "os_event", "pfs_event", "censored", "vital_status",
    "death", "fustat", "is_event", "relapse",
}
_VOLCANO_FC_COLS = {
    "log2fc", "log2foldchange", "log2_fc", "log2_fold_change", "logfc", "lfc", "avg_log2fc",
}
_VOLCANO_P_COLS = {
    "pval", "pvalue", "p_val", "p_value", "padj", "p_adj", "p_val_adj",
    "fdr", "qval", "q_value", "adj.p.val",
}
_DOSE_X_COLS = {
    "conc", "concentration", "dose", "log_conc", "log10_conc", "conc_nm",
    "conc_um", "drug_conc", "inhibitor_conc",
}
_DOSE_Y_COLS = {
    "viability", "cell_viability", "pct_viability", "response", "inhibition",
    "pct_inhibition", "activity", "relative_viability",
}


def _load_validator_fn():
    scripts_dir = str(Path(__file__).resolve().parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib

    val_mod = importlib.import_module("validator")
    return val_mod.audit_survival_and_roc


def audit_survival_and_roc(payload: Any) -> List[Dict[str, str]]:
    """Validate KM survival event counts/censoring and ROC class balance."""
    fn = _load_validator_fn()
    return fn(payload)


def _split_fcs_text_segment(text: str) -> Dict[str, str]:
    """Parse FCS primary TEXT segment key/value pairs using the first byte delimiter."""
    if not text:
        return {}
    delim = text[0]
    body = text[1:]
    tokens: List[str] = []
    cur: List[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == delim:
            if i + 1 < n and body[i + 1] == delim:
                cur.append(delim)
                i += 2
                continue
            tokens.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(ch)
            i += 1
    if cur:
        tokens.append("".join(cur))

    kv: Dict[str, str] = {}
    for idx in range(0, len(tokens) - 1, 2):
        k = tokens[idx].strip().upper()
        v = tokens[idx + 1].strip()
        if k:
            kv[k] = v
    return kv


def parse_fcs_header(filepath: str | Path) -> Dict[str, Any]:
    """
    Read standard ISAC Flow Cytometry Standard `.fcs` (`FCS2.0` / `FCS3.0` / `FCS3.1` / `FCS3.2`)
    58-byte ASCII header offsets and primary `TEXT` segment metadata (`$PAR`, `$TOT`, `$P1N..`).
    """
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"FCS file not found: {p}")

    with p.open("rb") as fh:
        hdr = fh.read(58)
        if len(hdr) < 58:
            raise ValueError(f"Invalid FCS file {p.name}: header shorter than 58 bytes ({len(hdr)} B).")
        version = hdr[:6].decode("ascii", errors="replace").strip()
        if not version.upper().startswith("FCS"):
            raise ValueError(f"Invalid FCS magic version {version!r} in {p.name}; expected 'FCS3.0'/'FCS3.1'.")

        def _parse_offset(b_slice: bytes, field_name: str) -> int:
            s = b_slice.decode("ascii", errors="replace").strip()
            if not s:
                return 0
            try:
                return int(s)
            except ValueError as exc:
                raise ValueError(f"Malformed FCS {field_name} offset {s!r} in {p.name}.") from exc

        text_start = _parse_offset(hdr[10:18], "TEXT_START")
        text_end = _parse_offset(hdr[18:26], "TEXT_END")
        data_start = _parse_offset(hdr[26:34], "DATA_START")
        data_end = _parse_offset(hdr[34:42], "DATA_END")
        ana_start = _parse_offset(hdr[42:50], "ANALYSIS_START")
        ana_end = _parse_offset(hdr[50:58], "ANALYSIS_END")

        if text_start <= 0 or text_end < text_start:
            raise ValueError(f"Invalid FCS TEXT segment offsets [{text_start}, {text_end}] in {p.name}.")

        fh.seek(text_start)
        text_bytes = fh.read(text_end - text_start + 1)

    text_str = text_bytes.decode("utf-8", errors="replace")
    kv = _split_fcs_text_segment(text_str)

    if data_start == 0 and "$BEGINDATA" in kv:
        data_start = int(kv["$BEGINDATA"].strip() or 0)
    if data_end == 0 and "$ENDDATA" in kv:
        data_end = int(kv["$ENDDATA"].strip() or 0)

    n_par = int(kv.get("$PAR", "0") or 0)
    n_tot = int(kv.get("$TOT", "0") or 0)

    channels: List[Dict[str, Any]] = []
    channel_names: List[str] = []
    for i in range(1, n_par + 1):
        short_name = kv.get(f"$P{i}N", f"P{i}")
        stain_name = kv.get(f"$P{i}S")
        rng_val = kv.get(f"$P{i}R")
        bits_val = kv.get(f"$P{i}B")
        channel_names.append(short_name)
        channels.append(
            {
                "index": i,
                "name": short_name,
                "label": stain_name,
                "range": int(float(rng_val)) if rng_val and re.match(r"^[+-]?\d+(?:\.\d+)?$", rng_val) else rng_val,
                "bits": int(bits_val) if bits_val and bits_val.isdigit() else bits_val,
            }
        )

    return {
        "pack_id": PACK_ID,
        "modality": "flow_cytometry_fcs",
        "file": str(p),
        "version": version,
        "offsets": {
            "text_start": text_start,
            "text_end": text_end,
            "data_start": data_start,
            "data_end": data_end,
            "analysis_start": ana_start,
            "analysis_end": ana_end,
        },
        "n_parameters": n_par,
        "n_events": n_tot,
        "datatype": kv.get("$DATATYPE", ""),
        "mode": kv.get("$MODE", ""),
        "byte_order": kv.get("$BYTEORD", ""),
        "cytometer": kv.get("$CYT"),
        "channel_names": channel_names,
        "channels": channels,
        "recommended_mode": "stat_violin_raincloud",
        "metadata": kv,
    }


def parse_mzml_metadata(filepath: str | Path) -> Dict[str, Any]:
    """Inspect HUPO-PSI `.mzML` XML header chunk for spectrum/chromatogram counts without full DOM load."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"mzML file not found: {p}")
    with p.open("rb") as fh:
        head_txt = fh.read(65536).decode("utf-8", errors="ignore")
    if "<mzml" not in head_txt.lower() and "<indexedmzml" not in head_txt.lower():
        raise ValueError(f"File {p.name} does not contain a valid <mzML> or <indexedmzML> root element.")

    spec_m = re.search(r"<spectrumList\b[^>]*\bcount=[\"'](\d+)[\"']", head_txt, flags=re.IGNORECASE)
    chrom_m = re.search(r"<chromatogramList\b[^>]*\bcount=[\"'](\d+)[\"']", head_txt, flags=re.IGNORECASE)
    ver_m = re.search(r"<mzML\b[^>]*\bversion=[\"']([^\"']+)[\"']", head_txt, flags=re.IGNORECASE)

    return {
        "pack_id": PACK_ID,
        "modality": "mass_spec_mzml",
        "file": str(p),
        "file_size_bytes": int(p.stat().st_size),
        "mzml_version": ver_m.group(1) if ver_m else None,
        "spectrum_count": int(spec_m.group(1)) if spec_m else None,
        "chromatogram_count": int(chrom_m.group(1)) if chrom_m else None,
        "recommended_mode": "volcano_plot",
    }


def parse_h5ad_metadata(filepath: str | Path) -> Dict[str, Any]:
    """Verify HDF5 magic signature and inspect AnnData `.h5ad` container metadata."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"h5ad file not found: {p}")
    with p.open("rb") as fh:
        sig = fh.read(8)
    if sig != b"\x89HDF\r\n\x1a\n":
        raise ValueError(f"File {p.name} lacks standard 8-byte HDF5 magic header.")

    info: Dict[str, Any] = {
        "pack_id": PACK_ID,
        "modality": "single_cell_h5ad",
        "file": str(p),
        "file_size_bytes": int(p.stat().st_size),
        "hdf5_signature_valid": True,
        "recommended_mode": "stat_violin_raincloud",
    }
    try:
        import h5py  # type: ignore

        with h5py.File(p, "r") as h5f:
            info["top_groups"] = sorted(list(h5f.keys()))
    except ImportError:
        pass
    return info


def _read_table_columns_fast(p: Path) -> Optional[List[str]]:
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


def sniff_biomed_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Sniff biomedical/omics files by extension (`.fcs`, `.mzML`, `.h5ad`) or canonical column headers."""
    p = Path(filepath)
    ext = p.suffix.lower()

    if ext == ".fcs":
        return {
            "pack_id": PACK_ID,
            "modality": "flow_cytometry_fcs",
            "recommended_mode": "stat_violin_raincloud",
            "extension": ext,
            "confidence": "high",
        }
    if ext == ".mzml":
        return {
            "pack_id": PACK_ID,
            "modality": "mass_spec_mzml",
            "recommended_mode": "volcano_plot",
            "extension": ext,
            "confidence": "high",
        }
    if ext == ".h5ad":
        return {
            "pack_id": PACK_ID,
            "modality": "single_cell_h5ad",
            "recommended_mode": "stat_violin_raincloud",
            "extension": ext,
            "confidence": "high",
        }

    if ext in (".csv", ".tsv", ".xlsx") and p.exists() and p.is_file():
        cols = _read_table_columns_fast(p)
        if not cols:
            return None
        low_map = {c.lower().strip(): c for c in cols}
        low_set = set(low_map.keys())

        t_hits = low_set & _SURV_TIME_COLS
        e_hits = low_set & _SURV_EVENT_COLS
        if t_hits and e_hits:
            return {
                "pack_id": PACK_ID,
                "modality": "survival_km",
                "recommended_mode": "kaplan_meier_plot",
                "extension": ext,
                "confidence": "high",
                "matched_columns": {
                    "time_col": low_map[sorted(t_hits)[0]],
                    "event_col": low_map[sorted(e_hits)[0]],
                },
            }

        fc_hits = low_set & _VOLCANO_FC_COLS
        p_hits = low_set & _VOLCANO_P_COLS
        if fc_hits and p_hits:
            return {
                "pack_id": PACK_ID,
                "modality": "volcano_deg",
                "recommended_mode": "volcano_plot",
                "extension": ext,
                "confidence": "high",
                "matched_columns": {
                    "fc_col": low_map[sorted(fc_hits)[0]],
                    "p_col": low_map[sorted(p_hits)[0]],
                },
            }

        dx_hits = low_set & _DOSE_X_COLS
        dy_hits = low_set & _DOSE_Y_COLS
        if dx_hits and dy_hits:
            return {
                "pack_id": PACK_ID,
                "modality": "dose_response",
                "recommended_mode": "dose_response_4pl",
                "extension": ext,
                "confidence": "high",
                "matched_columns": {
                    "conc_col": low_map[sorted(dx_hits)[0]],
                    "response_col": low_map[sorted(dy_hits)[0]],
                },
            }

    return None


def parse_biomed_file(filepath: str | Path) -> Dict[str, Any]:
    """Parse `.fcs`, `.mzML`, `.h5ad`, or biomedical survival/volcano/dose-response tables."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Biomed/omics file not found: {p}")

    ext = p.suffix.lower()
    if ext == ".fcs":
        return parse_fcs_header(p)
    if ext == ".mzml":
        return parse_mzml_metadata(p)
    if ext == ".h5ad":
        return parse_h5ad_metadata(p)

    sniff = sniff_biomed_file(p)
    if ext == ".csv":
        df = pd.read_csv(p)
    elif ext in (".tsv", ".txt"):
        df = pd.read_csv(p, sep="\t")
    elif ext == ".xlsx":
        df = pd.read_excel(p)
    else:
        raise ValueError(f"Unsupported biomed_omics file extension: {ext!r} ({p.name})")

    return {
        "pack_id": PACK_ID,
        "modality": sniff["modality"] if sniff else "biomed_table",
        "recommended_mode": sniff["recommended_mode"] if sniff else "stat_bar_dot_sig",
        "file": str(p),
        "n_rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "matched_columns": sniff.get("matched_columns", {}) if sniff else {},
        "head_preview": df.head(5).to_dict(orient="records"),
    }


def validate_biomed_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Audit survival, ROC, and replicate statistical rigor for biomedical payloads."""
    findings = list(audit_survival_and_roc(payload))

    scripts_dir = str(Path(__file__).resolve().parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib

    val_mod = importlib.import_module("validator")
    if "panels" in payload or "comparisons" in payload:
        findings.extend(val_mod.audit_statistical_rigor(payload))

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
    "parse_fcs_header",
    "parse_mzml_metadata",
    "parse_h5ad_metadata",
    "audit_survival_and_roc",
    "sniff_biomed_file",
    "parse_biomed_file",
    "validate_biomed_payload",
]
