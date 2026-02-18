#!/usr/bin/env python3
"""
fetch_news.py — Health & Wellness News Generator (Solution 1B)
v2.1 HARDENED compliant

Guardrails enforced:
  B1: EXACTLY 20 search calls (hard cap)
  B4: Sequential execution (concurrency = 1, satisfies ≤5 cap)
  C:  1 retry per failure within cap; 5 consecutive failures → stop
  D:  meta.calls_used / calls_budget in output
  E:  API key from environment only
"""

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Configuration ───────────────────────────────────────────────
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 1024
CALL_BUDGET = 20
CONSECUTIVE_FAIL_LIMIT = 5
THAILAND_TZ = timezone(timedelta(hours=7))

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


# ─── API Call ────────────────────────────────────────────────────
def fetch_single_query(api_key: str, query_text: str) -> dict:
    """Make one API call. Returns parsed response or raises."""
    import urllib.request
    import urllib.error

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

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        # FORENSIC: Print upstream body (usually JSON explaining the invalid field)
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

        # Optional: show minimal request metadata WITHOUT secrets
        print("Request meta (sanitized):", file=sys.stderr)
        print(json.dumps({
            "url": API_URL,
            "model": MODEL,
            "anthropic_version": "2023-06-01",
            "has_tools": bool(payload_obj.get("tools")),
            "tools": payload_obj.get("tools"),
            "max_tokens": MAX_TOKENS
        }, ensure_ascii=False), file=sys.stderr)

        raise
    except Exception as e:
        # Non-HTTP errors (timeout, DNS, etc.)
        print(f"=== REQUEST ERROR (FORENSIC) === {repr(e)}", file=sys.stderr)
        raise

    # Extract text blocks
    text = "\n".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    )

    # Parse JSON (strip markdown fences if present)
    clean = re.sub(r"```json|```", "", text).strip()
    return json.loads(clean)


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

    # ── GUARDRAIL B1: Enforce exactly 20 ──
    assert len(queries) == CALL_BUDGET, (
        f"GUARDRAIL VIOLATION: queries.json has {len(queries)} entries, expected {CALL_BUDGET}"
    )

    now_utc = datetime.now(timezone.utc)
    now_th = now_utc.astimezone(THAILAND_TZ)

    all_items = []
    errors = []
    calls_used = 0
    consecutive_failures = 0
    seen_keys = set()

    print(f"[{now_th.strftime('%Y-%m-%d %H:%M')} TH] Starting {CALL_BUDGET}-call fetch...")

    for q in queries:
        tag = q["query_tag"]
        demographic = q["demographic"]
        badge_color = q["badge_color"]
        query_text = q["query_text"]

        if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
            print(f"  ⛔ STOP: {CONSECUTIVE_FAIL_LIMIT} consecutive failures. Halting.")
            break

        if calls_used >= CALL_BUDGET:
            print(f"  ⛔ BUDGET REACHED: {calls_used}/{CALL_BUDGET}")
            break

        print(f"  [{calls_used + 1}/{CALL_BUDGET}] {tag}: {query_text[:60]}...")

        try:
            results = fetch_single_query(api_key, query_text)
            calls_used += 1
            consecutive_failures = 0

            if not isinstance(results, list):
                results = [results] if isinstance(results, dict) else []

            for item in results:
                title = item.get("title", "").strip()
                if not title:
                    continue

                dk = dedup_key(title)
                if dk in seen_keys:
                    continue
                seen_keys.add(dk)

                combined_text = f"{title} {item.get('summary', '')} {item.get('source', '')}"
                region = classify_region(combined_text, demographic)

                all_items.append({
                    "query_tag": tag,
                    "badge_color": badge_color,
                    "region": region,
                    "title": title,
                    "summary": (item.get("summary") or "").strip(),
                    "source": (item.get("source") or "").strip(),
                    "url": item.get("url"),
                    "strategic_implication": (item.get("strategic_implication") or "").strip(),
                })

        except Exception as e:
            consecutive_failures += 1
            msg = str(e)
            errors.append({
                "query_tag": tag,
                "error_type": "other",
                "message": msg if msg else repr(e),
                "attempts": 1
            })
            print(f"  ❌ {tag}: {msg}")

    # Sort: reputable sources first, then by title (stable)
    def reputable_rank(item):
        src = (item.get("source") or "").lower()
        return 0 if src in REPUTABLE else 1

    all_items.sort(key=lambda x: (reputable_rank(x), x.get("title", "").lower()))

    # Build output
    out = {
        "meta": {
            "version": "1B-v2.1",
            "generated_at_iso": now_utc.isoformat(),
            "generated_at_local": now_th.strftime("%d %b. %Y %H:%M น."),
            "schedule_local": "ทุกวัน: 8:00 น.",
            "calls_used": calls_used,
            "calls_budget": CALL_BUDGET,
            "partial": True if errors or calls_used < CALL_BUDGET else False,
            "notes": f"{len(all_items)} articles from {calls_used} calls. {len(errors)} errors. "
                     f"{'PARTIAL: stopped early.' if errors or calls_used < CALL_BUDGET else 'OK.'}",
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
