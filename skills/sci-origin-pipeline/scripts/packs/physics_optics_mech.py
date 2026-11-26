"""
Physics, Optics/Photonics & Solid Mechanics Domain Pack (`physics_optics_mech`).

Provides:
- RF/Microwave IEEE Touchstone `.s1p` / `.s2p` parser (`# GHz S DB R 50` / `MA` / `RI`
  option lines -> `freq_hz`, `s11_db`, `s21_db`, phase degrees, reference `z0_ohm`).
- `wavelength_nm_to_ev`: exact `hc / λ` (`1239.84193 / nm`) photon energy conversion
  plus Jacobian `|dE/dλ|` and `|dλ/dE|` spectral irradiance transformation & warning.
- `extract_stress_strain_metrics`: tensile Young's modulus `E`, `0.2%` offset yield
  strength, Ultimate Tensile Strength (`UTS`), and fracture toughness integral `U_T`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


PACK_ID = "physics_optics_mech"
DISPLAY_NAME_ZH = "物理、光学光子学与固体力学"
DISPLAY_NAME_EN = "Physics, Optics/Photonics & Mechanics"
MODALITIES = (
    "touchstone_rf",
    "optical_uv_vis_pl",
    "stress_strain_mechanics",
    "polar_radiation",
)
EXTENSIONS = (
    ".s1p",
    ".s2p",
    ".csv",
    ".tsv",
    ".txt",
    ".xlsx",
)
RECOMMENDED_MODES = (
    "dual_x_optical_spectrum",
    "polar_radar_plot",
    "broken_axis_plot",
    "linear_regression_ci",
    "waterfall",
)

HC_EV_NM = 1239.84193

_FREQ_MULTIPLIERS = {
    "HZ": 1.0,
    "KHZ": 1.0e3,
    "MHZ": 1.0e6,
    "GHZ": 1.0e9,
    "THZ": 1.0e12,
}


def _trapz_1d(y: np.ndarray, x: np.ndarray) -> float:
    trapz_fn = getattr(np, "trapezoid", None) or getattr(np, "trapz")
    return float(trapz_fn(y, x))


def _pair_to_db_and_deg(a: np.ndarray, b: np.ndarray, fmt: str) -> tuple[np.ndarray, np.ndarray]:
    if fmt == "DB":
        return a.astype(float), b.astype(float)
    if fmt == "MA":
        mag = np.maximum(a.astype(float), 1e-30)
        return 20.0 * np.log10(mag), b.astype(float)
    if fmt == "RI":
        comp = a.astype(float) + 1j * b.astype(float)
        mag = np.maximum(np.abs(comp), 1e-30)
        return 20.0 * np.log10(mag), np.rad2deg(np.angle(comp))
    raise ValueError(f"Unsupported Touchstone format token {fmt!r}; expected 'DB', 'MA', or 'RI'.")


def parse_touchstone_snp(filepath: str | Path) -> Dict[str, Any]:
    """
    Parse RF/microwave Touchstone ASCII `.s1p` or `.s2p` files (`# <freq_unit> <param> <fmt> R <z0>`),
    converting `DB`, `MA`, or `RI` network parameters into `freq_hz`, `s11_db`, and `s21_db`.
    """
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Touchstone file not found: {p}")

    ext = p.suffix.lower()
    m_port = re.match(r"^\.s([12])p$", ext)
    n_ports = int(m_port.group(1)) if m_port else 2

    text = p.read_text(encoding="utf-8", errors="replace")

    freq_unit = "GHZ"
    param_type = "S"
    data_fmt = "MA"
    z0_ohm = 50.0
    option_seen = False
    num_tokens: List[float] = []

    for raw_line in text.splitlines():
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            low_dir = line.lower()
            if low_dir.startswith("[number of ports]"):
                parts_np = line.split("]", 1)[1].strip().split()
                if parts_np:
                    n_ports = int(parts_np[0])
            continue

        if line.startswith("#"):
            if not option_seen:
                option_seen = True
                toks = line[1:].strip().upper().split()
                i = 0
                while i < len(toks):
                    tk = toks[i]
                    if tk in _FREQ_MULTIPLIERS:
                        freq_unit = tk
                    elif tk in ("S", "Y", "Z", "G", "H"):
                        param_type = tk
                    elif tk in ("DB", "MA", "RI"):
                        data_fmt = tk
                    elif tk == "R" and i + 1 < len(toks):
                        z0_ohm = float(toks[i + 1])
                        i += 1
                    i += 1
            continue

        for tok in line.split():
            num_tokens.append(float(tok))

    if n_ports not in (1, 2):
        raise ValueError(f"parse_touchstone_snp supports 1-port (.s1p) and 2-port (.s2p), got n_ports={n_ports}.")

    cols_per_row = 1 + 2 * (n_ports * n_ports)
    if len(num_tokens) < cols_per_row or (len(num_tokens) % cols_per_row) != 0:
        raise ValueError(
            f"Touchstone file {p.name} has {len(num_tokens)} numeric values, not divisible by "
            f"{cols_per_row} columns required for {n_ports}-port data."
        )

    mat = np.asarray(num_tokens, dtype=float).reshape(-1, cols_per_row)
    freq_raw = mat[:, 0]
    freq_hz = freq_raw * _FREQ_MULTIPLIERS[freq_unit]

    s11_db, s11_deg = _pair_to_db_and_deg(mat[:, 1], mat[:, 2], data_fmt)
    if n_ports == 2:
        s21_db, s21_deg = _pair_to_db_and_deg(mat[:, 3], mat[:, 4], data_fmt)
        s12_db, s12_deg = _pair_to_db_and_deg(mat[:, 5], mat[:, 6], data_fmt)
        s22_db, s22_deg = _pair_to_db_and_deg(mat[:, 7], mat[:, 8], data_fmt)
    else:
        s21_db = s21_deg = s12_db = s12_deg = s22_db = s22_deg = None

    return {
        "pack_id": PACK_ID,
        "modality": "touchstone_rf",
        "recommended_mode": "dual_x_optical_spectrum",
        "file": str(p),
        "n_ports": n_ports,
        "freq_unit": freq_unit,
        "param_type": param_type,
        "data_format": data_fmt,
        "z0_ohm": z0_ohm,
        "freq_raw": freq_raw,
        "freq_hz": freq_hz,
        "freq_ghz": freq_hz * 1.0e-9,
        "s11_db": s11_db,
        "s11_phase_deg": s11_deg,
        "s21_db": s21_db,
        "s21_phase_deg": s21_deg,
        "s12_db": s12_db,
        "s12_phase_deg": s12_deg,
        "s22_db": s22_db,
        "s22_phase_deg": s22_deg,
        "n_points": int(freq_hz.size),
        "freq_range_hz": [float(np.min(freq_hz)), float(np.max(freq_hz))],
    }


def wavelength_nm_to_ev(
    nm: Sequence[float] | float,
    spectral_density_y: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """
    Convert optical wavelength `nm` to photon energy `eV` (`E = 1239.84193 / nm`)
    and compute the Jacobian `|dE/dλ|` and `|dλ/dE|` with an explicit spectral
    irradiance / photoluminescence density warning.
    """
    is_scalar = isinstance(nm, (int, float, np.number))
    nm_arr = np.asarray(nm, dtype=float)
    if np.any(~np.isfinite(nm_arr)) or np.any(nm_arr <= 0.0):
        raise ValueError("wavelength_nm_to_ev requires strictly positive finite wavelength(s) in nm.")

    energy_ev = HC_EV_NM / nm_arr
    jac_de_dlam = HC_EV_NM / (nm_arr ** 2)
    jac_dlam_de = (nm_arr ** 2) / HC_EV_NM

    y_trans: Optional[np.ndarray] = None
    if spectral_density_y is not None:
        y_arr = np.asarray(spectral_density_y, dtype=float)
        if y_arr.shape != nm_arr.shape:
            raise ValueError(
                f"spectral_density_y shape {y_arr.shape} must match wavelength nm shape {nm_arr.shape}."
            )
        y_trans = y_arr * jac_dlam_de

    return {
        "wavelength_nm": float(nm_arr) if is_scalar else nm_arr,
        "energy_ev": float(energy_ev) if is_scalar else energy_ev,
        "jacobian_de_dlambda": float(jac_de_dlam) if is_scalar else jac_de_dlam,
        "jacobian_dlambda_de": float(jac_dlam_de) if is_scalar else jac_dlam_de,
        "y_jacobian_transformed": y_trans,
        "formula": "1239.84193/x",
        "jacobian_warning": (
            "Spectral density quantities (PL intensity per nm, spectral irradiance W·m⁻²·nm⁻¹) require "
            "the Jacobian factor I(E) = I(λ)·|dλ/dE| = I(λ)/|dE/dλ| = I(λ)·λ²/1239.84193 when converted "
            "onto a linear energy grid; dimensionless ratios (Absorbance, Transmittance, Reflectance) do not. "
            "Prefer a formula-linked top axis (`1239.84193/x`) to preserve raw wavelength-domain peak shapes."
        ),
    }


def extract_stress_strain_metrics(
    strain: Sequence[float],
    stress: Sequence[float],
    *,
    strain_in_percent: bool = False,
    offset: float = 0.002,
) -> Dict[str, Any]:
    """
    Extract mechanical tensile metrics from engineering strain and stress arrays:
    - `youngs_modulus`: initial linear elastic slope `E`
    - `yield_strength_02pct`: `0.2%` (`offset=0.002`) plastic offset yield strength
    - `uts`: Ultimate Tensile Strength (`max(stress)`)
    - `fracture_toughness_ut`: Modulus of toughness integral `U_T = ∫ σ dε`
    """
    eps_raw = np.asarray(strain, dtype=float).ravel()
    sig_raw = np.asarray(stress, dtype=float).ravel()
    if eps_raw.size != sig_raw.size:
        raise ValueError(
            f"strain ({eps_raw.size}) and stress ({sig_raw.size}) must have equal lengths."
        )
    valid = np.isfinite(eps_raw) & np.isfinite(sig_raw)
    eps = eps_raw[valid]
    sig = sig_raw[valid]
    if eps.size < 4:
        raise ValueError("extract_stress_strain_metrics requires at least 4 finite (strain, stress) points.")

    if strain_in_percent:
        eps = eps / 100.0

    idx_uts = int(np.argmax(sig))
    uts = float(sig[idx_uts])
    uniform_strain = float(eps[idx_uts])
    toughness_ut = float(_trapz_1d(sig, eps))

    pre_peak = np.arange(eps.size) <= max(idx_uts, 2)
    elastic_mask = pre_peak & (sig <= 0.45 * uts) & (eps >= float(eps[0]))
    if int(np.sum(elastic_mask)) < 3:
        n_init = min(max(3, idx_uts + 1), eps.size)
        elastic_mask = np.zeros(eps.size, dtype=bool)
        elastic_mask[:n_init] = True

    eps_el = eps[elastic_mask]
    sig_el = sig[elastic_mask]
    if float(np.ptp(eps_el)) <= 1e-15:
        raise ValueError("Degenerate zero-span elastic strain region; cannot determine Young's modulus.")

    slope_e, intercept_c = np.polyfit(eps_el, sig_el, 1)
    youngs_e = float(slope_e)
    sig_pred = youngs_e * eps_el + float(intercept_c)
    ss_res = float(np.sum((sig_el - sig_pred) ** 2))
    ss_tot = float(np.sum((sig_el - np.mean(sig_el)) ** 2))
    r2_el = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-15 else 1.0

    off_f = float(offset)
    g_diff = sig - (youngs_e * (eps - off_f) + float(intercept_c))
    yield_strength: Optional[float] = None
    yield_strain: Optional[float] = None

    for k in range(1, eps.size):
        if g_diff[k - 1] >= 0.0 and g_diff[k] <= 0.0:
            denom = float(g_diff[k - 1] - g_diff[k])
            frac = float(g_diff[k - 1] / denom) if denom > 1e-30 else 0.0
            yield_strain = float(eps[k - 1] + frac * (eps[k] - eps[k - 1]))
            yield_strength = float(sig[k - 1] + frac * (sig[k] - sig[k - 1]))
            break

    return {
        "youngs_modulus": youngs_e,
        "elastic_intercept": float(intercept_c),
        "elastic_r2": r2_el,
        "yield_strength_02pct": yield_strength,
        "yield_strain_02pct": yield_strain,
        "uts": uts,
        "uniform_strain": uniform_strain,
        "fracture_strain": float(eps[-1]),
        "fracture_toughness_ut": toughness_ut,
        "offset": off_f,
    }


def sniff_physics_file(filepath: str | Path) -> Optional[Dict[str, Any]]:
    """Sniff Touchstone `.s1p`/`.s2p` files or optical / stress-strain / polar tables."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext in (".s1p", ".s2p"):
        return {
            "pack_id": PACK_ID,
            "modality": "touchstone_rf",
            "recommended_mode": "dual_x_optical_spectrum",
            "extension": ext,
            "confidence": "high",
        }

    if ext in (".csv", ".tsv", ".xlsx") and p.exists() and p.is_file():
        try:
            df0 = pd.read_excel(p, nrows=3) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","), nrows=3)
        except Exception:
            return None
        low_set = {str(c).strip().lower() for c in df0.columns}

        if (low_set & {"wavelength_nm", "wavelength", "lambda_nm"}) and (
            low_set & {"absorbance", "transmittance", "pl_intensity", "reflectance", "intensity"}
        ):
            return {
                "pack_id": PACK_ID,
                "modality": "optical_uv_vis_pl",
                "recommended_mode": "dual_x_optical_spectrum",
                "extension": ext,
                "confidence": "high",
            }
        if (low_set & {"strain", "strain_pct", "eng_strain"}) and (
            low_set & {"stress", "stress_mpa", "eng_stress"}
        ):
            return {
                "pack_id": PACK_ID,
                "modality": "stress_strain_mechanics",
                "recommended_mode": "broken_axis_plot",
                "extension": ext,
                "confidence": "high",
            }
        if (low_set & {"theta", "theta_deg", "angle_deg"}) and (low_set & {"r", "gain_db", "intensity"}):
            return {
                "pack_id": PACK_ID,
                "modality": "polar_radiation",
                "recommended_mode": "polar_radar_plot",
                "extension": ext,
                "confidence": "high",
            }

    return None


