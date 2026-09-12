"""
Form 4 Insider Trading Scanner — Data Ingestion

Downloads and processes SEC Insider Transactions Data Sets
(Forms 3, 4, 5) from the SEC's quarterly ZIP archives.
Data is filtered to the curated watchlist of tickers.
"""
import asyncio
import httpx
import gzip
import shutil
import tempfile
import os
import io
import zipfile
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from .config import (
    DB_PATH, SEC_DATASTRUCTURES_BASE, SEC_USER_AGENT,
    DATA_DIR, WATCHLIST_PATH, TRANSACTION_CODES
)
from .db import get_db, init_insider_schema

logger = logging.getLogger(__name__)


def _load_watchlist() -> set[str]:
    """Load the curated ticker watchlist."""
    from .config import WATCHLIST_PATH
    watchlist_path = Path(WATCHLIST_PATH)
    tickers = set()
    if watchlist_path.exists():
        with open(watchlist_path, encoding="utf-8") as f:
            wl = json.load(f)
        # Handle both list-of-dicts and {"all_tickers": [...]} formats
        if isinstance(wl, list):
            for entry in wl:
                tickers.add(entry["symbol"].upper())
        elif isinstance(wl, dict):
            for t in wl.get("all_tickers", []):
                tickers.add(t.upper())
    return tickers


def _get_latest_available_quarter() -> str:
    """Determine the latest SEC quarter that should have been published.

    SEC publishes Insider Transactions Data Sets quarterly:
      Q1 (ends Mar 31) → published ~mid-May
      Q4 (ends Dec 31) → published ~mid-Feb (next year)

    As of September 2026, Q2 data (published ~mid-Aug) should be available.
    Q3 data won't be published until ~mid-November.
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # Map: which quarter of DATA is likely published by this month
    # Q1 published mid-May (month >= 5), Q2 mid-Aug (month >= 8),
    # Q3 mid-Nov (month >= 11), Q4 mid-Feb (month >= 2)
    if month >= 11:
        return f"{year}Q3"
    elif month >= 8:
        return f"{year}Q2"
    elif month >= 5:
        return f"{year}Q1"
    elif month >= 2:
        return f"{year - 1}Q4"
    else:
        return f"{year - 1}Q3"


def _quarter_url(quarter_str: str) -> list[str]:
    """Build SEC download URLs for a quarter.

    Returns a list of URLs to try (primary first).
    Format: 2026Q2 → https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/2026q2_form345.zip
    """
    parts = quarter_str.split("Q")
    year, q = parts[0], parts[1]
    lower = f"{year.lower()}q{q}_form345.zip"

    return [
        f"{SEC_DATASTRUCTURES_BASE}/{lower}",
        f"https://www.sec.gov/files/datastandardsinnovation/data/insider-transactions-data-sets/{lower}",
        f"https://www.sec.gov/files/insider-transactions-data-sets/{lower}",
    ]


def _download_quarter_zip(quarter_str: str, download_dir: Path) -> Optional[Path]:
    """Download a quarter's ZIP from SEC."""
    urls_to_try = _quarter_url(quarter_str)

    for url in urls_to_try:
        fname = url.split("/")[-1]
        out_path = download_dir / fname
        if out_path.exists():
            logger.info(f"  Already downloaded: {out_path.name}")
            return out_path

        logger.info(f"  Downloading {fname} from {url}...")
        try:
            # Use httpx with SEC-compliant user agent
            import time
            time.sleep(0.1)  # be polite
            # Try with requests first (simpler for this)
            import requests
            resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=120)
            resp.raise_for_status()

            out_path.write_bytes(resp.content)
            logger.info(f"  Downloaded {out_path.stat().st_size / 1e6:.1f} MB")
            return out_path
        except Exception as e:
            logger.warning(f"  Failed ({url}): {e}")
            continue

    logger.warning(f"  Could not download {quarter_str} from any URL")
    return None


def _parse_tsv(content: str) -> list[dict]:
    """Parse tab-delimited SEC data file into list of dicts."""
    lines = content.strip().split("\n")
    if not lines:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(headers):
            continue  # skip malformed lines
        rows.append(dict(zip(headers, parts)))
    return rows


