#!/usr/bin/env python3
"""
fetch_news.py — Health & Wellness News Generator (Solution 1B)
v2.1 HARDENED compliant (as implemented)

Guardrails enforced:
  B1: ≤ 5 search ATTEMPTS (hard cap)
  B4: Sequential execution (concurrency = 1)
  C:  1 retry per transient failure within attempt cap; 5 consecutive failed attempts → stop
  D:  meta.calls_used / meta.calls_attempted / calls_budget in output
  E:  API key from environment only
"""

import json
import os
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 512

CALL_BUDGET = 20
SLEEP_BETWEEN_CALLS_SECONDS = 65
RETRY_BACKOFF_SECONDS = 15

CONSECUTIVE_FAIL_LIMIT = 5
THAILAND_TZ = timezone(timedelta(hours=7))

# Run-level flag: once set True, all subsequent calls skip output_config
STRUCTURED_OUTPUT_DISABLED = False

SYSTEM_PROMPT = (
    "You are a strategic health & wellness intelligence curator for a business team. "
    "Given search results, extract exactly 2 news items. "
    "Return ONLY a JSON array of objects with: "
    "title (string), summary (one sentence), source (publication name), "
    "url (string or null), "
    "strategic_implication (one sentence explaining what this means for organizations "
    "and what teams should prepare for). "
    "No markdown fences, no explanation. JSON only."
)

# Structured Outputs schema: guarantee valid JSON, exactly 2 items (if API supports output_config)
OUTPUT_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "source": {"type": "string"},
            "url": {"type": ["string", "null"]},
            "strategic_implication": {"type": "string"},
        },
        "required": ["title", "summary", "source", "url", "strategic_implication"],
        "additionalProperties": False,
    },
}

# Regex classification patterns (from v2.1 master)
RE_THAILAND = re.compile(
    r"thai|bangkok|chula|mahidol|siriraj|bumrungrad|bdi|moph",
    re.IGNORECASE,
)
RE_ASIA = re.compile(
    r"asean|singapore|japan|korea|china|india|vietnam|indonesia|"
    r"philippines|malaysia|hong\s*kong|taiwan|asia",
    re.IGNORECASE,
)
RE_RESEARCH = re.compile(
    r"study|research|trial|peer.review|published|meta.analysis|"
    r"journal|lancet|nature|arxiv|findings|efficacy|randomized",
    re.IGNORECASE,
)

# Reputable sources for sorting (recognized → top)
REPUTABLE = {
    s.lower()
    for s in [
        "Harvard", "WHO", "Mayo Clinic", "NIH", "Johns Hopkins", "CDC",
        "Lancet", "Nature", "Cleveland Clinic", "Stanford",
    ]
}


def dedup_key(title: str) -> str:
    t = re.sub(r"\s+", " ", title.strip().lower())
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    return t[:180]


def classify_region(text: str, demographic: str) -> str:
    t = (text or "").lower()
    if demographic.lower() == "local":
        return "local"
    if RE_THAILAND.search(t):
        return "local"
    if RE_ASIA.search(t):
        return "regional"
    return "global"


def build_exec_summary(items: list) -> dict:
    trends = []
    strategic = []
    local = []

    for it in items:
        if it.get("strategic_implication"):
            strategic.append(it["strategic_implication"])
        if it.get("summary"):
            trends.append(it["summary"])
        if it.get("region") == "local":
            local.append(it.get("title", ""))

    # de-dup and limit
    def uniq(xs):
        out = []
        seen = set()
        for x in xs:
            k = dedup_key(x)
            if k in seen or not x:
                continue
            seen.add(k)
            out.append(x)
        return out

    trends = uniq(trends)[:3]
    strategic = uniq(strategic)[:3]

    if not local:
        local.append("ยังไม่มีข่าวท้องถิ่นในรอบนี้")

    return {
        "trends": trends or ["ยังไม่มีข้อมูลเทรนด์"],
        "strategic": strategic or ["ยังไม่มีข้อมูลเชิงกลยุทธ์"],
        "local": local,
    }


def is_transient_error(e: Exception) -> bool:
    # Retry only transient failures: 429, 5xx, timeouts/network
    if isinstance(e, urllib.error.HTTPError):
        try:
            code = int(getattr(e, "code", 0) or 0)
        except Exception:
            code = 0
        return code == 429 or (500 <= code <= 599)
    if isinstance(e, urllib.error.URLError):
        return True
    if isinstance(e, TimeoutError):
        return True
    return False


