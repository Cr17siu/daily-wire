#!/usr/bin/env python3
"""Build one day's news brief from RSS feeds.

Reads sources.yml, pulls every feed, keeps the last ~24 hours, merges stories
that several outlets are running, ranks them, and writes data/YYYY-MM-DD.json
plus a refreshed data/index.json.

No API key is needed. If GEMINI_API_KEY or GROQ_API_KEY is set in the
environment, one extra call adds a "why it matters" line to each story; without
a key the brief is built exactly the same way, minus those lines.

Usage:
    python scripts/build_brief.py
    python scripts/build_brief.py --fixtures tests/fixtures   # offline run
    python scripts/build_brief.py --date 2026-09-22           # override the date
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# Words that carry no signal when deciding whether two headlines are the same
# story. Kept deliberately small — over-stripping merges unrelated stories.
STOPWORDS = {
    "after", "again", "against", "all", "amid", "among", "ahead", "also", "and",
    "another", "any", "are", "back", "been", "before", "being", "between",
    "billion", "but", "can", "crore", "crores", "day", "days", "doe", "down",
    "due", "during", "each", "even", "ever", "every", "first", "for", "from",
    "get", "give", "govt", "had", "ha", "have", "her", "here", "high", "hi",
    "how", "into", "it", "just", "lakh", "last", "like", "long", "made", "make",
    "many", "may", "million", "more", "most", "much", "must", "near", "need",
    "new", "news", "next", "not", "now", "off", "one", "only", "other", "our",
    "out", "over", "per", "read", "said", "say", "see", "set", "she", "should",
    "since", "some", "still", "such", "take", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "those", "three",
    "through", "time", "today", "too", "top", "two", "under", "until", "update",
    "upto", "very", "wa", "way", "were", "what", "when", "where", "which",
    "while", "who", "why", "will", "with", "would", "year", "you", "your",
}

TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------- utilities


def strip_html(raw: str) -> str:
    """RSS descriptions arrive as escaped HTML. Return readable plain text."""
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Google News descriptions tail off into a list of related links.
    text = re.split(r"\s*(?:Read more|Continue reading|View Full Coverage)", text)[0]
    return text.strip()


def trim(text: str, limit: int = 260) -> str:
    """Cut to a sentence boundary under `limit` characters."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if stop > limit * 0.5:
        return cut[: stop + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"


def stem(word: str) -> str:
    """Crudest possible stemmer: enough to match closes/close, times/time."""
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def title_tokens(title: str) -> set[str]:
    """Content words plus every number — figures are the strongest match signal.

    Acronyms matter here (NSE, RBI, IPO, GST), so the length floor is 3 rather
    than 4, with the extra short filler words carried in STOPWORDS.
    """
    out = set()
    for word in WORD_RE.findall(title.lower()):
        if word.isdigit():
            out.add(word)
            continue
        word = stem(word)
        if len(word) >= 3 and word not in STOPWORDS:
            out.add(word)
    return out


def similarity(a: set[str], b: set[str]) -> float:
    """Overlap coefficient: shared tokens over the smaller set.

    Jaccard punishes the common case here — two outlets writing the same story
    at different lengths — because the longer headline inflates the union.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def same_story(a: set[str], b: set[str], threshold: float) -> bool:
    shared = len(a & b)
    floor = 2 if min(len(a), len(b)) <= 4 else 3
    return shared >= floor and similarity(a, b) >= threshold


def entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def source_name(entry, fallback: str) -> str:
    """Google News wraps the real publisher; prefer that over the feed's name."""
    src = entry.get("source")
    if isinstance(src, dict) and src.get("title"):
        return str(src["title"]).strip()
    # Google News titles end with " - Publisher".
    title = entry.get("title", "")
    if " - " in title:
        tail = title.rsplit(" - ", 1)[1].strip()
        if 2 < len(tail) < 40 and tail.count(" ") < 4:
            return tail
    return fallback


def clean_title(title: str) -> str:
    """Drop the trailing " - Publisher" that Google News appends."""
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if 2 < len(tail.strip()) < 40 and tail.count(" ") < 4 and len(head) > 25:
            return head.strip()
    return title.strip()


# ------------------------------------------------------------------- fetch


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def feed_location(feed: dict, fixtures: Path | None) -> str:
    """Point at a local fixture file when running offline."""
    if fixtures is None:
        return feed["url"]
    slug = re.sub(r"[^a-z0-9]+", "-", feed["name"].lower()).strip("-")
    candidate = fixtures / f"{slug}.xml"
    return str(candidate) if candidate.exists() else ""


def collect(config: dict, fixtures: Path | None) -> list[dict]:
    window = timedelta(hours=config.get("window_hours", 26))
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    seen_urls: set[str] = set()

    for feed in config["feeds"]:
        location = feed_location(feed, fixtures)
        if not location:
            print(f"  skip   {feed['name']} (no fixture)", file=sys.stderr)
            continue
        try:
            parsed = feedparser.parse(location)
        except Exception as exc:  # a bad feed must never fail the build
            print(f"  error  {feed['name']}: {exc}", file=sys.stderr)
            continue

        if parsed.get("bozo") and not parsed.entries:
            print(f"  error  {feed['name']}: {parsed.get('bozo_exception')}", file=sys.stderr)
            continue

        kept = 0
        for entry in parsed.entries:
            link = (entry.get("link") or "").strip()
            title = clean_title(entry.get("title", ""))
            if not link or not title or link in seen_urls:
                continue
            published = entry_time(entry)
            if published and now - published > window:
                continue
            seen_urls.add(link)
            items.append(
                {
                    "title": title,
                    "url": link,
                    "dek": trim(strip_html(entry.get("summary", ""))),
                    "sector": feed["sector"],
                    "source": source_name(entry, feed["name"]),
                    "weight": feed.get("weight", 1),
                    "published": published.isoformat() if published else None,
                    "_at": published or now,
                    "_tokens": title_tokens(title),
                }
            )
            kept += 1
        print(f"  ok     {feed['name']}: {kept} of {len(parsed.entries)}", file=sys.stderr)

    return items


# --------------------------------------------------------------- selection


# A real story runs on a handful of wires, not dozens. Past this many members a
# cluster has stopped being a story and become a magnet, so it takes no more —
# a cheap backstop against any similarity metric behaving badly on a corpus we
# have not seen.
MAX_CLUSTER = 6


def cluster(items: list[dict], threshold: float = 0.4) -> list[dict]:
    """Merge headlines about the same story. Cluster size = how many outlets ran it."""
    clusters: list[dict] = []
    for item in sorted(items, key=lambda i: (-i["weight"], i["_at"])):
        for group in clusters:
            if len(group["members"]) >= MAX_CLUSTER:
                continue
            # Compare against the cluster's FIRST headline, never an accumulated
            # union of every member's tokens. Unioning makes the set grow with
            # each merge while the overlap coefficient divides by the smaller
            # set, so a large cluster becomes a magnet that swallows anything
            # sharing three common words. That turned 163 unrelated stories
            # into one "cluster" on a real run.
            if same_story(item["_tokens"], group["_tokens"], threshold):
                group["members"].append(item)
                break
        else:
            clusters.append({"lead": item, "members": [item], "_tokens": set(item["_tokens"])})

    for group in clusters:
        outlets = {m["source"] for m in group["members"]}
        best = max(group["members"], key=lambda m: (m["weight"], len(m["dek"])))
        group["story"] = dict(best)
        group["story"]["coverage"] = len(outlets)
        group["story"]["also"] = sorted(outlets - {best["source"]})[:4]
    return clusters


def rank(clusters: list[dict], now: datetime) -> list[dict]:
    def score(group: dict) -> float:
        story = group["story"]
        hours_old = max((now - story["_at"]).total_seconds() / 3600, 0)
        freshness = max(0.0, 1.0 - hours_old / 30)
        return story["coverage"] * 2.0 + story["weight"] + freshness * 2.0

    return sorted(clusters, key=score, reverse=True)


def select(clusters: list[dict], config: dict) -> list[dict]:
    """Order the brief: sector-diverse leads first, then the rest under caps."""
    max_stories = config.get("max_stories", 28)
    max_per_sector = config.get("max_per_sector", 5)
    lead_count = config.get("leads", 3)
    ordered = [group["story"] for group in clusters]

    # The top three would otherwise all come from whichever sector had a busy
    # day. One lead per sector gives the brief a usable first screen — and
    # general news never leads a business brief, however fresh it is.
    eligible = set(config.get("lead_sectors") or []) or None
    leads: list[dict] = []
    used: set[str] = set()
    for pass_eligible in (True, False):  # second pass only if short of leads
        for story in ordered:
            if len(leads) >= lead_count:
                break
            sector = story["sector"]
            if sector in used:
                continue
            if pass_eligible and eligible and sector not in eligible:
                continue
            leads.append(story)
            used.add(sector)
        if len(leads) >= lead_count:
            break

    lead_ids = {id(s) for s in leads}
    chosen = list(leads)
    per_sector = {s["sector"]: 1 for s in leads}

    for story in ordered:
        if len(chosen) >= max_stories:
            break
        if id(story) in lead_ids:
            continue
        sector = story["sector"]
        if per_sector.get(sector, 0) >= max_per_sector:
            continue
        per_sector[sector] = per_sector.get(sector, 0) + 1
        chosen.append(story)
    return chosen


# ----------------------------------------------------------- the why layer


def ask_model(prompt: str) -> str | None:
    """One call to whichever free model has a key set. None if unavailable."""
    gemini = os.environ.get("GEMINI_API_KEY")
    groq = os.environ.get("GROQ_API_KEY")

    if gemini:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={gemini}"
        )
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        data = _post_json(url, body, {})
        if not data:
            return None
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            print("  warn   unexpected Gemini response shape", file=sys.stderr)
            return None

    if groq:
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        url = "https://api.groq.com/openai/v1/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        data = _post_json(url, body, {"Authorization": f"Bearer {groq}"})
        if not data:
            return None
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            print("  warn   unexpected Groq response shape", file=sys.stderr)
            return None

    return None


