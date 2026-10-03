"""APMT V1.9 — physical constants (CODATA 2018) in canonical platform units.

All values are exact where CODATA defines them exactly. Constants are exposed
as plain floats *and* as :class:`apmt.core.units.Quantity` objects so that
dimensional checks can be applied at use sites.
"""
from __future__ import annotations

from .units import q

# Exact SI (CODATA 2018 / SI 2019 definitions)
Q_C = 1.602176634e-19          # elementary charge [C]
H_J_S = 6.62607015e-34         # Planck constant [J s]
C_M_S = 299792458.0            # speed of light [m/s]
K_B_J_K = 1.380649e-23         # Boltzmann constant [J/K]
SIGMA_SB_W_M2_K4 = 5.670374419e-8   # Stefan-Boltzmann [W m^-2 K^-4]

# Derived convenience constants in PV units
EV_J = Q_C                      # 1 eV in joules
K_B_EV_K = K_B_J_K / Q_C        # 8.617333262e-5 eV/K
HC_EV_NM = 1239.8419843         # h*c in eV*nm (exact from the constants above)

# Reference conditions
T_REF_K = 298.15                # standard reporting temperature (25 degC)
T_SUN_K = 5778.0                # ASTM AM1.5G effective blackbody temperature
P_ONE_SUN_MW_CM2 = 100.0        # AM1.5G total irradiance in platform units
IRRADIANCE_AM15G_WM2 = 1000.37  # ASTM G173-03 nominal integrated irradiance

# Unit-qualified views (for dimensional checks at use sites)
ELECTRON_CHARGE = q(Q_C, "C")
PLANCK = q(H_J_S, "J*s")
SPEED_OF_LIGHT = q(C_M_S, "m/s")
BOLTZMANN = q(K_B_J_K, "J/K")
ONE_SUN = q(P_ONE_SUN_MW_CM2, "mW/cm^2")
