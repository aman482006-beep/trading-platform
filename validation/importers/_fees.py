"""Shared fee conventions for the MT5 report importers.

Three rules live here, each owned by exactly one function so the XLSX and the
HTML importer cannot drift apart on them:

* :func:`mt5_fee_cell` reads one report cell (``Kommission``/``Swap``).
* :func:`mt5_signed_costs_to_fee` converts MT5's signs into the Trade
  contract's sign.
* :func:`mt5_fee_or_none` maps MT5's exact-zero fee to ``None``.

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
    reads as ``0.0``. A cell that reaches the parser with a non-numeric text
    must fail the import: reading it as ``0.0`` would silently move the
    trade's ``net_pnl`` and its winner/loser classification. (An Excel error
    cell such as ``#DIV/0!`` also never gets that far: the XLSX importer
    refuses it beforehand, because ``pd.read_excel`` turns it into a NaN that
    this rule would otherwise read as "no fees".)
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
    must agree trade by trade, see
    ``test_split_fills.py::TestHTMLSplitFills``'s
    ``test_importers_agree_on_same_position_sequence``).

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


def mt5_fee_or_none(fees: float) -> float | None:
    """Map MT5's exact-zero fee to ``None`` (``Trade.fees`` is optional).

    Exact zero, not a tolerance: MT5 reports "no fees" as ``0.0``. Both
    importers reach the same mapping through this one function so the next
    editor changes the rule once. (``fees`` is finite by construction --
    :func:`mt5_signed_costs_to_fee` refuses anything else -- so falsiness
    here is exactly the reported ``0.0``/``-0.0``.)
    """
    return fees if fees else None
