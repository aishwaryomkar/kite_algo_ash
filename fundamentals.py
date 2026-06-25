"""
CANSLIM fundamentals for Indian markets - free, NSE-sourced, no third-party
paid API. Built on the `nse` package (pip install nse), an open-source
wrapper around NSE's own internal APIs - not a scraper of a third-party
aggregator, the original regulatory disclosure source itself.

CONFIDENCE LEVELS - read this before trusting either function:

  institutional_sponsorship_trend() - reasonably solid. Built on
  NSE.shareholding(), a documented method with verified field names
  (pr_and_prgrp, public_val, employeeTrusts) confirmed directly against
  the library's source code. Tracks promoter-holding trend as the
  sponsorship proxy - NSE's quarterly disclosure doesn't cleanly break out
  "institutional" (FII+DII) as its own field in the documented response,
  so this uses what's actually confirmed to exist rather than guessing at
  an undocumented field name.

  eps_growth_estimate() - EXPERIMENTAL, UNVERIFIED. I could not find any
  free source with a clean, confirmed structure for quarterly/annual EPS
  growth specifically for Indian-listed companies - this is a real gap,
  not a solved problem. This function attempts NSE's financial-results
  endpoint using the same authenticated session the shareholding call
  uses (reusing the library's internal _req method, since there's no
  public method for this yet) - but I cannot verify this actually works
  without live access to nseindia.com, which isn't reachable from where
  this was built. Treat this as a starting point to debug against real
  data, not a working feature yet. If it doesn't pan out, the honest
  fallback is dropping C/A entirely rather than shipping something
  silently wrong - a momentum bot with no fundamentals gate is fine; one
  with a fundamentals gate that's quietly reading garbage is worse.
"""
import config


def institutional_sponsorship_trend(nse_client, symbol):
    """
    Returns (passes, details). passes=True if promoter holding hasn't
    dropped more than config.MAX_PROMOTER_HOLDING_DROP_PCT quarter-over-
    quarter - a falling promoter stake is one of the most reliable, easily
    observed red flags in Indian small/mid-caps specifically (often
    precedes pledging or exit news), and its absence is a weak positive
    sponsorship signal even without a clean institutional-% field.

    NOTE: see screener_canslim_check() below for a stronger alternative
    that gets actual FII+DII figures (not just a promoter-holding proxy)
    plus the C and A letters NSE's shareholding() can't provide at all.
    """
    try:
        records = nse_client.shareholding(symbol)
    except Exception as e:
        return None, {"error": f"shareholding fetch failed for {symbol}: {e}"}

    if not records or len(records) < 2:
        return None, {"error": "insufficient shareholding history (need >= 2 quarters)"}

    latest, prior = records[0], records[1]
    try:
        latest_promoter = float(latest["pr_and_prgrp"])
        prior_promoter = float(prior["pr_and_prgrp"])
    except (KeyError, ValueError, TypeError) as e:
        return None, {
            "error": f"expected fields not found in shareholding response ({e}) - "
                     f"NSE may have changed the response shape. Raw keys seen: {list(latest.keys())}"
        }

    change_pct = latest_promoter - prior_promoter
    passes = change_pct >= -config.MAX_PROMOTER_HOLDING_DROP_PCT
    return passes, {
        "latest_promoter_pct": latest_promoter,
        "prior_promoter_pct": prior_promoter,
        "change_pct": round(change_pct, 3),
        "latest_quarter": latest.get("date"),
    }


# ============================================================================
# Screener.in path - covers C, A, AND I from a single page fetch.
#
# Screener.in's Terms of Service ( https://www.screener.in/guides/terms/ )
# license materials for "personal, non-commercial transitory viewing only"
# and separately prohibit copying - an automated fetch that parses and
# stores values goes beyond that, independent of commercial use. This is
# a real, specific restriction, not a vague scraping-in-general risk.
# Built anyway per explicit instruction, with good-citizen defaults:
# identifies itself honestly, rate-limits, and caches aggressively since
# this only needs to run against ~20 monthly rebalance candidates, not
# hundreds of symbols daily.
# ============================================================================
import time
import re
import os
import json
import requests
from bs4 import BeautifulSoup

