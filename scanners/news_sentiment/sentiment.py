"""
Sentiment analysis for financial news headlines.

Combines:
  1. VADER (NLTK) — general-purpose sentiment, good at negation/punctuation
  2. Financial lexicon overlay — domain-specific bullish/bearish words

VADER alone misses financial verbs ("surges", "rally", "misses", "raises target")
and overweights generic words ("fears", "concerns").  The financial lexicon
patches those gaps.  Final score = 0.35 * VADER + 0.65 * financial_lexicon,
but only when financial keywords are present; otherwise VADER alone.
"""
import re
from typing import Optional

# Lazily initialized VADER analyzer (vader_lexicon downloaded on first use)
_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        try:
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            _analyzer = SentimentIntensityAnalyzer()
        except Exception:
            _analyzer = False  # sentinel: tried and failed
    return _analyzer if _analyzer is not False else None


# ── Financial sentiment lexicon ──────────────────────────────────────
# word → sentiment weight (-1.0 extremely bearish … +1.0 extremely bullish)
# Curated for financial news headlines.
# Note: "cut/cuts" is intentionally excluded from single words — it's
# context-dependent (dividend cut = bearish, rate cut = bullish).
# Use the _FINANCIAL_PHRASES table for those.
_FINANCIAL_LEXICON = {
    # ── Bullish ──
    "surged": 0.8, "surges": 0.8, "surging": 0.8, "surge": 0.8,
    "rallied": 0.7, "rallies": 0.7, "rallying": 0.7, "rally": 0.7,
    "soared": 0.8, "soars": 0.8, "soaring": 0.8, "soar": 0.8,
    "jumped": 0.6, "jumps": 0.6, "jumping": 0.6, "jump": 0.6,
    "gained": 0.5, "gains": 0.5, "gaining": 0.5, "gain": 0.5,
    "climbed": 0.5, "climbs": 0.5, "climbing": 0.5, "climb": 0.5,
    "rose": 0.5, "roses": 0.5, "rising": 0.5, "rise": 0.5,
    "beat": 0.6, "beats": 0.6, "beaten": 0.6,
    "exceeded": 0.6, "exceeds": 0.6, "exceed": 0.6,
    "topped": 0.5, "surpassed": 0.6, "outpaced": 0.6,
    "raised": 0.5, "raises": 0.5, "raising": 0.5,
    "lifted": 0.5, "lifts": 0.5, "lifting": 0.5,
    "upgraded": 0.6, "upgrades": 0.6, "upgrading": 0.6, "upgrade": 0.6,
    "outperformed": 0.6, "outperform": 0.6, "outperforms": 0.6,
    "optimistic": 0.5, "optimism": 0.5, "optimistically": 0.5,
    "bullish": 0.6, "bullishness": 0.6,
    "strong": 0.4, "strongly": 0.4, "strengthened": 0.5, "strengthening": 0.5,
    "robust": 0.5, "resilient": 0.5, "resilience": 0.5,
    "solid": 0.4, "solidly": 0.4,
    "rebounded": 0.7, "rebounds": 0.7, "rebounding": 0.7, "rebound": 0.7,
    "recovered": 0.5, "recovers": 0.5, "recovering": 0.5, "recovery": 0.4,
    "growth": 0.4, "grew": 0.4, "growing": 0.4,
    "expansion": 0.4, "expanding": 0.4, "expanded": 0.4,
    "accelerating": 0.5, "momentum": 0.4,
    "upsized": 0.5, "increased": 0.3, "boosted": 0.5,
    "confidence": 0.3, "confident": 0.4,
    "profit": 0.3, "profitable": 0.3,
    "dividend": 0.2,
    "buyback": 0.4,
    "approval": 0.5, "approved": 0.5,
    "breakthrough": 0.6,
    "landmark": 0.4, "landed": 0.4,
    "success": 0.4, "successfully": 0.4,
    "progress": 0.3, "progressing": 0.3,
    "innovation": 0.3, "innovative": 0.3,
    "leadership": 0.3,
    "partnership": 0.2, "partnered": 0.3,
    "secured": 0.3,
    "contract": 0.2, "contracts": 0.2,
    "upside": 0.3,
    "healthy": 0.3, "healthier": 0.4,
    "thriving": 0.5, "prosper": 0.5,
    "defensive": 0.2,
    "overweight": 0.3,

    # ── Bearish ──
    "plunged": -0.8, "plunges": -0.8, "plunging": -0.8, "plunge": -0.8,
    "tumbled": -0.7, "tumbles": -0.7, "tumbling": -0.7, "tumble": -0.7,
    "slid": -0.5, "slides": -0.5, "sliding": -0.5, "slide": -0.5,
    "slumped": -0.6, "slumps": -0.6, "slumping": -0.6, "slump": -0.6,
    "dropped": -0.5, "drops": -0.5, "dropping": -0.5, "drop": -0.5,
    "dived": -0.6, "dives": -0.6, "diving": -0.6, "dive": -0.6,
    "fell": -0.4, "falls": -0.4, "falling": -0.4, "fall": -0.4,
    "missed": -0.6, "misses": -0.6, "missing": -0.6,
    "warning": -0.4, "warned": -0.4, "warn": -0.4,
    "lowered": -0.5, "lowers": -0.5, "lowering": -0.5,
    "downgraded": -0.6, "downgrades": -0.6, "downgrading": -0.6, "downgrade": -0.6,
    "underperform": -0.6, "underperforms": -0.6, "underperformed": -0.6,
    "loss": -0.4, "losses": -0.5, "loss-making": -0.4,
    "decline": -0.4, "declined": -0.4, "declining": -0.4, "declines": -0.4,
    "shrunk": -0.4, "shrinking": -0.4, "shrinks": -0.4,
    "contraction": -0.5, "contracted": -0.5, "contracting": -0.5,
    "shortfall": -0.5,
    "disappointment": -0.5, "disappointed": -0.5, "disappoints": -0.5, "disappointing": -0.5,
    "bearish": -0.4, "bearishness": -0.4,
    "pessimistic": -0.4, "pessimism": -0.4,
    "weak": -0.3, "weakness": -0.4, "weakly": -0.3,
    "fragile": -0.4, "vulnerable": -0.3,
    "concern": -0.2, "concerns": -0.2, "concerning": -0.2,
    "fear": -0.3, "fears": -0.3,
    "caution": -0.2, "cautious": -0.2,
    "selloff": -0.6, "sell-off": -0.6, "selling": -0.3,
    "dumped": -0.6, "dumping": -0.6, "dumps": -0.6, "dump": -0.5,
    "delisting": -0.7, "delisted": -0.7,
    "bankruptcy": -0.8, "bankrupt": -0.8, "bankrupting": -0.8,
    "investigation": -0.3, "investigated": -0.4, "investigating": -0.4,
    "probe": -0.3, "probed": -0.3, "prosecutor": -0.3,
    "charges": -0.5, "charged": -0.5, "fraud": -0.7, "fraudulent": -0.6,
    "layoffs": -0.5, "layoff": -0.5, "laying off": -0.5,
    "mass layoffs": -0.7,
    "recession": -0.6, "recessionary": -0.5,
    "hotter": -0.3,  # hotter-than-expected inflation (bearish)
    "shortage": -0.3, "shortages": -0.3, "supply crunch": -0.4,
    "delay": -0.2, "delayed": -0.3, "delays": -0.2, "delaying": -0.3,
    "disaster": -0.7, "disastrous": -0.6,
    "writedown": -0.6, "write-down": -0.6, "writedowns": -0.6,
    "impairment": -0.5,
    "default": -0.5, "defaulted": -0.5,
    "outflow": -0.3, "outflows": -0.3,
    "redemption": -0.3, "redemptions": -0.3,
    "withdrawal": -0.3, "withdrawals": -0.3,
    "liquidation": -0.6, "liquidated": -0.6,
    "margin call": -0.7,
    "hedge fund closure": -0.6,
    "ceased operations": -0.7, "cease operations": -0.7,
    "going concern": -0.5,
    "material weakness": -0.5,
    "sanction": -0.4, "sanctioned": -0.5, "sanctions": -0.4,
    "clawback": -0.4,
    "spook": -0.3, "spooked": -0.4, "spooking": -0.3, "spooks": -0.3,
    "underweight": -0.3,

    # ── Neutral financial terms (weight 0 — excluded from lexicon, but
    #    used for phrase context) ──
}
# Note: neutral terms like "expected", "forecast", "target", "estimate"
# are intentionally NOT in the lexicon.  VADER handles them as neutral,
# and including them would dilute the financial signal.