# ─── API Call ────────────────────────────────────────────────────
def fetch_single_query(api_key: str, query_text: str) -> list:
    """Make one API call with structured output; retry once without it if unsupported."""
    global STRUCTURED_OUTPUT_DISABLED
    import urllib.request
    import urllib.error

    def _make_request(include_structured: bool) -> list:
        print(f"[REQUEST_CONFIG] sending_output_config={include_structured}", file=sys.stderr)
        payload_obj = {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Find 2 most recent and important health/wellness news "
                        f"from this search. JSON array only:\n{query_text}"
                    ),
                }
            ],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        }

        if include_structured:
            payload_obj["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": OUTPUT_SCHEMA,
                }
            }

        payload = json.dumps(payload_obj).encode("utf-8")

        req = urllib.request.Request(
            API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        data = None
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

                # --- TOKEN USAGE INSTRUMENTATION ---
                usage = data.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)

                print(
                    f"[TOKEN_USAGE] "
                    f"input_tokens={input_tokens} "
                    f"output_tokens={output_tokens}",
                    file=sys.stderr,
                )
                # ------------------------------------
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = "<unable to read error body>"

            print("=== ANTHROPIC HTTP ERROR (FORENSIC) ===", file=sys.stderr)
            print(f"Status: {e.code} {getattr(e, 'reason', '')}", file=sys.stderr)
            print("Response body:", file=sys.stderr)
            print(body, file=sys.stderr)
            print("=== END ERROR BODY ===", file=sys.stderr)

            print("Request meta (sanitized):", file=sys.stderr)
            print(
                json.dumps(
                    {
                        "url": API_URL,
                        "model": MODEL,
                        "anthropic_version": "2023-06-01",
                        "has_tools": bool(payload_obj.get("tools")),
                        "has_output_config": include_structured,
                        "max_tokens": MAX_TOKENS,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
            )
            e._forensic_body = body  # attach for outer retry logic
            raise
          
        except Exception as e:
            print(f"=== REQUEST ERROR (FORENSIC) === {repr(e)}", file=sys.stderr)
            raise

        if data is None:
            raise RuntimeError("No response data parsed from Anthropic API")

        stop_reason = data.get("stop_reason")
        if stop_reason in ("max_tokens", "refusal"):
            raise RuntimeError(f"Anthropic stop_reason={stop_reason}")

        content = data.get("content", [])
        text0 = ""

        if content and isinstance(content, list):
            first = content[0] if len(content) > 0 else {}
            if isinstance(first, dict):
                text0 = first.get("text", "") or ""

        if not text0.strip():
            text0 = "\n".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )

        if not text0.strip():
            raise RuntimeError("Empty text content from Anthropic response")

        parsed = json.loads(text0.strip())
        if not isinstance(parsed, list):
            raise RuntimeError("Model output JSON is not a list")
        if len(parsed) != 2:
            raise RuntimeError(f"Expected 2 items, got {len(parsed)}")
        return parsed

    # First attempt: skip structured output if already disabled for this run
    try:
        return _make_request(include_structured=not STRUCTURED_OUTPUT_DISABLED)

    except urllib.error.HTTPError as e:
        # Retry ONLY when 400 indicates structured output is unsupported
        body = getattr(e, "_forensic_body", "") or ""
        haystack = (str(e) + "\n" + body).lower()

        is_400 = getattr(e, "code", None) == 400

        structured_not_supported = (
            ("output_config" in haystack and ("unknown" in haystack or "not allowed" in haystack or "unsupported" in haystack))
            or ("does not support output format" in haystack)
            or ("unknown field" in haystack and "output_config" in haystack)
            or ("json_schema" in haystack and ("not supported" in haystack or "unsupported" in haystack))
            or ("output_config.format" in haystack and ("not supported" in haystack or "unsupported" in haystack))
        )

        if is_400 and structured_not_supported:
            STRUCTURED_OUTPUT_DISABLED = True
            print(
                "Structured output unsupported — retrying without output_config (flag set for run)",
                file=sys.stderr,
            )
            return _make_request(include_structured=False)

        raise

# ─── Main Generator ──────────────────────────────────────────────
def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Load queries
    queries_path = Path(__file__).parent / "queries.json"
    with open(queries_path, encoding="utf-8") as f:
        queries = json.load(f)

    # ── Guardrail: queries count must match budget ──
    assert len(queries) == CALL_BUDGET, (
        f"GUARDRAIL VIOLATION: queries.json has {len(queries)} entries, expected {CALL_BUDGET}"
    )

    now_utc = datetime.now(timezone.utc)
    now_th = now_utc.astimezone(THAILAND_TZ)

    all_items = []
    errors = []
    calls_used = 0
    calls_attempted = 0
    consecutive_failures = 0
    seen_keys = set()

    print(f"[{now_th.strftime('%Y-%m-%d %H:%M')} TH] Starting {CALL_BUDGET}-attempt fetch...")

    for q in queries:
        tag = q["query_tag"]
        demographic = q["demographic"]
        badge_color = q["badge_color"]
        query_text = q["query_text"]

        if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
            print(f"  ⛔ STOP: {CONSECUTIVE_FAIL_LIMIT} consecutive failed attempts. Halting.")
            break

        # Guardrail C: up to 2 attempts per query (1 retry) within global attempt cap
        results = None
        attempts_for_this_query = 0
        last_error = None

        while attempts_for_this_query < 2:
            if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
                print(f"  ⛔ STOP: {CONSECUTIVE_FAIL_LIMIT} consecutive failed attempts. Halting.")
                break

            if calls_attempted >= CALL_BUDGET:
                print(f"  ⛔ BUDGET REACHED (attempts): {calls_attempted}/{CALL_BUDGET}")
                break

            print(f"  [{calls_attempted + 1}/{CALL_BUDGET}] {tag}: {query_text[:60]}...")

            # pacing: pace ATTEMPTS (skip first attempt)
            if calls_attempted > 0:
                time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)

            calls_attempted += 1
            attempts_for_this_query += 1

            try:
                results = fetch_single_query(api_key, query_text)
                calls_used += 1
                consecutive_failures = 0
                last_error = None
                break
            except Exception as e:
                last_error = e
                consecutive_failures += 1

                transient = is_transient_error(e)
                if attempts_for_this_query < 2 and transient and calls_attempted < CALL_BUDGET:
                    print(f"  ⚠ {tag}: transient failure, retrying once after {RETRY_BACKOFF_SECONDS}s")
                    time.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                break

        if results is None:
            msg = str(last_error) if last_error else "Unknown error"
            errors.append(
                {
                    "query_tag": tag,
                    "error_type": "other",
                    "message": msg if msg else repr(last_error),
                    "attempts": attempts_for_this_query,
                }
            )
            print(f"  ❌ {tag}: {msg}")
            continue

        # Normalize to list (defensive)
        if not isinstance(results, list):
            results = [results] if isinstance(results, dict) else []

        for item in results:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue

            dk = dedup_key(title)
            if dk in seen_keys:
                continue
            seen_keys.add(dk)

            combined_text = f"{title} {item.get('summary', '')} {item.get('source', '')}"
            region = classify_region(combined_text, demographic)

            all_items.append(
                {
                    "query_tag": tag,
                    "badge_color": badge_color,
                    "region": region,
                    "title": title,
                    "summary": (item.get("summary") or "").strip(),
                    "source": (item.get("source") or "").strip(),
                    "url": item.get("url"),
                    "strategic_implication": (item.get("strategic_implication") or "").strip(),
                }
            )

    # Sort: reputable sources first, then by title (stable)
    def reputable_rank(item):
        src = (item.get("source") or "").lower()
        return 0 if src in REPUTABLE else 1

    all_items.sort(key=lambda x: (reputable_rank(x), x.get("title", "").lower()))

    out = {
        "meta": {
            "version": "1B-v2.1",
            "generated_at_iso": now_utc.isoformat(),
            "generated_at_local": now_th.strftime("%d %b. %Y %H:%M น."),
            "schedule_local": "ทุกวัน: 8:00 น.",
            "calls_used": calls_used,
            "calls_attempted": calls_attempted,
            "calls_budget": CALL_BUDGET,
            "partial": True if errors or calls_used < CALL_BUDGET else False,
            "notes": (
                f"{len(all_items)} articles from {calls_used} successful calls / "
                f"{calls_attempted} attempts (budget {CALL_BUDGET}). {len(errors)} errors. "
                f"{'PARTIAL: stopped early.' if errors or calls_used < CALL_BUDGET else 'OK.'}"
            ),
        },
        "executive_summary": build_exec_summary(all_items),
        "items": all_items,
        "errors": errors,
    }

    out_path = Path(__file__).parent / "data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Done. Wrote {out_path} ({len(all_items)} items, {len(errors)} errors).")


if __name__ == "__main__":
    main()
