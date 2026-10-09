"""Research what top YouTube Shorts like ours use for titles, tags and hashtags.

Usage: python yt_research.py <out.md> "<search 1>" ["<search 2>" ...] [--top N]

Runs each search on YouTube (under-4-minute filter), opens every result's watch page,
keeps the Shorts (3 minutes or less) and ranks them by views. Tags are hidden from
viewers but present in the page data, so this reads them directly. Writes:
  <out.md>   - the top N (default 30): views, length, title, channel, tags, plus a
               pattern summary (how many skip tags, title length, top hashtags/tags)
  <out>.json - every Short found, for re-slicing later
Pick searches that describe the clip's game and kind of moment ("valheim troll",
"valheim funny shorts", "arc raiders funny"), not our own title. Run it once per game per
batch and reuse the results for every short from that game: it loads ~25 pages per search,
and too many in a row gets YouTube's bot check, which this stops on rather than works around.
"""
import collections
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


class Blocked(Exception):
    pass


def get(url):
    time.sleep(0.6)  # stay polite: a burst of ~150 fast page loads got this network a "please verify" check
    page = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", UA, "-H", "Accept-Language: en-US,en",
                           "-H", "Cookie: CONSENT=YES+1; SOCS=CAI", url], capture_output=True).stdout.decode("utf8", "ignore")
    if "unusual traffic" in page[:20000].lower():
        # YouTube's bot check (a CAPTCHA). Never try to get past it - stop and wait it out.
        raise Blocked("YouTube is showing its 'unusual traffic' check; wait a while (it clears on its own) and re-run")
    return page


def search(q):
    html = get("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q) + "&sp=EgIYAQ%253D%253D")
    return list(dict.fromkeys(re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)))[:25]


def details(vid):
    h = get("https://www.youtube.com/watch?v=" + vid)
    i = h.find('"videoDetails":')
    if i < 0:
        return None
    try:
        d, _ = json.JSONDecoder().raw_decode(h[i + len('"videoDetails":'):])
    except ValueError:
        return None
    up = re.search(r'"uploadDate":"([^"]*)"', h)
    likes = re.search(r'"likeCount":"?(\d+)', h)
    title, desc = d.get("title", ""), d.get("shortDescription") or ""
    return {"id": vid, "title": title, "channel": d.get("author"), "views": int(d.get("viewCount") or 0),
            "likes": int(likes.group(1)) if likes else None, "seconds": int(d.get("lengthSeconds") or 0),
            "tags": d.get("keywords") or [], "hashtags": re.findall(r"#\w+", title + " " + desc),
            "desc_len": len(desc), "uploaded": up.group(1)[:10] if up else None}


def report(shorts, queries, top_n):
    top = shorts[:top_n]
    n = len(top)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0
    lines = ["# Top Shorts: titles and tags", "",
             f"Searches: {', '.join(queries)}. {len(shorts)} Shorts found, ranked by views.", "",
             "| # | Views | Length | Title | Channel | Tags |", "|---|---|---|---|---|---|"]
    for i, x in enumerate(top, 1):
        tags = ", ".join(x["tags"]) if x["tags"] else "*(none)*"
        lines.append(f"| {i} | {x['views']:,} | {x['seconds']}s | {x['title'].replace('|', '/')} | "
                     f"{x['channel']} | {tags.replace('|', '/')} |")
    hashtags = collections.Counter(h.lower() for x in top for h in set(x["hashtags"]))
    tags = collections.Counter(t.lower() for x in top for t in x["tags"])
    lines += ["", f"## Patterns in the top {n}", "",
              f"- **No tags:** {sum(1 for x in top if not x['tags'])} of {n}. "
              f"**Empty description:** {sum(1 for x in top if x['desc_len'] == 0)} of {n}.",
              f"- **Title length:** median {med([len(x['title']) for x in top])} characters.",
              f"- **Hashtags:** median {med([len(x['hashtags']) for x in top])}; most used: "
              + ", ".join(f"{h} ({c})" for h, c in hashtags.most_common(8)) + ".",
              "- **Most-used tags:** " + ", ".join(f"{t} ({c})" for t, c in tags.most_common(12)) + ".",
              f"- **Length:** median {med([x['seconds'] for x in top])}s."]
    return "\n".join(lines) + "\n"


def main():
    args = sys.argv[1:]
    top_n = 30
    if "--top" in args:
        k = args.index("--top")
        top_n = int(args[k + 1])
        del args[k:k + 2]
    out, queries = args[0], args[1:]
    ids = []
    for q in queries:
        found = search(q)
        print(f"  {q!r}: {len(found)} results", flush=True)
        ids += [v for v in found if v not in ids]
    with ThreadPoolExecutor(2) as ex:
        rows = [r for r in ex.map(details, ids) if r]
    shorts = sorted([r for r in rows if 0 < r["seconds"] <= 180], key=lambda r: -r["views"])
    json.dump(shorts, open(os.path.splitext(out)[0] + ".json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    open(out, "w", encoding="utf-8").write(report(shorts, queries, top_n))
    print(f"{len(ids)} videos, {len(shorts)} Shorts; wrote {out}")


if __name__ == "__main__":
    try:
        main()
    except Blocked as e:
        raise SystemExit(f"stopped: {e}")