# Multi-word financial phrases (checked before single words).
# Phrases take priority: if a phrase matches, its component words
# are excluded from single-word matching to avoid double-counting.
_FINANCIAL_PHRASES = {
    "beats earnings": 0.7,
    "beats estimates": 0.7,
    "beats expectations": 0.7,
    "beats on the top line": 0.6,
    "misses earnings": -0.7,
    "misses estimates": -0.6,
    "misses expectations": -0.6,
    "missed earnings": -0.6,
    "missed estimates": -0.6,
    "earnings beat": 0.7,
    "earnings miss": -0.6,
    "profit beat": 0.6,
    "beat profit": 0.6,
    "record profit": 0.5,
    "record revenue": 0.5,
    "record high": 0.7,
    "all-time high": 0.7,
    "all time high": 0.7,
    "record low": -0.5,
    "new low": -0.4,
    "all-time low": -0.6,
    "all time low": -0.5,
    "rate hike": -0.3,
    "rate hikes": -0.3,
    "rate cut": 0.4,
    "rate cuts": 0.4,
    "rate increase": -0.3,
    "rate decrease": 0.3,
    "federal reserve pause": 0.2,
    "paused rate hikes": 0.3,
    "pause on rate hikes": 0.4,
    "fed pause": 0.3,
    "dividend increase": 0.5,
    "dividend hike": 0.5,
    "dividend cut": -0.7,
    "dividend slashed": -0.7,
    "cuts guidance": -0.7,
    "cut guidance": -0.6,
    "slashes guidance": -0.8,
    "slashed guidance": -0.8,
    "reduces guidance": -0.6,
    "reduced guidance": -0.6,
    "raises guidance": 0.7,
    "raised guidance": 0.7,
    "share buyback": 0.5,
    "stock buyback": 0.4,
    "outperform expectations": 0.7,
    "underperforms expectations": -0.6,
    "strong quarter": 0.6,
    "strong earnings": 0.6,
    "strong demand": 0.5,
    "slower demand": -0.4,
    "demand slowdown": -0.4,
    "credit losses": -0.5,
    "credit tightening": -0.4,
    "bear market": -0.8,
    "bull market": 0.8,
    "market correction": -0.3,
    "market rally": 0.5,
    "steeper yield curve": -0.2,
    "flattening yield curve": -0.2,
    "inverted yield curve": -0.6,
    "supply fears": -0.3,
    "supply disruption": -0.4,
    "supply crunch": -0.4,
}


