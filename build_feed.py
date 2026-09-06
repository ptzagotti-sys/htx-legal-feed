#!/usr/bin/env python3
"""Build a combined RSS feed for htx-legal.net and nm-legal.net.

htx-legal.net (Hostinger builder) publishes no feed, but embeds every blog
post's metadata in the /insights page HTML; this script parses that data.
nm-legal.net (WordPress) has a native feed, which is merged in. Published
posts from both sites are sorted newest first and written to feed.xml.
"""
import html, json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from email.utils import format_datetime

SITE = "https://htx-legal.net"
SRC = SITE + "/insights"
NM_FEED = "https://nm-legal.net/feed/"
OUT = "feed.xml"
LIMIT = 40

Q = r'"(?:[^"\\]|\\.)*"'          # a JSON string literal
S = lambda k: rf'"{k}":\[0,({Q})\]'  # Astro serialized string field
B = lambda k: rf'"{k}":\[0,(true|false)\]'

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (feed builder)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")

def fetch():
    return html.unescape(get(SRC))

def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()

def nm_posts():
    """Items from the nm-legal.net WordPress feed, normalized to the same shape."""
    try:
        root = ET.fromstring(get(NM_FEED).encode("utf-8"))
    except Exception as e:
        print(f"nm-legal.net feed failed: {e}", file=sys.stderr)
        return []
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        pub = it.findtext("pubDate")
        if not (link and title and pub):
            continue
        try:
            dt = parsedate_to_datetime(pub)
        except Exception:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append({"title": title, "url": link, "dt": dt,
                    "description": strip_tags(it.findtext("description")), "draft": False})
    return out

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
        p["url"] = f"{SITE}/{p['slug']}"
        live.append(p)
    now = datetime.now(timezone.utc)
    live += [p for p in nm_posts() if p["dt"] <= now]
    live.sort(key=lambda p: p["dt"], reverse=True)
    live = live[:LIMIT]

    def esc(s): return html.escape(s, quote=False)
    items = []
    for p in live:
        url = p["url"]
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
  <description>Tax, bankruptcy, and SBA debt insights from North Star Law Firm (htx-legal.net and nm-legal.net)</description>
  <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(feed)
    print(f"htx parsed {len(posts)}, combined live {len(live)}, wrote {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
