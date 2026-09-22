# Daily Wire

A daily business and markets brief that rebuilds itself every morning and costs
nothing to run.

A GitHub Action wakes up at 07:00 IST, reads a list of public RSS feeds, merges
the stories several outlets are running, ranks them, and commits the result as
a JSON file. GitHub Pages serves a small reader over those files. No server, no
database, no API keys, no paid tier.

```
feeds (RSS)  →  GitHub Action (daily cron)  →  data/YYYY-MM-DD.json  →  Pages reader
```

---

## Setup

### 1. Create the repo

Make it **public**. Actions minutes are free and unlimited on public repos; a
free private repo only gets 2,000 minutes a month.

```bash
git init
git add .
git commit -m "daily wire"
git branch -M main
git remote add origin https://github.com/<you>/daily-wire.git
git push -u origin main
```

### 2. Let the Action write to the repo

**Settings → Actions → General → Workflow permissions** → select *Read and
write permissions* → Save. Without this the daily job builds the brief and then
fails to push it.

### 3. Turn on Pages

**Settings → Pages → Source: Deploy from a branch → `main` / `(root)`** → Save.

A minute later the app is live at `https://<you>.github.io/daily-wire/`.

### 4. Build the first brief

**Actions → Daily brief → Run workflow.** After it finishes, reload the page.
From then on it runs on its own each morning.

---

## Running it locally

```bash
pip install -r requirements.txt
python scripts/build_brief.py          # writes data/<today>.json
python -m http.server 8000             # then open http://localhost:8000
```

Useful flags:

| Flag | What it does |
|---|---|
| `--date 2026-09-22` | build under a specific date |
| `--fixtures tests/fixtures` | read local sample feeds instead of the network |
| `--no-why` | skip the model call even if a key is set |

To test without touching the network at all:

```bash
python tests/make_fixtures.py
python scripts/build_brief.py --fixtures tests/fixtures --no-why
```

---

## The "why it matters" lines

By default each story shows its headline, summary, sector and source. The
italic *why it matters* line under a story is written by a language model, in
one batched call per day — roughly 30 calls a month, which sits inside the free
tiers of both providers supported here.

Set **one** of these in **Settings → Secrets and variables → Actions → New
repository secret**:

- `GEMINI_API_KEY` — from Google AI Studio
- `GROQ_API_KEY` — from the Groq console

Model names move. If the job logs `model call failed: 404`, the default model
name has been retired — set `GEMINI_MODEL` or `GROQ_MODEL` as a repository
*variable* to a current one. Everything else keeps working meanwhile; a failed
model call never fails the build.

Nothing breaks without a key. The brief just carries no commentary.

---

## Editing the feed list

`sources.yml` holds everything. Each entry is a sector, a name, a URL and a
weight:

```yaml
  - sector: Banking
    name: Moneycontrol Banking
    url: https://www.moneycontrol.com/rss/banking.xml
    weight: 2
```

- **weight** nudges ranking — a story from a weight-3 feed sorts above the same
  story from a weight-1 feed, and the higher-weight version is the one kept
  when duplicates merge.
- **Google News query feeds** cover anything without a native feed. Build one
  at `https://news.google.com/rss/search?q=<query>+when:1d&hl=en-IN&gl=IN&ceid=IN:en`.
- **lead_sectors** decides which sectors may take a top slot. General news can
  make the brief without ever leading it.
- A feed that 404s is skipped with a warning; it never fails the build.

Other knobs at the top of the file: `window_hours` (how far back to look),
`max_stories`, `max_per_sector`, `leads`.

---

## How stories get merged and ranked

Six outlets covering one story should appear once, and that story should
outrank a story only one outlet bothered with.

1. **Tokenise** each headline — content words plus every number. Figures are the
   strongest signal that two headlines are the same story, and acronyms (NSE,
   RBI, GST) are kept rather than filtered as short words.
2. **Cluster** by overlap coefficient — shared tokens over the smaller set,
   requiring at least three in common. Plain Jaccard fails here because the
   longer of two headlines inflates the union and pushes real matches below
   any usable threshold.
3. **Rank** on `coverage × 2 + feed weight + freshness × 2`.
4. **Select** — one lead per sector so the first screen isn't four versions of
   the same sector, then the rest under a per-sector cap.

The number of outlets that ran a story is shown on the card as a *wires* badge.

---

## Install it on your phone

Open the Pages URL in Chrome or Safari and choose **Add to Home Screen**. You
get an icon, a splash screen, no browser chrome, and the last brief you opened
stays readable with no signal. That is the whole PWA — `manifest.json` plus
`sw.js`, no build step, no app store, no developer account.

If you change `index.html`, bump `CACHE_VERSION` in `sw.js` or returning
visitors keep the old shell.

---

## Things that will eventually bite you

**Scheduled workflows get disabled after 60 days of repo inactivity.** GitHub
emails you first. It is not certain that the bot's own daily commits reset that
clock — push something by hand now and then, or just watch for the email.

**Cron is UTC and approximate.** `30 1 * * *` is 07:00 IST, but GitHub queues
scheduled jobs under load. Some mornings it lands at 07:15.

**Some publishers put almost nothing in their RSS description.** You get the
headline and a stub. Link out rather than scraping the article body — that is
what keeps this both cheap and uncontroversial.

**Feeds go stale silently.** If a source stops appearing, check the Action log:
every feed prints `ok`, `skip` or `error` with a count each run.

---

## Layout

```
.github/workflows/brief.yml   the daily cron job
scripts/build_brief.py        fetch, merge, rank, write
sources.yml                   feeds and tuning knobs
data/YYYY-MM-DD.json          one brief per day
data/index.json               list of available days
index.html                    the reader
manifest.json  sw.js  icons/  the installable-app bits
tests/make_fixtures.py        offline sample feeds
```

## Cost

Zero. GitHub Actions is free on public repos, Pages is free, RSS is free, and
the model key is optional and sits inside a free tier at one call a day.
