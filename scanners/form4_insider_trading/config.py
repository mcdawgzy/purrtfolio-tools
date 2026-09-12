"""
Configuration for Form 4 Insider Trading Scanner
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"
REFERENCES_DIR = BASE_DIR / "references"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Database — uses the unified purrtfolio.db
DB_PATH = Path("C:/Users/cho_i/purrtfolio.db")

# Watchlist — curated tickers for Form 4 scanning (same universe as short interest)
WATCHLIST_PATH = Path(__file__).resolve().parent / "ticker_watchlist.json"

# SEC Insider Transactions Data Sets
# Updated quarterly; URL pattern:
#   https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{YYYYqQ}_form345.zip
# e.g. https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/2026q2_form345.zip
SEC_BASE = "https://www.sec.gov/files"
SEC_DATASTRUCTURES_BASE = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets"

# User-Agent required by SEC (blocks generic agents)
SEC_USER_AGENT = "Form4Scanner/1.0 (hermes@purrtfolio.local)"

# Form type filter — Form 4 is the primary insider transaction filing
FORM_TYPES = {"4", "4/A"}  # "3" (initial), "4" (changes), "5" (annual) available in data

# SEC publishes new data quarterly (Q1 data ~mid-May, etc.)
# Settlement dates in Q1 file may lag — keep a backdata window
MAX_BACKFILL_QUARTERS = 4  # how far back to backfill on first run

# Transaction code descriptions (from SEC readme, Appendix 6.2)
TRANSACTION_CODES = {
    "A": "Grant, award or other acquisition pursuant to Rule 6b-3(d)",
    "C": "Conversion of derivative security",
    "D": "Disposition to the issuer of issuer equity securities",
    "E": "Expiration of short derivative position",
    "F": "Payment of exercise price or tax liability by delivering/withholding securities",
    "G": "Bona fide gift",
    "H": "Expiration (or cancellation) of long derivative position with value received",
    "I": "Discretionary transaction under Rule 6b-3(f)",
    "J": "Other acquisition or disposition (describe)",
    "L": "Small acquisition under Rule 16a-6",
    "M": "Exercise or conversion of derivative security exempted under Rule 16b-3",
    "O": "Exercise of out-of-the-money derivative security",
    "P": "Open market or private purchase",
    "S": "Open market or private sale",
    "U": "Disposition pursuant to tender of shares in change of control",
    "W": "Acquisition or disposition by will or laws of descent and distribution",
    "X": "Exercise of in-the-money or at-the-money derivative security",
    "Z": "Deposit into or withdrawal from voting trust",
}

# Ownership type
OWNERSHIP_DIRECT = "Direct"
OWNERSHIP_INDIRECT = "Indirect"

# Timeliness codes (Appendix 6.1)
TIMELINESS_CODES = {
    "E": "Early",
    "L": "Late",
    "": "On-time",
}
