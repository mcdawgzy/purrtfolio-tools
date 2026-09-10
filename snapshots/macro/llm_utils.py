#!/usr/bin/env python3
"""
LLM utilities for macro market update.

Uses the Nous inference API (the same provider the Hermes agent runs on)
so that captions and driver narratives are genuinely fresh every day —
never recycled from a template or static word bank.

Credentials are read from the Hermes auth file
(~/AppData/Local/hermes/auth.json) to stay consistent with the Hermes
agent's configured `provider: nous` in config.yaml.

To keep runtime practical (31 tickers), all driver narratives for a single run
are generated in ONE batched LLM call, and the caption is a second call.
"""

import os
import json
import textwrap

import requests


# ─── Model config ───────────────────────────────────────────────────────────

MODEL_ID = "poolside/laguna-s-2.1:free"
# Alternate models to try when the primary model is rate-limited (429).
# Returned by the Nous API in the "alternates" field of 429 responses.
FALLBACK_MODELS = []  # Nous API has only one free model; alternates require credits
NOUS_INFERENCE_URL = "https://inference-api.nousresearch.com/v1/chat/completions"


def _read_auth() -> dict:
    """Read Nous provider credentials from the Hermes auth file."""
    auth_path = os.path.join(
        os.environ.get("USERPROFILE", os.environ.get("HOME", "")),
        "AppData", "Local", "hermes", "auth.json",
    )
    if os.path.exists(auth_path):
        with open(auth_path) as f:
            data = json.load(f)
        nous = data.get("providers", {}).get("nous", {})
        access_token = nous.get("access_token")
        base_url = nous.get("inference_base_url", NOUS_INFERENCE_URL)
        if access_token:
            # inference_base_url is like "https://inference-api.nousresearch.com/v1"
            # The chat completions endpoint is base_url + "/chat/completions"
            api_url = base_url.rstrip("/") + "/chat/completions"
            return {"token": access_token, "base_url": api_url}

    # Fallback: env vars (for non-Hermes environments)
    token = os.environ.get("NOUS_ACCESS_TOKEN") or os.environ.get("OPENROUTER_API_KEY")
    if token:
        fallback_url = os.environ.get("NOUS_API_BASE_URL", NOUS_INFERENCE_URL)
        api_url = fallback_url.rstrip("/") + "/chat/completions"
        return {"token": token, "base_url": api_url}

    raise RuntimeError(
        "Nous API credentials not found. Ensure Hermes is authenticated "
        "(providers.nous in ~/AppData/Local/hermes/auth.json) or set "
        "NOUS_ACCESS_TOKEN / OPENROUTER_API_KEY env var."
    )


