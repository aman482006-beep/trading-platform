"""Shared fee-sign normalisation for the MT5 report importers.

MT5 signs commission and swap from the account's point of view: a cost is
negative, a swap credit is positive. The :class:`~shared.models.Trade`
contract defines ``fees`` as a positive cost (``net_pnl == pnl - fees``),
which is also the convention the live databases use (a stored commission is
a positive cost, #205), so the importers negate the MT5 signs at the import
boundary. A net swap credit therefore yields a negative ``fees``.
``meta.commission`` and ``meta.swap`` keep MT5's raw signed values.
"""

from __future__ import annotations


def mt5_signed_costs_to_fee(commission: float, swap: float) -> float:
    """Return the ``Trade.fees`` value for MT5's signed commission and swap.

    Both importers reach the same expression through this one function, so the
    XLSX and the HTML importer cannot drift apart on the sign convention (they
    must agree trade by trade, see ``test_importers_agree`` in
    ``tests/validation/test_split_fills.py``).
    """
    return -(commission + swap)
