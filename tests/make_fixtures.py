#!/usr/bin/env python3
"""Generate offline RSS fixtures so the builder can be tested without network.

Timestamps are written relative to "now", so the fixtures never age out of the
26-hour window. Two stories appear in several feeds on purpose — that is what
exercises the clustering and the coverage score.

    python tests/make_fixtures.py && python scripts/build_brief.py --fixtures tests/fixtures --no-why
"""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "fixtures"
NOW = datetime.now(timezone.utc)

# (filename, feed title, [(hours_ago, headline, description), ...])
FEEDS = [
    (
        "et-markets.xml",
        "ET Markets",
        [
            (4, "Nifty snaps four-day winning streak, ends at 23,329 as IT drags",
             "The Sensex fell 330 points. Nifty IT was the worst performing sector while realty led gains."),
            (5, "NSE IPO closes with 5.7 times subscription, all portions fully booked",
             "India's largest offer at Rs 22,562 crore drew bids for 50.58 crore shares against 8.86 crore on offer."),
            (7, "Defence stocks rally up to 10%; Unimech Aerospace, Apollo Micro Systems surge",
             "Order book visibility continues to drive the defence pack against a weak broader market."),
            (9, "Sterling and Wilson jumps 7.7% after winning Rs 985 crore of orders",
             "JSW Infrastructure rose 7.4% to Rs 375.50, now up 57% so far in FY27."),
        ],
    ),
    (
        "business-standard-markets.xml",
        "Business Standard Markets",
        [
            (3, "Stock Market Close: Nifty ends at 23,329, Sensex falls 330 points on IT weakness",
             "HCLTech, Tech Mahindra and Infosys led the declines on the Nifty50."),
            (6, "NSE's Rs 22,562-crore IPO subscribed 5.71 times as books close",
             "Investors accepted a valuation multiple above Nasdaq's on the strength of derivatives volumes."),
            (11, "India's crude oil import bill rises 48.4% to $74.8 billion in April-August",
             "Higher Brent prices and steady volume growth widened the bill over the first five months of FY27."),
        ],
    ),
    (
        "global-macro.xml",
        "Global macro",
        [
            (14, "Fed delivers first rate hike in three years as yields push past 5% - Reuters",
             "Markets are pricing a 54% chance of another quarter-point increase at the October meeting."),
            (15, "Dow posts worst week since March as crude holds above $100 - Bloomberg",
             "The Dow fell 1.7% on the week. The S&P 500 slipped 0.1% while the Nasdaq gained 0.7%."),
            (16, "US industrial production flat in August, missing forecasts - CNBC",
             "Manufacturing output contracted 0.3% and capacity utilisation held at 76.3%."),
        ],
    ),
    (
        "indian-it-services.xml",
        "Indian IT services",
        [
            (8, "Nifty IT falls again as Infosys, HCLTech slide on US spending freeze - Mint",
             "The sector remains India's worst performer of 2026 amid AI-driven pricing deflation in services deals."),
            (20, "Why India's IT majors are worried about AI-driven deflation - Forbes India",
             "Pricing pressure is reshaping growth as clients expect AI productivity gains to be passed on."),
        ],
    ),
    (
        "ipos-and-m-a.xml",
        "IPOs and M&A",
        [
            (6, "NSE IPO draws 5.7 times subscription as $2.4 billion offer closes - Bloomberg",
             "The exchange that lists India's biggest companies is finally listing itself."),
            (10, "Snapdeal parent AceVector seeks $182 million valuation, IPO opens September 25 - Moneycontrol",
             "A steep markdown from the company's private market peak."),
            (12, "Spinny confidentially pre-files for IPO - Entrackr",
             "The used-car platform joins a crowded 2026 listing pipeline."),
        ],
    ),
    (
        "pharma.xml",
        "Pharma",
        [
            (7, "ChrysCapital to steer 20-25% of new $2.2 billion fund into pharma and healthcare - Business Today",
             "The PE firm is backing CDMO, hospitals and diagnostics as its highest conviction India theme."),
            (18, "Indian pharma warns price hikes likely as energy costs surge - Whalesbook",
             "Power and fuel costs are feeding into API economics while output prices stay capped under NPPA rules."),
        ],
    ),
    (
        "startup-funding.xml",
        "Startup funding",
        [
            (9, "Definedge raises Rs 22 crore - StartupTalky",
             "The trading analytics platform closed a small round led by existing backers."),
            (22, "Flam raises $40 million as SEBI clears Fibe's Rs 750 crore IPO - Inc42",
             "Two more names move through a busy September for Indian startup financing."),
        ],
    ),
    (
        "the-hindu-national.xml",
        "The Hindu National",
        [
            (5, "President Murmu presents 72nd National Film Awards at Kevadia",
             "Article 370 won Best Feature Film at the ceremony in Ekta Nagar, Gujarat."),
            (13, "Jaishankar leads India's delegation at UN General Assembly high-level week",
             "Trade, multilateral reform and regional security are on the agenda in New York."),
            (17, "IMD issues heavy rainfall warnings for Telangana, Chhattisgarh and Kerala",
             "Significant rain is expected over the coming days as the monsoon withdraws unevenly."),
        ],
    ),
]

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{title}</title>
    <link>https://example.test/</link>
    <description>Offline fixture</description>
{items}  </channel>
</rss>
"""

ITEM = """    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{description}</description>
      <pubDate>{pub}</pubDate>
      <guid isPermaLink="false">{guid}</guid>
    </item>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, feed_title, entries in FEEDS:
        items = ""
        for n, (hours, headline, description) in enumerate(entries):
            slug = filename.replace(".xml", "")
            items += ITEM.format(
                title=escape(headline),
                link=f"https://example.test/{slug}/{n}",
                description=escape(description),
                pub=format_datetime(NOW - timedelta(hours=hours)),
                guid=f"{slug}-{n}",
            )
        (OUT / filename).write_text(
            TEMPLATE.format(title=escape(feed_title), items=items), encoding="utf-8"
        )
    print(f"Wrote {len(FEEDS)} fixture feeds to {OUT}")


if __name__ == "__main__":
    main()