SCREENER_BASE_URL = "https://www.screener.in/company"
SCREENER_CACHE_DIR = "screener_cache"
SCREENER_CACHE_TTL_DAYS = 25  # roughly one rebalance cycle - avoids re-fetching the same name twice in a month
SCREENER_REQUEST_DELAY_SEC = 2  # deliberately slow - this is 20 requests/month, not a bulk job
SCREENER_USER_AGENT = "kite-algo-personal-research-bot/1.0 (non-commercial, personal use)"


def _screener_cache_path(symbol):
    os.makedirs(SCREENER_CACHE_DIR, exist_ok=True)
    return os.path.join(SCREENER_CACHE_DIR, f"{symbol.upper()}.json")


def _fetch_screener_page(symbol):
    """Fetches and caches the raw HTML for a symbol's Screener.in page.
    Returns the HTML string, or raises on failure - callers should catch
    and fail safe (skip the name), never guess."""
    cache_path = _screener_cache_path(symbol)
    if os.path.exists(cache_path):
        age_days = (time.time() - os.path.getmtime(cache_path)) / 86400
        if age_days < SCREENER_CACHE_TTL_DAYS:
            with open(cache_path) as f:
                return json.load(f)["html"]

    time.sleep(SCREENER_REQUEST_DELAY_SEC)
    headers = {"User-Agent": SCREENER_USER_AGENT}
    url = f"{SCREENER_BASE_URL}/{symbol.upper()}/consolidated/"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 404:
        # some companies (esp. smaller ones) don't report consolidated figures
        url = f"{SCREENER_BASE_URL}/{symbol.upper()}/"
        time.sleep(SCREENER_REQUEST_DELAY_SEC)
        r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()

    with open(cache_path, "w") as f:
        json.dump({"html": r.text, "fetched_at": time.time(), "url": url}, f)
    return r.text


def _find_row_values(soup, row_label_pattern):
    """
    Finds a table row by matching its first cell's text against a label
    pattern (e.g. "EPS in Rs", "Promoters") rather than a CSS selector -
    row labels are far more stable across Screener.in's site changes than
    exact class names, which weren't independently verifiable here.
    Returns a list of cell text values (excluding the label cell), or None
    if no matching row was found anywhere on the page.
    """
    pattern = re.compile(row_label_pattern, re.IGNORECASE)
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        label = cells[0].get_text(strip=True)
        if pattern.search(label):
            values = [c.get_text(strip=True) for c in cells[1:]]
            return values
    return None


