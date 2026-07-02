#!/usr/bin/env python3
"""
Hero's Progress Log — self-hosted GitHub stats card for @cyberzal1.

Zero dependencies (Python 3 stdlib only). Two data modes:
  1. GITHUB_TOKEN set (e.g. inside GitHub Actions)  -> GraphQL API (exact)
  2. No token (e.g. run locally)                    -> scrapes public pages

Output: hero-progress.svg  (commit it, embed it in your profile README)
"""

import json
import math
import os
import re
import sys
import urllib.request
from datetime import date, timedelta

USERNAME = os.environ.get("GH_USERNAME", "cyberzal1")
OUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero-progress.svg")
UA = {"User-Agent": "hero-progress-card/1.0"}


def http_get(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


# ----------------------------------------------------------------------------
# Data collection
# ----------------------------------------------------------------------------

def fetch_via_graphql(token):
    """Exact numbers via the GitHub GraphQL API (used in Actions)."""
    query = """
    query($login: String!) {
      user(login: $login) {
        followers { totalCount }
        repositories(privacy: PUBLIC, ownerAffiliations: OWNER) { totalCount }
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"login": USERNAME}}).encode()
    resp = json.loads(http_get(
        "https://api.github.com/graphql",
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
        data=body,
    ))
    user = resp["data"]["user"]
    daily = {}
    for week in user["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for d in week["contributionDays"]:
            daily[d["date"]] = d["contributionCount"]
    return {
        "daily": daily,
        "followers": user["followers"]["totalCount"],
        "repos": user["repositories"]["totalCount"],
    }


def fetch_via_scrape():
    """No-token fallback: parse the public contribution calendar + profile."""
    html = http_get(f"https://github.com/users/{USERNAME}/contributions")
    cells = dict(re.findall(
        r'data-date="([0-9-]+)" id="(contribution-day-component-[\d-]+)"', html))
    id2date = {v: k for k, v in cells.items()}
    daily = {}
    for cid, text in re.findall(
            r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]+)</tool-tip>', html):
        d = id2date.get(cid)
        m = re.match(r"(\d+|No) contribution", text.strip())
        if d and m:
            daily[d] = 0 if m.group(1) == "No" else int(m.group(1))

    followers = repos = 0
    try:
        prof = http_get(f"https://github.com/{USERNAME}")
        m = re.search(r"(\d+)\s*</span>\s*follower", prof)
        followers = int(m.group(1)) if m else 0
        m = re.search(r'Repositories\s*<span[^>]*>\s*(\d+)', prof)
        repos = int(m.group(1)) if m else 0
    except Exception as e:  # non-fatal: card still renders
        print(f"[warn] profile scrape failed: {e}", file=sys.stderr)
    return {"daily": daily, "followers": followers, "repos": repos}


def compute_stats(raw):
    daily = raw["daily"]
    dates = sorted(daily)
    latest = date.fromisoformat(dates[-1])
    year = latest.year

    total = sum(daily.values())
    ytd = sum(v for d, v in daily.items() if d >= f"{year}-01-01")
    active_days = sum(1 for v in daily.values() if v > 0)
    best_date = max(daily, key=daily.get)
    best_count = daily[best_date]

    # Current streak: count back from the latest day (skip it if 0 so far today).
    cur, d = 0, latest
    if daily.get(d.isoformat(), 0) == 0:
        d -= timedelta(days=1)
    while daily.get(d.isoformat(), 0) > 0:
        cur += 1
        d -= timedelta(days=1)

    longest = run = 0
    for dt in dates:
        run = run + 1 if daily[dt] > 0 else 0
        longest = max(longest, run)

    # RPG level curve: reaching level N costs N^2 XP (1 XP = 1 contribution).
    level = max(1, int(math.isqrt(total)))
    floor_xp, next_xp = level ** 2, (level + 1) ** 2
    pct = 0.0 if next_xp == floor_xp else (total - floor_xp) / (next_xp - floor_xp)

    return {
        "total": total, "ytd": ytd, "year": year,
        "active_days": active_days,
        "best_count": best_count,
        "cur_streak": cur, "longest_streak": longest,
        "level": level, "next_xp": next_xp, "pct": max(0.0, min(1.0, pct)),
        "followers": raw["followers"], "repos": raw["repos"],
        "window": f"{date.fromisoformat(dates[0]):%b '%y} – {latest:%b '%y}".upper(),
        "updated": f"{latest:%d %b %Y}".upper(),
    }


# ----------------------------------------------------------------------------
# SVG rendering
# ----------------------------------------------------------------------------

VOID, PANEL, LINE = "#0d1117", "#131a24", "#1e2836"
ARCANE, CYBER = "#bb2acf", "#22d3ee"          # his purple + his cyan
TEXT, MUTED = "#e6edf3", "#7d8590"
MONO = "ui-monospace,'Cascadia Mono','Segoe UI Mono',Menlo,Consolas,monospace"

QUOTE = ("Even if the odds are against me, as long as I hold the CyberShield, "
         "I'll stand guard over the digital frontier.")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def stat_cell(x, y, value, label, sub):
    return f"""
  <g transform="translate({x},{y})">
    <rect width="124" height="84" rx="8" fill="{PANEL}" stroke="{LINE}"/>
    <text x="62" y="38" text-anchor="middle" font-family="{MONO}"
          font-size="26" font-weight="700" fill="{TEXT}">{value}</text>
    <text x="62" y="56" text-anchor="middle" font-family="{MONO}"
          font-size="10" letter-spacing="2" fill="{CYBER}">{label}</text>
    <text x="62" y="71" text-anchor="middle" font-family="{MONO}"
          font-size="8" letter-spacing="0.5" fill="{MUTED}">{sub}</text>
  </g>"""


def wrap_two(text, limit=70):
    """Split text into two lines at the word boundary nearest `limit`."""
    if len(text) <= limit:
        return text, ""
    cut = text.rfind(" ", 0, limit + 1)
    cut = limit if cut == -1 else cut
    return text[:cut], text[cut + 1:]


def render(s):
    q1, q2 = wrap_two(QUOTE)
    bar_w = 336
    fill_w = round(bar_w * s["pct"], 1)
    cells = [
        (s["total"],          "YEAR XP",  "PAST-YEAR CONTRIBS"),
        (s["ytd"],            f"{s['year']} XP", "YTD CONTRIBS"),
        (s["repos"],          "QUESTS",   "PUBLIC REPOS"),
        (s["longest_streak"], "COMBO",    "BEST STREAK · DAYS"),
        (s["best_count"],     "CRIT",     "BEST DAY · CONTRIBS"),
        (s["followers"],      "ALLIES",   "FOLLOWERS"),
    ]
    grid = ""
    for i, (v, lab, sub) in enumerate(cells):
        gx, gy = 420 + (i % 3) * 132, 84 + (i // 3) * 94
        grid += stat_cell(gx, gy, v, lab, sub)

    return f"""<svg width="840" height="330" viewBox="0 0 840 330"
     xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="Hero's Progress Log: live GitHub stats for {USERNAME}">
  <defs>
    <linearGradient id="xp" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{ARCANE}"/><stop offset="1" stop-color="{CYBER}"/>
    </linearGradient>
    <linearGradient id="name" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{CYBER}"/><stop offset="1" stop-color="{ARCANE}"/>
    </linearGradient>
  </defs>
  <style>
    .fill {{ transform: scaleX(0); transform-box: fill-box; transform-origin: left center;
             animation: xpfill 1.6s cubic-bezier(.2,.8,.2,1) .3s forwards; }}
    .dot  {{ animation: pulse 2s ease-in-out infinite; }}
    .scan {{ animation: sweep 9s linear infinite; }}
    @keyframes xpfill {{ to {{ transform: scaleX(1); }} }}
    @keyframes pulse  {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.25 }} }}
    @keyframes sweep  {{ from {{ transform: translateY(-10px) }}
                         to   {{ transform: translateY(340px) }} }}
    @media (prefers-reduced-motion: reduce) {{
      .fill {{ animation: none; transform: scaleX(1); }}
      .dot, .scan {{ animation: none; }}
    }}
  </style>

  <rect width="840" height="330" rx="12" fill="{VOID}" stroke="{LINE}"/>

  <!-- header -->
  <text x="32" y="40" font-family="{MONO}" font-size="12" letter-spacing="3"
        fill="{MUTED}"><tspan fill="{ARCANE}">//</tspan> HERO'S PROGRESS LOG</text>
  <circle class="dot" cx="676" cy="36" r="4" fill="#22c55e"/>
  <text x="688" y="40" font-family="{MONO}" font-size="11" letter-spacing="2"
        fill="{CYBER}">STATUS: ONLINE</text>
  <line x1="32" y1="58" x2="808" y2="58" stroke="{LINE}"/>

  <!-- identity -->
  <text x="32" y="106" font-family="{MONO}" font-size="27" font-weight="800"
        letter-spacing="1" fill="url(#name)">CYBERZAL</text>
  <text x="32" y="128" font-family="{MONO}" font-size="11" letter-spacing="2"
        fill="{MUTED}">CLASS · CYBER SECURITY OPS</text>

  <!-- level + XP -->
  <text x="32" y="180" font-family="{MONO}" font-size="13" font-weight="700"
        fill="{ARCANE}">LV</text>
  <text x="56" y="180" font-family="{MONO}" font-size="36" font-weight="800"
        fill="{ARCANE}">{s['level']}</text>
  <text x="368" y="178" text-anchor="end" font-family="{MONO}" font-size="11"
        fill="{MUTED}">{s['total']} / {s['next_xp']} XP</text>
  <rect x="32" y="190" width="{bar_w}" height="10" rx="5" fill="{PANEL}"
        stroke="{LINE}"/>
  <rect class="fill" x="32" y="190" width="{fill_w}" height="10" rx="5"
        fill="url(#xp)"/>
  <text x="32" y="216" font-family="{MONO}" font-size="10" letter-spacing="1"
        fill="{MUTED}">{s['next_xp'] - s['total']} XP TO LEVEL {s['level'] + 1}</text>
  <text x="32" y="240" font-family="{MONO}" font-size="10" letter-spacing="1"
        fill="{MUTED}">ACTIVE {s['active_days']} DAYS · {s['window']}</text>

  <!-- stat grid -->{grid}

  <!-- quote -->
  <line x1="32" y1="272" x2="808" y2="272" stroke="{LINE}"/>
  <rect x="32" y="288" width="3" height="26" fill="{CYBER}"/>
  <text x="46" y="299" font-family="{MONO}" font-size="10.5" font-style="italic"
        fill="{MUTED}">&#8220;{esc(q1)}</text>
  <text x="46" y="313" font-family="{MONO}" font-size="10.5" font-style="italic"
        fill="{MUTED}">{esc(q2)}&#8221;</text>
  <text x="808" y="313" text-anchor="end" font-family="{MONO}" font-size="9"
        letter-spacing="1" fill="{MUTED}">SYNCED {s['updated']}</text>

  <!-- signature scanline -->
  <rect class="scan" x="1" y="0" width="838" height="2" fill="{CYBER}"
        opacity="0.12"/>
</svg>
"""


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        print("[mode] GraphQL API (token found)")
        raw = fetch_via_graphql(token)
    else:
        print("[mode] public scrape (no token)")
        raw = fetch_via_scrape()

    stats = compute_stats(raw)
    print("[stats]", {k: v for k, v in stats.items() if k != "window"})

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(render(stats))
    print(f"[done] wrote {OUT_FILE}")


if __name__ == "__main__":
    main()
