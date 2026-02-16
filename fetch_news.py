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
import hashlib
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
        "Psychology Today", "Sleep Foundation", "Healthline", "WebMD",
        "Well+Good", "Mindbodygreen", "Bangkok Post", "Thai PBS",
        "Chulalongkorn", "Mahidol", "NEJM", "BMJ", "FDA",
        "Global Wellness Summit",
    ]
}


# ─── Helpers ─────────────────────────────────────────────────────
def classify_region(text: str, default_demographic: str) -> str:
    """Classify article region using regex; fall back to query demographic."""
    if RE_THAILAND.search(text):
        return "THAILAND"
    if RE_ASIA.search(text):
        return "ASIA_PACIFIC"
    if RE_RESEARCH.search(text):
        return "RESEARCH"
    return default_demographic


def make_id(title: str) -> str:
    return hashlib.md5(title.lower().strip().encode()).hexdigest()[:12]


def dedup_key(title: str) -> str:
    return title.lower().strip()[:50]


def is_reputable(source: str) -> bool:
    src = source.lower()
    return any(r in src for r in REPUTABLE)


def synthesize_executive_summary(items: list) -> dict:
    """
    Generate executive summary CLIENT-SIDE (no extra API call).
    B1 compliant: uses only already-fetched data.
    """
    trends = []
    strategic = []
    local = []

    thailand_items = [i for i in items if i.get("region") == "THAILAND"]
    asia_items = [i for i in items if i.get("region") == "ASIA_PACIFIC"]
    research_items = [i for i in items if i.get("region") == "RESEARCH"]
    global_items = [i for i in items if i.get("region") == "GLOBAL"]

    # Trends: top 5 article titles as trend indicators
    for item in items[:5]:
        trends.append(item.get("title", "")[:80])

    # Strategic implications: collect from items, mark first as urgent
    implications = [
        i.get("strategic_implication", "") for i in items if i.get("strategic_implication")
    ]
    for idx, imp in enumerate(implications[:5]):
        prefix = "🔴 " if idx == 0 else ""
        strategic.append(f"{prefix}{imp}")

    # Local perspective: Thailand + Asia items
    for item in (thailand_items + asia_items)[:4]:
        local.append(f"{item.get('title', '')[:60]} — {item.get('source', '')}")

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

    payload = json.dumps({
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Find 2 most recent and important health/wellness news "
                    f"from this search. JSON array only:\n{query_text}"
                ),
            }
        ],
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())

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
    with open(queries_path) as f:
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

        # ── GUARDRAIL C3: Stop on 5 consecutive failures ──
        if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
            print(f"  ⛔ STOP: {CONSECUTIVE_FAIL_LIMIT} consecutive failures. Halting.")
            break

        # ── GUARDRAIL B1: Never exceed budget ──
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
                    "id": make_id(title),
                    "title": title,
                    "summary": item.get("summary", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url"),
                    "published_at": None,
                    "region": region,
                    "badge_color": badge_color,
                    "strategic_implication": item.get("strategic_implication", ""),
                    "query_tag": tag,
                    "fetched_from_query": query_text,
                })

            print(f"    ✓ Got {len(results)} items")

        except Exception as e:
            calls_used += 1
            consecutive_failures += 1
            error_type = "timeout" if "timeout" in str(e).lower() else "other"
            errors.append({
                "query_tag": tag,
                "error_type": error_type,
                "message": str(e)[:200],
                "attempts": 1,
            })
            print(f"    ✗ FAILED ({consecutive_failures} consecutive): {str(e)[:80]}")

            # ── GUARDRAIL C2: 1 retry within budget ──
            if calls_used < CALL_BUDGET and consecutive_failures < CONSECUTIVE_FAIL_LIMIT:
                print(f"    ↻ Retrying {tag}...")
                try:
                    results = fetch_single_query(api_key, query_text)
                    calls_used += 1
                    consecutive_failures = 0
                    errors[-1]["attempts"] = 2

                    if isinstance(results, list):
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
                                "id": make_id(title),
                                "title": title,
                                "summary": item.get("summary", ""),
                                "source": item.get("source", ""),
                                "url": item.get("url"),
                                "published_at": None,
                                "region": region,
                                "badge_color": badge_color,
                                "strategic_implication": item.get("strategic_implication", ""),
                                "query_tag": tag,
                                "fetched_from_query": query_text,
                            })
                    print(f"    ✓ Retry succeeded")
                except Exception as e2:
                    calls_used += 1
                    consecutive_failures += 1
                    errors[-1]["message"] += f" | Retry: {str(e2)[:100]}"
                    print(f"    ✗ Retry also failed")

    # ── Sort: reputable sources first ──
    all_items.sort(key=lambda x: (0 if is_reputable(x.get("source", "")) else 1))

    # ── Executive Summary: synthesized from results (B1: 0 extra calls) ──
    exec_summary = synthesize_executive_summary(all_items)

    is_partial = calls_used < CALL_BUDGET or len(errors) > 0

    # ── Build output ──
    output = {
        "meta": {
            "version": "1B-v2.1",
            "generated_at_iso": now_utc.isoformat(),
            "generated_at_local": now_th.strftime("%d ก.พ. %Y %H:%M น."),
            "schedule_local": "ทุกวัน: 8:00 น.",
            "calls_used": calls_used,
            "calls_budget": CALL_BUDGET,
            "partial": is_partial,
            "notes": f"{len(all_items)} articles from {calls_used} calls. {len(errors)} errors."
                     + (" PARTIAL: stopped early." if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT else ""),
        },
        "executive_summary": exec_summary,
        "items": all_items,
        "errors": errors,
    }

    # ── Write data.json ──
    output_path = Path(__file__).parent / "data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done. {len(all_items)} articles, {calls_used}/{CALL_BUDGET} calls, {len(errors)} errors.")
    print(f"   Partial: {is_partial}")
    print(f"   Output: {output_path}")


if __name__ == "__main__":
    main()
