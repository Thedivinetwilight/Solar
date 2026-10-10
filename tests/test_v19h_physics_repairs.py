"""APMT V1.9-H — regression tests for the confirmed physics repairs R1/T21/U1.

Each repair below was confirmed by reproducing the defect against an
independent implementation or a closed-form derivation *before* the fix.
The tests pin the repaired behaviour; the historical (pre-fix) numbers are
preserved in git and in the V1.9-H report section, never silently updated.
"""
import numpy as np
import pytest

from apmt.core.constants import C_M_S, H_J_S, K_B_EV_K, Q_C
from apmt.device.detailed_balance import _emitted_current
from apmt.device.recombination import (
    j0_budget,
    j0_from_ere,
    j0_srh_slab_ma_cm2,
    j0_srh_temperature_scaled,
    radiative_j0_ma_cm2,
)
from apmt.device.tandem import _subcell_from_params, optics_for, spectrum_for
from apmt.materials.perovskite import (
    perovskite_alpha_cm1,
    photon_energy_ev,
)
from apmt.params.registry import ParamSet


# ---------------------------------------------------------------------------
# R1: radiative J0 was inflated 1000x by a spurious extra *1e3
# ---------------------------------------------------------------------------

class TestR1RadiativeJ0Scale:
    @pytest.mark.parametrize("eg_ev,temperature_k", [
        (1.121, 300.0), (1.68, 300.0), (1.121, 320.0), (1.68, 350.0),
    ])
    def test_matches_independent_detailed_balance(self, eg_ev, temperature_k):
        """Cross-check vs detailed_balance._emitted_current (separate code path).

        Residual ~1e-4 is grid convergence between the two integrators, not a
        scale error (the defect was 1000x)."""
        expected = _emitted_current(eg_ev, temperature_k, 0.0) * 0.1  # A/m2->mA/cm2
        got = radiative_j0_ma_cm2(eg_ev, temperature_k)
        assert got == pytest.approx(expected, rel=1e-3)

    def test_hand_closed_form_silicon_300k(self):
        """Boltzmann-tail closed form: J0 = q * 2*pi*(kT)^3*(x^2+2x+2)*e^-x/h^3c^2.

        x = Eg/kT = 1.121/0.025852 = 43.36; hand value 7.9318e-14 mA/cm^2.
        Residual vs the tool is the Boltzmann-vs-Bose difference plus grid."""
        kT_J = K_B_EV_K * 300.0 * Q_C
        x = 1.121 / (K_B_EV_K * 300.0)
        Phi = (2 * np.pi * kT_J ** 3 / (H_J_S ** 3 * C_M_S ** 2)
               * (x ** 2 + 2 * x + 2) * np.exp(-x))
        hand = Q_C * Phi * 0.1
        assert hand == pytest.approx(7.9318e-14, rel=1e-3)
        assert radiative_j0_ma_cm2(1.121, 300.0) == pytest.approx(hand, rel=2e-3)

    def test_absolute_scale_pins(self):
        """Absolute pins (grid-converged tool values, verified against the hand
        derivation above; any future 1000x-scale regression fails loudly)."""
        assert radiative_j0_ma_cm2(1.121, 300.0) == pytest.approx(7.9329e-14, rel=1e-3)
        assert radiative_j0_ma_cm2(1.68, 300.0) == pytest.approx(7.1347e-23, rel=1e-3)

    def test_ere_division_contract(self):
        assert j0_from_ere(1.68, 300.0, 1.0) == pytest.approx(
            radiative_j0_ma_cm2(1.68, 300.0))
        assert j0_from_ere(1.68, 300.0, 0.02) == pytest.approx(
            radiative_j0_ma_cm2(1.68, 300.0) / 0.02)
        with pytest.raises(ValueError):
            j0_from_ere(1.68, 300.0, 0.0)
        with pytest.raises(ValueError):
            j0_from_ere(1.68, 300.0, 1.5)


# ---------------------------------------------------------------------------
# T21: SRH J0 was temperature-scaled TWICE (slab(T) then rescale to T again)
# ---------------------------------------------------------------------------

