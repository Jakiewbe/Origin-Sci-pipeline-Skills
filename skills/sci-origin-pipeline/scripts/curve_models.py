"""
Universal scientific curve fitting and Jacobian delta-method 95% confidence band
engine for SciOrigin pipelines.

Supported models:
- linear, poly2, poly3, power, exp_decay, arrhenius,
  michaelis_menten, dose_response_4pl, langmuir.

Dependencies: Python standard library, numpy, scipy.optimize, scipy.stats.
Strictly zero dependency on originpro or matplotlib.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize, stats

R_GAS_J_MOL_K: float = 8.3144626

SUPPORTED_CURVE_MODELS: Tuple[str, ...] = (
    "linear",
    "poly2",
    "poly3",
    "power",
    "exp_decay",
    "arrhenius",
    "michaelis_menten",
    "dose_response_4pl",
    "langmuir",
)


def _compute_fit_statistics(
    y_obs: np.ndarray,
    y_hat: np.ndarray,
    n_params: int,
) -> Tuple[float, float, float, float, float, float]:
    """Return (ss_res, r2, adj_r2, aic, bic, rmse) on original observation scale."""
    n = int(y_obs.size)
    resid = y_obs - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y_obs - float(np.mean(y_obs))) ** 2))

    if ss_tot > 1e-30:
        r2 = float(1.0 - ss_res / ss_tot)
    else:
        r2 = 1.0 if ss_res <= 1e-30 else 0.0

    if n > n_params and n > 1:
        adj_r2 = float(1.0 - (1.0 - r2) * float(n - 1) / float(n - n_params))
    else:
        adj_r2 = r2

    rmse = float(math.sqrt(max(ss_res / float(max(n, 1)), 0.0)))
    sigma2_mle = max(ss_res / float(max(n, 1)), 1e-300)
    log_lik = -0.5 * float(n) * (math.log(2.0 * math.pi * sigma2_mle) + 1.0)
    k = float(n_params)
    aic = float(2.0 * k - 2.0 * log_lik)
    bic = float(k * math.log(float(max(n, 1))) - 2.0 * log_lik)
    return ss_res, r2, adj_r2, aic, bic, rmse


def _build_x_grid(
    x_v: np.ndarray,
    n_grid: int,
    x_scale: str,
    model: str,
) -> np.ndarray:
    x_min = float(np.min(x_v))
    x_max = float(np.max(x_v))
    if n_grid < 2:
        n_grid = 2
    if x_max <= x_min:
        return np.full(n_grid, x_min, dtype=float)

    use_log = (str(x_scale).strip().lower() == "log10" or model == "dose_response_4pl") and (x_min > 0.0)
    if use_log:
        return np.geomspace(x_min, x_max, n_grid, dtype=float)
    return np.linspace(x_min, x_max, n_grid, dtype=float)


def _delta_method_band(
    jac_grid: np.ndarray,
    cov: np.ndarray,
    y_grid: np.ndarray,
    dof: int,
    ci_level: float,
) -> Tuple[np.ndarray, np.ndarray, float]:
    alpha = 1.0 - float(ci_level)
    t_crit = float(stats.t.ppf(1.0 - 0.5 * alpha, df=max(int(dof), 1)))
    # Diagonal of J @ cov @ J.T
    var_pred = np.einsum("ij,jk,ik->i", jac_grid, cov, jac_grid)
    se_pred = np.sqrt(np.maximum(var_pred, 0.0))
    hw = t_crit * se_pred
    return y_grid - hw, y_grid + hw, t_crit


def _safe_nonlinear_fit(
    func: Callable[..., np.ndarray],
    jac_fn: Callable[..., np.ndarray],
    x_v: np.ndarray,
    y_v: np.ndarray,
    p0: Sequence[float],
    bounds: Tuple[Sequence[float], Sequence[float]] = (-np.inf, np.inf),
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit nonlinear model via curve_fit with analytical Jacobian and safe pcov fallback."""
    n = int(x_v.size)
    p = len(p0)
    dof = max(n - p, 1)

    popt, pcov = optimize.curve_fit(
        func,
        x_v,
        y_v,
        p0=np.asarray(p0, dtype=float),
        bounds=bounds,
        jac=jac_fn,
        maxfev=25000,
    )
    popt = np.asarray(popt, dtype=float)
    y_hat = func(x_v, *popt)
    ss_res = float(np.sum((y_v - y_hat) ** 2))

    if ss_res <= 1e-28:
        cov = np.zeros((p, p), dtype=float)
    elif pcov is None or not np.all(np.isfinite(pcov)):
        j_obs = np.asarray(jac_fn(x_v, *popt), dtype=float)
        s2 = ss_res / float(dof)
        cov = s2 * np.linalg.pinv(j_obs.T @ j_obs)
    else:
        cov = np.asarray(pcov, dtype=float)
    return popt, cov


