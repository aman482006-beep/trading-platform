"""The single fee-sign convention both MT5 importers share.

MT5 signs commission and swap from the account's point of view (a cost is
negative); :class:`~shared.models.Trade` defines ``fees`` as a positive cost.
``validation.importers._fees.mt5_signed_costs_to_fee`` is the one place that
converts between the two, so a change to the convention is caught here rather
than in one importer only.
"""

from __future__ import annotations

import math

import pytest

from validation.importers._fees import mt5_signed_costs_to_fee


class TestSignedCostsBecomeTradeFees:
    @pytest.mark.parametrize(
        ("commission", "swap", "expected"),
        [
            (-2.5, -1.5, 4.0),  # commission and swap cost money
            (-0.5, 1.5, -1.0),  # net swap credit stays a negative fee
            (0.0, -0.3, 0.3),
            (0.0, 0.0, 0.0),
        ],
    )
    def test_negates_the_account_view_cost(self, commission: float, swap: float, expected: float):
        assert mt5_signed_costs_to_fee(commission, swap) == pytest.approx(expected)

    def test_net_pnl_identity_holds_for_a_credit(self):
        fees = mt5_signed_costs_to_fee(-0.5, 1.5)
        assert fees < 0.0
        assert 100.0 - fees == pytest.approx(101.0)


class TestNonFiniteCostsAreRefused:
    @pytest.mark.parametrize(
        ("commission", "swap"),
        [
            (math.nan, 0.0),
            (0.0, math.nan),
            (math.inf, 0.0),
            (0.0, -math.inf),
            (math.inf, -math.inf),
        ],
    )
    def test_corrupt_cells_fail_the_import(self, commission: float, swap: float):
        """Never store a nan/inf fee or net_pnl: refuse the report instead."""
        with pytest.raises(ValueError, match="must be finite"):
            mt5_signed_costs_to_fee(commission, swap)