def _post_json(url: str, body: dict, headers: dict) -> dict | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        print(f"  warn   model call failed: {exc.code} {detail}", file=sys.stderr)
    except Exception as exc:
        print(f"  warn   model call failed: {exc}", file=sys.stderr)
    return None


def extract_json(text: str):
    """Models like to wrap JSON in prose or a code fence. Dig it out."""
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def add_why(stories: list[dict]) -> None:
    """Add a one-line 'why it matters' to each story, in a single model call."""
    if not stories:
        return
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        print("  note   no model key set — skipping the 'why it matters' lines", file=sys.stderr)
        return

    listing = "\n".join(
        f'{i}. [{s["sector"]}] {s["title"]} — {s["dek"][:180]}'
        for i, s in enumerate(stories)
    )
    prompt = (
        "You are briefing an Indian MBA finance student preparing for placement "
        "interviews. For each numbered story below, write one sentence (max 28 "
        "words) explaining why it matters — the implication, the mechanism, or "
        "the interview angle. Never restate the headline. If a story is routine "
        "general news with no analytical angle, return an empty string for it.\n\n"
        "Reply with ONLY a JSON array of objects, one per story, in the same "
        'order: [{"i": 0, "why": "..."}]\n\n'
        f"{listing}"
    )

    raw = ask_model(prompt)
    if not raw:
        return
    parsed = extract_json(raw)
    if not isinstance(parsed, list):
        print("  warn   could not parse the model's reply — continuing without it", file=sys.stderr)
        return

    for row in parsed:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("i", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(stories):
            stories[index]["why"] = str(row.get("why", "")).strip()
    print(f"  ok     added context to {sum(1 for s in stories if s.get('why'))} stories", file=sys.stderr)


# ------------------------------------------------------------------ output


def build_standfirst(stories: list[dict]) -> str:
    """A one-line summary of the brief itself, shown under the masthead."""
    sectors = len({s["sector"] for s in stories})
    widely = sum(1 for s in stories if s.get("coverage", 1) > 1)
    parts = [f"{len(stories)} stories across {sectors} sectors"]
    if widely:
        parts.append(f"{widely} running on more than one wire")
    return " · ".join(parts)


def to_public(story: dict, is_lead: bool) -> dict:
    return {
        "id": re.sub(r"[^a-z0-9]+", "-", story["title"].lower())[:60].strip("-"),
        "lead": is_lead,
        "sector": story["sector"],
        "title": story["title"],
        "dek": story["dek"],
        "why": story.get("why", ""),
        "source": story["source"],
        "also": story.get("also", []),
        "coverage": story.get("coverage", 1),
        "url": story["url"],
        "published": story["published"],
    }


def write_outputs(stories: list[dict], day: str, config: dict) -> Path:
    leads = config.get("leads", 3)
    DATA.mkdir(parents=True, exist_ok=True)

    brief = {
        "date": day,
        "dateLabel": datetime.strptime(day, "%Y-%m-%d").strftime("%A, %-d %B %Y"),
        "builtAt": datetime.now(IST).isoformat(),
        "standfirst": build_standfirst(stories),
        "sectors": sorted({s["sector"] for s in stories}),
        "stories": [to_public(s, i < leads) for i, s in enumerate(stories)],
    }

    day_file = DATA / f"{day}.json"
    day_file.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")

    dates = sorted(
        (p.stem for p in DATA.glob("*.json") if p.stem != "index"), reverse=True
    )
    index = {
        "updated": datetime.now(IST).isoformat(),
        "latest": dates[0] if dates else day,
        "dates": dates,
    }
    (DATA / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return day_file


# -------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the daily news brief.")
    parser.add_argument("--config", default=str(ROOT / "sources.yml"))
    parser.add_argument("--date", help="YYYY-MM-DD; defaults to today in IST")
    parser.add_argument("--fixtures", help="read local .xml files instead of the network")
    parser.add_argument("--no-why", action="store_true", help="skip the model call")
    args = parser.parse_args()

    day = args.date or datetime.now(IST).strftime("%Y-%m-%d")
    fixtures = Path(args.fixtures).resolve() if args.fixtures else None
    config = load_config(Path(args.config))

    print(f"Building the brief for {day}", file=sys.stderr)
    items = collect(config, fixtures)
    if not items:
        print("No stories found — leaving the existing data untouched.", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    stories = select(rank(cluster(items), now), config)

    if not args.no_why:
        add_why(stories)

    path = write_outputs(stories, day, config)
    print(f"Wrote {len(stories)} stories to {path.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
