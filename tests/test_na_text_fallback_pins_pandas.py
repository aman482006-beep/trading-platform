"""Pin the fallback copy of pandas' NA-value set against pandas itself.

``validation.importers.mt5_xlsx`` imports ``STR_NA_VALUES`` from pandas to
know which fee-cell texts ``pd.read_excel`` reads as "no value", and keeps a
pinned copy (``_NA_TEXT_FALLBACK``) in case that import ever disappears. If
pandas adds a sentinel the copy does not know, the XLSX fee guard would stop
refusing that text and a reported cost could silently become zero fees, so
the divergence must fail a test here rather than stay silent -- including
when pandas has renamed the module the guard imports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from validation.importers.mt5_xlsx import _NA_TEXT_FALLBACK  # noqa: E402


def _pandas_na_values() -> set[str]:
    """pandas' current NA texts, through whichever module still exports them.

    Both paths are private; a pandas that drops both must fail this test
    rather than let the pinned copy drift silently out of date.
    """
    try:
        from pandas._libs.parsers import STR_NA_VALUES
    except ImportError:
        try:
            from pandas.io.parsers.base_parser import STR_NA_VALUES
        except ImportError as exc:  # pragma: no cover - pandas API rename
            pytest.fail(
                "pandas no longer exports STR_NA_VALUES; update "
                "validation.importers.mt5_xlsx._NA_TEXT_FALLBACK and its import"
            )
            raise exc
    return set(frozenset(STR_NA_VALUES) - {""})


def test_the_fallback_copy_matches_pandas_current_set() -> None:
    """The live import is a tautology here; the copy is what must be compared."""
    assert set(_NA_TEXT_FALLBACK) == _pandas_na_values()


def test_pandas_reads_every_refused_text_as_no_value(tmp_path: Path) -> None:
    """The guard's set is exactly what ``pd.read_excel`` turns into NaN."""
    import openpyxl
    import pandas as pd

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for offset, text in enumerate(sorted(_NA_TEXT_FALLBACK), start=1):
        sheet.cell(row=offset, column=1, value=text)
    path = tmp_path / "na_texts.xlsx"
    workbook.save(path)

    read_back = pd.read_excel(path, header=None, sheet_name=0).squeeze("columns")
    assert list(read_back.isna()) == [True] * len(_NA_TEXT_FALLBACK)
