"""Ingest UCI Online Retail II into clean order lines.

The raw workbook mixes types inside columns, so every cell is read as text and
cast in SQL; dates arrive as Excel serial numbers and are converted by hand.
Rows that cannot carry a price signal -- returns, zero prices, cancellations,
non-UK markets, and the non-product stock codes -- are dropped here, once.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import duckdb

RAW_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
XLSX_NAME = "online_retail_II.xlsx"
SHEETS = ("Year 2009-2010", "Year 2010-2011")

# Product codes are five digits with up to three trailing letters. Everything
# else in StockCode is postage (POST, DOT), manual entries (M, ADJUST, AMAZONFEE,
# BANK CHARGES), gift vouchers (gift_0001_20) or internal codes (DCGS0058, PADS).
# DOT would otherwise look like the most price-variable product in the file.
PRODUCT_CODE = re.compile(r"^\d{5}[A-Za-z]{0,3}$")

# One market, so the price a product was sold at is comparable across rows.
# The rest is 8% and mostly wholesale (EIRE orders the same day at case prices).
COUNTRY = "United Kingdom"

DATA_DIR = Path(os.getenv("DP_DATA_DIR", "data"))
RAW_XLSX = DATA_DIR / "raw" / XLSX_NAME
ORDERS_PARQUET = DATA_DIR / "processed" / "orders.parquet"

# Excel counts days from 1899-12-30 (1900 leap-year bug included).
EXCEL_EPOCH = "TIMESTAMP '1899-12-30 00:00:00'"


def is_product_code(code: str) -> bool:
    """True for a real product code, False for postage, adjustments and vouchers."""
    return bool(PRODUCT_CODE.match(code.strip()))


def raw_sql(xlsx: Path | str, sheet: str) -> str:
    """Read one sheet as text and cast it, so a single bad cell cannot kill the load."""
    return f"""
        SELECT "Invoice" AS invoice,
               "StockCode" AS stock_code,
               "Description" AS description,
               CAST("Quantity" AS INTEGER) AS quantity,
               {EXCEL_EPOCH} + to_seconds(CAST("InvoiceDate" AS DOUBLE) * 86400)
                   AS invoice_ts,
               CAST("Price" AS DOUBLE) AS price,
               CAST("Customer ID" AS DOUBLE) AS customer_id,
               "Country" AS country
        FROM read_xlsx('{xlsx}', sheet = '{sheet}', header = true, all_varchar = true)
    """


def clean_sql(source_sql: str) -> str:
    """Drop every row that cannot carry a price signal, from any source relation.

    A subquery rather than a CTE, because these get joined with UNION ALL and a
    WITH inside a union branch is not valid SQL.
    """
    return f"""
        SELECT * FROM ({source_sql})
        WHERE quantity > 0
          AND price > 0
          AND NOT starts_with(invoice, 'C')
          AND country = '{COUNTRY}'
          AND regexp_matches(stock_code, '{PRODUCT_CODE.pattern}')
    """


def describe(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, Any]:
    keys = ("rows", "invoices", "products", "first_ts", "last_ts", "units", "revenue")
    row = con.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT invoice), COUNT(DISTINCT stock_code),
               MIN(invoice_ts), MAX(invoice_ts), SUM(quantity),
               ROUND(SUM(quantity * price), 2)
        FROM {table}
        """
    ).fetchone()
    assert row is not None  # a COUNT over an existing table always returns a row
    return dict(zip(keys, row, strict=True))


def ingest(
    xlsx: Path | str = RAW_XLSX, out: Path | str = ORDERS_PARQUET
) -> dict[str, Any]:
    """Read both sheets, clean once, write a Parquet of order lines, return counts."""
    xlsx = Path(xlsx)
    if not xlsx.exists():
        raise FileNotFoundError(f"{xlsx} is missing; run scripts/fetch_data.sh first")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    # ponytail: the excel extension is downloaded on first use and cached in
    # ~/.duckdb; if CI ever runs the ingest it needs network once.
    con.execute("INSTALL excel; LOAD excel;")
    union = " UNION ALL ".join(clean_sql(raw_sql(xlsx, sheet)) for sheet in SHEETS)
    con.execute(f"CREATE TEMP TABLE orders AS ({union})")

    stats = describe(con, "orders")
    con.execute(f"COPY orders TO '{out}' (FORMAT parquet)")
    con.close()

    stats["dropped"] = _raw_rows(xlsx) - stats["rows"]
    stats["parquet"] = str(out)
    return stats


def _raw_rows(xlsx: Path | str) -> int:
    """Rows in the workbook, for the dropped-rows count in the report."""
    con = duckdb.connect()
    con.execute("INSTALL excel; LOAD excel;")
    total = 0
    for sheet in SHEETS:
        row = con.execute(
            f"SELECT COUNT(*) FROM read_xlsx('{xlsx}', sheet = '{sheet}',"
            " header = true, all_varchar = true)"
        ).fetchone()
        assert row is not None
        total += row[0]
    con.close()
    return int(total)


def main() -> int:
    for key, value in ingest().items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
