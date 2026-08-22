"""STEP 2 — Excel -> SQLite, plus low-level typed accessors.

This module knows nothing about auth. Scoping is enforced one layer up in
tools.py. Keeping the raw DB layer scope-free means the same loader serves both
the customer bot and authorised internal/proactive workflows.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Optional

import pandas as pd

from . import config as C

_TABLES = ["accounts", "orders", "tickets"]


def build_sqlite() -> None:
    """Load every data sheet of the workbook into a fresh SQLite file."""
    C.BUILD_DIR.mkdir(exist_ok=True)
    xls = pd.read_excel(C.XLSX_PATH, sheet_name=None)  # all sheets
    con = sqlite3.connect(C.DB_PATH)
    try:
        for name in _TABLES:
            df = xls[name].where(pd.notna(xls[name]), None)  # NaN -> None
            df.to_sql(name, con, if_exists="replace", index=False)
        con.commit()
    finally:
        con.close()


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(C.DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


# --- raw (unscoped) accessors ------------------------------------------------
def get_order(order_id: str) -> Optional[dict]:
    r = _rows("SELECT * FROM orders WHERE order_id = ?", (order_id,))
    return r[0] if r else None


def get_account(account_id: str) -> Optional[dict]:
    r = _rows("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
    return r[0] if r else None


def get_ticket(ticket_id: str) -> Optional[dict]:
    r = _rows("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,))
    return r[0] if r else None


def orders_for_account(account_id: str) -> list[dict]:
    return _rows("SELECT * FROM orders WHERE account_id = ?", (account_id,))


def tickets_for_account(account_id: str) -> list[dict]:
    return _rows("SELECT * FROM tickets WHERE account_id = ?", (account_id,))


def all_tickets() -> list[dict]:
    return _rows("SELECT * FROM tickets")


def all_orders() -> list[dict]:
    return _rows("SELECT * FROM orders")


# --- helpers -----------------------------------------------------------------
def parse_dt(value: Optional[str]):
    """Parse a workbook timestamp into an IST-aware datetime (or None)."""
    if not value:
        return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=C.IST)
        except ValueError:
            continue
    return None
