from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


FALLBACK_XLRD_CANDIDATES = [
    r"C:\ProgramData\Miniconda3\python.exe",
    r"C:\ProgramData\Anaconda3\python.exe",
    os.path.expanduser(r"~\miniconda3\python.exe"),
    os.path.expanduser(r"~\anaconda3\python.exe"),
]


def _find_xlrd_python() -> Optional[str]:
    for cand in FALLBACK_XLRD_CANDIDATES:
        if os.path.exists(cand):
            return cand
    return None


def _read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="ignore")


def _load_xls_sheets_via_xlrd_or_bridge(path: Path) -> Dict[str, List[List[Any]]]:
    """Read legacy .xls workbook sheets either via local xlrd or base Miniconda bridge."""
    try:
        import xlrd  # type: ignore
        wb = xlrd.open_workbook(str(path))
        return {s: [wb.sheet_by_name(s).row_values(r) for r in range(wb.sheet_by_name(s).nrows)] for s in wb.sheet_names()}
    except ImportError:
        fb_py = _find_xlrd_python()
        if not fb_py:
            raise RuntimeError("xlrd not installed in current env and no fallback Miniconda/Anaconda python.exe found.")
        helper_code = (
            "import sys, json, xlrd\n"
            "wb = xlrd.open_workbook(sys.argv[1])\n"
            "print(json.dumps({s: [wb.sheet_by_name(s).row_values(r) for r in range(wb.sheet_by_name(s).nrows)] "
            "for s in wb.sheet_names()}))\n"
        )
        proc = subprocess.run(
            [fb_py, "-c", helper_code, str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout)


def parse_xps_avantage(path: str | Path, region_hint: str = "C1s") -> Dict[str, Any]:
    """Parse Thermo Avantage exported .xls / .xlsx spectrum sheet (e.g. 'C1s Scan', 'F1s Scan', 'Li1s Scan')."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
        target_sheet = _match_sheet_name(wb.sheetnames, region_hint)
        ws = wb[target_sheet]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return _extract_avantage_rows(rows, target_sheet, str(p))

    if ext == ".xls":
        sheets_map = _load_xls_sheets_via_xlrd_or_bridge(p)
        target_sheet = _match_sheet_name(list(sheets_map.keys()), region_hint)
        return _extract_avantage_rows(sheets_map[target_sheet], target_sheet, str(p))

    if ext == ".vms":
        return parse_xps_vamas(p, region_hint)

    if ext in (".txt", ".csv"):
        xy = parse_xy_text(p, despike=False)
        return {
            "modality": "XPS",
            "region": region_hint,
            "source": str(p),
            "x": xy["x"],
            "y": xy["y"],
            "vendor_bg": None,
            "x_unit": "eV",
            "y_unit": "Counts / s",
        }

    if ext == ".vgd":
        raise ValueError(
            f"Direct .VGD file ({p.name}) contains raw detector counts without Avantage transmission/CAE scaling. "
            f"Please pass the companion Avantage exported .xls/.xlsx file in the same folder for quantitative Counts/s."
        )

    raise ValueError(f"Unsupported XPS file format: {p}")


def _match_sheet_name(sheets: List[str], hint: str) -> str:
    h = hint.lower().replace(" ", "")
    for s in sheets:
        if h in s.lower().replace(" ", ""):
            return s
    raise KeyError(f"Region '{hint}' not found among sheets: {sheets}")


def _extract_avantage_rows(rows: List[List[Any]], sheet_name: str, source: str) -> Dict[str, Any]:
    xs: List[float] = []
    ys: List[float] = []
    bgs: List[float] = []

    for r in rows:
        if not r or len(r) < 2:
            continue
        v0 = r[0]
        v_raw = r[2] if (len(r) >= 3 and r[1] in ("", None) and isinstance(r[2], (int, float))) else r[1]
        if isinstance(v0, (int, float)) and isinstance(v_raw, (int, float)):
            if np.isfinite(v0) and np.isfinite(v_raw):
                xs.append(float(v0))
                ys.append(float(v_raw))
                if len(r) >= 5 and isinstance(r[4], (int, float)) and float(r[4]) > 0:
                    bgs.append(float(r[4]))
                else:
                    bgs.append(np.nan)

    if len(xs) < 10:
        raise ValueError(f"Failed to extract numeric XPS spectrum from {source} [{sheet_name}]")

    x_arr = np.asarray(xs, dtype=float)
    y_arr = np.asarray(ys, dtype=float)
    bg_arr = np.asarray(bgs, dtype=float)
    order = np.argsort(x_arr)
    return {
        "modality": "XPS",
        "region": sheet_name,
        "source": source,
        "x": x_arr[order],
        "y": y_arr[order],
        "vendor_bg": bg_arr[order] if np.isfinite(bg_arr).sum() > 5 else None,
        "x_unit": "eV",
        "y_unit": "Counts / s",
    }


def parse_xy_text(path: str | Path, despike: bool = True, x_col: int = 0, y_col: int = 1) -> Dict[str, Any]:
    """Parse generic 2+ column ASCII spectrum or table (Raman .txt/.csv, exported curves)."""
    p = Path(path)
    txt = _read_text_auto(p)
    xs: List[float] = []
    ys: List[float] = []
    for line in txt.splitlines():
        s = line.strip()
        if not s or s[0] in ("#", "*", ";", "["):
            continue
        parts = [tok for tok in re.split(r"[\s,;]+", s) if tok]
        if len(parts) > max(x_col, y_col):
            try:
                xv = float(parts[x_col])
                yv = float(parts[y_col])
                if np.isfinite(xv) and np.isfinite(yv):
                    xs.append(xv)
                    ys.append(yv)
            except ValueError:
                continue

    if len(xs) < 4:
        raise ValueError(f"Insufficient numeric XY rows in {p}")

    x_arr = np.asarray(xs, dtype=float)
    y_arr = np.asarray(ys, dtype=float)
    order = np.argsort(x_arr)
    x_arr, y_arr = x_arr[order], y_arr[order]

    if despike and len(y_arr) > 15:
        y_arr = _despike_cosmic_rays(y_arr)

    return {
        "modality": "XY_Spectrum",
        "source": str(p),
        "x": x_arr,
        "y": y_arr,
    }


def _despike_cosmic_rays(y: np.ndarray, z_thresh: float = 7.5) -> np.ndarray:
    y_clean = y.copy()
    dy = np.diff(y_clean, prepend=y_clean[0])
    med = np.median(dy)
    mad = np.median(np.abs(dy - med)) + 1e-9
    mod_z = 0.6745 * np.abs(dy - med) / mad
    spikes = np.where(mod_z > z_thresh)[0]
    for idx in spikes:
        left = max(0, idx - 2)
        right = min(len(y_clean) - 1, idx + 2)
        neighbors = [y_clean[k] for k in range(left, right + 1) if k not in spikes]
        if neighbors:
            y_clean[idx] = float(np.median(neighbors))
    return y_clean


def parse_ftir(path: str | Path) -> Dict[str, Any]:
    """Parse FTIR .CSV or binary Thermo OMNIC .SPA file."""
    p = Path(path)
    if p.suffix.lower() == ".spa":
        raw = p.read_bytes()
        if not raw.startswith(b"Spectral Data File"):
            raise ValueError(f"Invalid OMNIC .SPA signature: {p}")
        wn_max, wn_min = None, None
        data_offset, data_len = None, None
        pos = 0x0130
        while pos + 16 <= min(len(raw), 0x0600):
            key = struct.unpack_from("<H", raw, pos)[0]
            offset = struct.unpack_from("<I", raw, pos + 2)[0]
            length = struct.unpack_from("<I", raw, pos + 6)[0]
            if key == 0x0002 and offset + 24 <= len(raw):
                wn_max, wn_min = struct.unpack_from("<ff", raw, offset + 16)
            elif key == 0x0003 and offset > 0 and length > 0:
                data_offset, data_len = offset, length
            if key == 0x0000 and offset == 0 and pos > 0x0160:
                break
            pos += 16
        if data_offset is None:
            raise ValueError(f"Could not locate spectrum float block in .SPA: {p}")
        count = data_len // 4
        y_arr = np.frombuffer(raw, dtype="<f4", count=count, offset=data_offset).astype(float)
        if wn_max is not None and wn_min is not None and count > 1:
            x_arr = np.linspace(float(wn_max), float(wn_min), count)
        else:
            x_arr = np.linspace(4000.0, 400.0, count)
        order = np.argsort(x_arr)
        return {"modality": "FTIR", "source": str(p), "x": x_arr[order], "y": y_arr[order]}

    res = parse_xy_text(p, despike=False)
    res["modality"] = "FTIR"
    return res


def parse_xrd(path: str | Path) -> Dict[str, Any]:
    """Parse Rigaku .rasx (ZIP archive), Rigaku .txt (*RAS_INT_START), or .asc XRD files."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".rasx" and zipfile.is_zipfile(p):
        with zipfile.ZipFile(p, "r") as zf:
            prof_names = [n for n in zf.namelist() if n.lower().endswith("profile0.txt")]
            if not prof_names:
                raise ValueError(f"No Profile0.txt inside Rigaku .rasx: {p}")
            txt = zf.read(prof_names[0]).decode("utf-8-sig", errors="ignore")
        xs, ys = [], []
        for line in txt.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    xs.append(float(parts[0]))
                    ys.append(float(parts[1]))
                except ValueError:
                    continue
        return {"modality": "XRD", "source": str(p), "x": np.asarray(xs), "y": np.asarray(ys)}

    txt = _read_text_auto(p)
    if "*ASC_START" in txt or "*COUNT" in txt or "*STEP" in txt:
        start_m = re.search(r"\*START\s*=\s*([0-9.+-eE]+)", txt)
        step_m = re.search(r"\*STEP\s*=\s*([0-9.+-eE]+)", txt)
        if start_m and step_m:
            start_2t = float(start_m.group(1))
            step_2t = float(step_m.group(1))
            intensities: List[float] = []
            in_data = False
            for line in txt.splitlines():
                s = line.strip()
                if s.startswith("*COUNT"):
                    in_data = True
                    continue
                if s.startswith("*END"):
                    in_data = False
                if in_data and s and not s.startswith("*"):
                    for tok in re.split(r"[\s,]+", s):
                        if tok:
                            try:
                                intensities.append(float(tok))
                            except ValueError:
                                pass
            if len(intensities) > 10:
                x_arr = start_2t + np.arange(len(intensities)) * step_2t
                return {"modality": "XRD", "source": str(p), "x": x_arr, "y": np.asarray(intensities)}

    res = parse_xy_text(p, despike=False)
    res["modality"] = "XRD"
    return res


def parse_eis(path: str | Path) -> Dict[str, Any]:
    """Parse EIS impedance from CHI binary .bin ('IMP...A.C. Impedance'), 5-col .txt, or CorrTest .z60."""
    p = Path(path)
    if p.suffix.lower() == ".bin":
        raw = p.read_bytes()
        if b"A.C. Impedance" in raw[:120] and len(raw) > 1458:
            payload = raw[1442:]
            n_rec = len(payload) // 16
            arr = np.frombuffer(payload, dtype="<f4", count=n_rec * 4).reshape(-1, 4)
            f_arr = arr[:, 0].astype(float)
            zr_arr = arr[:, 2].astype(float)
            zi_arr = arr[:, 3].astype(float)
            valid = np.isfinite(f_arr) & (f_arr > 0) & np.isfinite(zr_arr) & np.isfinite(zi_arr)
            f_arr, zr_arr, zi_arr = f_arr[valid], zr_arr[valid], zi_arr[valid]
            neg_zi = -zi_arr if np.median(zi_arr) < 0 else zi_arr
            return {
                "modality": "EIS",
                "source": str(p),
                "freq_Hz": f_arr,
                "z_real": zr_arr,
                "neg_z_imag": neg_zi,
                "z_imag_raw": zi_arr,
                "z_mod": np.hypot(zr_arr, zi_arr),
                "phase_deg": np.degrees(np.arctan2(zi_arr, zr_arr)),
            }
        raise ValueError(f"Unsupported binary EIS .bin variant: {p}")

    txt = _read_text_auto(p)
    freqs, z_re, z_im_raw = [], [], []

    for line in txt.splitlines():
        s = line.strip()
        if not s or s[0].isalpha() or s[0] in ("*", "#", ";", "["):
            continue
        parts = [tok for tok in re.split(r"[\s,;]+", s) if tok]
        nums = []
        for tok in parts:
            try:
                nums.append(float(tok))
            except ValueError:
                nums = []
                break
        if len(nums) == 5 and nums[0] > 0:
            freqs.append(nums[0])
            z_re.append(nums[1])
            z_im_raw.append(nums[2])
        elif len(nums) >= 6 and p.suffix.lower() == ".z60" and nums[0] > 0:
            freqs.append(nums[0])
            z_re.append(nums[4])
            z_im_raw.append(nums[5])

    if len(freqs) < 4:
        raise ValueError(f"Could not extract valid EIS impedance rows from {p}")

    f_arr = np.asarray(freqs, dtype=float)
    zr_arr = np.asarray(z_re, dtype=float)
    zi_arr = np.asarray(z_im_raw, dtype=float)
    neg_zi = -zi_arr if np.median(zi_arr) < 0 else zi_arr
    z_mod = np.hypot(zr_arr, zi_arr)
    phase_deg = np.degrees(np.arctan2(zi_arr, zr_arr))

    return {
        "modality": "EIS",
        "source": str(p),
        "freq_Hz": f_arr,
        "z_real": zr_arr,
        "neg_z_imag": neg_zi,
        "z_imag_raw": zi_arr,
        "z_mod": z_mod,
        "phase_deg": phase_deg,
    }


def parse_epr(path: str | Path) -> Dict[str, Any]:
    """Parse EPR ASCII (+g / field table) or Bruker BES3T (.DSC/.DTA) first-derivative spectrum."""
    p = Path(path)
    if p.suffix.lower() in (".dsc", ".dta"):
        dsc_p = p.with_suffix(".DSC") if p.with_suffix(".DSC").exists() else p.with_suffix(".dsc")
        dta_p = p.with_suffix(".DTA") if p.with_suffix(".DTA").exists() else p.with_suffix(".dta")
        if dsc_p.exists() and dta_p.exists():
            dsc_txt = _read_text_auto(dsc_p)
            xmin_m = re.search(r"XMIN\s+([0-9.+-eE]+)", dsc_txt)
            xwid_m = re.search(r"XWID\s+([0-9.+-eE]+)", dsc_txt)
            mwfq_m = re.search(r"MWFQ\s+([0-9.+-eE]+)", dsc_txt)
            bseq_big = "BIG" in dsc_txt
            dt = ">f8" if bseq_big else "<f8"
            y_arr = np.frombuffer(dta_p.read_bytes(), dtype=dt).astype(float)
            x0 = float(xmin_m.group(1)) if xmin_m else 3300.0
            xw = float(xwid_m.group(1)) if xwid_m else 200.0
            b_gauss = np.linspace(x0, x0 + xw, len(y_arr))
            if mwfq_m:
                nu_hz = float(mwfq_m.group(1))
                # g = h * nu / (mu_B * B_Tesla), where B_Tesla = B_Gauss * 1e-4
                h_planck = 6.62607015e-34
                mu_bohr = 9.2740100783e-24
                g_arr = (h_planck * nu_hz) / (mu_bohr * b_gauss * 1e-4)
                order = np.argsort(g_arr)
                return {"modality": "EPR", "source": str(p), "x": g_arr[order], "y": y_arr[order], "x_label": "$g$-factor"}
            return {"modality": "EPR", "source": str(p), "x": b_gauss, "y": y_arr, "x_label": "Magnetic Field (G)"}

    txt = _read_text_auto(p)
    xs, ys = [], []
    x_label = "$g$-factor"
    for line in txt.splitlines():
        s = line.strip()
        if "Field" in s and "[G]" in s:
            x_label = "Magnetic Field (G)"
        parts = s.split()
        if len(parts) == 3:
            try:
                _ = int(parts[0])
                xs.append(float(parts[1]))
                ys.append(float(parts[2]))
            except ValueError:
                continue
    if len(xs) < 10:
        res = parse_xy_text(p, despike=False)
        res["modality"] = "EPR"
        res["x_label"] = x_label
        return res
    x_arr = np.asarray(xs, dtype=float)
    y_arr = np.asarray(ys, dtype=float)
    order = np.argsort(x_arr)
    return {"modality": "EPR", "source": str(p), "x": x_arr[order], "y": y_arr[order], "x_label": x_label}


def parse_bet_isotherm(path: str | Path) -> Dict[str, Any]:
    """Parse N2 Adsorption-Desorption Isotherm CSV/XLSX and automatically split Adsorption vs Desorption branches."""
    p = Path(path)
    if p.suffix.lower() == ".xlsx":
        df = pd.read_excel(p)
        vals = df.select_dtypes(include=[np.number]).dropna().to_numpy()
        p_rel, vol = vals[:, 0], vals[:, 1]
    else:
        txt = _read_text_auto(p)
        pr_list, v_list = [], []
        for line in txt.splitlines():
            parts = [tok.strip().strip('"') for tok in line.split(",")]
            if len(parts) >= 2:
                try:
                    pr_list.append(float(parts[0]))
                    v_list.append(float(parts[1]))
                except ValueError:
                    continue
        p_rel = np.asarray(pr_list, dtype=float)
        vol = np.asarray(v_list, dtype=float)

    if len(p_rel) < 5:
        raise ValueError(f"Insufficient isotherm points in {p}")

    # Split at maximum relative pressure apex into Adsorption (ascending P/P0) and Desorption (descending P/P0)
    apex_idx = int(np.argmax(p_rel))
    ads_x, ads_y = p_rel[: apex_idx + 1], vol[: apex_idx + 1]
    des_x, des_y = p_rel[apex_idx:], vol[apex_idx:]

    return {
        "modality": "BET_Isotherm",
        "source": str(p),
        "ads_p_p0": ads_x,
        "ads_vol": ads_y,
        "des_p_p0": des_x,
        "des_vol": des_y,
        "max_vol_cm3_g": float(np.max(vol)),
    }


def parse_bet_psd(path: str | Path) -> Dict[str, Any]:
    """Parse BJH / DFT / HK Pore Size Distribution CSV (Diameter, Pore Volume, Pore Surf Area, dV(d), dS(d), dV(logd)...)."""
    p = Path(path)
    df = pd.read_csv(p)
    cols = [c.strip() for c in df.columns]
    df.columns = cols
    diam = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy()
    cum_vol = pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy()
    # Prefer dV(logd) if present, else dV(d)
    dv_logd_col = next((c for c in cols if "logd" in c.lower() and "dv" in c.lower()), None)
    dv_d_col = next((c for c in cols if "dv" in c.lower()), cols[min(3, len(cols) - 1)])
    use_col = dv_logd_col or dv_d_col
    diff_val = pd.to_numeric(df[use_col], errors="coerce").to_numpy()

    mask = np.isfinite(diam) & np.isfinite(diff_val)
    return {
        "modality": "BET_PSD",
        "source": str(p),
        "diameter_nm": diam[mask],
        "cum_pore_vol": cum_vol[mask],
        "diff_vol": diff_val[mask],
        "y_label": "$\\mathrm{d}V/\\mathrm{d}\\log D$ ($\\mathrm{cm^3\\ g^{-1}}$)" if dv_logd_col else "$\\mathrm{d}V/\\mathrm{d}D$ ($\\mathrm{cm^3\\ g^{-1}\\ nm^{-1}}$)",
    }


def parse_mastersizer_xls(path: str | Path) -> Dict[str, Any]:
    """Parse Malvern Mastersizer 2000 .xls/.xlsx report into logarithmic channels, differential Vol%, cumulative Vol%, and D10/D50/D90."""
    p = Path(path)
    if p.suffix.lower() == ".xls":
        sheets_map = _load_xls_sheets_via_xlrd_or_bridge(p)
        rows = next(iter(sheets_map.values()))
    else:
        import openpyxl
        wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
        ws = wb[wb.sheetnames[0]]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()

    meta: Dict[str, float] = {}
    sizes_um: List[float] = []
    vol_avg: List[float] = []
    replicates_list: List[List[float]] = []

    in_channels = False
    for r in rows:
        if not r:
            continue
        k = str(r[0] or "").strip().lower()
        nums_in_row = [float(v) for v in r[1:] if isinstance(v, (int, float)) and np.isfinite(v)]
        if k.startswith("d (0.1)") and nums_in_row:
            meta["D10_um"] = nums_in_row[-1]
        elif k.startswith("d (0.5)") and nums_in_row:
            meta["D50_um"] = nums_in_row[-1]
        elif k.startswith("d (0.9)") and nums_in_row:
            meta["D90_um"] = nums_in_row[-1]
        elif "d [4, 3]" in k and nums_in_row:
            meta["D43_um"] = nums_in_row[-1]
        elif k == "span" and nums_in_row:
            meta["Span"] = nums_in_row[-1]
        elif "result between user sizes" in k or "sizes in um" in k:
            in_channels = True
            continue
        elif in_channels:
            if len(r) >= 3 and isinstance(r[1], (int, float)) and isinstance(r[2], (int, float)):
                sz = float(r[1])
                row_vals = [float(v) for v in r[2:] if isinstance(v, (int, float))]
                if sz > 0 and row_vals:
                    sizes_um.append(sz)
                    vol_avg.append(row_vals[-1])
                    replicates_list.append(row_vals[:-1] if len(row_vals) > 1 else [row_vals[-1]])

    if len(sizes_um) < 10:
        raise ValueError(f"Could not extract Mastersizer size channels from {p}")

    sz_arr = np.asarray(sizes_um, dtype=float)
    vol_arr = np.asarray(vol_avg, dtype=float)
    total = float(np.sum(vol_arr))
    cum_arr = np.cumsum(vol_arr) * (100.0 / total if total > 0 else 1.0)

    return {
        "modality": "Particle_Size",
        "source": str(p),
        "size_um": sz_arr,
        "diff_vol_pct": vol_arr,
        "cum_vol_pct": cum_arr,
        "metrics": meta,
    }


def parse_conductivity_xlsx(path: str | Path) -> Dict[str, Any]:
    """Parse 4-probe powder resistivity/conductivity vs pressure .xlsx report (e.g. ST2742B-SD)."""
    import openpyxl

    p = Path(path)
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    header_idx = None
    col_map: Dict[str, int] = {}
    for i, r in enumerate(rows):
        joined = " ".join(str(c or "") for c in r)
        if "压强" in joined and ("电导率" in joined or "电阻率" in joined):
            header_idx = i
            for c_i, cell in enumerate(r):
                cs = str(cell or "")
                if "压强" in cs:
                    col_map["pressure_MPa"] = c_i
                elif "密度" in cs:
                    col_map["density_g_cm3"] = c_i
                elif "电阻率" in cs and "读数" not in cs:
                    col_map["resistivity"] = c_i
                    col_map["resistivity_unit"] = cs
                elif "电导率" in cs:
                    col_map["conductivity"] = c_i
                    col_map["conductivity_unit"] = cs
            break

    if header_idx is None or "pressure_MPa" not in col_map:
        raise ValueError(f"Could not locate pressure/conductivity header in {p}")

    pressures, densities, conds, resis = [], [], [], []
    for r in rows[header_idx + 1 :]:
        if not r or not isinstance(r[0], (int, float)):
            continue
        pr = r[col_map["pressure_MPa"]]
        if not isinstance(pr, (int, float)):
            continue
        pressures.append(float(pr))
        dn = r[col_map["density_g_cm3"]] if "density_g_cm3" in col_map else np.nan
        densities.append(float(dn) if isinstance(dn, (int, float)) else np.nan)
        cd = r[col_map["conductivity"]] if "conductivity" in col_map else np.nan
        conds.append(float(cd) if isinstance(cd, (int, float)) else np.nan)
        rs = r[col_map["resistivity"]] if "resistivity" in col_map else np.nan
        resis.append(float(rs) if isinstance(rs, (int, float)) else np.nan)

    cond_unit_raw = str(col_map.get("conductivity_unit", "S/cm"))
    cond_arr = np.asarray(conds, dtype=float)
    y_unit = "Conductivity (nS cm$^{-1}$)" if "ns" in cond_unit_raw.lower() else (
        "Conductivity ($\\mu$S cm$^{-1}$)" if ("us" in cond_unit_raw.lower() or "μs" in cond_unit_raw.lower()) else "Conductivity (S cm$^{-1}$)"
    )

    return {
        "modality": "Conductivity",
        "source": str(p),
        "pressure_MPa": np.asarray(pressures, dtype=float),
        "density_g_cm3": np.asarray(densities, dtype=float),
        "conductivity": cond_arr,
        "resistivity": np.asarray(resis, dtype=float),
        "conductivity_label": y_unit,
    }


def parse_neware_ndax(path: str | Path, mass_mg_override: Optional[float] = None) -> Dict[str, Any]:
    """
    Native pure-Python binary parser for Neware BTS8 (.ndax) files (NDC v11 / v14+).
    Directly decodes Step.xml, data.ndc, and data_runInfo.ndc without BTSDA client export,
    preserving true hardware millisecond timing and float32 voltage/current precision.
    """
    p = Path(path)
    if not zipfile.is_zipfile(p):
        raise ValueError(f"File is not a valid ZIP-based Neware .ndax archive: {p}")

    with zipfile.ZipFile(p, "r") as zf:
        names = set(zf.namelist())
        if "data.ndc" not in names or "data_runInfo.ndc" not in names:
            raise ValueError(f"Missing data.ndc or data_runInfo.ndc inside .ndax: {p}")
        b_dat = zf.read("data.ndc")
        b_run = zf.read("data_runInfo.ndc")
        step_xml = zf.read("Step.xml").decode("gb18030", errors="ignore") if "Step.xml" in names else ""

    # 1. Extract active mass (mg) from override -> Step.xml <SCQ Value="928"/> (ug) -> filename regex
    mass_mg: Optional[float] = mass_mg_override
    if mass_mg is None and step_xml:
        scq_m = re.search(r'<SCQ\s+Value="([0-9.+-eE]+)"', step_xml)
        if scq_m and float(scq_m.group(1)) > 0:
            mass_mg = float(scq_m.group(1)) / 1000.0
    if mass_mg is None:
        fn_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mg", p.name, re.IGNORECASE)
        if fn_m:
            mass_mg = float(fn_m.group(1))

    # 2. Decode data.ndc 4096-byte pages using fixed 8-byte slot stride & 128-byte validity bitmask
    _, ndc_ver = struct.unpack_from("<HH", b_dat, 0)
    _, run_ver = struct.unpack_from("<HH", b_run, 0)
    max_slots_dat = (4096 - 132) // 8
    n_pages_dat = len(b_dat) // 4096
    v_list: List[float] = []
    i_list: List[float] = []

    for pg in range(1, n_pages_dat):
        base_off = pg * 4096
        p_type, _ = struct.unpack_from("<HH", b_dat, base_off)
        if p_type == 0:
            continue
        bm = b_dat[base_off + 4 : base_off + 132]
        if bm == b"\xff" * 61 + b"\x7f" + b"\x00" * 66:
            # Fast-path for full 495-slot page
            arr = np.frombuffer(b_dat, dtype="<f4", count=max_slots_dat * 2, offset=base_off + 132).reshape(-1, 2)
            v_list.extend(arr[:, 0].tolist())
            i_list.extend(arr[:, 1].tolist())
        else:
            for k in range(max_slots_dat):
                if (bm[k >> 3] >> (k & 7)) & 1:
                    vf, cf = struct.unpack_from("<ff", b_dat, base_off + 132 + k * 8)
                    v_list.append(vf)
                    i_list.append(cf)

    if not v_list:
        raise ValueError(f"No valid voltage/current records decoded from data.ndc in {p}")

    v_raw = np.asarray(v_list, dtype=float)
    i_raw = np.asarray(i_list, dtype=float)

    # NDC v11 stores 0.1 mV & mA; NDC v14+ stores SI Volts & Amps
    if ndc_ver <= 11 or float(np.nanmax(np.abs(v_raw))) > 100.0:
        voltage_V = v_raw / 10000.0
        current_A = i_raw / 1000.0
    else:
        voltage_V = v_raw
        current_A = i_raw

    n_total = len(voltage_V)

    # 3. Decode data_runInfo.ndc keyframes using fixed version record size (47B for v11, 55B for v14+) & bitmask
    rec_sz_run = 47 if run_ver <= 11 else 55
    max_slots_run = (4096 - 132) // rec_sz_run
    n_pages_run = len(b_run) // 4096
    kf_step: List[int] = []
    kf_rec: List[int] = []
    kf_tms: List[int] = []

    for pg in range(1, n_pages_run):
        base_off = pg * 4096
        p_type, _ = struct.unpack_from("<HH", b_run, base_off)
        if p_type == 0:
            continue
        bm = b_run[base_off + 4 : base_off + 132]
        for k in range(max_slots_run):
            if (bm[k >> 3] >> (k & 7)) & 1:
                r_off = base_off + 132 + k * rec_sz_run
                t_ms = struct.unpack_from("<I", b_run, r_off)[0]
                step_seq, rec_seq = struct.unpack_from("<II", b_run, r_off + 37)
                if step_seq > 0 and 1 <= rec_seq <= n_total:
                    kf_step.append(int(step_seq))
                    kf_rec.append(int(rec_seq - 1))
                    kf_tms.append(int(t_ms))

    step_seq_arr = np.ones(n_total, dtype=int)
    step_time_s = np.zeros(n_total, dtype=float)

    if kf_rec:
        kf_step_a = np.asarray(kf_step, dtype=int)
        kf_rec_a = np.asarray(kf_rec, dtype=int)
        kf_t_a = np.asarray(kf_tms, dtype=float) / 1000.0

        # Group keyframes by step_seq to interpolate step_time_s smoothly inside each step
        unique_steps = []
        for s_id in kf_step_a:
            if not unique_steps or unique_steps[-1] != s_id:
                unique_steps.append(int(s_id))

        for s_id in unique_steps:
            m_s = kf_step_a == s_id
            r_idx = kf_rec_a[m_s]
            t_vals = kf_t_a[m_s]
            i0, i1 = int(r_idx[0]), int(r_idx[-1])
            step_seq_arr[i0 : i1 + 1] = s_id
            if len(r_idx) >= 2 and i1 > i0:
                grid = np.arange(i0, i1 + 1, dtype=float)
                step_time_s[i0 : i1 + 1] = np.interp(grid, r_idx.astype(float), t_vals)
            else:
                step_time_s[i0] = float(t_vals[0])

        # Extend tail if any trailing samples beyond last keyframe
        last_i = int(kf_rec_a[-1])
        if last_i + 1 < n_total:
            step_seq_arr[last_i + 1 :] = int(kf_step_a[-1])
            dt_est = float(step_time_s[last_i] - step_time_s[max(0, last_i - 1)]) if last_i > 0 else 0.1
            step_time_s[last_i + 1 :] = step_time_s[last_i] + np.arange(1, n_total - last_i) * max(dt_est, 0.001)

    # 4. Build cumulative total_time_s and per-step capacity_mAh / energy_mWh via exact trapezoidal rule
    total_time_s = np.zeros(n_total, dtype=float)
    step_cap_mAh = np.zeros(n_total, dtype=float)
    step_eng_mWh = np.zeros(n_total, dtype=float)

    t_accum = 0.0
    for s_id in np.unique(step_seq_arr):
        idxs = np.where(step_seq_arr == s_id)[0]
        if len(idxs) == 0:
            continue
        st = step_time_s[idxs]
        total_time_s[idxs] = t_accum + st
        if len(idxs) > 1:
            dt = np.diff(st, prepend=st[0])
            dt = np.maximum(dt, 0.0)
            i_abs = np.abs(current_A[idxs])
            v_seg = voltage_V[idxs]
            # Trapezoidal incremental dQ (A*s / 3.6 = mAh) and dE (W*s / 3.6 = mWh)
            i_mid = 0.5 * (i_abs + np.roll(i_abs, 1))
            i_mid[0] = i_abs[0]
            p_mid = 0.5 * (i_abs * v_seg + np.roll(i_abs * v_seg, 1))
            p_mid[0] = i_abs[0] * v_seg[0]
            step_cap_mAh[idxs] = np.cumsum(i_mid * dt / 3.6)
            step_eng_mWh[idxs] = np.cumsum(p_mid * dt / 3.6)
        t_accum = float(total_time_s[idxs[-1]])

    has_mass = bool(mass_mg and mass_mg > 0)
    mass_g = (mass_mg / 1000.0) if has_mass else None
    spec_cap_mAh_g = (step_cap_mAh / mass_g) if mass_g else None
    spec_eng_Wh_kg = (step_eng_mWh / mass_g) if mass_g else None  # mWh / g == Wh / kg

    return {
        "modality": "Neware_NDAX",
        "source": str(p),
        "ndc_version": int(ndc_ver),
        "mass_mg": mass_mg if has_mass else None,
        "has_active_mass": has_mass,
        "step_seq": step_seq_arr,
        "step_time_s": step_time_s,
        "total_time_s": total_time_s,
        "voltage_V": voltage_V,
        "current_A": current_A,
        "capacity_mAh": step_cap_mAh,
        "specific_capacity_mAh_g": spec_cap_mAh_g,
        "energy_mWh": step_eng_mWh,
        "specific_energy_Wh_kg": spec_eng_Wh_kg,
    }


def parse_xps_vamas(path: str | Path, region_hint: str = "C1s") -> Dict[str, Any]:
    """Parse standard ISO 14976 VAMAS (.vms) multi-block ASCII XPS file (CasaXPS / Kratos / PHI)."""
    p = Path(path)
    lines = [l.strip() for l in _read_text_auto(p).splitlines()]
    # Locate block matching region_hint (e.g., 'C 1s' or 'C1s')
    h_norm = region_hint.lower().replace(" ", "")
    # Scan for kinetic/binding energy step markers ('binding energy' or 'kinetic energy' + source energy)
    blocks: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines):
        if ln.lower() in ("binding energy", "kinetic energy") and i + 15 < len(lines):
            # Look back ~15 lines for species/transition label
            window_back = " ".join(lines[max(0, i - 18) : i]).lower().replace(" ", "")
            try:
                x_start = float(lines[i + 2])
                x_step = float(lines[i + 3])
                # Find '1' or n_corresponding_variables followed by point count
                y_vals: List[float] = []
                # In standard regular-scan VAMAS, data count integer sits ~10-20 lines after axis unit
                for j in range(i + 6, min(len(lines) - 5, i + 32)):
                    if lines[j].isdigit() and int(lines[j]) >= 20:
                        n_pts = int(lines[j])
                        # Check if lines[j+3 : j+3+n_pts] (after min/max ordinates) are floats
                        cand = lines[j + 3 : j + 3 + n_pts]
                        if len(cand) == n_pts:
                            y_vals = [float(v) for v in cand]
                            x_arr = x_start + np.arange(n_pts, dtype=float) * x_step
                            if ln.lower() == "kinetic energy":
                                # Try finding photon energy (e.g. 1486.6 eV Al Ka) right before
                                hv = 1486.6
                                for b_ln in lines[max(0, i - 8) : i]:
                                    try:
                                        fv = float(b_ln)
                                        if 1000.0 < fv < 5000.0:
                                            hv = fv
                                            break
                                    except ValueError:
                                        pass
                                x_arr = hv - x_arr
                            order = np.argsort(x_arr)
                            blocks.append({"tag": window_back, "x": x_arr[order], "y": np.asarray(y_vals, dtype=float)[order]})
                            break
            except ValueError:
                continue

    if not blocks:
        raise ValueError(f"No valid regular-scan VAMAS spectrum blocks parsed from {p}")
    for b in blocks:
        if h_norm in b["tag"]:
            return {"modality": "XPS", "region": region_hint, "source": str(p), "x": b["x"], "y": b["y"], "vendor_bg": None, "x_unit": "eV", "y_unit": "Counts / s"}
    raise KeyError(f"Region '{region_hint}' not found in VAMAS blocks {[b['tag'] for b in blocks]} of {p.name}")