def parse_physics_file(filepath: str | Path) -> Dict[str, Any]:
    """Parse Touchstone `.s1p`/`.s2p` or optical/mechanical tabular files."""
    p = Path(filepath)
    ext = p.suffix.lower()
    if ext in (".s1p", ".s2p"):
        return parse_touchstone_snp(p)

    if not p.exists():
        raise FileNotFoundError(f"Physics/optics/mechanics file not found: {p}")
    sniff = sniff_physics_file(p)
    df = pd.read_excel(p) if ext == ".xlsx" else pd.read_csv(p, sep=("\t" if ext == ".tsv" else ","))
    return {
        "pack_id": PACK_ID,
        "modality": sniff["modality"] if sniff else "physics_table",
        "recommended_mode": sniff["recommended_mode"] if sniff else "dual_x_optical_spectrum",
        "file": str(p),
        "n_rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "head_preview": df.head(5).to_dict(orient="records"),
    }


def validate_physics_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate optical dual-axis wavelength domain (> 0 nm) and mechanical strain/stress sanity."""
    findings: List[Dict[str, str]] = []
    if payload.get("wavelength_nm") is not None:
        wl = np.asarray(payload["wavelength_nm"], dtype=float).ravel()
        if np.any(wl <= 0.0):
            findings.append(
                {
                    "level": "ERROR_NONPOSITIVE_WAVELENGTH",
                    "region": "Optical_Spectrum",
                    "detail": "Wavelength values must be strictly > 0 nm to avoid singularity in E = 1239.84193 / λ.",
                }
            )
        if payload.get("replot_linear_energy") and not payload.get("jacobian_applied"):
            findings.append(
                {
                    "level": "WARN_MISSING_JACOBIAN_SCALING",
                    "region": "Optical_Spectrum",
                    "detail": (
                        "Replotting spectral irradiance/PL density onto a linear eV axis without Jacobian "
                        "I(E) = I(λ)·λ²/1239.84193 distorts peak positions; use linked top axis or apply Jacobian."
                    ),
                }
            )

    if payload.get("strain") is not None and payload.get("stress") is not None:
        metrics = extract_stress_strain_metrics(
            payload["strain"],
            payload["stress"],
            strain_in_percent=bool(payload.get("strain_in_percent", False)),
        )
        if metrics["youngs_modulus"] <= 0.0:
            findings.append(
                {
                    "level": "ERROR_NEGATIVE_YOUNGS_MODULUS",
                    "region": "Stress_Strain",
                    "detail": f"Estimated Young's modulus E = {metrics['youngs_modulus']:.4g} <= 0; check initial unloading/slack.",
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
    "HC_EV_NM",
    "parse_touchstone_snp",
    "wavelength_nm_to_ev",
    "extract_stress_strain_metrics",
    "sniff_physics_file",
    "parse_physics_file",
    "validate_physics_payload",
]