def _fit_ols_polynomial(
    x_v: np.ndarray,
    y_v: np.ndarray,
    x_grid: np.ndarray,
    degree: int,
    ci_level: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    n = int(x_v.size)
    p = degree + 1
    dof = max(n - p, 1)
    design_obs = np.column_stack([x_v ** pw for pw in range(degree, -1, -1)])
    coeffs, *_ = np.linalg.lstsq(design_obs, y_v, rcond=None)
    coeffs = np.asarray(coeffs, dtype=float)

    y_hat = design_obs @ coeffs
    ss_res = float(np.sum((y_v - y_hat) ** 2))
    s2 = ss_res / float(dof)
    cov = s2 * np.linalg.pinv(design_obs.T @ design_obs)
    se = np.sqrt(np.maximum(np.diag(cov), 0.0))

    design_grid = np.column_stack([x_grid ** pw for pw in range(degree, -1, -1)])
    y_grid = design_grid @ coeffs
    y_low, y_high, _ = _delta_method_band(design_grid, cov, y_grid, dof=dof, ci_level=ci_level)
    return coeffs, se, y_hat, y_grid, y_low, y_high


def _fmt_signed(val: float) -> str:
    sign = "+" if val >= 0.0 else "-"
    return f"{sign} {abs(val):.4g}"


def fit_curve_with_ci95(
    x: Sequence[float],
    y: Sequence[float],
    model: str = "linear",
    *,
    n_grid: int = 200,
    ci_level: float = 0.95,
    x_scale: str = "linear",
    T_in_kelvin: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Universal scientific curve fitter returning smooth curves, Student-t Jacobian
    delta-method confidence bands, model selection criteria, Origin rich-text equations,
    and domain-specific key metrics.
    """
    norm_model = str(model or "linear").strip().lower()
    if norm_model not in SUPPORTED_CURVE_MODELS:
        raise ValueError(
            f"Unsupported curve model {model!r}; expected one of {SUPPORTED_CURVE_MODELS}."
        )
    if not (0.0 < float(ci_level) < 1.0):
        raise ValueError(f"ci_level must be strictly in (0, 1), got {ci_level!r}.")

    x_arr = np.asarray(x, dtype=float).ravel()
    y_arr = np.asarray(y, dtype=float).ravel()
    if x_arr.size != y_arr.size:
        raise ValueError(f"x ({x_arr.size}) and y ({y_arr.size}) must have the same length.")

    valid = np.isfinite(x_arr) & np.isfinite(y_arr)
    x_v = x_arr[valid]
    y_v = y_arr[valid]
    n = int(x_v.size)
    if n < 3:
        raise ValueError(f"fit_curve_with_ci95 requires >= 3 finite data points, got {n}.")

    x_grid = _build_x_grid(x_v, n_grid=n_grid, x_scale=x_scale, model=norm_model)

    # ---- 1. Linear: y = a*x + b ----
    if norm_model == "linear":
        coeffs, se, y_hat, y_grid, y_low, y_high = _fit_ols_polynomial(
            x_v, y_v, x_grid, degree=1, ci_level=ci_level
        )
        a, b = float(coeffs[0]), float(coeffs[1])
        params = {"a": a, "b": b}
        param_se = {"a": float(se[0]), "b": float(se[1])}
        eq_text = f"y = {a:.4g}x {_fmt_signed(b)}"
        rich_eq = f"\\i(y) = {a:.4g}\\i(x) {_fmt_signed(b)}"
        key_metrics: Dict[str, Any] = {"slope": a, "intercept": b}
        n_params = 2

    # ---- 2. Quadratic: y = a*x^2 + b*x + c ----
    elif norm_model == "poly2":
        coeffs, se, y_hat, y_grid, y_low, y_high = _fit_ols_polynomial(
            x_v, y_v, x_grid, degree=2, ci_level=ci_level
        )
        a, b, c = float(coeffs[0]), float(coeffs[1]), float(coeffs[2])
        params = {"a": a, "b": b, "c": c}
        param_se = {"a": float(se[0]), "b": float(se[1]), "c": float(se[2])}
        eq_text = f"y = {a:.4g}x^2 {_fmt_signed(b)}x {_fmt_signed(c)}"
        rich_eq = f"\\i(y) = {a:.4g}\\i(x)\\+(2) {_fmt_signed(b)}\\i(x) {_fmt_signed(c)}"
        vertex_x = float(-b / (2.0 * a)) if abs(a) > 1e-15 else None
        key_metrics = {"vertex_x": vertex_x}
        n_params = 3

    # ---- 3. Cubic: y = a*x^3 + b*x^2 + c*x + d ----
    elif norm_model == "poly3":
        if n < 4:
            raise ValueError(f"poly3 model requires >= 4 finite data points, got {n}.")
        coeffs, se, y_hat, y_grid, y_low, y_high = _fit_ols_polynomial(
            x_v, y_v, x_grid, degree=3, ci_level=ci_level
        )
        a, b, c, d = (float(coeffs[i]) for i in range(4))
        params = {"a": a, "b": b, "c": c, "d": d}
        param_se = {k: float(se[i]) for i, k in enumerate(("a", "b", "c", "d"))}
        eq_text = f"y = {a:.4g}x^3 {_fmt_signed(b)}x^2 {_fmt_signed(c)}x {_fmt_signed(d)}"
        rich_eq = (
            f"\\i(y) = {a:.4g}\\i(x)\\+(3) {_fmt_signed(b)}\\i(x)\\+(2) "
            f"{_fmt_signed(c)}\\i(x) {_fmt_signed(d)}"
        )
        key_metrics = {"a": a, "b": b, "c": c, "d": d}
        n_params = 4

    # ---- 4. Power law: y = a * x^b ----
    elif norm_model == "power":
        if np.any(x_v <= 0.0):
            raise ValueError("power model requires all x > 0.")
        pos_y = y_v > 0.0
        if np.count_nonzero(pos_y) >= 2:
            lx = np.log(x_v[pos_y])
            ly = np.log(y_v[pos_y])
            c_init, *_ = np.linalg.lstsq(np.column_stack([lx, np.ones(lx.size)]), ly, rcond=None)
            b0 = float(c_init[0])
            a0 = float(np.exp(np.clip(c_init[1], -100.0, 100.0)))
        else:
            a0, b0 = float(np.mean(y_v) or 1.0), 1.0

        def _pow_fn(xv: np.ndarray, a_p: float, b_p: float) -> np.ndarray:
            return a_p * np.power(xv, b_p)

        def _pow_jac(xv: np.ndarray, a_p: float, b_p: float) -> np.ndarray:
            xb = np.power(xv, b_p)
            return np.column_stack([xb, a_p * xb * np.log(xv)])

        popt, cov = _safe_nonlinear_fit(_pow_fn, _pow_jac, x_v, y_v, p0=[a0, b0])
        a, b = float(popt[0]), float(popt[1])
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
        y_hat = _pow_fn(x_v, a, b)
        y_grid = _pow_fn(x_grid, a, b)
        y_low, y_high, _ = _delta_method_band(
            _pow_jac(x_grid, a, b), cov, y_grid, dof=max(n - 2, 1), ci_level=ci_level
        )
        params = {"a": a, "b": b}
        param_se = {"a": float(se[0]), "b": float(se[1])}
        eq_text = f"y = {a:.4g} * x^{b:.4g}"
        rich_eq = f"\\i(y) = {a:.4g} \\i(x)\\+({b:.4g})"
        key_metrics = {"amplitude": a, "exponent": b}
        n_params = 2

    # ---- 5. Exponential decay: y = y0 + A * exp(-x / tau) ----
    elif norm_model == "exp_decay":
        order = np.argsort(x_v)
        xs, ys = x_v[order], y_v[order]
        y0_init = float(ys[-1])
        a_init = float(ys[0] - ys[-1])
        if abs(a_init) < 1e-12:
            a_init = float(np.ptp(y_v) or 1.0)
        x_span = max(float(xs[-1] - xs[0]), 1e-6)
        tau_init = 0.35 * x_span
        shifted = (ys - y0_init) / a_init
        pos_mask = shifted > 0.05
        if np.count_nonzero(pos_mask) >= 2:
            slope_est, *_ = np.linalg.lstsq(
                np.column_stack([xs[pos_mask], np.ones(np.count_nonzero(pos_mask))]),
                np.log(shifted[pos_mask]),
                rcond=None,
            )
            if float(slope_est[0]) < -1e-12:
                tau_init = float(-1.0 / float(slope_est[0]))

        def _exp_fn(xv: np.ndarray, y0_p: float, a_p: float, tau_p: float) -> np.ndarray:
            return y0_p + a_p * np.exp(-np.clip(xv / tau_p, -500.0, 500.0))

        def _exp_jac(xv: np.ndarray, y0_p: float, a_p: float, tau_p: float) -> np.ndarray:
            ex = np.exp(-np.clip(xv / tau_p, -500.0, 500.0))
            return np.column_stack([np.ones_like(xv), ex, a_p * ex * (xv / (tau_p ** 2))])

        popt, cov = _safe_nonlinear_fit(
            _exp_fn,
            _exp_jac,
            x_v,
            y_v,
            p0=[y0_init, a_init, max(tau_init, 1e-9)],
            bounds=([-np.inf, -np.inf, 1e-15], [np.inf, np.inf, np.inf]),
        )
        y0_v, a_v, tau_v = float(popt[0]), float(popt[1]), float(popt[2])
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
        y_hat = _exp_fn(x_v, y0_v, a_v, tau_v)
        y_grid = _exp_fn(x_grid, y0_v, a_v, tau_v)
        y_low, y_high, _ = _delta_method_band(
            _exp_jac(x_grid, y0_v, a_v, tau_v), cov, y_grid, dof=max(n - 3, 1), ci_level=ci_level
        )
        half_life = float(tau_v * math.log(2.0))
        params = {"y0": y0_v, "A": a_v, "tau": tau_v}
        param_se = {"y0": float(se[0]), "A": float(se[1]), "tau": float(se[2])}
        eq_text = f"y = {y0_v:.4g} {_fmt_signed(a_v)} * exp(-x / {tau_v:.4g})"
        rich_eq = f"\\i(y) = {y0_v:.4g} {_fmt_signed(a_v)} exp(-\\i(x)/{tau_v:.4g})"
        key_metrics = {"tau": tau_v, "half_life": half_life}
        n_params = 3

    # ---- 6. Arrhenius: k(T) = A*exp(-Ea/(R*T)) OR 1000/T vs ln(k) / k ----
    elif norm_model == "arrhenius":
        if np.any(x_v <= 0.0):
            raise ValueError("arrhenius model requires all x > 0 (Kelvin T or 1000/T).")

        x_min, x_max = float(np.min(x_v)), float(np.max(x_v))
        if T_in_kelvin is not None:
            is_kelvin = bool(T_in_kelvin)
        else:
            is_kelvin = bool(x_min >= 50.0)

        if is_kelvin:
            if np.any(y_v <= 0.0):
                raise ValueError("arrhenius Kelvin form k = A*exp(-Ea/(R*T)) requires all y > 0.")
            inv_rt = 1000.0 / (R_GAS_J_MOL_K * x_v)
            c_lin, *_ = np.linalg.lstsq(
                np.column_stack([-inv_rt, np.ones(n)]), np.log(y_v), rcond=None
            )
            ea_kj_0 = float(c_lin[0])
            lna_0 = float(c_lin[1])

            def _arr_k_fn(tv: np.ndarray, lna_p: float, ea_kj_p: float) -> np.ndarray:
                exponent = np.clip(lna_p - (ea_kj_p * 1000.0) / (R_GAS_J_MOL_K * tv), -500.0, 500.0)
                return np.exp(exponent)

            def _arr_k_jac(tv: np.ndarray, lna_p: float, ea_kj_p: float) -> np.ndarray:
                kv = _arr_k_fn(tv, lna_p, ea_kj_p)
                return np.column_stack([kv, -kv * (1000.0 / (R_GAS_J_MOL_K * tv))])

            popt, cov = _safe_nonlinear_fit(_arr_k_fn, _arr_k_jac, x_v, y_v, p0=[lna_0, ea_kj_0])
            lna_fit, ea_kj = float(popt[0]), float(popt[1])
            a_pre = float(math.exp(max(min(lna_fit, 500.0), -500.0)))
            ea_j = float(ea_kj * 1000.0)
            se_internal = np.sqrt(np.maximum(np.diag(cov), 0.0))
            y_hat = _arr_k_fn(x_v, lna_fit, ea_kj)
            y_grid = _arr_k_fn(x_grid, lna_fit, ea_kj)
            y_low, y_high, _ = _delta_method_band(
                _arr_k_jac(x_grid, lna_fit, ea_kj), cov, y_grid, dof=max(n - 2, 1), ci_level=ci_level
            )
            params = {"A": a_pre, "Ea": ea_j, "Ea_kJ_mol": ea_kj}
            param_se = {
                "A": float(a_pre * se_internal[0]),
                "Ea": float(1000.0 * se_internal[1]),
                "Ea_kJ_mol": float(se_internal[1]),
            }
            eq_text = f"y = {a_pre:.4g} * exp(-{ea_j:.4g} / (R * T))"
            rich_eq = f"\\i(E)\\-(a) = {ea_kj:.3g} kJ mol\\+(-1)"
            key_metrics = {"Ea_kJ_mol": ea_kj, "Ea_J_mol": ea_j, "A": a_pre}
            n_params = 2
        else:
            # Reciprocal temperature x = 1000/T (in ~0.1..25 K^-1) or 1/T (< 0.05 K^-1)
            scale_1000 = 1.0 if x_max >= 0.05 else 1000.0
            # Compare linearized ln(k) vs exponential k when all y > 0
            coeffs_lin, se_lin, yhat_lin, ygrid_lin, ylo_lin, yhi_lin = _fit_ols_polynomial(
                x_v, y_v, x_grid, degree=1, ci_level=ci_level
            )
            ss_lin = float(np.sum((y_v - yhat_lin) ** 2))

            use_linear_lnk = bool(np.any(y_v <= 0.0))
            exp_candidate = None
            if not use_linear_lnk:
                c0, *_ = np.linalg.lstsq(
                    np.column_stack([-x_v, np.ones(n)]), np.log(y_v), rcond=None
                )
                b_init = float(c0[0])
                lna_init = float(c0[1])

                def _arr_rec_exp(xv: np.ndarray, lna_p: float, b_p: float) -> np.ndarray:
                    return np.exp(np.clip(lna_p - b_p * xv, -500.0, 500.0))

                def _arr_rec_jac(xv: np.ndarray, lna_p: float, b_p: float) -> np.ndarray:
                    kv = _arr_rec_exp(xv, lna_p, b_p)
                    return np.column_stack([kv, -kv * xv])

                try:
                    popt_e, cov_e = _safe_nonlinear_fit(
                        _arr_rec_exp, _arr_rec_jac, x_v, y_v, p0=[lna_init, b_init]
                    )
                    yhat_e = _arr_rec_exp(x_v, float(popt_e[0]), float(popt_e[1]))
                    ss_exp = float(np.sum((y_v - yhat_e) ** 2))
                    if ss_exp < 0.5 * ss_lin:
                        exp_candidate = (popt_e, cov_e, yhat_e, _arr_rec_exp, _arr_rec_jac)
                    else:
                        use_linear_lnk = True
                except Exception:
                    use_linear_lnk = True

            if use_linear_lnk or exp_candidate is None:
                slope, intercept = float(coeffs_lin[0]), float(coeffs_lin[1])
                # For y = ln(k) vs x = 1000/T: slope = -Ea_J / (1000 * R) = -Ea_kJ / R
                ea_kj = float(-slope * R_GAS_J_MOL_K / scale_1000)
                se_ea_kj = float(se_lin[0] * R_GAS_J_MOL_K / scale_1000)
                y_hat, y_grid, y_low, y_high = yhat_lin, ygrid_lin, ylo_lin, yhi_lin
                params = {"slope": slope, "intercept": intercept, "Ea_kJ_mol": ea_kj}
                param_se = {
                    "slope": float(se_lin[0]),
                    "intercept": float(se_lin[1]),
                    "Ea_kJ_mol": se_ea_kj,
                }
                eq_text = f"ln(k) = {slope:.4g}x {_fmt_signed(intercept)} (Ea = {ea_kj:.3g} kJ/mol)"
                rich_eq = f"\\i(y) = {slope:.4g}\\i(x) {_fmt_signed(intercept)}, \\i(E)\\-(a) = {ea_kj:.3g} kJ mol\\+(-1)"
                key_metrics = {
                    "Ea_kJ_mol": ea_kj,
                    "Ea_J_mol": float(ea_kj * 1000.0),
                    "ln_A": intercept,
                }
                n_params = 2
            else:
                popt_e, cov_e, yhat_e, fn_e, jac_e = exp_candidate
                lna_fit, b_fit = float(popt_e[0]), float(popt_e[1])
                a_pre = float(math.exp(max(min(lna_fit, 500.0), -500.0)))
                ea_kj = float(b_fit * R_GAS_J_MOL_K / scale_1000)
                se_e = np.sqrt(np.maximum(np.diag(cov_e), 0.0))
                y_hat = yhat_e
                y_grid = fn_e(x_grid, lna_fit, b_fit)
                y_low, y_high, _ = _delta_method_band(
                    jac_e(x_grid, lna_fit, b_fit), cov_e, y_grid, dof=max(n - 2, 1), ci_level=ci_level
                )
                params = {"A": a_pre, "Ea": float(ea_kj * 1000.0), "Ea_kJ_mol": ea_kj}
                param_se = {
                    "A": float(a_pre * se_e[0]),
                    "Ea": float(1000.0 * se_e[1] * R_GAS_J_MOL_K / scale_1000),
                    "Ea_kJ_mol": float(se_e[1] * R_GAS_J_MOL_K / scale_1000),
                }
                eq_text = f"y = {a_pre:.4g} * exp(-{b_fit:.4g} * x) (Ea = {ea_kj:.3g} kJ/mol)"
                rich_eq = f"\\i(E)\\-(a) = {ea_kj:.3g} kJ mol\\+(-1)"
                key_metrics = {"Ea_kJ_mol": ea_kj, "Ea_J_mol": float(ea_kj * 1000.0), "A": a_pre}
                n_params = 2

    # ---- 7. Michaelis-Menten: y = Vmax * x / (Km + x) ----
    elif norm_model == "michaelis_menten":
        if np.any(x_v < 0.0):
            raise ValueError("michaelis_menten model requires all x >= 0.")
        vmax_0 = float(max(np.max(y_v) * 1.15, 1e-9))
        pos_x = x_v[x_v > 0.0]
        half_idx = int(np.argmin(np.abs(y_v - 0.5 * float(np.max(y_v)))))
        km_0 = float(x_v[half_idx]) if x_v[half_idx] > 0.0 else (float(np.median(pos_x)) if pos_x.size else 1.0)

        def _mm_fn(xv: np.ndarray, vmax_p: float, km_p: float) -> np.ndarray:
            return (vmax_p * xv) / (km_p + xv)

        def _mm_jac(xv: np.ndarray, vmax_p: float, km_p: float) -> np.ndarray:
            denom = km_p + xv
            return np.column_stack([xv / denom, -(vmax_p * xv) / (denom ** 2)])

        popt, cov = _safe_nonlinear_fit(
            _mm_fn,
            _mm_jac,
            x_v,
            y_v,
            p0=[vmax_0, max(km_0, 1e-9)],
            bounds=([0.0, 1e-15], [np.inf, np.inf]),
        )
        vmax_v, km_v = float(popt[0]), float(popt[1])
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
        y_hat = _mm_fn(x_v, vmax_v, km_v)
        y_grid = _mm_fn(x_grid, vmax_v, km_v)
        y_low, y_high, _ = _delta_method_band(
            _mm_jac(x_grid, vmax_v, km_v), cov, y_grid, dof=max(n - 2, 1), ci_level=ci_level
        )
        params = {"Vmax": vmax_v, "Km": km_v}
        param_se = {"Vmax": float(se[0]), "Km": float(se[1])}
        eq_text = f"y = {vmax_v:.4g} * x / ({km_v:.4g} + x)"
        rich_eq = f"\\i(y) = {vmax_v:.4g}\\i(x) / ({km_v:.4g} + \\i(x))"
        key_metrics = {"Vmax": vmax_v, "Km": km_v}
        n_params = 2

    # ---- 8. Four-parameter logistic (4PL): bottom + (top - bottom) / (1 + (x / ic50)^hill) ----
    elif norm_model == "dose_response_4pl":
        if n < 4:
            raise ValueError(f"dose_response_4pl requires >= 4 finite data points, got {n}.")
        if np.any(x_v < 0.0) or np.count_nonzero(x_v > 0.0) < 3:
            raise ValueError("dose_response_4pl requires non-negative concentrations with >= 3 strictly positive x values.")

        pos_mask = x_v > 0.0
        order_pos = np.argsort(x_v[pos_mask])
        xp = x_v[pos_mask][order_pos]
        yp = y_v[pos_mask][order_pos]

        bottom_0 = float(np.min(y_v))
        top_0 = float(np.max(y_v))
        if top_0 <= bottom_0 + 1e-12:
            top_0 = bottom_0 + 1.0
        mid_0 = 0.5 * (bottom_0 + top_0)

        k_edge = max(1, xp.size // 4)
        hill_0 = 1.0 if float(np.mean(yp[:k_edge])) >= float(np.mean(yp[-k_edge:])) else -1.0
        mid_idx = int(np.argmin(np.abs(yp - mid_0)))
        log_ic50_0 = float(np.log(xp[mid_idx]))

        def _eval_4pl(xv: np.ndarray, bot_p: float, top_p: float, log_ic50_p: float, hill_p: float) -> np.ndarray:
            out = np.empty_like(xv, dtype=float)
            z_mask = xv <= 0.0
            p_mask = ~z_mask
            if np.any(z_mask):
                if hill_p > 0.0:
                    out[z_mask] = top_p
                elif hill_p < 0.0:
                    out[z_mask] = bot_p
                else:
                    out[z_mask] = 0.5 * (bot_p + top_p)
            if np.any(p_mask):
                u = np.clip(hill_p * (np.log(xv[p_mask]) - log_ic50_p), -500.0, 500.0)
                out[p_mask] = bot_p + (top_p - bot_p) / (1.0 + np.exp(u))
            return out

        def _jac_4pl(xv: np.ndarray, bot_p: float, top_p: float, log_ic50_p: float, hill_p: float) -> np.ndarray:
            m = xv.size
            j_mat = np.zeros((m, 4), dtype=float)
            z_mask = xv <= 0.0
            p_mask = ~z_mask
            if np.any(z_mask):
                if hill_p > 0.0:
                    j_mat[z_mask, 1] = 1.0
                elif hill_p < 0.0:
                    j_mat[z_mask, 0] = 1.0
                else:
                    j_mat[z_mask, 0] = 0.5
                    j_mat[z_mask, 1] = 0.5
            if np.any(p_mask):
                dx = np.log(xv[p_mask]) - log_ic50_p
                u = np.clip(hill_p * dx, -500.0, 500.0)
                eu = np.exp(u)
                inv_1peu = 1.0 / (1.0 + eu)
                # Sigmoid derivative factor eu / (1 + eu)^2 computed overflow-free
                sig_deriv = (eu * inv_1peu) * inv_1peu
                span_p = top_p - bot_p
                j_mat[p_mask, 0] = 1.0 - inv_1peu
                j_mat[p_mask, 1] = inv_1peu
                j_mat[p_mask, 2] = span_p * sig_deriv * hill_p
                j_mat[p_mask, 3] = -span_p * sig_deriv * dx
            return j_mat

        y_span = max(top_0 - bottom_0, 1.0)
        ln_min, ln_max = float(np.log(xp[0])), float(np.log(xp[-1]))
        ln_pad = max(4.0, 0.5 * (ln_max - ln_min))
        popt, cov = _safe_nonlinear_fit(
            _eval_4pl,
            _jac_4pl,
            x_v,
            y_v,
            p0=[bottom_0, top_0, log_ic50_0, hill_0],
            bounds=(
                [bottom_0 - 1.5 * y_span, bottom_0 - 0.5 * y_span, ln_min - ln_pad, -25.0],
                [top_0 + 0.5 * y_span, top_0 + 1.5 * y_span, ln_max + ln_pad, 25.0],
            ),
        )
        bot_v, top_v, log_ic50_v, hill_v = (float(popt[i]) for i in range(4))
        ic50_v = float(math.exp(log_ic50_v))
        se_vec = np.sqrt(np.maximum(np.diag(cov), 0.0))
        se_log_ic50 = float(se_vec[2])
        se_ic50 = float(ic50_v * se_log_ic50)

        dof = max(n - 4, 1)
        y_hat = _eval_4pl(x_v, bot_v, top_v, log_ic50_v, hill_v)
        y_grid = _eval_4pl(x_grid, bot_v, top_v, log_ic50_v, hill_v)
        y_low, y_high, t_crit = _delta_method_band(
            _jac_4pl(x_grid, bot_v, top_v, log_ic50_v, hill_v),
            cov,
            y_grid,
            dof=dof,
            ci_level=ci_level,
        )
        ic50_ci_low = float(math.exp(max(log_ic50_v - t_crit * se_log_ic50, -500.0)))
        ic50_ci_high = float(math.exp(min(log_ic50_v + t_crit * se_log_ic50, 500.0)))
        mid_y = float(0.5 * (bot_v + top_v))

        params = {
            "bottom": bot_v,
            "top": top_v,
            "ic50": ic50_v,
            "hill": hill_v,
        }
        param_se = {
            "bottom": float(se_vec[0]),
            "top": float(se_vec[1]),
            "ic50": se_ic50,
            "hill": float(se_vec[3]),
        }
        eq_text = (
            f"y = {bot_v:.4g} + ({top_v:.4g} - {bot_v:.4g}) / "
            f"(1 + (x / {ic50_v:.4g})^{hill_v:.3g})"
        )
        rich_eq = f"IC\\-(50) = {ic50_v:.4g}, Hill = {hill_v:.3g}"
        key_metrics = {
            "IC50": ic50_v,
            "IC50_ci95_low": ic50_ci_low,
            "IC50_ci95_high": ic50_ci_high,
            "hill_slope": hill_v,
            "bottom": bot_v,
            "top": top_v,
            "mid_y": mid_y,
        }
        n_params = 4

    # ---- 9. Langmuir isotherm: y = qmax * K * x / (1 + K * x) ----
    else:  # "langmuir"
        if np.any(x_v < 0.0):
            raise ValueError("langmuir model requires all x >= 0.")
        qmax_0 = float(max(np.max(y_v) * 1.15, 1e-9))
        pos_x = x_v[x_v > 0.0]
        half_idx = int(np.argmin(np.abs(y_v - 0.5 * float(np.max(y_v)))))
        x_half = float(x_v[half_idx]) if x_v[half_idx] > 0.0 else (float(np.median(pos_x)) if pos_x.size else 1.0)
        k_0 = 1.0 / max(x_half, 1e-9)

        def _lang_fn(xv: np.ndarray, qmax_p: float, k_p: float) -> np.ndarray:
            return (qmax_p * k_p * xv) / (1.0 + k_p * xv)

        def _lang_jac(xv: np.ndarray, qmax_p: float, k_p: float) -> np.ndarray:
            denom = 1.0 + k_p * xv
            return np.column_stack([(k_p * xv) / denom, (qmax_p * xv) / (denom ** 2)])

        popt, cov = _safe_nonlinear_fit(
            _lang_fn,
            _lang_jac,
            x_v,
            y_v,
            p0=[qmax_0, max(k_0, 1e-9)],
            bounds=([0.0, 1e-15], [np.inf, np.inf]),
        )
        qmax_v, k_v = float(popt[0]), float(popt[1])
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
        y_hat = _lang_fn(x_v, qmax_v, k_v)
        y_grid = _lang_fn(x_grid, qmax_v, k_v)
        y_low, y_high, _ = _delta_method_band(
            _lang_jac(x_grid, qmax_v, k_v), cov, y_grid, dof=max(n - 2, 1), ci_level=ci_level
        )
        params = {"qmax": qmax_v, "K": k_v}
        param_se = {"qmax": float(se[0]), "K": float(se[1])}
        eq_text = f"y = ({qmax_v:.4g} * {k_v:.4g} * x) / (1 + {k_v:.4g} * x)"
        rich_eq = f"\\i(y) = {qmax_v:.4g}\\i(K)\\i(x) / (1 + \\i(K)\\i(x)), \\i(q)\\-(max) = {qmax_v:.4g}"
        key_metrics = {"qmax": qmax_v, "K": k_v}
        n_params = 2

    _, r2, adj_r2, aic, bic, rmse = _compute_fit_statistics(y_v, y_hat, n_params=n_params)

    x_grid_list = [float(v) for v in x_grid]
    y_fit_list = [float(v) for v in y_grid]
    y_low_list = [float(v) for v in y_low]
    y_high_list = [float(v) for v in y_high]

    return {
        "model": norm_model,
        "params": params,
        "param_se": param_se,
        "equation_text": eq_text,
        "equation_str": eq_text,
        "origin_rich_eq": rich_eq,
        "r2": float(r2),
        "adj_r2": float(adj_r2),
        "aic": float(aic),
        "bic": float(bic),
        "rmse": float(rmse),
        "x_grid": x_grid_list,
        "x_fit": x_grid_list,
        "y_fit": y_fit_list,
        "y_low": y_low_list,
        "y_high": y_high_list,
        "key_metrics": key_metrics,
    }


# Backward-compatible alias
fit_xy_with_ci95 = fit_curve_with_ci95

__all__ = [
    "SUPPORTED_CURVE_MODELS",
    "fit_curve_with_ci95",
    "fit_xy_with_ci95",
]