def parse_neware_nda(path: str | Path, mass_mg_override: Optional[float] = None) -> Dict[str, Any]:
    """
    Native pure-Python binary parser for legacy Neware BTS7 (.nda, 'NEWARE...' header) files.
    Reads active mass (@152 ug), hardware current range (@2070 mA), and 86-byte 0x0055 data records.
    """
    p = Path(path)
    raw = p.read_bytes()
    if not raw.startswith(b"NEWARE"):
        raise ValueError(f"Invalid Neware .nda signature: {p}")

    mass_mg = mass_mg_override
    if mass_mg is None and len(raw) >= 160:
        ug = struct.unpack_from("<I", raw, 152)[0]
        if 10 <= ug <= 50_000_000:
            mass_mg = float(ug) / 1000.0
    if mass_mg is None:
        fn_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mg", p.name, re.IGNORECASE)
        if fn_m:
            mass_mg = float(fn_m.group(1))

    data_off = struct.unpack_from("<I", raw, 64)[0]
    data_len = struct.unpack_from("<I", raw, 68)[0]
    curr_range_mA = struct.unpack_from("<i", raw, 2070)[0] if len(raw) > 2080 else 100
    if curr_range_mA <= 0:
        curr_range_mA = 100
    # 1 current count = (CurrRange_mA / 10000) mA = CurrRange_mA * 1e-7 A
    curr_scale_A = float(curr_range_mA) * 1e-7
    cap_scale_mAh = (float(curr_range_mA) * 1e-4) / 3600.0

    stride = 86
    n_rec = min((len(raw) - data_off) // stride, data_len // stride if data_len > 0 else 10_000_000)
    if n_rec <= 0:
        raise ValueError(f"No 86-byte data records found in .nda: {p}")

    step_ids: List[int] = []
    step_tms: List[float] = []
    volts: List[float] = []
    currs: List[float] = []
    caps_mAh: List[float] = []
    engs_mWh: List[float] = []

    prev_stype = -1
    logical_step_seq = 0

    for k in range(n_rec):
        roff = data_off + k * stride
        magic = struct.unpack_from("<H", raw, roff)[0]
        if magic != 0x0055:
            continue
        _, _, sid, stype, tms, v_i, cur_i = struct.unpack_from("<IIHHQii", raw, roff + 2)
        _, q_dchg, _, e_dchg = struct.unpack_from("<QQQQ", raw, roff + 38)
        if stype != prev_stype or (tms == 0 and k > 0 and step_tms and step_tms[-1] > 0):
            logical_step_seq += 1
            prev_stype = stype
        # Sign convention: stype == 2 is discharge (negative current)
        i_val = float(cur_i) * curr_scale_A
        if stype == 2 and i_val > 0:
            i_val = -i_val
        step_ids.append(max(logical_step_seq, 1))
        step_tms.append(float(tms) / 1000.0)
        volts.append(float(v_i) / 10000.0)
        currs.append(i_val)
        caps_mAh.append(float(q_dchg) * cap_scale_mAh)
        engs_mWh.append(float(e_dchg) * cap_scale_mAh)  # 0.1mV * count scaling aligns via V integration below

    step_seq_arr = np.asarray(step_ids, dtype=int)
    step_time_s = np.asarray(step_tms, dtype=float)
    voltage_V = np.asarray(volts, dtype=float)
    current_A = np.asarray(currs, dtype=float)
    step_cap_mAh = np.asarray(caps_mAh, dtype=float)

    # Compute exact step energy_mWh and total_time_s from V(t), I(t), and step_cap_mAh increments
    total_time_s = np.zeros_like(step_time_s)
    step_eng_mWh = np.zeros_like(step_cap_mAh)
    t_acc = 0.0
    for s_id in np.unique(step_seq_arr):
        idxs = np.where(step_seq_arr == s_id)[0]
        total_time_s[idxs] = t_acc + step_time_s[idxs]
        if len(idxs) > 1:
            dq = np.diff(step_cap_mAh[idxs], prepend=0.0)
            dq = np.maximum(dq, 0.0)
            step_eng_mWh[idxs] = np.cumsum(dq * voltage_V[idxs])
        t_acc = float(total_time_s[idxs[-1]])

    has_mass = bool(mass_mg and mass_mg > 0)
    mass_g = (mass_mg / 1000.0) if has_mass else None
    return {
        "modality": "Neware_NDA",
        "source": str(p),
        "mass_mg": mass_mg if has_mass else None,
        "has_active_mass": has_mass,
        "step_seq": step_seq_arr,
        "step_time_s": step_time_s,
        "total_time_s": total_time_s,
        "voltage_V": voltage_V,
        "current_A": current_A,
        "capacity_mAh": step_cap_mAh,
        "specific_capacity_mAh_g": (step_cap_mAh / mass_g) if mass_g else None,
        "energy_mWh": step_eng_mWh,
        "specific_energy_Wh_kg": (step_eng_mWh / mass_g) if mass_g else None,
    }


def parse_neware_auto(path: str | Path, mass_mg_override: Optional[float] = None) -> Dict[str, Any]:
    """Unified dispatcher for Neware BTS8 (.ndax), legacy BTS7 (.nda), and exported (.csv) files."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".ndax":
        return parse_neware_ndax(p, mass_mg_override=mass_mg_override)
    if ext == ".nda":
        return parse_neware_nda(p, mass_mg_override=mass_mg_override)
    if ext == ".csv":
        for enc in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                df = pd.read_csv(p, encoding=enc, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"Cannot decode CSV encoding: {p}")
        mass_mg = mass_mg_override
        if mass_mg is None:
            for mcol in ("活性物质质量(mg)", "质量(mg)", "Mass(mg)"):
                if mcol in df.columns:
                    mv = pd.to_numeric(df[mcol], errors="coerce").dropna()
                    if len(mv) > 0 and float(mv.iloc[0]) > 0:
                        mass_mg = float(mv.iloc[0])
                        break
        if mass_mg is None:
            fn_m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*mg", p.name, re.IGNORECASE)
            if fn_m:
                mass_mg = float(fn_m.group(1))
        step_seq = pd.to_numeric(df.get("工步序号", df.get("工步号", 1)), errors="coerce").fillna(1).astype(int).to_numpy()
        t_s = pd.to_numeric(df.get("时间(s)", 0.0), errors="coerce").fillna(0.0).to_numpy()
        volt = pd.to_numeric(df["电压(V)"], errors="coerce").to_numpy()
        curr = pd.to_numeric(df.get("电流(A)", 0.0), errors="coerce").fillna(0.0).to_numpy()
        cap_mAh = pd.to_numeric(df.get("容量(mAh)", 0.0), errors="coerce").fillna(0.0).to_numpy()
        eng_mWh = pd.to_numeric(df.get("能量(mWh)", 0.0), errors="coerce").fillna(0.0).to_numpy()
        has_mass = bool(mass_mg and mass_mg > 0)
        mass_g = (mass_mg / 1000.0) if has_mass else None
        return {
            "modality": "Neware_CSV",
            "source": str(p),
            "mass_mg": mass_mg if has_mass else None,
            "has_active_mass": has_mass,
            "step_seq": step_seq,
            "step_time_s": t_s,
            "total_time_s": np.cumsum(np.maximum(np.diff(t_s, prepend=0.0), 0.0)),
            "voltage_V": volt,
            "current_A": curr,
            "capacity_mAh": cap_mAh,
            "specific_capacity_mAh_g": (cap_mAh / mass_g) if mass_g else None,
            "energy_mWh": eng_mWh,
            "specific_energy_Wh_kg": (eng_mWh / mass_g) if mass_g else None,
        }
    raise ValueError(f"Unsupported Neware file extension '{ext}': {p}")


def extract_primary_discharge_curve(ndax_data: Dict[str, Any], voltage_cutoff: Optional[float] = None) -> Dict[str, Any]:
    """Select the main discharge step (largest capacity step with I < 0); preserve raw mAh when mass is absent."""
    step_seq = ndax_data["step_seq"]
    cur = ndax_data["current_A"]
    cap_raw = ndax_data["capacity_mAh"]
    eng_raw = ndax_data["energy_mWh"]
    has_mass = bool(ndax_data.get("has_active_mass", bool(ndax_data.get("mass_mg"))))
    cap_spec = ndax_data.get("specific_capacity_mAh_g") if has_mass else None
    eng_spec = ndax_data.get("specific_energy_Wh_kg") if has_mass else None
    volt = ndax_data["voltage_V"]
    t_s = ndax_data["step_time_s"]

    best_step = None
    best_q = -1.0
    for s_id in np.unique(step_seq):
        m = step_seq == s_id
        if np.median(cur[m]) < -1e-7:
            q_max = float(np.max(cap_raw[m]))
            if q_max > best_q:
                best_q = q_max
                best_step = int(s_id)

    if best_step is None:
        raise ValueError(f"No discharge step (I < 0) found in {ndax_data.get('source')}")

    mask = step_seq == best_step
    if voltage_cutoff is not None:
        mask = mask & (volt >= voltage_cutoff)

    q_raw_out = cap_raw[mask]
    e_raw_out = eng_raw[mask]
    q_spec_out = cap_spec[mask] if cap_spec is not None else None
    e_spec_out = eng_spec[mask] if eng_spec is not None else None
    v_out = volt[mask]
    t_out = t_s[mask]
    dur_h = max(float(t_out[-1] - t_out[0]), 1e-6) / 3600.0
    i_mean_mA = float(np.mean(np.abs(cur[mask])) * 1000.0)

    half_q = 0.5 * float(np.max(q_raw_out))
    med_v = float(v_out[int(np.argmin(np.abs(q_raw_out - half_q)))])
    max_cap_raw = float(np.max(q_raw_out))
    max_eng_raw = float(np.max(e_raw_out))

    return {
        "step_seq": best_step,
        "time_s": t_out,
        "has_active_mass": has_mass,
        "mass_mg": ndax_data.get("mass_mg") if has_mass else None,
        "capacity_mAh": q_raw_out,
        "energy_mWh": e_raw_out,
        "specific_capacity_mAh_g": q_spec_out,
        "voltage_V": v_out,
        "max_capacity_mAh": max_cap_raw,
        "max_energy_mWh": max_eng_raw,
        "avg_power_mW": float(max_eng_raw / dur_h),
        "max_capacity_mAh_g": float(np.max(q_spec_out)) if q_spec_out is not None else None,
        "max_energy_Wh_kg": float(np.max(e_spec_out)) if e_spec_out is not None else None,
        "median_voltage_V": med_v,
        "avg_power_W_kg": float(np.max(e_spec_out) / dur_h) if e_spec_out is not None else None,
        "mean_current_mA": i_mean_mA,
    }


def scan_directory(target_dir: str | Path) -> Dict[str, Any]:
    """Scan an experimental folder, classify files by all 12 modalities, and surface README/notes."""
    root = Path(target_dir).resolve()
    ext_counts: Dict[str, int] = {}
    detected_files: Dict[str, List[str]] = {
        "XPS": [],
        "Raman_or_XY": [],
        "FTIR": [],
        "XRD": [],
        "EIS": [],
        "BET_Porosity": [],
        "Particle_Size": [],
        "Conductivity": [],
        "Electrochem_Neware": [],
        "EPR": [],
        "Microscopy": [],
        "Notes": [],
    }

    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            fp = Path(dirpath) / fn
            rel = str(fp.relative_to(root))
            ext = fp.suffix.lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

            low_fn = fn.lower()
            low_path = str(fp).lower()
            if "说明" in low_fn or "readme" in low_fn:
                detected_files["Notes"].append(rel)
            elif ext in (".vgd", ".vgp") or ("xps" in low_path and ext in (".xls", ".xlsx")):
                detected_files["XPS"].append(rel)
            elif ext in (".rasx", ".asc", ".raw") or ("xrd" in low_path and ext == ".txt"):
                detected_files["XRD"].append(rel)
            elif ext == ".spa" or ("ftir" in low_path and ext == ".csv"):
                detected_files["FTIR"].append(rel)
            elif ext in (".z60", ".cor") or (("阻抗" in str(fp) or "eis" in low_path) and ext == ".txt"):
                detected_files["EIS"].append(rel)
            elif ("isotherm" in low_fn or "bjh" in low_fn or "dft" in low_fn or "比表" in str(fp)) and ext in (".csv", ".xlsx", ".qps"):
                detected_files["BET_Porosity"].append(rel)
            elif ("粒度" in str(fp) or "mastersizer" in low_fn) and ext in (".xls", ".xlsx"):
                detected_files["Particle_Size"].append(rel)
            elif ("电导" in str(fp) or "电阻" in str(fp)) and ext in (".xls", ".xlsx"):
                detected_files["Conductivity"].append(rel)
            elif ext in (".ndax", ".nda", ".cex"):
                detected_files["Electrochem_Neware"].append(rel)
            elif ext in (".dsc", ".dta") or "+g" in low_fn or ("epr" in low_path and ext == ""):
                detected_files["EPR"].append(rel)
            elif ext in (".dm4", ".hdr", ".oipx"):
                detected_files["Microscopy"].append(rel)
            elif ext == ".txt":
                detected_files["Raman_or_XY"].append(rel)

    notes_preview = {}
    for n_rel in detected_files["Notes"][:5]:
        notes_preview[n_rel] = _read_text_auto(root / n_rel)[:600]

    return {
        "scanned_root": str(root),
        "extension_counts": dict(sorted(ext_counts.items(), key=lambda kv: -kv[1])),
        "classified_counts": {k: len(v) for k, v in detected_files.items() if v},
        "sample_files": {k: v[:12] for k, v in detected_files.items() if v},
        "notes_preview": notes_preview,
    }


def _estimate_snr_quick(y: np.ndarray) -> float:
    if len(y) < 12:
        return 0.0
    k = max(1, min(6, len(y) // 6))
    y0, y1 = float(np.mean(y[:k])), float(np.mean(y[-k:]))
    bg = np.linspace(y0, y1, len(y))
    net = y - bg
    dy_noise = float(np.std(np.diff(y)) / 1.4142) if len(y) > 5 else 1.0
    return round(float(np.max(net)) / max(dy_noise, 1e-9), 2)


def inspect_data_file(path: str | Path) -> Dict[str, Any]:
    """Open an experimental file or directory and report its real sheets/regions, columns, units, SNR, and missing metadata."""
    p = Path(path).resolve()
    if p.is_dir():
        return scan_directory(p)
    ext = p.suffix.lower()

    if ext in (".xls", ".xlsx"):
        if ext == ".xls":
            sheets_map = _load_xls_sheets_via_xlrd_or_bridge(p)
        else:
            import openpyxl
            wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
            sheets_map = {s: [list(r) for r in wb[s].iter_rows(values_only=True)] for s in wb.sheetnames}
            wb.close()

        sheet_reports: Dict[str, Any] = {}
        for sname, rows in sheets_map.items():
            non_empty = [r for r in rows if any(v not in ("", None) for v in r)]
            head_sample = [r[:10] for r in non_empty[:4]]
            info: Dict[str, Any] = {"row_count": len(rows), "head_preview": head_sample}
            # Try extracting Avantage spectrum metrics when possible
            if ("scan" in sname.lower() or "survey" in sname.lower()) and len(rows) > 15:
                try:
                    spec = _extract_avantage_rows(rows, sname, str(p))
                    xv, yv = spec["x"], spec["y"]
                    pk_idx = int(np.argmax(yv))
                    info.update(
                        {
                            "kind": "XPS_Spectrum",
                            "x_range_eV": [round(float(xv.min()), 2), round(float(xv.max()), 2)],
                            "y_range": [round(float(yv.min()), 1), round(float(yv.max()), 1)],
                            "raw_max_peak_eV": round(float(xv[pk_idx]), 2),
                            "approx_snr": _estimate_snr_quick(yv),
                            "n_points": int(len(xv)),
                        }
                    )
                except Exception:
                    pass
            elif len(non_empty) > 5 and isinstance(non_empty[1][0] if len(non_empty) > 1 and non_empty[1] else None, (int, float)):
                info["kind"] = "Tabular_or_Fitted_Sheet"
                info["columns"] = [str(c) for c in non_empty[0] if c not in ("", None)]
            sheet_reports[sname] = info

        return {
            "file": str(p),
            "extension": ext,
            "sheet_names": list(sheets_map.keys()),
            "sheets": sheet_reports,
        }

    if ext in (".ndax", ".nda", ".csv"):
        try:
            nd = parse_neware_auto(p)
            step_seq = nd["step_seq"]
            steps_summary = []
            for s_id in np.unique(step_seq)[:12]:
                m = step_seq == s_id
                i_med = float(np.median(nd["current_A"][m]))
                steps_summary.append(
                    {
                        "step": int(s_id),
                        "points": int(np.sum(m)),
                        "median_current_mA": round(i_med * 1000.0, 4),
                        "v_range_V": [round(float(nd["voltage_V"][m].min()), 3), round(float(nd["voltage_V"][m].max()), 3)],
                        "max_cap_mAh": round(float(nd["capacity_mAh"][m].max()), 4),
                    }
                )
            return {
                "file": str(p),
                "modality": nd["modality"],
                "has_active_mass": nd["has_active_mass"],
                "mass_mg": nd["mass_mg"],
                "missing_fields": ([] if nd["has_active_mass"] else ["active_mass_mg"]),
                "total_points": int(len(nd["voltage_V"])),
                "steps": steps_summary,
            }
        except Exception:
            pass

    if ext in (".rasx", ".asc", ".raw"):
        d = parse_xrd(p)
        return {"file": str(p), "modality": "XRD", "x_range": [float(d["x"].min()), float(d["x"].max())], "n_points": int(len(d["x"]))}
    if ext == ".spa":
        d = parse_ftir(p)
        return {"file": str(p), "modality": "FTIR", "x_range": [float(d["x"].min()), float(d["x"].max())], "n_points": int(len(d["x"]))}
    if ext == ".bin" or ext == ".z60":
        d = parse_eis(p)
        return {"file": str(p), "modality": "EIS", "freq_range_Hz": [float(d["freq_Hz"].min()), float(d["freq_Hz"].max())], "n_points": int(len(d["freq_Hz"]))}

    d = parse_xy_text(p, despike=False)
    return {
        "file": str(p),
        "modality": d["modality"],
        "x_range": [round(float(d["x"].min()), 3), round(float(d["x"].max()), 3)],
        "approx_snr": _estimate_snr_quick(d["y"]),
        "n_points": int(len(d["x"])),
    }


def parse_fitted_deconv_excel(
    path: str | Path,
    sheet_name: str,
    palette: Optional[List[str]] = None,
    invert_x: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Parse an already-fitted deconvolution Excel worksheet WITHOUT refitting.
    Supports both SciOrigin sheets ('Raw', 'Fitting', 'Backgnd.', '<Comp> (含基线)', 'Residuals')
    and Origin-ready sheets ('Processed Data', '<Peak1>', ..., 'Backgnd.', 'Envelope').
    """
    import openpyxl

    p = Path(path)
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        raise KeyError(f"Sheet '{sheet_name}' not found in {p.name}: {wb.sheetnames}")
    ws = wb[sheet_name]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    if len(rows) < 10:
        raise ValueError(f"Sheet '{sheet_name}' has too few rows to replot.")

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    x_col = 0
    raw_col, fit_col, bg_col, res_col = None, None, None, None
    comp_cols: List[Tuple[int, str]] = []
    comp_baseline_added: List[Tuple[int, str]] = []

    for idx, h in enumerate(headers[1:], start=1):
        hl = h.lower()
        if not h:
            continue
        if hl.startswith("net_"):
            continue
        if raw_col is None and (hl == "raw" or hl.startswith("raw ") or "processed data" in hl):
            raw_col = idx
        elif fit_col is None and (hl == "fitting" or hl.startswith("fitting ") or "envelope" in hl):
            fit_col = idx
        elif bg_col is None and ("backgnd" in hl or "background" in hl):
            bg_col = idx
        elif res_col is None and "residual" in hl:
            res_col = idx
        elif "(含基线)" in h:
            comp_baseline_added.append((idx, h.replace("(含基线)", "").strip()))
        else:
            comp_cols.append((idx, h))

    use_comps = comp_baseline_added if comp_baseline_added else comp_cols
    if raw_col is None or fit_col is None or bg_col is None or not use_comps:
        raise ValueError(f"Could not map Raw/Fitting/Backgnd/Component columns in '{sheet_name}': {headers}")

    data_rows = []
    for r in rows[1:]:
        if len(r) <= max(x_col, raw_col, fit_col, bg_col):
            continue
        if isinstance(r[x_col], (int, float)) and isinstance(r[raw_col], (int, float)):
            bg_v = float(r[bg_col]) if r[bg_col] is not None else 0.0
            comp_vals_raw = [float(r[ci]) if r[ci] is not None else 0.0 for ci, _ in use_comps]
            # Drop Origin polygon-closure dummy edge rows (bg==0 and all components==0 while Raw > 0)
            if bg_v == 0.0 and all(v == 0.0 for v in comp_vals_raw) and abs(float(r[raw_col])) > 10.0:
                continue
            data_rows.append(r)

    x_arr = np.asarray([float(r[x_col]) for r in data_rows], dtype=float)
    y_raw = np.asarray([float(r[raw_col]) for r in data_rows], dtype=float)
    y_fit = np.asarray([float(r[fit_col]) for r in data_rows], dtype=float)
    bg = np.asarray([float(r[bg_col]) for r in data_rows], dtype=float)
    resid = (
        np.asarray([float(r[res_col]) for r in data_rows], dtype=float)
        if res_col is not None
        else (y_raw - y_fit)
    )

    order = np.argsort(x_arr)
    x_arr, y_raw, y_fit, bg, resid = x_arr[order], y_raw[order], y_fit[order], bg[order], resid[order]

    pal = palette or ["#2E5B88", "#4A8DB7", "#65A882", "#E5B245", "#E07A5F", "#8C5679", "#5C6BC0", "#26A69A"]
    trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    comp_curves_with_bg: List[np.ndarray] = []
    comp_curves_net: List[np.ndarray] = []
    comp_metrics: List[Dict[str, Any]] = []

    for c_i, (col_i, cname) in enumerate(use_comps):
        vals = np.asarray([float(r[col_i]) if r[col_i] is not None else bg[k] for k, r in enumerate(data_rows)], dtype=float)[order]
        # Detect if curve already includes baseline or is pure net peak
        c_net = np.maximum(vals - bg, 0.0)
        c_bg = vals
        area = float(trapz(c_net, x_arr))
        cen = float(x_arr[int(np.argmax(c_net))]) if np.max(c_net) > 0 else float(np.mean(x_arr))
        comp_curves_with_bg.append(c_bg)
        comp_curves_net.append(c_net)
        clean_disp_label = re.sub(r"[\u4e00-\u9fff]+", "", cname).strip() or cname
        comp_metrics.append(
            {
                "name": cname,
                "label": clean_disp_label,
                "color": pal[c_i % len(pal)],
                "center": cen,
                "fwhm": 0.0,
                "eta": 0.0,
                "height": float(np.max(c_net)),
                "area": area,
                "in_subgroup": False,
                "note": "Reused directly from fitted table",
            }
        )

    tot_area = max(sum(m["area"] for m in comp_metrics), 1e-12)
    for m in comp_metrics:
        m["area_pct"] = 100.0 * m["area"] / tot_area
        m["subgroup_pct"] = None

    dyn_range = max(float(np.max(y_raw) - np.min(y_raw)), 1e-9)
    nrmse_pct = 100.0 * float(np.sqrt(np.mean((y_raw - y_fit) ** 2))) / dyn_range
    ss_tot = max(float(np.sum((y_raw - np.mean(y_raw)) ** 2)), 1e-12)
    r_sq = 1.0 - float(np.sum((y_raw - y_fit) ** 2)) / ss_tot
    x_lbl = headers[x_col] or "Binding Energy (eV)"
    inv_x = invert_x if invert_x is not None else ("ev" in x_lbl.lower() or "binding" in x_lbl.lower())

    return {
        "x": x_arr,
        "y_raw": y_raw,
        "baseline": bg,
        "y_fit": y_fit,
        "residuals": resid,
        "comp_curves_net": comp_curves_net,
        "comp_curves_with_bg": comp_curves_with_bg,
        "components": comp_metrics,
        "charge_shift_eV": 0.0,
        "nrmse_pct": nrmse_pct,
        "r_squared": r_sq,
        "subgroup_name": None,
        "invert_x": inv_x,
        "x_label": x_lbl,
        "y_label": "Intensity (a.u.)",
        "extra_ratios": {},
        "snr": _estimate_snr_quick(y_raw),
        "audit_flags": [],
        "audit_summary": "REPLOTTED_FROM_USER_TABLE",
    }

