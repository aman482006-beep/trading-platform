"""Shared fee conventions for the MT5 report importers.

Two rules live here, both owned by exactly one function so the XLSX and the
HTML importer cannot drift apart on them:

* :func:`mt5_fee_cell` reads one report cell (``Kommission``/``Swap``).
* :func:`mt5_signed_costs_to_fee` converts MT5's signs into the Trade
  contract's sign.

MT5 signs commission and swap from the account's point of view: a cost is
negative, a swap credit is positive. The :class:`~shared.models.Trade`
contract defines ``fees`` as a positive cost (``net_pnl == pnl - fees``),
which is the same convention the live databases use for a stored commission
(a charge is a positive cost, a rebate negative; see
``live_runner/base_adapter.py``'s ``commission_cost`` for the live-side twin
of this rule). So the importers negate the MT5 signs at the import boundary;
``meta.commission`` and ``meta.swap`` keep MT5's raw signed values.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


def mt5_fee_cell(value: Any, column: str, parse: Callable[[Any], float | None]) -> float:
    """Parse one MT5 fee cell (``Kommission``/``Swap``) into a signed number.

    ``parse`` is the caller's locale-aware number parser; each MT5 importer
    owns one, and both return ``None`` for "not a number".

    MT5 reports "no fees" through a missing, blank or ``0.0`` cell, which
    reads as ``0.0``. A cell that *has* a value the parser cannot read (an
    Excel error string, ``"n/a"``) must fail the import: reading it as
    ``0.0`` would silently move the trade's ``net_pnl`` and its
    winner/loser classification.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    if str(value).strip() == "":
        return 0.0
    parsed = parse(value)
    if parsed is None:
        raise ValueError(f"MT5 {column} cell is not a number: {value!r}")
    return parsed


def mt5_signed_costs_to_fee(commission: float, swap: float) -> float:
    """Return the ``Trade.fees`` value for MT5's signed commission and swap.

    A net swap credit (swap positive) therefore yields a negative ``fees``.
    Both importers reach the same expression through this one function, so the
    XLSX and the HTML importer cannot drift apart on the sign convention (they
    must agree trade by trade, see ``test_importers_agree`` in
    ``tests/validation/test_split_fills.py``).

    A non-finite commission or swap (``inf``) is refused rather than stored:
    storing it would put a non-finite ``fees`` or ``net_pnl`` on the trade.
    (``nan`` cells never reach this function: :func:`mt5_fee_cell` reads them
    as MT5's "no fees".)
    """
    total = commission + swap
    if not math.isfinite(total):
        raise ValueError(
            "MT5 commission and swap must be finite numbers, got "
            f"commission={commission!r}, swap={swap!r}"
        )
    return -total
