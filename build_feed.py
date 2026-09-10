#!/usr/bin/env python3
"""Build a combined RSS feed for htx-legal.net, nm-legal.net, and ca-legal.net.

htx-legal.net (Hostinger builder) publishes no feed, but embeds every blog
post's metadata in the /insights page HTML; this script parses that data.
nm-legal.net and ca-legal.net (WordPress) have native feeds, which are merged
in. Published posts from all sites are sorted newest first and written to
feed.xml.

Network fetches retry with backoff. If a source is unreachable after the
retries, the previous feed.xml is left untouched and the run exits cleanly,
so a transient outage never fails the Action or blanks the feed.
"""
import html, json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime, format_datetime
from datetime import datetime, timezone

SITE = "https://htx-legal.net"
SRC = SITE + "/insights"
NM_FEED = "https://nm-legal.net/feed/"
CA_FEED = "https://ca-legal.net/feed/"
# Only ca-legal.net posts dated on/after this go into the feed. The site launched
# with ten backdated posts (Aug 31 - Sep 9, 2026); without this cutoff dlvr.it
# would push all of them to LinkedIn at once. Set to None to disable.
CA_START = datetime(2026, 9, 10, tzinfo=timezone.utc)
OUT = "feed.xml"
LIMIT = 40
# Hostinger's bot filter returned 403 to a bare "feed builder" user agent from
# GitHub's runners, so present as an ordinary browser.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

Q = r'"(?:[^"\\]|\\.)*"'          # a JSON string literal
S = lambda k: rf'"{k}":\[0,({Q})\]'  # Astro serialized string field
B = lambda k: rf'"{k}":\[0,(true|false)\]'

def get(url, tries=4):
    """GET with retries: 4 attempts, waiting 5s, 15s, 45s between them."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            print(f"fetch {url} attempt {i+1}/{tries} failed: {e}", file=sys.stderr)
            if i < tries - 1:
                time.sleep(5 * 3 ** i)
    raise last

def fetch():
    return html.unescape(get(SRC))

def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()

def wp_posts(feed_url, start=None):
    """Items from a WordPress feed, normalized to the same shape as htx posts.
    If the fetch fails, returns [] so the other sites still publish."""
    try:
        root = ET.fromstring(get(feed_url).encode("utf-8"))
    except Exception as e:
        print(f"{feed_url} failed: {e}", file=sys.stderr)
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
        if start and dt < start:
            continue
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
    try:
        page = fetch()
    except Exception as e:
        # htx-legal.net is the primary source. Keep the last good feed rather
        # than publishing a feed with the htx posts missing.
        print(f"htx-legal.net unreachable, keeping existing {OUT}: {e}", file=sys.stderr)
        sys.exit(0 if os.path.exists(OUT) else 1)
    posts = parse(page)
    if not posts:
        print("htx-legal.net returned a page with no post data (layout change?), "
              f"keeping existing {OUT}", file=sys.stderr)
        sys.exit(0 if os.path.exists(OUT) else 1)
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
    live += [p for p in wp_posts(NM_FEED) if p["dt"] <= now]
    live += [p for p in wp_posts(CA_FEED, CA_START) if p["dt"] <= now]
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
  <description>Tax, bankruptcy, and SBA debt insights from North Star Law Firm (htx-legal.net, nm-legal.net, and ca-legal.net)</description>
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
