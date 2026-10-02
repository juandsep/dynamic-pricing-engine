"""The ingest is a pile of filters, so the filters are what gets tested."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import duckdb
import openpyxl
import pytest

from dp.data import clean_sql, is_product_code, raw_sql

PRODUCT_CODES = ("85123A", "71053", "85099C", "20685", " 85123A ")
NON_PRODUCT_CODES = (
    "POST",
    "DOT",
    "M",
    "C2",
    "D",
    "S",
    "ADJUST",
    "BANK CHARGES",
    "AMAZONFEE",
    "DCGS0058",
    "gift_0001_20",
    "PADS",
)

# One row that must survive, then one row per reason to drop it.
FIXTURE_ROWS = [
    ("536365", "85123A", 6, 2.55, "United Kingdom"),
    ("536366", "85123A", -6, 2.55, "United Kingdom"),  # return
    ("536367", "85123A", 6, 0.0, "United Kingdom"),  # not sold, given away
    ("C536368", "85123A", 6, 2.55, "United Kingdom"),  # cancellation
    ("536369", "85123A", 6, 2.55, "EIRE"),  # another market, another price list
    ("536370", "POST", 1, 18.0, "United Kingdom"),  # postage
    ("536371", "DOT", 1, 9.0, "United Kingdom"),  # postage
    ("536372", "M", 1, 5.0, "United Kingdom"),  # manual entry
]


def test_is_product_code_keeps_products_and_drops_the_rest() -> None:
    for code in PRODUCT_CODES:
        assert is_product_code(code), code
    for code in NON_PRODUCT_CODES:
        assert not is_product_code(code), code


@pytest.fixture
def orders_csv(tmp_path: Path) -> Path:
    """Header names already match the clean schema; the reader infers the types."""
    path = tmp_path / "orders.csv"
    lines = ["invoice,stock_code,quantity,price,country"]
    lines += [",".join(map(str, row)) for row in FIXTURE_ROWS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_clean_sql_keeps_only_rows_that_carry_a_price_signal(orders_csv: Path) -> None:
    source = f"SELECT * FROM read_csv('{orders_csv}', header = true)"
    kept = duckdb.connect().execute(clean_sql(source)).df()
    assert list(kept["invoice"]) == ["536365"]


def test_two_cleaned_sources_union_into_one_table(orders_csv: Path) -> None:
    """The sheets are joined with UNION ALL, which a CTE branch would break."""
    source = f"SELECT * FROM read_csv('{orders_csv}', header = true)"
    union = " UNION ALL ".join([clean_sql(source), clean_sql(source)])
    con = duckdb.connect()
    con.execute(f"CREATE TEMP TABLE orders AS ({union})")
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone() == (2,)


def test_raw_sql_reads_datetimes_from_excel_serials(tmp_path: Path) -> None:
    """The workbook stores dates as serial numbers; the cast has to bring them back."""
    # A naive datetime on purpose: Excel serials carry no zone, so there is none to compare.
    when = datetime.fromisoformat("2010-12-01 08:26:00")
    book = openpyxl.Workbook()
    sheet = book.worksheets[0]
    sheet.append(
        [
            "Invoice",
            "StockCode",
            "Description",
            "Quantity",
            "InvoiceDate",
            "Price",
            "Customer ID",
            "Country",
        ]
    )
    sheet.append(
        [
            "536365",
            "85123A",
            "WHITE HANGING HEART",
            6,
            when,
            2.55,
            17850.0,
            "United Kingdom",
        ]
    )
    xlsx = tmp_path / "one_sheet.xlsx"
    book.save(xlsx)

    con = duckdb.connect()
    con.execute("INSTALL excel; LOAD excel;")
    row = con.execute(raw_sql(xlsx, "Sheet")).df().iloc[0]

    assert row["invoice"] == "536365"
    assert row["stock_code"] == "85123A"
    assert row["quantity"] == 6
    assert row["price"] == pytest.approx(2.55)
    assert row["customer_id"] == pytest.approx(17850.0)
    assert row["invoice_ts"].to_pydatetime() == when
