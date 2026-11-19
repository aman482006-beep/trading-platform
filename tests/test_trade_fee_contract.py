"""The Trade fee contract: ``fees`` is an optional positive cost.

``net_pnl == pnl - fees`` is load-bearing for every importer and engine that
fills the field, so the defaults are pinned here: an omitted fee means "not
reported" (``None``), never a reported zero, and switching the default would
silently upgrade every fee-free trade to "no cost".
"""

from __future__ import annotations

import pytest

from shared.models import Trade, TradeExit


def _trade() -> Trade:
    return Trade(
        id=1,
        symbol="AAPL",
        direction="LONG",
        entry_time="2024-01-02T14:30:00Z",
        entry_price=100.0,
        quantity=10.0,
        exits=[TradeExit(time="2024-01-02T15:30:00Z", price=101.0, quantity=10.0)],
        pnl=10.0,
    )


class TestFeeDefaults:
    def test_fees_and_net_pnl_default_to_none_not_zero(self) -> None:
        trade = _trade()
        assert trade.fees is None
        assert trade.net_pnl is None

    def test_from_dict_without_fees_keeps_them_none(self) -> None:
        trade = Trade.from_dict(_trade().to_dict())
        assert trade.fees is None
        assert trade.net_pnl is None

    def test_from_dict_round_trips_a_stored_fee(self) -> None:
        stored = _trade()
        stored.fees = 4.0
        stored.net_pnl = 6.0
        trade = Trade.from_dict(stored.to_dict())
        assert trade.fees == pytest.approx(4.0)
        assert trade.net_pnl == pytest.approx(6.0)