class TestT21SingleTemperatureScaling:
    def test_subcell_uses_slab_at_temperature_directly(self):
        """The built subcells' SRH J0 must equal the slab model evaluated AT T.

        The defect applied j0_srh_temperature_scaled() on top of the already
        T-dependent slab value, inflating high-T SRH recombination (x32 at
        320 K for the bottom cell with n = 1.05)."""
        ps = ParamSet.defaults()
        opt = optics_for(ps)
        sp = spectrum_for(ps)
        T = 320.0
        top, bottom, eg_top, eg_bottom = _subcell_from_params(ps, opt, T, sp)
        slab_top = j0_srh_slab_ma_cm2(
            T, eg_top, ps["perovskite_thickness_nm"] * 1e-7,
            ps["perovskite_srh_lifetime_ns"] * 1e-9, ps["perovskite_doping_cm3"],
            ps["perovskite_srv_cm_s"])
        slab_bot = j0_srh_slab_ma_cm2(
            T, eg_bottom, ps["silicon_thickness_um"] * 1e-4,
            ps["silicon_bulk_lifetime_ms"] * 1e-3, ps["silicon_doping_cm3"],
            ps["silicon_srv_cm_s"])
        assert top.j0_budget.j0_srh_ma_cm2 == pytest.approx(slab_top, rel=1e-12)
        assert bottom.j0_budget.j0_srh_ma_cm2 == pytest.approx(slab_bot, rel=1e-12)
        assert top.j0_budget.detail["srh_route"] == "slab SRH+surface model"

    def test_temperature_ratio_is_pure_slab_ratio(self):
        """J0(T)/J0(Tref) must equal the slab ratio alone (no hidden rescale)."""
        ps = ParamSet.defaults()
        opt = optics_for(ps)
        sp = spectrum_for(ps)
        built = {}
        for T in (300.0, 320.0):
            top, _, eg_top, _ = _subcell_from_params(ps, opt, T, sp)
            built[T] = (top.j0_budget.j0_srh_ma_cm2, eg_top)
        slab = {T: j0_srh_slab_ma_cm2(
            T, eg, ps["perovskite_thickness_nm"] * 1e-7,
            ps["perovskite_srh_lifetime_ns"] * 1e-9, ps["perovskite_doping_cm3"],
            ps["perovskite_srv_cm_s"]) for T, (_, eg) in built.items()}
        assert built[320.0][0] / built[300.0][0] == pytest.approx(
            slab[320.0] / slab[300.0], rel=1e-12)
        assert built[320.0][0] > built[300.0][0]  # recombination grows with T

    def test_scaler_standalone_contract(self):
        """j0_srh_temperature_scaled is no longer called by production code,
        but its documented ref->T contract is pinned (it is the correct tool
        for scaling a fitted 298 K value)."""
        assert j0_srh_temperature_scaled(1.0, 298.15, 298.15, 1.68, 1.68, 1.45) == \
            pytest.approx(1.0)
        kT, kTr = K_B_EV_K * 320.0, K_B_EV_K * 298.15
        hand = 2.5 * (320.0 / 298.15) ** 3 * np.exp(
            -1.67 / (1.05 * kT) + 1.68 / (1.05 * kTr))
        assert j0_srh_temperature_scaled(2.5, 320.0, 298.15, 1.67, 1.68, 1.05) == \
            pytest.approx(hand, rel=1e-12)


# ---------------------------------------------------------------------------
# U1: Urbach branch missed the 1/e matching factor (edge jumped by e ~ 2.718x)
# ---------------------------------------------------------------------------

class TestU1UrbachEdgeContinuity:
    EG, PEAK, EU_MEV = 1.68, 1.0e5, 15.0

    def test_branches_match_at_edge(self):
        """Both branches give peak*sqrt(Eu) at E = Eg + Eu (docstring contract)."""
        Eu = self.EU_MEV * 1e-3
        # dense wavelength grid straddling the edge energy
        E = np.linspace(self.EG + Eu - 5e-4, self.EG + Eu + 5e-4, 2001)
        wl = H_J_S * C_M_S / (E * Q_C) * 1e9
        alpha = perovskite_alpha_cm1(self.EG, self.PEAK, self.EU_MEV, wl)
        assert alpha[1000] == pytest.approx(self.PEAK * np.sqrt(Eu), rel=1e-6)
        # continuity across the branch boundary (no e-fold jump)
        assert alpha[1001] / alpha[999] == pytest.approx(1.0, rel=1e-3)

    def test_below_gap_slope_is_one_over_eu(self):
        E = np.linspace(self.EG - 0.05, self.EG - 0.01, 51)
        wl = H_J_S * C_M_S / (E * Q_C) * 1e9
        alpha = perovskite_alpha_cm1(self.EG, self.PEAK, self.EU_MEV, wl)
        slope = np.polyfit(E, np.log(alpha), 1)[0]
        assert slope == pytest.approx(1.0 / (self.EU_MEV * 1e-3), rel=1e-6)

    def test_above_gap_is_pure_tauc(self):
        """Above Eg + 5Eu the model is exactly peak*sqrt(E - Eg) (registered)."""
        E = np.linspace(self.EG + 0.1, self.EG + 0.5, 11)
        wl = H_J_S * C_M_S / (E * Q_C) * 1e9
        alpha = perovskite_alpha_cm1(self.EG, self.PEAK, self.EU_MEV, wl)
        assert alpha == pytest.approx(self.PEAK * np.sqrt(E - self.EG), rel=1e-12)

    def test_monotone_and_guarded(self):
        wl = np.linspace(300.0, 1200.0, 901)
        alpha = perovskite_alpha_cm1(self.EG, self.PEAK, self.EU_MEV, wl)
        assert np.all(np.diff(alpha[::-1]) >= 0.0)  # rising with photon energy
        with pytest.raises(ValueError):
            perovskite_alpha_cm1(self.EG, 1.0e9, self.EU_MEV, wl)


