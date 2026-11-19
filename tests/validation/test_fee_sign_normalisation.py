"""The single fee-sign convention both MT5 importers share.

MT5 signs commission and swap from the account's point of view (a cost is
negative); :class:`~shared.models.Trade` defines ``fees`` as a positive cost.
``validation.importers._fees`` is the one place that converts between the
two, so a change to the convention is caught here rather than in one
importer only.
"""

from __future__ import annotations

import math

import pytest

from validation.importers._fees import mt5_fee_cell, mt5_fee_or_none, mt5_signed_costs_to_fee


def _never_parses(value: object) -> float | None:
    return None


def _dot_or_comma_decimal(raw: str | None) -> float | None:
    """Stand-in for an importer's locale-aware parser."""
    if raw is None:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


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


class TestNonFiniteSumsAreRefused:
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
    def test_non_finite_sums_are_refused(self, commission: float, swap: float):
        """Never store an inf fee or net_pnl: refuse the value instead."""
        with pytest.raises(ValueError, match="must be finite"):
            mt5_signed_costs_to_fee(commission, swap)


class TestFeeOrNone:
    """The zero-to-``None`` mapping both importers share (``mt5_fee_or_none``)."""

    def test_exact_zero_is_mt5s_no_fees(self):
        assert mt5_fee_or_none(0.0) is None

    @pytest.mark.parametrize("fee", [0.004, -0.004, 1e-9, -1e-9])
    def test_a_tiny_non_zero_fee_is_kept(self, fee: float):
        """Exact zero, not a tolerance: a real sub-cent cost is a cost.

        A swap credit on a small lot can be ``0.004``; mapping it away would
        contradict ``net_pnl == pnl - fees`` for every consumer that
        reconstructs the net figure from ``fees``.
        """
        assert mt5_fee_or_none(fee) == pytest.approx(fee)


class TestFeeCellRule:
    """The cell-level rule both importers share (``mt5_fee_cell``)."""

    @pytest.mark.parametrize("value", [None, "", "   ", math.nan])
    def test_missing_cell_is_mt5s_no_fees(self, value: object):
        assert mt5_fee_cell(value, "Kommission", _never_parses) == 0.0

    @pytest.mark.parametrize("value", ["-2.5", "-2,5", "0,00"])
    def test_present_number_goes_through_the_callers_parser(self, value: str):
        assert mt5_fee_cell(value, "Kommission", _dot_or_comma_decimal) == pytest.approx(
            float(value.replace(",", "."))
        )

    def test_present_but_unparseable_cell_fails_the_import(self):
        """Reading "#DIV/0!" as 0.0 would silently move net_pnl and win/loss."""
        with pytest.raises(ValueError, match="Kommission cell is not a number"):
            mt5_fee_cell("#DIV/0!", "Kommission", _never_parses)

    def test_non_finite_text_is_refused(self):
        with pytest.raises(ValueError, match="Swap cell is not a number"):
            mt5_fee_cell("inf", "Swap", _never_parses)
