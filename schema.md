# data.json Schema — v2.1 HARDENED

## Top-level structure

```
{
  "meta": { ... },
  "executive_summary": { ... },
  "items": [ ... ],
  "errors": [ ... ]
}
```

## meta

| Field | Type | Description |
|-------|------|-------------|
| version | string | Always "1B-v2.1" |
| generated_at_iso | string | UTC ISO timestamp |
| generated_at_local | string | Thai-formatted timestamp |
| schedule_local | string | "ทุกวัน: 8:00 น." |
| calls_used | int | Actual API calls made (≤ 20) |
| calls_budget | int | Always 20 |
| partial | bool | true if stopped early or had errors |
| notes | string | Human-readable summary |

## executive_summary

| Field | Type | Description |
|-------|------|-------------|
| trends | string[] | 4-5 trend observations |
| strategic | string[] | 4-5 actionable implications (🔴 prefix = urgent) |
| local | string[] | 3-4 Thailand/ASEAN perspectives |

**⚠️ Generated WITHOUT extra API calls (B1 compliant)**

## items[]

| Field | Type | Description |
|-------|------|-------------|
| id | string | MD5 hash of title (first 12 chars) |
| title | string | Article headline |
| summary | string | One-sentence summary |
| source | string | Publication name |
| url | string|null | Link to article |
| published_at | string|null | Date if available |
| region | enum | GLOBAL, ASIA_PACIFIC, THAILAND, RESEARCH |
| badge_color | string | Hex color for UI badge |
| strategic_implication | string | "So what?" for organizations |
| query_tag | string | e.g. GLOBAL_1, THAILAND_3 |
| fetched_from_query | string | Original search query |

## errors[]

| Field | Type | Description |
|-------|------|-------------|
| query_tag | string | Which query failed |
| error_type | string | timeout, parse, http, other |
| message | string | Short error description |
| attempts | int | 1 or 2 (if retried) |
