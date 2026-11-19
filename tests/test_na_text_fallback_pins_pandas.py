"""Pin the fallback copy of pandas' NA-value set against pandas itself.

``validation.importers.mt5_xlsx`` imports ``STR_NA_VALUES`` from pandas'
private parser module to know which fee-cell texts ``pd.read_excel`` reads as
"no value", and keeps a pinned copy in case that import ever disappears. If
pandas adds a sentinel the copy does not know, the XLSX fee guard would stop
refusing that text and a reported cost could silently become zero fees, so
the divergence must fail a test here rather than stay silent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pandas_parsers = pytest.importorskip("pandas._libs.parsers")

from validation.importers.mt5_xlsx import _PANDAS_NO_VALUE_TEXTS  # noqa: E402


def test_the_pinned_set_is_pandas_current_set() -> None:
    expected = frozenset(pandas_parsers.STR_NA_VALUES) - {""}
    assert set(_PANDAS_NO_VALUE_TEXTS) == set(expected)


def test_pandas_reads_every_refused_text_as_no_value(tmp_path: Path) -> None:
    """The guard's set is exactly what ``pd.read_excel`` turns into NaN."""
    import openpyxl
    import pandas as pd

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for offset, text in enumerate(sorted(_PANDAS_NO_VALUE_TEXTS), start=1):
        sheet.cell(row=offset, column=1, value=text)
    path = tmp_path / "na_texts.xlsx"
    workbook.save(path)

    read_back = pd.read_excel(path, header=None, sheet_name=0).squeeze("columns")
    assert list(read_back.isna()) == [True] * len(_PANDAS_NO_VALUE_TEXTS)