def _financial_score(text: str) -> Optional[float]:
    """Score *text* using the financial lexicon.

    Returns the mean of all matched keyword/phrase weights (range –1..+1),
    or *None* when no financial keywords are matched.

    Phrases are checked longest-first so that "pause on rate hikes" consumes
    the phrase before "rate hikes" or "rate hike" can match the same span.
    Matched phrase text is removed from the remaining string to prevent
    overlapping phrase matches and double-counting of component words.
    """
    lower = text.lower()
    scores = []
    remaining = lower  # progressively reduced as phrases match

    # Sort phrases by length (longest first) to prevent substring overlap
    sorted_phrases = sorted(
        _FINANCIAL_PHRASES.items(), key=lambda x: len(x[0]), reverse=True
    )
    for phrase, weight in sorted_phrases:
        idx = remaining.find(phrase)
        if idx != -1:
            scores.append(weight)
            # Remove the matched text so shorter overlapping phrases don't re-match
            remaining = remaining[:idx] + " " * len(phrase) + remaining[idx + len(phrase):]

    # Check single words (word-boundary match) in the remaining text
    for word, weight in _FINANCIAL_LEXICON.items():
        if weight == 0.0:
            continue
        if re.search(r'\b' + re.escape(word) + r'\b', remaining):
            scores.append(weight)

    if not scores:
        return None
    return sum(scores) / len(scores)


def score_headline(text: str) -> dict:
    """Score a headline combining VADER + financial lexicon.

    Returns {'compound': float, 'label': str}.
    """
    # VADER base score
    analyzer = _get_analyzer()
    vader_score = 0.0
    if analyzer:
        vader_score = analyzer.polarity_scores(text).get("compound", 0.0)

    # Financial lexicon overlay
    fin_score = _financial_score(text)

    if fin_score is not None:
        # Blend: 35 % VADER + 65 % financial lexicon
        compound = 0.35 * vader_score + 0.65 * fin_score
    else:
        compound = vader_score

    label = _compound_to_label(compound)
    return {"compound": round(compound, 4), "label": label}


def _compound_to_label(compound: float) -> str:
    """Map a compound score to bullish/bearish/neutral."""
    if compound >= 0.15:
        return "bullish"
    elif compound <= -0.15:
        return "bearish"
    return "neutral"


# ── Test corpus — used for verification ──────────────────────────────
if __name__ == "__main__":
    tests = [
        ("NVDA stock surges 15% after blowout earnings report", "bullish"),
        ("Tesla misses delivery targets amid production delays", "bearish"),
        ("Apple warns of slower iPhone demand in China market", "bearish"),
        ("Fed signals rate cuts ahead as inflation cools", "bullish"),
        ("Oil prices jump on Middle East supply fears", "neutral"),
        ("Goldman Sachs raises S&P 500 target for 2025", "bullish"),
        ("Bank stocks slide as credit losses mount", "bearish"),
        ("Semiconductor sector rallies on AI chip demand optimism", "bullish"),
        ("Inflation data comes in hotter than expected, spooking investors", "bearish"),
        ("Company announces share buyback program worth $2 billion", "bullish"),
        ("SEC charges hedge fund with fraud in $500M scheme", "bearish"),
        ("Strong consumer spending fuels Q3 GDP growth", "bullish"),
        ("Yield curve inverts as recession fears deepen", "bearish"),
        ("Tech stocks rally after Fed pause on rate hikes", "bullish"),
        ("Energy sector braces for price slump as oil dips below $70", "bearish"),
        ("Fed holds rates steady as expected", "neutral"),
        ("CPI comes in line with expectations", "neutral"),
    ]
    print(f"{'Score':>8}  {'Label':<10}  Expected   Headline")
    print("-" * 80)
    passed = 0
    for text, expected in tests:
        result = score_headline(text)
        match = "✓" if result["label"] == expected else "✗"
        if result["label"] == expected:
            passed += 1
        print(f"{result['compound']:+8.3f}  {result['label']:<10}  {expected:<8} {match}  {text}")
    print(f"\n{passed}/{len(tests)} correct")