def _parse_date(date_str: str | None) -> str | None:
    """SEC dates are DD-MON-YYYY (e.g. '15-MAR-2024'). Convert to YYYY-MM-DD."""
    if not date_str or date_str.strip() == "":
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%d-%b-%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        # Some dates may already be ISO
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    return None


def _safe_float(val: str | None) -> float | None:
    if val is None or val.strip() == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _safe_int(val: str | None) -> int | None:
    if val is None or val.strip() == "":
        return None
    try:
        return int(val)
    except ValueError:
        try:
            return int(float(val))
        except ValueError:
            return None


def _compute_transaction_value(shares: float | None, price: float | None) -> int | None:
    """Compute transaction value USD = shares * price_per_share."""
    if shares is None or price is None:
        return None
    try:
        return int(round(shares * price))
    except (TypeError, ValueError):
        return None


def ingest_quarter(quarter_str: str, download_dir: Optional[Path] = None) -> dict:
    """Download and ingest a single quarter of SEC insider transaction data.

    Returns: {quarter, status, total_submissions, watchlist_submissions, new_rows, updated_rows}
    """
    import time
    download_dir = download_dir or DATA_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    # Log start
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO ingestion_log_insider (quarter, total_submissions, watchlist_submissions,
                                               new_rows, updated_rows, status)
            VALUES (?, 0, 0, 0, 0, 'started')
        """, (quarter_str,))
        log_id = c.lastrowid
        conn.commit()

    # Download ZIP
    zip_path = _download_quarter_zip(quarter_str, download_dir)
    if not zip_path:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE ingestion_log_insider SET status = 'download_failed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (log_id,))
            conn.commit()
        return {"quarter": quarter_str, "status": "download_failed"}

    watchlist = _load_watchlist()
    # SEC ticker symbols may differ from our watchlist; normalize
    watchlist_upper = {t.upper() for t in watchlist}

    # Extract and parse all 8 TSV files
    logger.info(f"  Extracting {zip_path.name}...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            logger.info(f"  Files in ZIP: {names}")

            # Each file is gzipped TSV
            def read_tsv(name: str) -> list[dict]:
                try:
                    raw = zf.read(name)
                    # Try gzip first, then plain
                    try:
                        raw = gzip.decompress(raw)
                    except Exception:
                        pass
                    return _parse_tsv(raw.decode("utf-8"))
                except KeyError:
                    logger.warning(f"  {name} not found in ZIP")
                    return []

            # Note: SEC filenames vary; we try multiple patterns
            def read_tsv_flexible(prefix: str) -> list[dict]:
                """Try reading a TSV by common filename patterns."""
                candidates = [
                    f"{prefix}.tsv",
                    f"{prefix}.txt",
                    f"{prefix}.tsv.gz",
                    f"{prefix}.txt.gz",
                ]
                for fname in candidates:
                    try:
                        raw = zf.read(fname)
                        try:
                            raw = gzip.decompress(raw)
                        except Exception:
                            pass
                        return _parse_tsv(raw.decode("utf-8"))
                    except KeyError:
                        continue
                # Fallback: search by prefix
                for member in names:
                    if member.lower().startswith(prefix.lower()) and (member.endswith(".tsv") or member.endswith(".txt")):
                        try:
                            raw = zf.read(member)
                            try:
                                raw = gzip.decompress(raw)
                            except Exception:
                                pass
                            return _parse_tsv(raw.decode("utf-8"))
                        except Exception:
                            continue
                logger.warning(f"  Could not find {prefix} in ZIP (members: {names})")
                return []

            submissions = read_tsv_flexible("SUBMISSION")
            owners = read_tsv_flexible("REPORTINGOWNER")
            nonderiv_trans = read_tsv_flexible("NONDERIV_TRANS")
            nonderiv_holding = read_tsv_flexible("NONDERIV_HOLDING")
            deriv_trans = read_tsv_flexible("DERIV_TRANS")
            deriv_holding = read_tsv_flexible("DERIV_HOLDING")
            footnotes = read_tsv_flexible("FOOTNOTES")
            signatures = read_tsv_flexible("OWNER_SIGNATURE")

    except Exception as e:
        logger.error(f"  Error extracting ZIP: {e}")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE ingestion_log_insider SET status = 'extract_failed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (log_id,))
            conn.commit()
        return {"quarter": quarter_str, "status": "extract_failed", "error": str(e)}

    logger.info(f"  Parsed: {len(submissions)} submissions, {len(owners)} owners, "
                f"{len(nonderiv_trans)} transactions, {len(deriv_trans)} deriv trans")

    # --- Filter to watchlist tickers ---
    # Match by ISSUERTRADINGSYMBOL (the ticker column in SUBMISSION)
    watchlist_submissions = [
        s for s in submissions
        if s.get("ISSUERTRADINGSYMBOL", "").upper().strip() in watchlist_upper
    ]
    logger.info(f"  Watchlist submissions (Form 4/3/5): {len(watchlist_submissions)} of {len(submissions)}")

    # Track stats
    new_submissions = 0
    updated_submissions = 0

    with get_db() as conn:
        c = conn.cursor()

        # Ensure schema
        # (tables already created, just ensure)

        for s in watchlist_submissions:
            accession = s.get("ACCESSION_NUMBER", "").strip()
            if not accession:
                continue

            ticker = s.get("ISSUERTRADINGSYMBOL", "").strip()
            issuer_cik = s.get("ISSUERCIK", "").strip()
            doc_type = s.get("DOCUMENT_TYPE", "").strip()

            # Check if exists
            existing = c.execute(
                "SELECT 1 FROM insider_submissions WHERE accession_number = ?",
                (accession,)
            ).fetchone()

            filing_date = _parse_date(s.get("FILING_DATE"))
            period_date = _parse_date(s.get("PERIOD_OF_REPORT"))
            orig_date = _parse_date(s.get("DATE_OF_ORIG_SUB"))

            sub_data = (
                accession,
                filing_date,
                period_date,
                orig_date,
                s.get("NO_SECURITIES_OWNED"),
                s.get("NOT_SUBJECT_SEC16"),
                s.get("FORM3_HOLDING_REPORTED"),
                s.get("FORM4_TRANS_REPORTED"),
                doc_type,
                issuer_cik,
                s.get("ISSUERNAME", "").strip(),
                ticker,
                s.get("REMARKS"),
                quarter_str,
            )

            if existing:
                c.execute("""
                    UPDATE insider_submissions SET
                        filing_date = ?, period_of_report = ?, date_of_orig_sub = ?,
                        no_securities_owned = ?, not_subject_sec16 = ?,
                        form3_holding_reported = ?, form4_trans_reported = ?,
                        document_type = ?, issuercik = ?, issuername = ?,
                        issuertradingsymbol = ?, remarks = ?, quarter = ?
                    WHERE accession_number = ?
                """, (*sub_data[1:], accession))
                updated_submissions += 1
            else:
                c.execute("""
                    INSERT OR REPLACE INTO insider_submissions
                        (accession_number, filing_date, period_of_report, date_of_orig_sub,
                         no_securities_owned, not_subject_sec16, form3_holding_reported,
                         form4_trans_reported, document_type, issuercik, issuername,
                         issuertradingsymbol, remarks, quarter)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, sub_data)
                new_submissions += 1

            # --- Reporting Owners ---
            for o in owners:
                if o.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                owner_cik = o.get("RPTOWNERCIK", "").strip()
                if not owner_cik:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_owners
                        (accession_number, rptownercik, rptownername,
                         rptowner_relationship, rptowner_title, rptowner_txt,
                         rptowner_street1, rptowner_street2, rptowner_city,
                         rptowner_state, rptowner_zipcode, rptowner_state_desc, file_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    accession, owner_cik,
                    o.get("RPTOWNERNAME", "").strip(),
                    o.get("RPTOWNER_RELATIONSHIP", "").strip(),
                    o.get("RPTOWNERTITLE", "").strip(),
                    o.get("RPTOWNER_TXT", "").strip(),
                    o.get("RPTOWNER_STREET1", "").strip(),
                    o.get("RPTOWNER_STREET2", "").strip(),
                    o.get("RPTOWNER_CITY", "").strip(),
                    o.get("RPTOWNER_STATE", "").strip(),
                    o.get("RPTOWNER_ZIPCODE", "").strip(),
                    o.get("RPTOWNER_STATE_DESC", "").strip(),
                    o.get("FILE_NUMBER", "").strip(),
                ))

            # --- Non-Derivative Transactions ---
            for t in nonderiv_trans:
                if t.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                trans_sk = t.get("NONDERIV_TRANS_SK", "").strip()
                if not trans_sk:
                    continue

                shares = _safe_float(t.get("TRANS_SHARES"))
                price = _safe_float(t.get("TRANS_PRICEPERSHARE"))
                trans_value = _compute_transaction_value(shares, price)

                c.execute("""
                    INSERT OR REPLACE INTO insider_transactions
                        (accession_number, nonderiv_trans_sk, security_title, security_title_fn,
                         trans_date, trans_date_fn, deemed_execution_date, deemed_execution_date_fn,
                         trans_form_type, trans_code, equity_swap_involved, trans_timeliness,
                         trans_timeliness_fn, trans_shares, trans_shares_fn,
                         trans_pricepershare, trans_pricepershare_fn,
                         trans_acquired_disp_cd, trans_acquired_disp_cd_fn,
                         shrs_ownfollowingtrans, shrs_ownfollowingtrans_fn,
                         val_ownfollowingtrans, val_ownfollowingtrans_fn,
                         direct_indirect_ownership, direct_indirect_ownership_fn,
                         nature_of_ownership, nature_of_ownership_fn,
                         transaction_value_usd)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    accession, trans_sk,
                    t.get("SECURITY_TITLE", "").strip(),
                    t.get("SECURITY_TITLE_FN", "").strip(),
                    _parse_date(t.get("TRANS_DATE")),
                    t.get("TRANS_DATE_FN", "").strip() or None,
                    _parse_date(t.get("DEEMED_EXECUTION_DATE")),
                    t.get("DEEMED_EXECUTION_DATE_FN", "").strip() or None,
                    t.get("TRANS_FORM_TYPE", "").strip() or None,
                    t.get("TRANS_CODE", "").strip() or None,
                    t.get("EQUITY_SWAP_INVOLVED", "").strip() or None,
                    t.get("TRANS_TIMELINESS", "").strip() or None,
                    t.get("TRANS_TIMELINESS_FN", "").strip() or None,
                    shares,
                    t.get("TRANS_SHARES_FN", "").strip() or None,
                    price,
                    t.get("TRANS_PRICEPERSHARE_FN", "").strip() or None,
                    t.get("TRANS_ACQUIRED_DISP_CD", "").strip() or None,
                    t.get("TRANS_ACQUIRED_DISP_CD_FN", "").strip() or None,
                    _safe_float(t.get("SHRS_OWNFOLLOWINGTRANS")),
                    t.get("SHRS_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    _safe_float(t.get("VAL_OWNFOLLOWINGTRANS")),
                    t.get("VAL_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    t.get("DIRECT_INDIRECT_OWNERSHIP", "").strip(),
                    t.get("DIRECT_INDIRECT_OWNERSHIP_FN", "").strip() or None,
                    t.get("NATURE_OF_OWNERSHIP", "").strip() or None,
                    t.get("NATURE_OF_OWNERSHIP_FN", "").strip() or None,
                    trans_value,
                ))

            # --- Non-Derivative Holdings ---
            for h in nonderiv_holding:
                if h.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                holding_sk = h.get("NONDERIV_HOLDING_SK", "").strip()
                if not holding_sk:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_holdings
                        (accession_number, nonderiv_holding_sk, security_title, security_title_fn,
                         trans_form_type, trans_form_type_fn,
                         shrs_ownfollowingtrans, shrs_ownfollowingtrans_fn,
                         val_ownfollowingtrans, val_ownfollowingtrans_fn,
                         direct_indirect_ownership, direct_indirect_ownership_fn,
                         nature_of_ownership, nature_of_ownership_fn)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    accession, holding_sk,
                    h.get("SECURITY_TITLE", "").strip(),
                    h.get("SECURITY_TITLE_FN", "").strip() or None,
                    h.get("TRANS_FORM_TYPE", "").strip() or None,
                    h.get("TRANS_FORM_TYPE_FN", "").strip() or None,
                    _safe_float(h.get("SHRS_OWNFOLLOWINGTRANS")),
                    h.get("SHRS_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    _safe_float(h.get("VAL_OWNFOLLOWINGTRANS")),
                    h.get("VAL_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    h.get("DIRECT_INDIRECT_OWNERSHIP", "").strip(),
                    h.get("DIRECT_INDIRECT_OWNERSHIP_FN", "").strip() or None,
                    h.get("NATURE_OF_OWNERSHIP", "").strip() or None,
                    h.get("NATURE_OF_OWNERSHIP_FN", "").strip() or None,
                ))

            # --- Derivative Transactions ---
            for dt in deriv_trans:
                if dt.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                deriv_sk = dt.get("DERIV_TRANS_SK", "").strip()
                if not deriv_sk:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_deriv_trans
                        (accession_number, deriv_trans_sk, security_title, security_title_fn,
                         conv_exercise_price, conv_exercise_price_fn,
                         trans_date, trans_date_fn, deemed_execution_date, deemed_execution_date_fn,
                         trans_form_type, trans_code, equity_swap_involved,
                         trans_timeliness, trans_timeliness_fn,
                         trans_shares, trans_shares_fn, trans_total_value, trans_total_value_fn,
                         trans_pricepershare, trans_pricepershare_fn,
                         trans_acquired_disp_cd, trans_acquired_disp_cd_fn,
                         shrs_ownfollowingtrans, shrs_ownfollowingtrans_fn,
                         val_ownfollowingtrans, val_ownfollowingtrans_fn,
                         direct_indirect_ownership, direct_indirect_ownership_fn,
                         nature_of_ownership, nature_of_ownership_fn,
                         underlying_sec_title, underlying_sec_title_fn,
                         underlying_sec_shares, underlying_sec_shares_fn,
                         underlying_sec_value, underlying_sec_value_fn,
                         exercise_date, exercise_date_fn,
                         expiration_date, expiration_date_fn)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    accession, deriv_sk,
                    dt.get("SECURITY_TITLE", "").strip(),
                    dt.get("SECURITY_TITLE_FN", "").strip() or None,
                    _safe_float(dt.get("CONV_EXERCISE_PRICE")),
                    dt.get("CONV_EXERCISE_PRICE_FN", "").strip() or None,
                    _parse_date(dt.get("TRANS_DATE")),
                    dt.get("TRANS_DATE_FN", "").strip() or None,
                    _parse_date(dt.get("DEEMED_EXECUTION_DATE")),
                    dt.get("DEEMED_EXECUTION_DATE_FN", "").strip() or None,
                    dt.get("TRANS_FORM_TYPE", "").strip() or None,
                    dt.get("TRANS_CODE", "").strip() or None,
                    dt.get("EQUITY_SWAP_INVOLVED", "").strip() or None,
                    dt.get("TRANS_TIMELINESS", "").strip() or None,
                    dt.get("TRANS_TIMELINESS_FN", "").strip() or None,
                    _safe_float(dt.get("TRANS_SHARES")),
                    dt.get("TRANS_SHARES_FN", "").strip() or None,
                    _safe_float(dt.get("TRANS_TOTAL_VALUE")),
                    dt.get("TRANS_TOTAL_VALUE_FN", "").strip() or None,
                    _safe_float(dt.get("TRANS_PRICEPERSHARE")),
                    dt.get("TRANS_PRICEPERSHARE_FN", "").strip() or None,
                    dt.get("TRANS_ACQUIRED_DISP_CD", "").strip() or None,
                    dt.get("TRANS_ACQUIRED_DISP_CD_FN", "").strip() or None,
                    _safe_float(dt.get("SHRS_OWNFOLLOWINGTRANS")),
                    dt.get("SHRS_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    _safe_float(dt.get("VAL_OWNFOLLOWINGTRANS")),
                    dt.get("VAL_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    dt.get("DIRECT_INDIRECT_OWNERSHIP", "").strip(),
                    dt.get("DIRECT_INDIRECT_OWNERSHIP_FN", "").strip() or None,
                    dt.get("NATURE_OF_OWNERSHIP", "").strip() or None,
                    dt.get("NATURE_OF_OWNERSHIP_FN", "").strip() or None,
                    dt.get("UNDERLYING_SEC_TITLE", "").strip() or None,
                    dt.get("UNDERLYING_SEC_TITLE_FN", "").strip() or None,
                    _safe_float(dt.get("UNDERLYING_SEC_SHARES")),
                    dt.get("UNDERLYING_SEC_SHARES_FN", "").strip() or None,
                    _safe_float(dt.get("UNDERLYING_SEC_VALUE")),
                    dt.get("UNDERLYING_SEC_VALUE_FN", "").strip() or None,
                    _parse_date(dt.get("EXERCISE_DATE")),
                    dt.get("EXERCISE_DATE_FN", "").strip() or None,
                    _parse_date(dt.get("EXPIRATION_DATE")),
                    dt.get("EXPIRATION_DATE_FN", "").strip() or None,
                ))

            # --- Derivative Holdings ---
            for dh in deriv_holding:
                if dh.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                deriv_hsk = dh.get("DERIV_HOLDING_SK", "").strip()
                if not deriv_hsk:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_deriv_holdings
                        (accession_number, deriv_holding_sk, security_title, security_title_fn,
                         conv_exercise_price, conv_exercise_price_fn,
                         trans_form_type, trans_form_type_fn,
                         exercise_date, exercise_date_fn,
                         expiration_date, expiration_date_fn,
                         underlying_sec_title, underlying_sec_title_fn,
                         underlying_sec_shares, underlying_sec_shares_fn,
                         underlying_sec_value, underlying_sec_value_fn,
                         shrs_ownfollowingtrans, shrs_ownfollowingtrans_fn,
                         val_ownfollowingtrans, val_ownfollowingtrans_fn,
                         direct_indirect_ownership, direct_indirect_ownership_fn,
                         nature_of_ownership, nature_of_ownership_fn)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    accession, deriv_hsk,
                    dh.get("SECURITY_TITLE", "").strip(),
                    dh.get("SECURITY_TITLE_FN", "").strip() or None,
                    _safe_float(dh.get("CONV_EXERCISE_PRICE")),
                    dh.get("CONV_EXERCISE_PRICE_FN", "").strip() or None,
                    dh.get("TRANS_FORM_TYPE", "").strip() or None,
                    dh.get("TRANS_FORM_TYPE_FN", "").strip() or None,
                    _parse_date(dh.get("EXERCISE_DATE")),
                    dh.get("EXERCISE_DATE_FN", "").strip() or None,
                    _parse_date(dh.get("EXPIRATION_DATE")),
                    dh.get("EXPIRATION_DATE_FN", "").strip() or None,
                    dh.get("UNDERLYING_SEC_TITLE", "").strip() or None,
                    dh.get("UNDERLYING_SEC_TITLE_FN", "").strip() or None,
                    _safe_float(dh.get("UNDERLYING_SEC_SHARES")),
                    dh.get("UNDERLYING_SEC_SHARES_FN", "").strip() or None,
                    _safe_float(dh.get("UNDERLYING_SEC_VALUE")),
                    dh.get("UNDERLYING_SEC_VALUE_FN", "").strip() or None,
                    _safe_float(dh.get("SHRS_OWNFOLLOWINGTRANS")),
                    dh.get("SHRS_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    _safe_float(dh.get("VAL_OWNFOLLOWINGTRANS")),
                    dh.get("VAL_OWNFOLLOWINGTRANS_FN", "").strip() or None,
                    dh.get("DIRECT_INDIRECT_OWNERSHIP", "").strip(),
                    dh.get("DIRECT_INDIRECT_OWNERSHIP_FN", "").strip() or None,
                    dh.get("NATURE_OF_OWNERSHIP", "").strip() or None,
                    dh.get("NATURE_OF_OWNERSHIP_FN", "").strip() or None,
                ))

            # --- Footnotes ---
            for fn in footnotes:
                if fn.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                fn_id = fn.get("FOOTNOTE_ID", "").strip()
                if not fn_id:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_footnotes (accession_number, footnote_id, footnote_text)
                    VALUES (?, ?, ?)
                """, (
                    accession, fn_id,
                    fn.get("FOOTNOTE_TXT", "").strip() or "",
                ))

            # --- Signatures ---
            for sig in signatures:
                if sig.get("ACCESSION_NUMBER", "").strip() != accession:
                    continue
                sig_name = sig.get("OWNERSIGNATURENAME", "").strip()
                if not sig_name:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO insider_signatures (accession_number, ownersignaturename, ownersignaturedate)
                    VALUES (?, ?, ?)
                """, (
                    accession, sig_name,
                    _parse_date(sig.get("OWNERSIGNATUREDATE")),
                ))

        conn.commit()

    # Update log
    new_tx = new_submissions + updated_submissions
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE ingestion_log_insider
            SET total_submissions = ?, watchlist_submissions = ?,
                new_rows = ?, updated_rows = ?, status = 'completed', completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (len(submissions), len(watchlist_submissions), new_submissions, updated_submissions, log_id))
        conn.commit()

    result = {
        "quarter": quarter_str,
        "status": "completed",
        "total_submissions": len(submissions),
        "watchlist_submissions": len(watchlist_submissions),
        "new_rows": new_submissions,
        "updated_rows": updated_submissions,
    }
    logger.info(f"  Done: {result}")
    return result


def backfill_quarters(start_quarter: str, end_quarter: str) -> list[dict]:
    """Backfill multiple quarters.

    Args:
        start_quarter: e.g. "2024Q1"
        end_quarter: e.g. "2026Q2"
    """
    results = []
    year_q = start_quarter.split("Q")
    start_y, start_q = int(year_q[0]), int(year_q[1])
    year_q = end_quarter.split("Q")
    end_y, end_q = int(year_q[0]), int(year_q[1])

    quarters = []
    y, q = start_y, start_q
    while (y < end_y) or (y == end_y and q <= end_q):
        quarters.append(f"{y}Q{q}")
        q += 1
        if q > 4:
            q = 1
            y += 1

    for q_str in quarters:
        logger.info(f"Ingesting {q_str}...")
        result = ingest_quarter(q_str)
        results.append(result)

    return results


def ingest_latest_quarter() -> dict:
    """Ingest the latest available SEC Insider Transactions Data Set.

    Checks for new quarterly data, downloads it, and ingests for the
    curated watchlist. Returns a summary dict.

    This is the main cron entry point.
    """
    from .db import sync_watchlist, get_ingestion_log_last, log_ingestion

    tickers_ingested = []
    new_count = 0
    updated_count = 0

    # 1. Ensure watchlist tickers are in the DB
    sync_watchlist()

    # 2. Determine latest available quarter
    latest_q = _get_latest_available_quarter()

    # 3. Check if already ingested
    last_log = get_ingestion_log_last()
    if last_log and last_log.get("quarter") == latest_q:
        logger.info(f"Quarter {latest_q} already ingested, skipping.")
        return {
            "status": "no_new_data",
            "quarter": latest_q,
            "tickers_ingested": [],
            "new_count": 0,
            "updated_count": 0,
            "ticker_results": [],
        }

    # 4. Ingest
    result = ingest_quarter(latest_q)
    tickers_ingested = result.get("tickers_ingested", [])
    new_count = result.get("new_rows", 0)
    updated_count = result.get("updated_rows", 0)
    ticker_results = result.get("ticker_results", [])

    # 5. Log
    log_ingestion(
        quarter=latest_q,
        record_count=new_count + updated_count,
        new_count=new_count,
        updated_count=updated_count,
        status="completed" if new_count > 0 else "no_new_data",
    )

    return {
        "status": "completed" if new_count > 0 else "no_new_data",
        "quarter": latest_q,
        "tickers_ingested": tickers_ingested,
        "new_count": new_count,
        "updated_count": updated_count,
        "ticker_results": ticker_results,
    }