# ---------------------------------------------------------------------------
# F1: fast-solver V(J) grid endpoint poisoned by inverse-table tie-breaking
# ---------------------------------------------------------------------------

class TestF1FastSolverEndpointPoison:
    def test_raw_table_tie_returns_pad(self):
        """Documents the trap F1 repairs: the raw inverse-table lookup at
        J == Jsc tie-breaks to the -v_pad endpoint instead of V(Jsc) = 0.

        J(V) is numerically flat below diode turn-on, so every table row
        there ties at J ~= Jsc; np.interp returns the leftmost tie, which is
        the V = -0.25 pad point -- a 250 mV error at the V(J) grid endpoint
        that poisons any MPP search adjacent to it (heavy-shunt corners).
        The repair re-evaluates such queries with the exact scalar inversion
        (whose anchor V(Jsc) = 0 is asserted below)."""
        from apmt.device.subcell import voltage_at_current
        from apmt.device.tandem import build_tandem, subcell_table
        ps = ParamSet.defaults().with_mapping({"rsh_ohm_cm2": 60.0})
        T = 298.15
        dev = build_tandem(ps, "IQE-M1", T)
        Vt_tab, Jt_tab, _ = subcell_table(dev.top, T, 4001)
        Jt_asc, Vt_asc = Jt_tab[::-1], Vt_tab[::-1]
        jsc_tbl = float(np.interp(0.0, Vt_tab, Jt_tab))
        raw = float(np.interp(np.clip(jsc_tbl, Jt_asc[0], Jt_asc[-1]),
                              Jt_asc, Vt_asc))
        assert raw == pytest.approx(-0.25, abs=1e-12)
        assert voltage_at_current(dev.top, jsc_tbl, T) == pytest.approx(0.0, abs=1e-6)

    def test_heavily_shunted_agreement_is_tight(self):
        """Rsh = 60 puts the MPP search interval adjacent to the grid endpoint.

        Pre-fix dPCE was 0.051 (edge-test tolerance 5e-3); post-fix the fast
        path must match the reference oracle to 1e-4 without any tolerance
        relaxation (measured post-fix dPCE = 2.4e-7)."""
        from apmt.device.tandem import evaluate_tandem
        ps = ParamSet.defaults().with_mapping({"rsh_ohm_cm2": 60.0})
        ref = evaluate_tandem(ps, solver="reference", self_heating=False)
        fast = evaluate_tandem(ps, solver="fast", self_heating=False)
        assert abs(ref.pce_pct - fast.pce_pct) < 1e-4
        assert abs(ref.voc_v - fast.voc_v) < 1e-6
        assert abs(ref.ff - fast.ff) < 1e-5


# ---------------------------------------------------------------------------
# J-sens: Jsc conditioning diagnostic fabricated a slope when unbracketed
# ---------------------------------------------------------------------------

class TestJSensBracketFlag:
    def test_bracketed_curve_reports_finite_slope(self):
        """A matched-style V(J) crossing 20 mV gives the exact linear slope."""
        from apmt.device.tandem import curve_metrics_by_current
        J = np.linspace(0.0, 15.0, 301)
        V = 1.8 * (1.0 - J / 15.1)          # V(15) = 0.0119 < 0.02: bracketed
        m = curve_metrics_by_current(J, V, float("inf"))
        assert m["jsc_bias_sensitivity_bracketed"] is True
        j_at_dv = 15.1 * (1.0 - 0.02 / 1.8)
        assert m["jsc_bias_sensitivity_ma_cm2_per_v"] == pytest.approx(
            abs(15.0 - j_at_dv) / 0.02, rel=1e-9)

    def test_unbracketed_curve_reports_nan_with_flag(self):
        """A mismatched-style V(J) that never reaches 20 mV must be NaN.

        Pre-fix this returned the bisection midpoint, fabricating
        sens = j_hi/0.04 with a physical-sounding comment."""
        from apmt.device.tandem import curve_metrics_by_current
        J = np.linspace(0.0, 15.0, 301)
        V = 1.8 - 1.0 * J / 15.0            # V(15) = 0.8 > 0.02: unbracketed
        m = curve_metrics_by_current(J, V, float("inf"))
        assert m["jsc_bias_sensitivity_bracketed"] is False
        assert np.isnan(m["jsc_bias_sensitivity_ma_cm2_per_v"])

    def test_twin_point_is_unbracketed(self):
        """The registry-default twin is current-mismatched: the bottom cell
        still holds ~0.5 V when the top hits Jsc, so V(J) never reaches the
        20 mV probe and the diagnostic is honestly NaN (old artifact value
        j_hi/0.04 = 385.6 is preserved in git history)."""
        from apmt.device.tandem import evaluate_tandem
        res = evaluate_tandem(ParamSet.defaults(), self_heating=False)
        assert res.detail["jsc_bias_sensitivity_bracketed"] is False
        assert np.isnan(res.detail["jsc_bias_sensitivity_ma_cm2_per_v"])


