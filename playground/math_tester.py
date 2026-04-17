"""
F^{ω, ω'}_h(λ) = (1 / Γ(λ)) ∫_X |f|^{2λ} f̄^{-h} ρ ω ∧ ω̄'

Implemented as a standalone function with numerical integration.
Uses scipy if available, else a simple numpy integrator.
"""

import math
import numpy as np

try:
    from scipy.integrate import dblquad
    _has_scipy = True
except ImportError:
    _has_scipy = False


def F_omega_omega_prime_h(
    lam: float,
    h: float,
    f_func,
    rho_func,
    omega_wedge_omega_bar_func,
    x_lo: float,
    x_hi: float,
    y_lo: float,
    y_hi: float,
    *,
    f_conj_power_neg_h_handles_zero: bool = True,
) -> complex:
    r"""
    Compute
        F^{ω, ω'}_h(λ) := (1 / Γ(λ)) ∫_X |f|^{2λ} f̄^{-h} ρ ω ∧ ω̄'

    Parameters
    ----------
    lam : float
        λ; must be > 0 so that Γ(λ) is defined.
    h : float
        Exponent in f̄^{-h} (conjugate of f to power -h).
    f_func : callable
        f(x, y) returning complex (or real). Used for |f|^{2λ} and f̄^{-h}.
    rho_func : callable
        ρ(x, y), scalar weight.
    omega_wedge_omega_bar_func : callable
        (x, y) -> real. Density from ω ∧ ω̄' (e.g. (i/2) dz∧d̄z in coords).
    x_lo, x_hi, y_lo, y_hi : float
        Integration bounds for X (rectangle in R^2).
    f_conj_power_neg_h_handles_zero : bool
        If True, treat integrand as 0 where f = 0 when -h < 0 (avoid 0^{-h}).

    Returns
    -------
    complex
        Value of F^{ω, ω'}_h(λ).
    """
    if lam <= 0:
        raise ValueError("λ must be > 0 for Γ(λ).")

    def integrand(y, x):
        f = f_func(x, y)
        f_abs = np.abs(f)
        rho = np.asarray(rho_func(x, y), dtype=complex)
        om = np.asarray(omega_wedge_omega_bar_func(x, y), dtype=complex)
        term = (f_abs ** (2 * lam)) * rho * om
        if np.isclose(f, 0):
            if f_conj_power_neg_h_handles_zero and h > 0:
                return 0.0
            if h != 0:
                return np.nan  # f̄^{-h} undefined at 0 for h != 0
            return float(term)
        conj_f = np.conj(f)
        term = term * (conj_f ** (-h))
        return np.real(term) if np.isrealobj(term) else term

    # Real part of integrand for dblquad (real-valued integrand)
    def real_integrand(y, x):
        v = integrand(y, x)
        return np.real(v) if np.iscomplexobj(v) else float(v)

    def imag_integrand(y, x):
        v = integrand(y, x)
        return np.imag(v) if np.iscomplexobj(v) else 0.0

    if _has_scipy:
        re_val, _ = dblquad(real_integrand, x_lo, x_hi, y_lo, y_hi)
        im_val, _ = dblquad(imag_integrand, x_lo, x_hi, y_lo, y_hi)
        integral = re_val + 1j * im_val
    else:
        integral = _integrate_2d_rect(
            integrand, x_lo, x_hi, y_lo, y_hi, n=200
        )

    Gamma_lam = math.gamma(lam)
    return (1.0 / Gamma_lam) * integral


def _integrate_2d_rect(integrand, x_lo, x_hi, y_lo, y_hi, n=200):
    """Simple 2D rectangular rule (fallback when scipy not available)."""
    x = np.linspace(x_lo, x_hi, n)
    y = np.linspace(y_lo, y_hi, n)
    dx = (x_hi - x_lo) / (n - 1) if n > 1 else 0
    dy = (y_hi - y_lo) / (n - 1) if n > 1 else 0
    total = 0.0 + 0.0j
    for xx in x:
        for yy in y:
            total += integrand(yy, xx)
    return total * dx * dy


# ----- Example: runnable standalone -----

def _example_f(x, y):
    """f(z) = x + i y on X."""
    return x + 1j * y


def _example_rho(x, y):
    return 1.0


def _example_omega_wedge(x, y):
    """ω ∧ ω̄' as density (e.g. constant 1 for area form)."""
    return 1.0


if __name__ == "__main__":
    # Example: X = [0.1, 1] × [0.1, 1], λ=1, h=0
    # F = (1/Γ(1)) ∫ |f|^{2} ρ ω∧ω̄' = ∫ (x^2+y^2) over unit square
    result = F_omega_omega_prime_h(
        lam=1.0,
        h=0.0,
        f_func=_example_f,
        rho_func=_example_rho,
        omega_wedge_omega_bar_func=_example_omega_wedge,
        x_lo=0.1,
        x_hi=1.0,
        y_lo=0.1,
        y_hi=1.0,
    )
    print("F^{omega,omega'}_h(lambda) =", result)
    print("(Example: lambda=1, h=0, f(z)=z, rho=1, omega wedge omega'=1 on [0.1,1]^2)")
