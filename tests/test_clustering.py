#!/usr/bin/env python3
"""Regression test for story clustering.

The failure this guards against: greedy clustering that unions each new
member's tokens into the cluster's token set. The set grows without bound, the
overlap coefficient divides by the SMALLER set, and after a few merges any
headline sharing three words with the accumulated pile gets absorbed. On a real
run with 23 feeds this produced a single cluster claiming 69 outlets, mixing
eurozone bond yields with Autocar India.

Run:  python tests/test_clustering.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_brief import cluster, title_tokens  # noqa: E402

NOW = datetime.now(timezone.utc)

# Deliberately varied headlines across sectors, the way a real morning looks.
DISTINCT = [
    "Eurozone bond yields rise as oil prices rebound above $100",
    "Microsoft eyes north and west India for data centre expansion",
    "OpenAI calls for US to take lead in global technical standards",
    "From Maruti to Mahindra, top execs say GST 2.0 changed demand",
    "Rupee ends at record low against dollar on importer demand",
    "Gold holds near all-time high as investors seek safety",
    "Paytm shares rally 6% after brokerage upgrade",
    "Sun Pharma gets USFDA nod for generic oncology drug",
    "Adani Green commissions 500 MW solar capacity in Rajasthan",
    "Zomato quarterly loss narrows on advertising revenue growth",
    "SEBI tightens disclosure norms for portfolio managers",
    "Tata Steel to invest in Kalinganagar expansion phase two",
    "IndiGo adds 20 weekly flights to Southeast Asian destinations",
    "Nykaa appoints new chief financial officer",
    "Bharti Airtel wins spectrum in three circles at auction",
    "Wipro bags five-year deal with European retailer",
    "Monsoon withdrawal begins from northwest India, says IMD",
    "Parliament panel reviews data protection rules implementation",
    "Reliance Retail opens 200th store in tier-two cities",
    "ONGC discovers gas reserves in Krishna Godavari basin",
    "HUL raises prices of select detergent packs",
    "Ola Electric recalls scooters over battery fault",
    "Infosys names new head of financial services vertical",
    "India's services PMI eases to 58.4 in September",
    "Coal India output rises 7% year on year in August",
]

# Three stories that several outlets genuinely ran. These MUST merge.
DUPLICATES = [
    ("NSE IPO closes with 5.7 times subscription, all portions booked", "ET Markets"),
    ("NSE's Rs 22,562-crore IPO subscribed 5.71 times as books close", "Business Standard"),
    ("NSE IPO draws 5.7 times subscription as $2.4 billion offer closes", "Bloomberg"),
    ("Fed delivers first rate hike in three years as yields push past 5%", "Reuters"),
    ("Fed hikes rates for first time in three years, yields cross 5%", "Mint"),
    ("Nifty snaps four-day winning streak, ends at 23,329 as IT drags", "ET Markets"),
    ("Nifty ends at 23,329, Sensex falls 330 points on IT weakness", "Moneycontrol"),
]


# Volume is what triggers the drift: 23 feeds deliver roughly 400 items, and a
# cluster that accumulates tokens only becomes a magnet after dozens of merges.
# These share the vocabulary Indian business headlines actually share — shares,
# crore, India, quarter — without being the same story as each other.
COMPANIES = [
    "Reliance", "TCS", "HDFC Bank", "ICICI Bank", "Infosys", "ITC", "L&T",
    "Axis Bank", "Kotak Mahindra", "Bajaj Finance", "Maruti Suzuki", "Titan",
    "Asian Paints", "Nestle India", "Wipro", "UltraTech", "Grasim", "JSW Steel",
    "Hindalco", "Tech Mahindra", "Power Grid", "NTPC", "Coal India", "Cipla",
    "Dr Reddy's", "Divi's Labs", "Britannia", "Dabur", "Marico", "Godrej",
]
VERBS = [
    "approves", "flags", "completes", "expands", "defers", "wins", "explores",
    "halts", "revives", "doubles", "trims", "launches",
]
OBJECTS = [
    "capital expenditure plan", "margin guidance", "buyback programme",
    "manufacturing footprint", "dividend policy", "export order book",
    "retail partnership", "debt refinancing", "hiring target",
    "warehouse network", "battery venture", "cloud migration",
]
QUALIFIERS = [
    # Nothing here may echo a phrase used in DISTINCT, or the filler collides
    # with a real headline by construction and the test measures the generator
    # rather than the algorithm.
    "in Gujarat", "across eastern markets", "before the festive quarter",
    "citing input costs", "after regulatory clearance", "on weak demand",
    "with a Japanese partner", "ahead of the board meeting",
    "following the audit", "as volumes recover", "under the new tariff",
    "amid a leadership change",
]


def bulk_items():
    """~360 headlines with realistically low pairwise overlap.

    Index mixing with coprime strides means no two headlines share the same
    verb, object and qualifier — so any pair has at most a word or two in
    common, the way genuinely different stories do. If these cluster, the
    algorithm is drifting, not finding duplicates.
    """
    out = []
    n = 0
    for i, company in enumerate(COMPANIES):
        for j in range(12):
            verb = VERBS[(i * 5 + j) % len(VERBS)]
            obj = OBJECTS[(i * 7 + j * 3) % len(OBJECTS)]
            qual = QUALIFIERS[(i * 11 + j * 5) % len(QUALIFIERS)]
            # The trailing clause repeats the vocabulary real Indian business
            # headlines repeat, so the rarity counter sees those words at a
            # realistic frequency. Without it the corpus is unrealistically
            # varied and every word looks distinctive.
            out.append(
                f"{company} {verb} {obj} {qual}, shares rise 4 per cent "
                f"in India on crore inflows, sources say {900 + n}"
            )
            n += 1
    return out


# Different stories that happen to share the filler vocabulary every Indian
# business headline uses — shares, rise, India, crore, per cent. Raw word
# overlap says these match; nothing identifying is shared, so they must not.
COMMON_VOCAB = [
    "Tata Power shares rise 4 per cent as India adds solar capacity",
    "Bajaj Auto shares rise 4 per cent as India exports climb",
    "Vedanta shares rise 4 per cent as India demand improves",
]


def item(title, source, weight=2, hours=3):
    return {
        "title": title,
        "url": f"https://example.test/{abs(hash(title))}",
        "dek": "",
        "sector": "Markets",
        "source": source,
        "weight": weight,
        "published": None,
        "_at": NOW - timedelta(hours=hours),
        "_tokens": title_tokens(title),
    }


def main() -> int:
    items = [item(t, f"Outlet {i}") for i, t in enumerate(DISTINCT)]
    items += [item(t, src) for t, src in DUPLICATES]
    items += [item(t, f"Wire {i % 40}", hours=(i % 20) + 1) for i, t in enumerate(bulk_items())]
    items += [item(t, f"Common {i}") for i, t in enumerate(COMMON_VOCAB)]

    groups = cluster(items)
    sizes = sorted((len(g["members"]) for g in groups), reverse=True)
    failures = []

    # 1. Nothing exceeds the hard cap.
    if sizes[0] > 6:
        biggest = max(groups, key=lambda g: len(g["members"]))
        failures.append(
            f"cluster of {sizes[0]} exceeds MAX_CLUSTER:\n    "
            + "\n    ".join(m["title"][:70] for m in biggest["members"][:8])
        )

    # 2. The real drift test. The 25 hand-written DISTINCT headlines are about
    # genuinely different things, so not one of them may end up in a cluster
    # with anything else — including the bulk filler, which is only there to
    # apply volume pressure.
    for g in groups:
        contaminated = [m for m in g["members"] if m["title"] in DISTINCT]
        if contaminated and len(g["members"]) > 1:
            failures.append(
                "distinct story absorbed into a cluster:\n    "
                + "\n    ".join(m["title"][:70] for m in g["members"][:6])
            )

    # 2. The genuine duplicates still merge.
    def group_of(fragment):
        for g in groups:
            if any(fragment in m["title"] for m in g["members"]):
                return g
        return None

    for fragment, expected in (("NSE IPO closes", 3), ("Fed delivers", 2), ("Nifty snaps", 2)):
        g = group_of(fragment)
        got = len(g["members"]) if g else 0
        if got != expected:
            failures.append(
                f"'{fragment}' clustered {got} members, expected {expected}"
                + ("\n    " + "\n    ".join(m["title"] for m in g["members"]) if g else "")
            )

    # 3. Shared filler vocabulary is not evidence of a shared story.
    for g in groups:
        common = [m for m in g["members"] if m["title"] in COMMON_VOCAB]
        if len(common) > 1:
            failures.append(
                "merged on common vocabulary alone:\n    "
                + "\n    ".join(m["title"] for m in common)
            )

    # 4. The 25 distinct stories stay distinct.
    merged_distinct = [
        g for g in groups
        if len(g["members"]) > 1 and all(m["title"] in DISTINCT for m in g["members"])
    ]
    for g in merged_distinct:
        failures.append(
            "unrelated stories merged:\n    " + "\n    ".join(m["title"] for m in g["members"])
        )

    print(f"{len(items)} items -> {len(groups)} clusters; sizes {sizes[:6]}")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print("  - " + f)
        return 1
    print("PASSED: no runaway clusters, real duplicates merged, distinct stories kept apart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
