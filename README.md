# 🧬 Global Health & Wellness News Dashboard

**Solution 1B — Automated Static via GitHub Actions**
v2.1 HARDENED compliant

## What This Does

- Fetches health & wellness news from 20 reputable sources daily at 08:00 Thailand time
- Generates a static `data.json` with news + strategic implications
- Serves a beautiful dashboard via GitHub Pages — **no login required for viewers**
- Cost: ~$7.20/month (20 API calls × 30 days)

## Setup Guide (45 minutes)

### Step 1: Create GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Name: `health-wellness-news` (or whatever you like)
3. Set to **Public** (required for free GitHub Pages)
4. Upload all files from this folder

### Step 2: Add API Key

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Name: `ANTHROPIC_API_KEY`
4. Value: Your Anthropic API key (get from [console.anthropic.com](https://console.anthropic.com))
5. Click **Add secret**

⚠️ The API key is NEVER stored in code, NEVER in the frontend, NEVER in the repo.

### Step 3: Enable GitHub Pages

1. Go to repo → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: `main`, folder: `/ (root)`
4. Click **Save**
5. Your site will be at: `https://YOUR-USERNAME.github.io/health-wellness-news/`

### Step 4: Test the Workflow

1. Go to repo → **Actions** → **Update Health News**
2. Click **Run workflow** → **Run workflow**
3. Wait 2-3 minutes for it to complete
4. Check that `data.json` was updated (you'll see a new commit)
5. Visit your GitHub Pages URL — the dashboard should show live data

### Step 5: Share

Copy the GitHub Pages URL and share via LINE, email, etc.
**No Claude account needed for viewers.**

## File Overview

| File | Purpose |
|------|---------|
| `dashboard.html` | Static frontend (fetches only data.json) |
| `data.json` | News data (auto-updated by workflow) |
| `fetch_news.py` | Python script that calls Anthropic API |
| `queries.json` | 20 search queries with demographic mapping |
| `schema.md` | data.json contract documentation |
| `.github/workflows/update.yml` | GitHub Actions schedule |

## Architecture

```
GitHub Actions (01:00 UTC / 08:00 TH daily)
    ↓
fetch_news.py (20 API calls → Anthropic)
    ↓
data.json (committed to repo)
    ↓
GitHub Pages serves dashboard.html + data.json
    ↓
Viewers see dashboard (no login, no billing)
```

## Guardrails

- **20-call hard cap**: Script enforces exactly 20 search calls
- **No client-side API calls**: dashboard.html fetches ONLY data.json
- **Failure policy**: Partial results shown if some calls fail; stops after 5 consecutive failures
- **Cost transparency**: UI shows calls used (X/20) and last updated time

## Monthly Cost

| Item | Cost |
|------|------|
| Anthropic API (20 calls × 30 days) | ~$7.20 |
| GitHub Actions | $0 (free tier) |
| GitHub Pages | $0 (free) |
| **Total** | **~$7.20/month** |

## To Stop

1. Go to repo → **Actions** → **Update Health News** → disable workflow
2. Or delete the repo
3. Billing stops immediately

---

*Owner: Dr.Dangjaithawin Anantachai · Built by Dr.Ant · v2.1 HARDENED*