def _llm_call(messages: list[dict], temperature: float = 0.7, max_tokens: int = 500) -> str:
    """Make a single conversational call to the LLM via the Nous inference API.

    Retries with exponential backoff on 429 (rate limit) errors, and falls
    back to alternate models when the primary model is rate-limited.
    """
    import time

    auth = _read_auth()
    api_key = auth["token"]
    base_url = auth["base_url"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://hermes-agent.nousresearch.com/",
        "X-Title": "Hermes Macro Market Update",
    }

    # Try primary model first, then alternates
    models_to_try = [MODEL_ID] + FALLBACK_MODELS
    last_err = None

    for model_idx, current_model in enumerate(models_to_try):
        payload = {
            "model": current_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        for attempt in range(4):
            try:
                resp = requests.post(base_url, headers=headers, json=payload, timeout=90)
                if resp.status_code == 429 and attempt < 3:
                    # Parse retry_after from response body
                    wait = 5 * (attempt + 1)  # default backoff
                    try:
                        body = resp.json()
                        retry_after = body.get("retry_after")
                        if retry_after and isinstance(retry_after, (int, float)):
                            wait = min(retry_after, 30)  # cap at 30s
                    except Exception:
                        pass
                    print(f"[LLM] ⚠️ Rate-limited (429) on {current_model}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 429 and attempt >= 3:
                    # Exhausted retries on this model — try next alternate
                    print(f"[LLM] ⚠️ {current_model} exhausted retries, trying next model...")
                    last_err = RuntimeError(f"HTTP 429 on {current_model}")
                    break
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content is None:
                    content = ""
                if model_idx > 0:
                    print(f"[LLM] ✅ Succeeded with alternate model: {current_model}")
                return content.strip()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < 3:
                    wait = 5 * (attempt + 1)
                    try:
                        body = e.response.json()
                        retry_after = body.get("retry_after")
                        if retry_after and isinstance(retry_after, (int, float)):
                            wait = min(retry_after, 30)
                    except Exception:
                        pass
                    print(f"[LLM] ⚠️ Rate-limited (429) on {current_model}, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                elif e.response.status_code == 429 and attempt >= 3:
                    print(f"[LLM] ⚠️ {current_model} exhausted retries, trying next model...")
                    last_err = e
                    break
                raise
            except Exception as e:
                last_err = e
                if attempt < 3 and ("429" in str(e) or "Too Many" in str(e)):
                    wait = 5 * (attempt + 1)
                    print(f"[LLM] ⚠️ Rate-limited, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
                raise
        # If we exhausted retries on this model, continue to next model in outer loop
    if last_err:
        raise last_err
    raise RuntimeError("All models exhausted")


# ─── Cross-asset context ─────────────────────────────────────────────────────

def build_cross_asset_context(data: dict) -> str:
    """Build a compact summary of all market data for LLM context."""
    lines = []
    for name, md in sorted(data.items(), key=lambda x: x[1].category):
        if md.error or md.pct_change is None:
            continue
        symbol = md.symbol
        direction = "up" if md.pct_change > 0 else "down"
        lines.append(
            f"[{md.category}] {name} ({symbol}): {md.pct_change:+.2f}% — {direction}"
        )
    return "\n".join(lines)


# ─── Driver narrative generation (BATCHED) ──────────────────────────────────

NARRATIVE_SYSTEM = textwrap.dedent("""\
    You are a financial market analyst writing concise driver narratives for
    a daily macro snapshot. Your job is to explain WHY each asset moved today,
    with specific, fresh language that could only apply to today's data.

    Rules:
    - NEVER use template phrasing or recycled wording. Every narrative must
      sound like it was written fresh for today's specific numbers.
    - Reference concrete catalysts: specific economic data, central bank
      signals, earnings, geopolitical events, technical flows, or cross-asset
      effects.
    - Match the direction: if the asset rose, the reason should be bullish;
      if it fell, the reason should be bearish.
    - Each narrative is a single short phrase starting with "on " — e.g.
      "on tech earnings beating after strong Apple results" or
      "on hotter-than-expected CPI reigniting taper talk".
    - Max 75 characters per narrative (including the "on " prefix).
    - Give each ticker a UNIQUE narrative — no two should be the same.
    - Do NOT mention "template", "generated", "AI", or "automated".
""")


def generate_all_drivers(data: dict) -> dict[str, str]:
    """
    Generate fresh LLM-powered driver narratives for ALL tickers in a single
    batched LLM call.  Returns a dict mapping ticker name -> driver string.

    Falls back to deterministic per-ticker calls if the batch fails, and to
    simple fallbacks if those also fail.
    """
    if not data:
        return {}

    cross_asset = build_cross_asset_context(data)

    # Build a compact per-ticker spec list
    ticker_lines = []
    for name, md in data.items():
        if md.error or md.pct_change is None:
            ticker_lines.append(f"- {name}: ERROR ({md.error})")
            continue
        direction = "rose" if md.pct_change > 0 else "fell"
        ticker_lines.append(
            f"- {name} | {direction} {abs(md.pct_change):.2f}% | "
            f"price: {md.price} | {md.category}"
        )
    ticker_spec = "\n".join(ticker_lines)

    user_msg = (
        f"Today's market data (all tickers, with cross-asset context):\n\n"
        f"{cross_asset}\n\n"
        f"Per-ticker specs:\n{ticker_spec}\n\n"
        f"Write ONE driver phrase for EACH ticker above (skip any with ERROR).\n"
        f"Format each line as: NAME|on [reason]  (e.g. 'S&P 500|on tech earnings')\n"
        f"Each reason must be specific to today's data, max 75 chars including 'on '.\n"
        f"No two narratives should be identical. No template language.\n"
        f"Sort output in the same order as the input list."
    )

    try:
        result = _llm_call(
            [
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=3000,  # 31 tickers * ~80 chars each + context
        )
        # Parse the batched response: "NAME|on [reason]" per line
        drivers = {}
        for line in result.split("\n"):
            line = line.strip()
            if "|" not in line:
                continue
            name, _, reason = line.partition("|")
            name = name.strip()
            reason = reason.strip()
            if name and reason:
                # Ensure it starts with "on "
                if not reason.lower().startswith("on "):
                    reason = f"on {reason}"
                # Truncate to 75 chars
                if len(reason) > 75:
                    reason = reason[:72].rstrip() + "..."
                drivers[name] = reason
        # Verify we got drivers for all valid tickers
        valid_names = {n for n, md in data.items() if not md.error and md.pct_change is not None}
        missing = valid_names - set(drivers.keys())
        if missing:
            print(f"[LLM] ⚠️ Batch produced {len(drivers)}/{len(valid_names)} drivers; "
                  f"filling {len(missing)} gaps individually")
            import time
            for name in missing:
                md = data[name]
                drivers[name] = _generate_single_driver(name, md, cross_asset)
                time.sleep(1)  # avoid rate-limiting on individual calls
        return drivers
    except Exception as e:
        print(f"[LLM] ⚠️ Batch driver generation failed ({e}); using simple fallbacks")
        import time
        drivers = {}
        for name, md in data.items():
            if md.error or md.pct_change is None:
                continue
            # Simple fallback that doesn't call the LLM
            direction = "rose" if md.pct_change > 0 else "fell"
            drivers[name] = f"on {direction} {abs(md.pct_change):.2f}%"
        return drivers


def _generate_single_driver(asset_name: str, md, cross_asset: str) -> str:
    """Generate a single driver with LLM, with fallback on failure."""
    direction = "rose" if md.pct_change > 0 else "fell"
    abs_pct = abs(md.pct_change)

    user_msg = textwrap.dedent(f"""\
        Asset: {asset_name}
        Category: {md.category}
        Direction: {direction} by {abs_pct:.2f}%
        Level: {md.price}

        Other market movements today (cross-asset context):
        {cross_asset}

        Write a single driver phrase (max 75 chars, format: "on [reason]")
        explaining why {asset_name} {direction} today. Be specific to today's
        data — no templates.
    """)

    try:
        driver = _llm_call(
            [
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.85,
            max_tokens=60,
        )
        driver = driver.strip().rstrip(".")
        if driver.lower().startswith("on "):
            driver = driver[3:].strip()
        if len(driver) > 72:
            driver = driver[:72].rstrip() + ".."
        return f"on {driver}"
    except Exception as e:
        print(f"[LLM] ⚠️ Driver for {asset_name} failed, using fallback: {e}")
        return f"on {direction} by {abs_pct:.2f}%"


# ─── Caption generation ─────────────────────────────────────────────────────

CAPTION_SYSTEM = textwrap.dedent("""\
    You are a market commentator writing a single-sentence caption for a daily
    macro market snapshot posted to Discord. Produce a fresh, original caption
    every time — never reuse templates, never repeat phrasing from previous
    days, and never use the same wording twice.

    The caption is ONE sentence (one period, at the end). It should be 70-120
    characters. It distills the dominant market theme of the day from the
    data provided: which assets led the moves, whether risk was on or off,
    and what cross-asset dynamic stood out (e.g. yields vs equities, dollar
    vs commodities, VIX vs everything).

    Write in a punchy, observational tone — not dry reporting, not hype.
    Reference the actual data points (specific tickers, specific directions,
    specific magnitudes) so the caption could only have been written for
    THIS day's numbers.
""")


def generate_caption(rows: list) -> str:
    """Generate a fresh LLM-powered caption from the report rows."""
    data_rows = [r for r in rows if r["type"] == "row" and r.get("pct_change") is not None]
    if not data_rows:
        return "Mixed signals across markets today."

    # Build a compact data digest for the LLM
    section_map = {}
    current_section = None
    for r in rows:
        if r["type"] == "section":
            current_section = r["name"]
            section_map[current_section] = []
        elif current_section and r.get("pct_change") is not None:
            section_map[current_section].append(r)

    lines = []
    for sec_name, items in section_map.items():
        for item in sorted(items, key=lambda x: abs(x["pct_change"]), reverse=True):
            lines.append(
                f"{sec_name} | {item['name']} | {item['pct_change']:+.2f}%"
            )
    data_digest = "\n".join(lines)

    top3 = sorted(data_rows, key=lambda x: abs(x["pct_change"]), reverse=True)[:3]
    top3_str = ", ".join(f"{t['name']} ({t['pct_change']:+.2f}%)" for t in top3)

    user_msg = (
        f"Today's macro snapshot data (sorted by magnitude within each section):\n\n"
        f"{data_digest}\n\n"
        f"Top 3 biggest movers: {top3_str}\n\n"
        f"Write a single-sentence Discord caption (70-120 chars, one sentence) "
        f"that captures today's dominant market theme using the specific data above."
    )

    try:
        caption = _llm_call(
            [
                {"role": "system", "content": CAPTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.8,
            max_tokens=80,  # ~120 chars at typical token/char ratio
        )
        # Safety: ensure single sentence with ending period
        caption = caption.strip().rstrip()
        if not caption.endswith("."):
            caption += "."
        # If it got cut off mid-sentence (no period except at end), it's fine — one sentence
        return caption
    except Exception as e:
        print(f"[LLM] ⚠️ Caption generation failed, falling back: {e}")
        return "Mixed signals across markets today."
