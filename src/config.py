"""Global constants for ParcelPilot Sentinel.

The dataset snapshot time is the single reference clock for ALL time-based
reasoning (cancellation windows, pickup delays, SLA breaches). It comes from
the workbook README sheet and must never be replaced with wall-clock now().
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# --- paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BUILD_DIR = ROOT / "build"          # generated artifacts (sqlite, sections.json)
DB_PATH = BUILD_DIR / "parcelpilot.db"
SECTIONS_PATH = BUILD_DIR / "sections.json"
XLSX_PATH = DATA_DIR / "ParcelPilot_Assessment_Data.xlsx"

# --- reference clock (from workbook README) ----------------------------------
IST = ZoneInfo("Asia/Kolkata")
SNAPSHOT_TIME = datetime(2026, 8, 16, 11, 0, tzinfo=IST)

# --- authority tiers (higher wins) -------------------------------------------
# Retrieval finds relevant text; these tiers + scope decide which text GOVERNS.
TIER_CUSTOMER_AGREEMENT = 40   # a signed, in-scope customer contract
TIER_CURRENT_POLICY = 30       # current global policy / SOP / product guide
TIER_DEPRECATED_POLICY = 10    # superseded policy — retrievable, never authoritative
TIER_HISTORICAL_TICKET = 0     # past resolutions — context only, may be WRONG

# Sources at or below this tier can be shown as context but may NEVER be the
# basis of a ruling.
NON_AUTHORITATIVE_MAX_TIER = TIER_DEPRECATED_POLICY