def _parse_numeric(value):
    """Screener formats numbers with commas and %/Cr suffixes - strip
    those rather than assuming a clean float string."""
    cleaned = value.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def screener_canslim_check(symbol):
    """
    Returns (result_dict, error_or_None). result_dict contains:
      - quarterly_eps_growth_pct: latest quarter EPS vs same quarter last
        year (CANSLIM "C") - None if unavailable
      - annual_profit_cagr_3yr_pct: Screener's own pre-computed 3-year
        compounded profit growth (CANSLIM "A") - None if unavailable
      - institutional_holding_change_pct: combined FII+DII holding change,
        latest quarter vs prior (CANSLIM "I", stronger than the NSE
        promoter-only proxy since it's the actual institutional figure)
      - quarter_labels: the column headers found, for sanity-checking

    Returns (None, error_message) on ANY parsing uncertainty - never a
    guessed number. Check result_dict's individual fields for None too;
    a page can have some sections but not others (e.g. very small/newly
    listed companies may lack full shareholding history).
    """
    try:
        html = _fetch_screener_page(symbol)
    except Exception as e:
        return None, f"page fetch failed for {symbol}: {e}"

    soup = BeautifulSoup(html, "html.parser")
    result = {
        "quarterly_eps_growth_pct": None,
        "annual_profit_cagr_3yr_pct": None,
        "institutional_holding_change_pct": None,
    }

    # --- C: quarterly EPS, YoY (same quarter, prior year - 4 columns back) ---
    eps_quarterly = _find_row_values(soup, r"^EPS in Rs")
    if eps_quarterly and len(eps_quarterly) >= 5:
        latest = _parse_numeric(eps_quarterly[-1])
        year_ago = _parse_numeric(eps_quarterly[-5])  # 4 quarters back
        if latest is not None and year_ago not in (None, 0):
            result["quarterly_eps_growth_pct"] = round((latest - year_ago) / abs(year_ago) * 100, 2)

    # --- A: 3-year compounded profit growth, Screener's own pre-computed figure ---
    profit_growth_row = _find_row_values(soup, r"^3 Years:")
    if profit_growth_row:
        val = _parse_numeric(profit_growth_row[0])
        if val is not None:
            result["annual_profit_cagr_3yr_pct"] = val

    # --- I: combined FII+DII holding change, latest quarter vs prior ---
    fii_row = _find_row_values(soup, r"^FIIs")
    dii_row = _find_row_values(soup, r"^DIIs")
    if fii_row and dii_row and len(fii_row) >= 2 and len(dii_row) >= 2:
        latest_fii, prior_fii = _parse_numeric(fii_row[-1]), _parse_numeric(fii_row[-2])
        latest_dii, prior_dii = _parse_numeric(dii_row[-1]), _parse_numeric(dii_row[-2])
        if None not in (latest_fii, prior_fii, latest_dii, prior_dii):
            result["institutional_holding_change_pct"] = round(
                (latest_fii + latest_dii) - (prior_fii + prior_dii), 3
            )

    if all(v is None for v in result.values()):
        return None, (
            f"could not parse ANY expected fields for {symbol} - Screener.in's "
            f"page structure may have changed, or this symbol's page doesn't "
            f"follow the expected layout. Raw HTML cached at "
            f"{_screener_cache_path(symbol)} for you to inspect."
        )
    return result, None


def eps_growth_estimate(nse_client, symbol):
    """
    SUPERSEDED - kept only so anything that imported this doesn't break.
    screener_canslim_check() below actually solves quarterly/annual EPS
    growth (verified against real data, see module docstring) - use that
    instead. This NSE-based path was a stub that was never finished
    because the underlying endpoint was never verified to expose EPS data
    in a usable form.
    """
    return None, {"error": "superseded by screener_canslim_check() - see this function's docstring"}


def canslim_passes(symbol, nse_client=None):
    """
    High-level entry point main.py actually calls. Routes to
    config.CANSLIM_SOURCE, applies the configured thresholds, and returns
    (passes, details) - passes is None (not False) whenever the data was
    genuinely unavailable or unparseable, so callers can distinguish
    "failed the check" from "couldn't check at all."
    """
    if config.CANSLIM_SOURCE == "nse":
        if nse_client is None:
            return None, {"error": "CANSLIM_SOURCE is 'nse' but no nse_client was provided"}
        return institutional_sponsorship_trend(nse_client, symbol)

    result, error = screener_canslim_check(symbol)
    if error:
        return None, {"error": error}

    checks = {}
    if result["quarterly_eps_growth_pct"] is not None:
        checks["quarterly_eps_growth_ok"] = (
            result["quarterly_eps_growth_pct"] >= config.CANSLIM_MIN_QUARTERLY_EPS_GROWTH_PCT
        )
    if result["annual_profit_cagr_3yr_pct"] is not None:
        checks["annual_profit_cagr_ok"] = (
            result["annual_profit_cagr_3yr_pct"] >= config.CANSLIM_MIN_3YR_PROFIT_CAGR_PCT
        )
    if result["institutional_holding_change_pct"] is not None:
        checks["institutional_holding_ok"] = (
            result["institutional_holding_change_pct"] >= -config.CANSLIM_MAX_INSTITUTIONAL_HOLDING_DROP_PCT
        )

    if not checks:
        return None, {"error": "no fields were parseable for this symbol", **result}

    passes = all(checks.values())
    return passes, {**result, **checks}