# ---------------------------------------------------------------------------
# Rs-sign: subcell series resistance RAISED the current (wrong junction-bias sign)
# ---------------------------------------------------------------------------

class TestRsSignHurts:
    def _cells(self):
        from dataclasses import replace
        from apmt.device.tandem import build_tandem
        dev = build_tandem(ParamSet.defaults(), "IQE-M1", 298.15)
        return dev.top, replace(dev.top, rs_ohm_cm2=5.0)

    def test_series_resistance_lowers_current(self):
        """Vj = V + J*Rs: at fixed terminal bias, Rs can only hurt.

        Pre-fix the minus sign under-biased the junction, so Rs = 5 raised
        J(1.0 V) from 15.422584 to 15.422765 (and the scalar/vector paths
        disagreed with each other). Production builds use subcell rs = 0,
        so this repairs a latent path with zero live impact."""
        from apmt.device.subcell import current_density
        from apmt.device.tandem import current_density_vectorized
        c0, c5 = self._cells()
        V = np.array([0.0, 0.5, 1.0, 1.2])
        js0 = current_density(c0, V, 298.15)
        js5 = current_density(c5, V, 298.15)
        jv5, diag = current_density_vectorized(c5, V, 298.15)
        # at Jsc the Rs drop changes J only below solver noise (1e-10 bisection
        # tol), so allow noise there; strict in the power quadrant (V = 1.0 V
        # differs by 3.6e-3, far above noise)
        assert np.all(js5 <= js0 + 1e-9)
        assert js5[2] < js0[2] - 1e-6
        assert diag["converged_fraction"] == pytest.approx(1.0)
        assert js5 == pytest.approx(jv5, rel=1e-9)   # paths agree post-fix

    def test_zero_rs_is_ideal(self):
        """Rs = 0 reproduces the explicit ideal diode (guards the edit)."""
        from apmt.device.subcell import current_density
        from apmt.device.tandem import current_density_vectorized
        c0, _ = self._cells()
        # production table span only: beyond Voc*1.01 + 0.02 the vector path's
        # clip range +/-(2*Jph + 10) saturates deep-forward currents (pre-existing
        # limitation, never queried by the solvers; not part of this repair)
        V = np.linspace(0.0, 1.3, 14)
        js0 = current_density(c0, V, 298.15)
        jv0, _ = current_density_vectorized(c0, V, 298.15)
        assert js0 == pytest.approx(jv0, rel=1e-12)


# ---------------------------------------------------------------------------
# F-heat: heat load subtracted the FULL extracted power from fractioned absorption
# ---------------------------------------------------------------------------

class TestFHeatForm:
    @pytest.mark.parametrize("f_heat,expected", [(1.0, 6000.0), (0.5, 3000.0), (0.0, 0.0)])
    def test_heat_is_fraction_of_non_extracted(self, f_heat, expected):
        """heat = f_heat * (P_absorbed - P_extracted), the documented form.

        Constant-stub electrical model (P_abs = 8000, P_e = 2000 mW/cm^2):
        the old form gave f*P_abs - P_e (2000.0 at f = 0.5), the repaired
        form gives f*(P_abs - P_e) (3000.0). Identical at f = 1.0, so the
        registry-default twin is untouched by this repair."""
        from apmt.device.thermal import solve_equilibrium
        ps = ParamSet.defaults().with_mapping({"absorption_heat_fraction": f_heat})
        st = solve_equilibrium(ps, 8000.0, lambda T: 2000.0)
        assert st.heat_load_mw_cm2 == pytest.approx(expected, rel=1e-9)
        assert abs(st.residual_mw_cm2) < 1e-3

    def test_lower_heat_fraction_cools(self):
        from apmt.device.thermal import solve_equilibrium
        ps = ParamSet.defaults()
        hot = solve_equilibrium(ps.with_mapping({"absorption_heat_fraction": 1.0}),
                                8000.0, lambda T: 2000.0)
        warm = solve_equilibrium(ps.with_mapping({"absorption_heat_fraction": 0.5}),
                                 8000.0, lambda T: 2000.0)
        assert warm.junction_k < hot.junction_k
