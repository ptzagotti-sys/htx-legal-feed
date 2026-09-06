#!/usr/bin/env python3
"""Build an RSS feed for htx-legal.net/insights.

The Hostinger site builder does not publish a feed, but it embeds every blog
post's metadata in the /insights page HTML. This script parses that data,
keeps published (non-draft, date in the past) posts, and writes feed.xml.
"""
import html, json, re, sys, urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime

SITE = "https://htx-legal.net"
SRC = SITE + "/insights"
OUT = "feed.xml"
LIMIT = 30

Q = r'"(?:[^"\\]|\\.)*"'          # a JSON string literal
S = lambda k: rf'"{k}":\[0,({Q})\]'  # Astro serialized string field
B = lambda k: rf'"{k}":\[0,(true|false)\]'

def fetch():
    req = urllib.request.Request(SRC, headers={"User-Agent": "Mozilla/5.0 (feed builder)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return html.unescape(r.read().decode("utf-8", "replace"))

def js(s):
    return json.loads(s)

def parse(page):
    posts = []
    for m in re.finditer(r'"type":\[0,"blog"\],' + S("name") + ',' + S("slug") + ',' + S("date") + ',' + B("isDraft") + ',' + B("isScheduled"), page):
        name, slug, date, draft, sched = m.groups()
        tail = page[m.end(): m.end() + 6000]
        desc = re.search(r'"meta":\[0,\{"title":\[0,' + Q + r'\],"description":\[0,(' + Q + r')\]', tail)
        cover = re.search(S("coverImageOrigin") + r'.*?' + S("coverImageAlt"), tail)
        posts.append({
            "title": js(name), "slug": js(slug), "date": js(date),
            "draft": draft == "true", "scheduled": sched == "true",
            "description": js(desc.group(1)) if desc else "",
        })
    return posts

def main():
    page = fetch()
    posts = parse(page)
    now = datetime.now(timezone.utc)
    live = []
    for p in posts:
        if p["draft"]:
            continue
        try:
            dt = datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt > now:
            continue
        p["dt"] = dt
        live.append(p)
    live.sort(key=lambda p: p["dt"], reverse=True)
    live = live[:LIMIT]

    def esc(s): return html.escape(s, quote=False)
    items = []
    for p in live:
        url = f"{SITE}/{p['slug']}"
        items.append(f"""  <item>
    <title>{esc(p['title'])}</title>
    <link>{url}</link>
    <guid isPermaLink="true">{url}</guid>
    <pubDate>{format_datetime(p['dt'])}</pubDate>
    <description>{esc(p['description'])}</description>
  </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>North Star Law Firm Insights</title>
  <link>{SRC}</link>
  <description>Business tax and bankruptcy insights from North Star Law Firm, Houston</description>
  <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(feed)
    print(f"parsed {len(posts)} posts, {len(live)} live, wrote {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
