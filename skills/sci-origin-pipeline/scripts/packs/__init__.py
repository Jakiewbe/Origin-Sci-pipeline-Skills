"""
Pluggable 6-Domain Scientific Pack Architecture (`packs/`).

Unifies file-format sniffing, domain-specific parsing, and physical/statistical
payload validation across:
  1. `materials_electrochem` — Materials Characterization & Electrochemistry
  2. `biomed_omics`          — Biomedicine, Clinical Survival & Multi-Omics
  3. `chem_catalysis`        — Chemical Spectroscopy & Catalysis
  4. `physics_optics_mech`   — Physics, Optics/Photonics & Mechanics
  5. `geo_env`               — Earth, Ocean, Atmospheric & Environmental Science
  6. `ml_ai4s`               — Machine Learning, AI4Science & Benchmarks
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import (
    biomed_omics,
    chem_catalysis,
    geo_env,
    materials_electrochem,
    ml_ai4s,
    physics_optics_mech,
)


@dataclass(frozen=True)
class DomainPack:
    pack_id: str
    display_name_zh: str
    display_name_en: str
    modalities: Tuple[str, ...]
    extensions: Tuple[str, ...]
    recommended_modes: Tuple[str, ...]
    sniff_fn: Callable[[str | Path], Optional[Dict[str, Any]]]
    parse_fn: Callable[[str | Path], Dict[str, Any]]
    validate_fn: Callable[[Dict[str, Any]], Dict[str, Any]]


PACK_ORDER: Tuple[str, ...] = (
    "materials_electrochem",
    "biomed_omics",
    "chem_catalysis",
    "physics_optics_mech",
    "geo_env",
    "ml_ai4s",
)

_PACK_REGISTRY: Dict[str, DomainPack] = {
    materials_electrochem.PACK_ID: DomainPack(
        pack_id=materials_electrochem.PACK_ID,
        display_name_zh=materials_electrochem.DISPLAY_NAME_ZH,
        display_name_en=materials_electrochem.DISPLAY_NAME_EN,
        modalities=tuple(materials_electrochem.MODALITIES),
        extensions=tuple(materials_electrochem.EXTENSIONS),
        recommended_modes=tuple(materials_electrochem.RECOMMENDED_MODES),
        sniff_fn=materials_electrochem.sniff_materials_file,
        parse_fn=materials_electrochem.parse_materials_file,
        validate_fn=materials_electrochem.validate_materials_payload,
    ),
    biomed_omics.PACK_ID: DomainPack(
        pack_id=biomed_omics.PACK_ID,
        display_name_zh=biomed_omics.DISPLAY_NAME_ZH,
        display_name_en=biomed_omics.DISPLAY_NAME_EN,
        modalities=tuple(biomed_omics.MODALITIES),
        extensions=tuple(biomed_omics.EXTENSIONS),
        recommended_modes=tuple(biomed_omics.RECOMMENDED_MODES),
        sniff_fn=biomed_omics.sniff_biomed_file,
        parse_fn=biomed_omics.parse_biomed_file,
        validate_fn=biomed_omics.validate_biomed_payload,
    ),
    chem_catalysis.PACK_ID: DomainPack(
        pack_id=chem_catalysis.PACK_ID,
        display_name_zh=chem_catalysis.DISPLAY_NAME_ZH,
        display_name_en=chem_catalysis.DISPLAY_NAME_EN,
        modalities=tuple(chem_catalysis.MODALITIES),
        extensions=tuple(chem_catalysis.EXTENSIONS),
        recommended_modes=tuple(chem_catalysis.RECOMMENDED_MODES),
        sniff_fn=chem_catalysis.sniff_chem_file,
        parse_fn=chem_catalysis.parse_chem_file,
        validate_fn=chem_catalysis.validate_chem_payload,
    ),
    physics_optics_mech.PACK_ID: DomainPack(
        pack_id=physics_optics_mech.PACK_ID,
        display_name_zh=physics_optics_mech.DISPLAY_NAME_ZH,
        display_name_en=physics_optics_mech.DISPLAY_NAME_EN,
        modalities=tuple(physics_optics_mech.MODALITIES),
        extensions=tuple(physics_optics_mech.EXTENSIONS),
        recommended_modes=tuple(physics_optics_mech.RECOMMENDED_MODES),
        sniff_fn=physics_optics_mech.sniff_physics_file,
        parse_fn=physics_optics_mech.parse_physics_file,
        validate_fn=physics_optics_mech.validate_physics_payload,
    ),
    geo_env.PACK_ID: DomainPack(
        pack_id=geo_env.PACK_ID,
        display_name_zh=geo_env.DISPLAY_NAME_ZH,
        display_name_en=geo_env.DISPLAY_NAME_EN,
        modalities=tuple(geo_env.MODALITIES),
        extensions=tuple(geo_env.EXTENSIONS),
        recommended_modes=tuple(geo_env.RECOMMENDED_MODES),
        sniff_fn=geo_env.sniff_geo_file,
        parse_fn=geo_env.parse_geo_file,
        validate_fn=geo_env.validate_geo_payload,
    ),
    ml_ai4s.PACK_ID: DomainPack(
        pack_id=ml_ai4s.PACK_ID,
        display_name_zh=ml_ai4s.DISPLAY_NAME_ZH,
        display_name_en=ml_ai4s.DISPLAY_NAME_EN,
        modalities=tuple(ml_ai4s.MODALITIES),
        extensions=tuple(ml_ai4s.EXTENSIONS),
        recommended_modes=tuple(ml_ai4s.RECOMMENDED_MODES),
        sniff_fn=ml_ai4s.sniff_ml_file,
        parse_fn=ml_ai4s.parse_ml_file,
        validate_fn=ml_ai4s.validate_ml_payload,
    ),
}


def list_domain_packs() -> List[Dict[str, Any]]:
    """Return JSON-serializable metadata for all 6 registered domain packs in canonical order."""
    out: List[Dict[str, Any]] = []
    for pid in PACK_ORDER:
        pk = _PACK_REGISTRY[pid]
        out.append(
            {
                "pack_id": pk.pack_id,
                "display_name_zh": pk.display_name_zh,
                "display_name_en": pk.display_name_en,
                "modalities": list(pk.modalities),
                "extensions": list(pk.extensions),
                "recommended_modes": list(pk.recommended_modes),
            }
        )
    return out


def get_domain_pack(pack_id: str) -> DomainPack:
    """Retrieve a registered `DomainPack` by `pack_id`."""
    key = str(pack_id or "").strip().lower()
    if key not in _PACK_REGISTRY:
        raise KeyError(f"Unknown domain pack {pack_id!r}; expected one of {PACK_ORDER}.")
    return _PACK_REGISTRY[key]


def sniff_domain_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """
    Sniff a file across all registered domain packs in `PACK_ORDER`, returning
    the first matching pack/modality/recommended_mode descriptor or `None`.
    """
    p = Path(filepath)
    for pid in PACK_ORDER:
        pk = _PACK_REGISTRY[pid]
        hit = pk.sniff_fn(p)
        if hit is not None:
            res = dict(hit)
            res.setdefault("pack_id", pk.pack_id)
            res.setdefault("file", str(p))
            return res
    return None


def parse_domain_file(filepath: str | Path) -> Dict[str, Any]:
    """Sniff and parse `filepath` via its matching `DomainPack`."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Domain file not found: {p}")

    hit = sniff_domain_file(p)
    if hit is None:
        raise ValueError(
            f"Could not match {p.name!r} to any registered domain pack ({', '.join(PACK_ORDER)})."
        )
    pk = get_domain_pack(hit["pack_id"])
    parsed = dict(pk.parse_fn(p))
    parsed.setdefault("pack_id", pk.pack_id)
    parsed.setdefault("file", str(p))
    return parsed


def audit_domain_payload(pack_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run domain-specific validation rules for `pack_id` on `payload`."""
    pk = get_domain_pack(pack_id)
    return pk.validate_fn(payload)


__all__ = [
    "DomainPack",
    "PACK_ORDER",
    "list_domain_packs",
    "get_domain_pack",
    "sniff_domain_file",
    "parse_domain_file",
    "audit_domain_payload",
]
