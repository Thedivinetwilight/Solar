"""APMT V1.9 — machine-checkable dimensional safety (directive §37).

Every module in the V1.9 platform declares its canonical units. This module
provides a small, dependency-free quantity system whose job is to make unit
errors *fail loudly* instead of silently changing a physical result.

Canonical internal units (documented, single source of truth)
-----------------------------------------------------------
quantity                     canonical unit
wavelength                   nm
energy                       eV
current density (J)          mA/cm^2
power density                mW/cm^2
irradiance / spectral irr.   W/m^2  and  W/m^2/nm
thickness                    nm
area                         cm^2
temperature                  K
resistance (specific)        ohm*cm^2
time                         s
photon flux                  photons/s/cm^2/nm
dimensionless                ``1``

The Quantity object is deliberately minimal: it tracks a dimension vector and
the unit string used for display. It is *not* a full units library; it exists
so that the platform cannot add a resistance to a current density by accident.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Tuple

# Base dimensions tracked: length, time, current, temperature, mass, amount.
_DIMS = ("L", "T", "I", "TH", "M", "N")

# unit -> (factor to SI base combination, dimension vector)
# Factors convert to the SI base unit of the dimension vector.
_UNIT_TABLE: Dict[str, Tuple[float, Tuple[int, ...]]] = {
    # length
    "m": (1.0, (1, 0, 0, 0, 0, 0)),
    "cm": (1e-2, (1, 0, 0, 0, 0, 0)),
    "mm": (1e-3, (1, 0, 0, 0, 0, 0)),
    "um": (1e-6, (1, 0, 0, 0, 0, 0)),
    "nm": (1e-9, (1, 0, 0, 0, 0, 0)),
    # time
    "s": (1.0, (0, 1, 0, 0, 0, 0)),
    "h": (3600.0, (0, 1, 0, 0, 0, 0)),
    # current
    "A": (1.0, (0, 0, 1, 0, 0, 0)),
    "mA": (1e-3, (0, 0, 1, 0, 0, 0)),
    "uA": (1e-6, (0, 0, 1, 0, 0, 0)),
    # temperature
    "K": (1.0, (0, 0, 0, 1, 0, 0)),
    # mass / amount
    "kg": (1.0, (0, 0, 0, 0, 1, 0)),
    "g": (1e-3, (0, 0, 0, 0, 1, 0)),
    "mol": (1.0, (0, 0, 0, 0, 0, 1)),
    # energy
    "eV": (1.602176634e-19, (2, -2, 0, 0, 1, 0)),
    "J": (1.0, (2, -2, 0, 0, 1, 0)),
    # power
    "W": (1.0, (2, -3, 0, 0, 1, 0)),
    "mW": (1e-3, (2, -3, 0, 0, 1, 0)),
    # electrical
    "ohm": (1.0, (2, -3, -2, 0, 1, 0)),
    "S": (-1.0, (-2, 3, 2, 0, -1, 0)),  # siemens (inverse ohm)
    "C": (1.0, (0, 1, 1, 0, 0, 0)),
    # photometric/radiometric helpers used by the platform
    "photon": (1.0, (0, 0, 0, 0, 0, 1)),
    # dimensionless
    "1": (1.0, (0, 0, 0, 0, 0, 0)),
    "%": (1e-2, (0, 0, 0, 0, 0, 0)),
}

_SUPERSCRIPT = str.maketrans("⁻⁻¹²³⁴⁵⁶⁷⁸⁹", "--123456789")  # unused, kept for clarity


class UnitError(ValueError):
    """Raised when a unit string cannot be parsed or dimensions mismatch."""


class DimensionError(UnitError):
    """Raised when an operation mixes incompatible dimensions."""


@dataclass(frozen=True)
class _Parsed:
    factor: float          # multiplicative factor to SI base combination
    dim: Tuple[int, ...]   # exponent vector over _DIMS
    is_affine: bool        # True for units needing an offset (degC)


def _parse_unit(unit: str) -> _Parsed:
    """Parse expressions such as ``mA/cm^2``, ``W/m^2/nm``, ``ohm*cm^2``."""
    u = unit.strip()
    if u in ("", "1", "-"):
        return _Parsed(1.0, (0,) * len(_DIMS), False)
    if u in ("degC", "°C", "Celsius"):
        # affine temperature: treated as K with a recorded offset flag
        return _Parsed(1.0, _UNIT_TABLE["K"][1], True)
    factor = 1.0
    dim = [0] * len(_DIMS)
    # split on * and / keeping explicit signs
    tokens = re.split(r"([*/])", u)
    sign = 1
    for tok in tokens:
        if tok == "*":
            sign = 1
            continue
        if tok == "/":
            sign = -1
            continue
        if not tok:
            continue
        m = re.fullmatch(r"([A-Za-z%]+)\s*\^?\s*(-?\d+)?", tok)
        if not m:
            raise UnitError(f"cannot parse unit token {tok!r} in {unit!r}")
        name, exp = m.group(1), m.group(2)
        if name not in _UNIT_TABLE:
            raise UnitError(f"unknown unit {name!r} in {unit!r}")
        e = int(exp) if exp is not None else 1
        f, d = _UNIT_TABLE[name]
        factor *= f ** (sign * e)
        for i in range(len(_DIMS)):
            dim[i] += sign * e * d[i]
    return _Parsed(factor, tuple(dim), False)


@dataclass(frozen=True)
class Quantity:
    """A value with a unit string and machine-checked dimensions."""

    value: float
    unit: str

    def __post_init__(self):
        object.__setattr__(self, "_parsed", _parse_unit(self.unit))

    # -- conversion ---------------------------------------------------------
    def to(self, unit: str) -> "Quantity":
        """Convert to another unit with identical dimensions."""
        p_new = _parse_unit(unit)
        p_old = self._parsed
        if p_new.dim != p_old.dim:
            raise DimensionError(
                f"cannot convert {self.unit!r} -> {unit!r}: dimensions "
                f"{p_old.dim} != {p_new.dim}"
            )
        if p_old.is_affine or p_new.is_affine:
            raise UnitError("affine temperature conversion is not supported; use K")
        return Quantity(self.value * p_old.factor / p_new.factor, unit)

    def si_value(self) -> float:
        return self.value * self._parsed.factor

    # -- arithmetic ---------------------------------------------------------
    def _check_same_dim(self, other: "Quantity") -> None:
        if self._parsed.dim != other._parsed.dim:
            raise DimensionError(
                f"incompatible dimensions: {self.unit!r} {self._parsed.dim} vs "
                f"{other.unit!r} {other._parsed.dim}"
            )

    def __add__(self, other: "Quantity") -> "Quantity":
        self._check_same_dim(other)
        return Quantity(self.value + other.to(self.unit).value, self.unit)

    __radd__ = __add__

    def __sub__(self, other: "Quantity") -> "Quantity":
        self._check_same_dim(other)
        return Quantity(self.value - other.to(self.unit).value, self.unit)

    def __mul__(self, other) -> "Quantity":
        if isinstance(other, Quantity):
            return _mul_quantity(self, other)
        return Quantity(self.value * float(other), self.unit)

    __rmul__ = __mul__

    def __truediv__(self, other) -> "Quantity":
        if isinstance(other, Quantity):
            return _div_quantity(self, other)
        return Quantity(self.value / float(other), self.unit)

    def __pow__(self, p: int) -> "Quantity":
        dim = tuple(e * p for e in self._parsed.dim)
        return Quantity(self.value ** p, _unit_from_dim(dim))

    def __neg__(self) -> "Quantity":
        return Quantity(-self.value, self.unit)

    def __float__(self) -> float:
        return float(self.value)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Quantity({self.value!r}, {self.unit!r})"


# Explicit dimension -> preferred display unit (for products/quotients).
_PREFERRED = {
    (1, 0, 0, 0, 0, 0): "nm",
    (0, 1, 0, 0, 0, 0): "s",
    (0, 0, 1, 0, 0, 0): "mA",
    (0, 0, 0, 1, 0, 0): "K",
    (2, -2, 0, 0, 1, 0): "eV",
    (2, -3, 0, 0, 1, 0): "mW",
    (2, -3, -2, 0, 1, 0): "ohm",
    (0, 0, 0, 0, 0, 0): "1",
    (2, -2, -1, 0, 1, 0): "eV/mA",
}


def _unit_from_dim(dim: Tuple[int, ...]) -> str:
    if dim in _PREFERRED:
        return _PREFERRED[dim]
    parts = [f"{n}^{e}" for n, e in zip(_DIMS, dim) if e]
    return "*".join(parts) if parts else "1"


def _mul_quantity(a: Quantity, b: Quantity) -> Quantity:
    dim = tuple(x + y for x, y in zip(a._parsed.dim, b._parsed.dim))
    # value in SI base so that the result is unit-system independent
    value_si = a.si_value() * b.si_value()
    unit = _unit_from_dim(dim)
    fac = _parse_unit(unit).factor
    return Quantity(value_si / fac, unit)


def _div_quantity(a: Quantity, b: Quantity) -> Quantity:
    dim = tuple(x - y for x, y in zip(a._parsed.dim, b._parsed.dim))
    value_si = a.si_value() / b.si_value()
    unit = _unit_from_dim(dim)
    fac = _parse_unit(unit).factor
    return Quantity(value_si / fac, unit)


def q(value: float, unit: str) -> Quantity:
    """Shorthand constructor: ``q(19.23, "mA/cm^2")``."""
    return Quantity(value, unit)


def same_dimension(a: str, b: str) -> bool:
    return _parse_unit(a).dim == _parse_unit(b).dim


def check_dimension(quantity: Quantity, expected_unit: str, name: str = "value") -> Quantity:
    """Assert a quantity has the dimensions of ``expected_unit``; return it."""
    if not same_dimension(quantity.unit, expected_unit):
        raise DimensionError(
            f"{name}: expected dimensions of {expected_unit!r}, got "
            f"{quantity.unit!r}"
        )
    return quantity


def convert(value: float, from_unit: str, to_unit: str) -> float:
    return Quantity(value, from_unit).to(to_unit).value


# ---------------------------------------------------------------------------
# Physical-invariant helpers that only make sense once dimensions are known.
# ---------------------------------------------------------------------------
def closure_residual(parts: Dict[str, float], total: float = 1.0) -> float:
    """|sum(parts) - total| for a dimensionless closure such as R+T+A=1."""
    s = float(sum(parts.values()))
    return abs(s - total)


def assert_bounded(name: str, value: float, lo: float, hi: float,
                   tol: float = 0.0) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} = {value!r} is not finite")
    if value < lo - tol or value > hi + tol:
        raise ValueError(f"{name} = {value!r} outside physical bounds [{lo}, {hi}]")
