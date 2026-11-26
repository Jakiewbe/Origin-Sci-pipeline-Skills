"""
Materials Characterization & Electrochemistry Domain Pack (`materials_electrochem`).

Wraps the suite's spectroscopy, diffraction, porosity, impedance, and battery cycler
parsers (`parsers.py`) and physical sanity auditors (`validator.py`) into the unified
pluggable `DomainPack` interface.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


PACK_ID = "materials_electrochem"
DISPLAY_NAME_ZH = "材料表征与电化学储能"
DISPLAY_NAME_EN = "Materials Characterization & Electrochemistry"
MODALITIES = (
    "xps",
    "raman",
    "xrd",
    "ftir",
    "epr",
    "bet",
    "eis",
    "neware",
    "particle_size",
    "conductivity",
)
EXTENSIONS = (
    ".vgd",
    ".vgp",
    ".vms",
    ".rasx",
    ".asc",
    ".raw",
    ".spa",
    ".z60",
    ".cor",
    ".ndax",
    ".nda",
    ".cex",
    ".dsc",
    ".dta",
    ".qps",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
)
RECOMMENDED_MODES = (
    "deconv",
    "waterfall",
    "eis",
    "bet",
    "epr",
    "neware",
    "dva_ica",
    "contour_2d",
    "heatmap_matrix",
)


def _import_sibling(mod_name: str) -> Any:
    scripts_dir = str(Path(__file__).resolve().parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import importlib

    return importlib.import_module(mod_name)


def sniff_materials_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Identify materials characterization or electrochemistry vendor/tabular files."""
    p = Path(filepath)
    ext = p.suffix.lower()
    low_fn = p.name.lower()
    low_path = str(p).lower()

    if ext in (".vgd", ".vgp", ".vms") or ("xps" in low_path and ext in (".xls", ".xlsx")):
        return {
            "pack_id": PACK_ID,
            "modality": "xps",
            "recommended_mode": "deconv",
            "extension": ext,
            "confidence": "high",
        }
    if ext in (".rasx", ".asc", ".raw") or ("xrd" in low_path and ext in (".txt", ".csv", ".xy")):
        return {
            "pack_id": PACK_ID,
            "modality": "xrd",
            "recommended_mode": "waterfall",
            "extension": ext,
            "confidence": "high",
        }
    if ext == ".spa" or ("ftir" in low_path and ext in (".csv", ".txt")):
        return {
            "pack_id": PACK_ID,
            "modality": "ftir",
            "recommended_mode": "waterfall",
            "extension": ext,
            "confidence": "high",
        }
    if ext in (".z60", ".cor") or (("eis" in low_path or "nyquist" in low_fn or "阻抗" in str(p)) and ext in (".txt", ".csv")):
        return {
            "pack_id": PACK_ID,
            "modality": "eis",
            "recommended_mode": "eis",
            "extension": ext,
            "confidence": "high",
        }
    if ext in (".ndax", ".nda", ".cex"):
        return {
            "pack_id": PACK_ID,
            "modality": "neware",
            "recommended_mode": "neware",
            "extension": ext,
            "confidence": "high",
        }
    if ext in (".dsc", ".dta") or ("epr" in low_path and ext in ("", ".txt", ".csv")):
        return {
            "pack_id": PACK_ID,
            "modality": "epr",
            "recommended_mode": "epr",
            "extension": ext,
            "confidence": "high",
        }
    if ext == ".qps" or (
        any(tok in low_fn for tok in ("isotherm", "bjh", "dft")) and ext in (".csv", ".xlsx", ".txt")
    ):
        return {
            "pack_id": PACK_ID,
            "modality": "bet",
            "recommended_mode": "bet",
            "extension": ext,
            "confidence": "high",
        }
    if ("mastersizer" in low_fn or "粒度" in str(p)) and ext in (".xls", ".xlsx"):
        return {
            "pack_id": PACK_ID,
            "modality": "particle_size",
            "recommended_mode": "particle_size",
            "extension": ext,
            "confidence": "medium",
        }
    if ("conductivity" in low_fn or "电导" in str(p)) and ext in (".xls", ".xlsx"):
        return {
            "pack_id": PACK_ID,
            "modality": "conductivity",
            "recommended_mode": "conductivity",
            "extension": ext,
            "confidence": "medium",
        }
    if "raman" in low_path and ext in (".txt", ".csv"):
        return {
            "pack_id": PACK_ID,
            "modality": "raman",
            "recommended_mode": "deconv",
            "extension": ext,
            "confidence": "medium",
        }
    return None


def parse_materials_file(filepath: str | Path) -> Dict[str, Any]:
    """Dispatch a materials/electrochem file to its canonical parser in `parsers.py`."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Materials data file not found: {p}")

    parsers_mod = _import_sibling("parsers")
    sniff = sniff_materials_file(p)
    mod = sniff["modality"] if sniff else None
    ext = p.suffix.lower()

    if mod == "xps" and ext == ".vms":
        out = parsers_mod.parse_xps_vamas(p)
    elif mod == "xrd":
        out = parsers_mod.parse_xrd(p)
    elif mod == "ftir":
        out = parsers_mod.parse_ftir(p)
    elif mod == "eis":
        out = parsers_mod.parse_eis(p)
    elif mod == "neware":
        out = parsers_mod.parse_neware_auto(p)
    elif mod == "epr":
        out = parsers_mod.parse_epr(p)
    elif mod == "bet":
        out = parsers_mod.parse_bet_isotherm(p)
    elif mod == "particle_size":
        out = parsers_mod.parse_mastersizer_xls(p)
    elif mod == "conductivity":
        out = parsers_mod.parse_conductivity_xlsx(p)
    elif mod == "raman":
        out = parsers_mod.parse_xy_text(p, despike=True)
        out["modality"] = "raman"
    else:
        out = parsers_mod.inspect_data_file(p)

    res = dict(out)
    res.setdefault("pack_id", PACK_ID)
    res.setdefault("file", str(p))
    return res


def validate_materials_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run XPS, deconvolution, Neware active-mass, and statistical rigor audits."""
    validator_mod = _import_sibling("validator")
    findings: List[Dict[str, str]] = []

    if isinstance(payload.get("regions_results"), dict):
        reg_cfgs = payload.get("regions_config") if isinstance(payload.get("regions_config"), dict) else {}
        for r_name, fit_res in payload["regions_results"].items():
            if isinstance(fit_res, dict) and "y_raw" in fit_res and "y_fit" in fit_res:
                findings.extend(validator_mod.audit_deconv_region(r_name, fit_res, reg_cfgs.get(r_name, {})))
        findings.extend(
            validator_mod.audit_xps_inter_region_charging(
                payload["regions_results"],
                cross_check_cfg=payload.get("cross_check_anchor"),
                primary_anchor_cfg=payload.get("primary_anchor"),
            )
        )

    if isinstance(payload.get("rate_items"), list):
        findings.extend(
            validator_mod.audit_neware_mass(
                payload["rate_items"],
                str(payload.get("capacity_basis", "raw_mAh")),
            )
        )

    if "panels" in payload or "comparisons" in payload:
        findings.extend(validator_mod.audit_statistical_rigor(payload))

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
    "sniff_materials_file",
    "parse_materials_file",
    "validate_materials_payload",
]
