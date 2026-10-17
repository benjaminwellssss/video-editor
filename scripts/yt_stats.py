"""Pull your channel's per-video numbers so you can see which Shorts hook and hold people.

Usage: python yt_stats.py [--days 90] [--out <folder>]

Writes yt_stats_<date>.md and .csv (newest uploads first) with, per video: views, "stayed" (engaged views
divided by views - the API's closest stand-in for Studio's "viewed vs swiped away", which the API doesn't
expose), average % viewed, average watch time, subscribers gained per 1,000 views, likes, shares, comments.
Videos of 3 minutes or less are marked as Shorts.

One-time setup (YouTube needs your permission, so it can't be skipped):
1. In Google Cloud Console make a project, enable "YouTube Data API v3" and "YouTube Analytics API".
2. Create an OAuth client ID of type "Desktop app" and download its JSON.
3. Save it as ~/.config/video-editor/youtube_client_secret.json
The first run opens your browser to sign in; the token is kept next to that file. Neither is in any repo.
"""
import csv
import datetime as dt
import os
import re
import sys

CONF = os.path.join(os.path.expanduser("~"), ".config", "video-editor")
SECRET = os.path.join(CONF, "youtube_client_secret.json")
TOKEN = os.path.join(CONF, "youtube_token.json")
SCOPES = ["https://www.googleapis.com/auth/youtube.readonly", "https://www.googleapis.com/auth/yt-analytics.readonly"]
METRICS = "views,engagedViews,averageViewPercentage,averageViewDuration,subscribersGained,likes,shares,comments"
SHORT_MAX_S = 180


def seconds(iso):
    """ISO 8601 duration (PT1M5S) -> seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def row_stats(views, engaged, subs):
    stayed = engaged / views if views else 0.0
    per_k = subs * 1000 / views if views else 0.0
    return round(stayed * 100, 1), round(per_k, 2)


def credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not os.path.exists(SECRET):
            sys.exit(f"Missing {SECRET} - see the setup steps at the top of this script.")
        creds = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES).run_local_server(port=0)
    os.makedirs(CONF, exist_ok=True)
    open(TOKEN, "w").write(creds.to_json())
    return creds


def main():
    from googleapiclient.discovery import build
    args = sys.argv[1:]
    days = int(args[args.index("--days") + 1]) if "--days" in args else 90
    out_dir = args[args.index("--out") + 1] if "--out" in args else r"E:\Streaming\Videos\Analytics"
    creds = credentials()
    yt = build("youtube", "v3", credentials=creds)
    ya = build("youtubeAnalytics", "v2", credentials=creds)

    uploads = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    vids, page = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50, pageToken=page).execute()
        for it in r["items"]:
            published = dt.datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
            if published >= since:
                vids.append(it["contentDetails"]["videoId"])
        page = r.get("nextPageToken")
        if not page or (r["items"] and published < since):
            break
    if not vids:
        sys.exit(f"No uploads in the last {days} days.")

    info = {}
    for i in range(0, len(vids), 50):
        for v in yt.videos().list(part="snippet,contentDetails", id=",".join(vids[i:i + 50])).execute()["items"]:
            info[v["id"]] = {"title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"][:10],
                             "seconds": seconds(v["contentDetails"]["duration"])}

    rows = []
    start = min(x["published"] for x in info.values())
    for i in range(0, len(vids), 200):
        rep = ya.reports().query(ids="channel==MINE", startDate=start, endDate=dt.date.today().isoformat(),
                                 metrics=METRICS, dimensions="video", filters="video==" + ",".join(vids[i:i + 200]),
                                 maxResults=200).execute()
        heads = [h["name"] for h in rep.get("columnHeaders", [])]
        for r in rep.get("rows", []):
            d = dict(zip(heads, r))
            v = info.get(d["video"], {})
            stayed, per_k = row_stats(d["views"], d["engagedViews"], d["subscribersGained"])
            rows.append({"published": v.get("published", ""), "type": "Short" if v.get("seconds", 999) <= SHORT_MAX_S else "Long",
                         "length_s": v.get("seconds", 0), "title": v.get("title", d["video"]), "views": d["views"],
                         "stayed_%": stayed, "avg_viewed_%": round(d["averageViewPercentage"], 1),
                         "avg_watch_s": round(d["averageViewDuration"]), "subs": d["subscribersGained"],
                         "subs_per_1k": per_k, "likes": d["likes"], "shares": d["shares"], "comments": d["comments"],
                         "url": "https://youtu.be/" + d["video"]})
    rows.sort(key=lambda r: r["published"], reverse=True)

    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"yt_stats_{dt.date.today().isoformat()}")
    with open(stem + ".csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    cols = ["published", "type", "length_s", "views", "stayed_%", "avg_viewed_%", "avg_watch_s", "subs_per_1k", "likes", "shares", "title"]
    with open(stem + ".md", "w", encoding="utf-8") as f:
        f.write(f"# Channel stats, last {days} days (pulled {dt.date.today().isoformat()})\n\n")
        f.write("stayed_% = engaged views / views (stand-in for Studio's viewed vs swiped away)\n\n")
        f.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
        for r in rows:
            f.write("| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |\n")
    print(f"{len(rows)} videos -> {stem}.md / .csv")


if __name__ == "__main__":
    assert seconds("PT1M5S") == 65 and seconds("PT45S") == 45 and seconds("PT1H2M") == 3720
    assert row_stats(1000, 620, 3) == (62.0, 3.0) and row_stats(0, 0, 0) == (0.0, 0.0)
    main()
