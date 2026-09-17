#!/usr/bin/env python3
"""Render a commit-rhythm SVG card from the GitHub GraphQL API.

The metrics `habits` plugin relies on the Events API, which no longer exposes
`payload.commits`, so commit timing is fetched from the commit history of every
repository the token can see (private ones included).

Env:
  GITHUB_TOKEN  PAT with repo + read:user scope
  GH_LOGIN      user whose commits are counted (default: Flogss)
  TZ_OFFSET     hours added to UTC timestamps (default: 2, Europe/Paris DST)
  OUT           output path (default: metrics/rhythm.svg)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

API = "https://api.github.com/graphql"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
LOGIN = os.environ.get("GH_LOGIN", "Flogss")
TZ = timezone(timedelta(hours=float(os.environ.get("TZ_OFFSET", "2"))))
OUT = os.environ.get("OUT", "metrics/rhythm.svg")

# Only repos touched in the last N days are worth paginating through.
HISTORY_CAP = 2000  # max commits pulled per repository

BG = "#000000"
FG = "#ffffff"
DIM = "#8b949e"
ACCENT = "#ff0000"
GRID = "#21262d"


def graphql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": f"{LOGIN}-commit-rhythm",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"GraphQL HTTP {exc.code}: {exc.read().decode()[:500]}")
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {json.dumps(payload['errors'])[:500]}")
    return payload["data"]


VIEWER = """
query($login:String!) {
  user(login:$login) { id }
}
"""

REPOS = """
query($login:String!, $cursor:String) {
  user(login:$login) {
    repositories(first:50, after:$cursor, ownerAffiliations:OWNER, isFork:false,
                 orderBy:{field:PUSHED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { name isEmpty defaultBranchRef { name } }
    }
  }
}
"""

HISTORY = """
query($owner:String!, $name:String!, $author:ID!, $cursor:String) {
  repository(owner:$owner, name:$name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first:100, after:$cursor, author:{id:$author}) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate }
          }
        }
      }
    }
  }
}
"""


def fetch_repos():
    cursor, repos = None, []
    while True:
        data = graphql(REPOS, {"login": LOGIN, "cursor": cursor})["user"]["repositories"]
        for node in data["nodes"]:
            if not node["isEmpty"] and node["defaultBranchRef"]:
                repos.append(node["name"])
        if not data["pageInfo"]["hasNextPage"]:
            return repos
        cursor = data["pageInfo"]["endCursor"]


def fetch_commit_dates(repo, author_id):
    cursor, dates = None, []
    while len(dates) < HISTORY_CAP:
        ref = graphql(
            HISTORY,
            {"owner": LOGIN, "name": repo, "author": author_id, "cursor": cursor},
        )["repository"]["defaultBranchRef"]
        if not ref or not ref["target"]:
            return dates
        history = ref["target"]["history"]
        dates += [n["committedDate"] for n in history["nodes"]]
        if not history["pageInfo"]["hasNextPage"]:
            return dates
        cursor = history["pageInfo"]["endCursor"]
    return dates


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def bars(counts, labels, x0, y0, width, height, highlight=None):
    """Horizontal-axis bar chart as raw SVG elements."""
    peak = max(counts) or 1
    slot = width / len(counts)
    bar_w = slot * 0.62
    out = []
    for i, value in enumerate(counts):
        h = (value / peak) * height
        x = x0 + i * slot + (slot - bar_w) / 2
        y = y0 + height - h
        opacity = "1" if (highlight is None or i == highlight) else "0.55"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 1):.1f}" '
            f'rx="1.5" fill="{ACCENT}" opacity="{opacity}"/>'
        )
    for i, label in enumerate(labels):
        if label is None:
            continue
        x = x0 + i * slot + slot / 2
        out.append(
            f'<text x="{x:.1f}" y="{y0 + height + 13}" fill="{DIM}" font-size="9" '
            f'text-anchor="middle">{esc(label)}</text>'
        )
    return "\n".join(out)


def render(total, year, hours, weekdays, streak_days, active_repos, peak_hour, peak_day):
    w, h = 840, 300
    hour_labels = [str(i) if i % 3 == 0 else None for i in range(24)]
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    def stat(x, value, label):
        return (
            f'<text x="{x}" y="86" fill="{ACCENT}" font-size="26" font-weight="700">{esc(value)}</text>'
            f'<text x="{x}" y="104" fill="{DIM}" font-size="10.5" letter-spacing="0.6">{esc(label)}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="'JetBrains Mono','SFMono-Regular',Consolas,monospace">
  <rect width="{w}" height="{h}" rx="8" fill="{BG}" stroke="{GRID}"/>

  <text x="28" y="38" fill="{FG}" font-size="15" font-weight="700">Commit rhythm</text>
  <text x="28" y="55" fill="{DIM}" font-size="10">{esc(LOGIN)} · default-branch history across every repo · private included</text>
  <line x1="28" y1="64" x2="{w - 28}" y2="64" stroke="{GRID}"/>

  {stat(28, f"{total:,}".replace(",", " "), "TOTAL COMMITS")}
  {stat(190, f"{year:,}".replace(",", " "), "LAST 365 DAYS")}
  {stat(330, streak_days, "ACTIVE DAYS / YR")}
  {stat(500, active_repos, "REPOS COMMITTED")}
  {stat(660, f"{peak_hour:02d}h", "PEAK HOUR")}

  <line x1="28" y1="124" x2="{w - 28}" y2="124" stroke="{GRID}"/>

  <text x="28" y="148" fill="{FG}" font-size="11" font-weight="600">By hour of day</text>
  <text x="28" y="163" fill="{DIM}" font-size="9">local time · peak {peak_hour:02d}h</text>
  {bars(hours, hour_labels, 28, 172, 470, 82, highlight=peak_hour)}

  <text x="556" y="148" fill="{FG}" font-size="11" font-weight="600">By weekday</text>
  <text x="556" y="163" fill="{DIM}" font-size="9">peak {esc(day_labels[peak_day])}</text>
  {bars(weekdays, day_labels, 556, 172, 256, 82, highlight=peak_day)}
</svg>
"""


def main():
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is required")

    author_id = graphql(VIEWER, {"login": LOGIN})["user"]["id"]
    repos = fetch_repos()

    stamps = []
    committed_repos = 0
    for repo in repos:
        dates = fetch_commit_dates(repo, author_id)
        if dates:
            committed_repos += 1
        stamps += dates

    if not stamps:
        sys.exit("no commits found — check the token's scopes")

    parsed = [
        datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ) for s in stamps
    ]
    cutoff = datetime.now(TZ) - timedelta(days=365)
    recent = [d for d in parsed if d >= cutoff]

    hours = Counter(d.hour for d in parsed)
    weekdays = Counter(d.weekday() for d in parsed)
    hour_counts = [hours.get(i, 0) for i in range(24)]
    day_counts = [weekdays.get(i, 0) for i in range(7)]

    svg = render(
        total=len(parsed),
        year=len(recent),
        hours=hour_counts,
        weekdays=day_counts,
        streak_days=len({d.date() for d in recent}),
        active_repos=committed_repos,
        peak_hour=hour_counts.index(max(hour_counts)),
        peak_day=day_counts.index(max(day_counts)),
    )

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w") as fd:
        fd.write(svg)
    print(f"{OUT}: {len(parsed)} commits across {committed_repos} repos")


if __name__ == "__main__":
    main()
