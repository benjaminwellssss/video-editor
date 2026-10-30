"""YouTube control from the command line: who am I, livestreams, uploads, edits. Separate token from yt_stats.py.

Usage:
  python yt_api.py auth                         one-time (or after expiry): opens the browser consent
  python yt_api.py whoami                       channel + token scopes/expiry (read-only)
  python yt_api.py live list                    my broadcasts and stream names (never the stream keys) (read-only)
  python yt_api.py live create --title T [--description D] [--start 2026-11-01T20:00 | +90m] [--stream STREAM_ID]
                               [--thumb file.png] [--privacy private] [--confirm]
  python yt_api.py upload FILE --title T [--description D] [--tags a,b] [--category 20] [--thumb file.png]
                               [--privacy private] [--confirm]
  python yt_api.py edit VIDEO_ID [--title T] [--description D] [--tags a,b] [--thumb file.png] [--privacy X] [--confirm]
  python yt_api.py selftest

Safety (the user's rules): without --confirm every write only prints what it WOULD send. Privacy defaults to private;
public/unlisted needs --confirm AND --allow-public. Every write is read back and printed. Stream keys, tokens and the
client secret are never printed. Scopes: youtube + youtube.force-ssl + yt-analytics.readonly.
Note: videos uploaded through an unaudited API project are forced private by YouTube until the project passes its audit.
"""
import argparse
import datetime as dt
import os
import re
import sys

CONF = os.path.join(os.path.expanduser("~"), ".config", "video-editor")
SECRET = os.path.join(CONF, "youtube_client_secret.json")
TOKEN = os.path.join(CONF, "youtube_api_token.json")  # yt_stats.py keeps its own youtube_token.json
SCOPES = ["https://www.googleapis.com/auth/youtube", "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
PRIVACY = ("private", "unlisted", "public")


def parse_start(text):
    """'+90m' / '+2h' (from now) or an ISO local time -> UTC ISO string for scheduledStartTime."""
    now = dt.datetime.now(dt.timezone.utc)
    m = re.fullmatch(r"\+(\d+)([mh])", text or "")
    if m:
        t = now + dt.timedelta(minutes=int(m.group(1))) if m.group(2) == "m" else now + dt.timedelta(hours=int(m.group(1)))
    else:
        t = dt.datetime.fromisoformat(text)
        if t.tzinfo is None:
            t = t.astimezone()  # naive = this PC's local time
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def strip_secrets(obj):
    """Copy of an API response without anything that carries a stream key / ingestion address."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if k not in ("cdn", "ingestionInfo", "streamName", "ingestionAddress")}
    if isinstance(obj, list):
        return [strip_secrets(x) for x in obj]
    return obj


def check_privacy(a):
    if a.privacy not in PRIVACY:
        sys.exit(f"--privacy must be one of {PRIVACY}")
    if a.privacy != "private" and not a.allow_public:
        sys.exit(f"--privacy {a.privacy} needs --allow-public as well (and --confirm). Default is private.")


def credentials(interactive=False):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            if not interactive:
                sys.exit(f"The saved token no longer works ({e}). Run: python yt_api.py auth   (the app in Testing mode expires every 7 days)")
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            sys.exit("Not signed in. Run: python yt_api.py auth")
        if not os.path.exists(SECRET):
            sys.exit(f"Missing {SECRET}")
        creds = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES).run_local_server(port=0, prompt="consent", access_type="offline")
    os.makedirs(CONF, exist_ok=True)
    open(TOKEN, "w").write(creds.to_json())
    return creds


def service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials())


def tags_of(s):
    return [t.strip() for t in s.split(",") if t.strip()] if s else None


def show(label, obj):
    import json
    print(f"{label}: " + json.dumps(strip_secrets(obj), indent=2, ensure_ascii=False))


def dry(a, what, body):
    if not a.confirm:
        show(f"DRY RUN - would {what}", body)
        print("Nothing sent. Add --confirm to do it.")
        return True
    return False


def set_thumb(yt, video_id, path):
    from googleapiclient.http import MediaFileUpload
    yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(path)).execute()
    print(f"thumbnail set on {video_id} from {os.path.basename(path)}")


def cmd_whoami(a):
    yt = service()
    c = yt.channels().list(part="snippet,statistics", mine=True).execute()["items"][0]
    print(f"channel: {c['snippet']['title']} ({c['id']})  handle: {c['snippet'].get('customUrl')}  "
          f"subs: {c['statistics'].get('subscriberCount')}  videos: {c['statistics'].get('videoCount')}")
    import json
    t = json.load(open(TOKEN))
    print("token scopes:", " ".join(s.rsplit("/", 1)[-1] for s in t.get("scopes", [])), "| expiry:", t.get("expiry"))


def cmd_live_list(a):
    yt = service()
    for b in yt.liveBroadcasts().list(part="snippet,status,contentDetails", mine=True, maxResults=25).execute().get("items", []):
        print(f"broadcast {b['id']}: {b['snippet']['title']!r} {b['status']['lifeCycleStatus']} {b['status']['privacyStatus']} "
              f"start {b['snippet'].get('scheduledStartTime')} bound stream: {b['contentDetails'].get('boundStreamId')}")
    for s in yt.liveStreams().list(part="snippet,status,cdn", mine=True, maxResults=25).execute().get("items", []):
        print(f"stream {s['id']}: {s['snippet']['title']!r} {s['status']['streamStatus']} {s['cdn'].get('resolution')} {s['cdn'].get('frameRate')}")


def cmd_live_create(a):
    check_privacy(a)
    body = {"snippet": {"title": a.title, "description": a.description or "", "scheduledStartTime": parse_start(a.start or "+60m")},
            "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False},
            "contentDetails": {"enableAutoStart": False, "enableAutoStop": False}}
    if dry(a, f"create a {a.privacy} broadcast" + (f", bind stream {a.stream}" if a.stream else "") + (", set a thumbnail" if a.thumb else ""), body):
        return
    yt = service()
    b = yt.liveBroadcasts().insert(part="snippet,status,contentDetails", body=body).execute()
    if a.stream:
        yt.liveBroadcasts().bind(id=b["id"], part="id,contentDetails", streamId=a.stream).execute()
    if a.thumb:
        set_thumb(yt, b["id"], a.thumb)
    got = yt.liveBroadcasts().list(part="snippet,status,contentDetails", id=b["id"]).execute()["items"][0]
    show("READ BACK", {"id": got["id"], "title": got["snippet"]["title"], "start": got["snippet"].get("scheduledStartTime"),
                       "privacy": got["status"]["privacyStatus"], "state": got["status"]["lifeCycleStatus"],
                       "boundStreamId": got["contentDetails"].get("boundStreamId")})


def cmd_upload(a):
    check_privacy(a)
    if not os.path.exists(a.file):
        sys.exit(f"missing file {a.file}")
    body = {"snippet": {"title": a.title, "description": a.description or "", "categoryId": a.category, **({"tags": tags_of(a.tags)} if a.tags else {})},
            "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False}}
    if dry(a, f"upload {os.path.basename(a.file)} ({os.path.getsize(a.file) / 1e6:.0f} MB) as {a.privacy}", body):
        return
    from googleapiclient.http import MediaFileUpload
    yt = service()
    req = yt.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(a.file, chunksize=32 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            print(f"  uploaded {int(st.progress() * 100)}%", flush=True)
    if a.thumb:
        set_thumb(yt, resp["id"], a.thumb)
    got = yt.videos().list(part="snippet,status", id=resp["id"]).execute()["items"][0]
    show("READ BACK", {"id": got["id"], "title": got["snippet"]["title"], "privacy": got["status"]["privacyStatus"],
                       "uploadStatus": got["status"].get("uploadStatus"), "link": f"https://youtu.be/{got['id']}"})
    if got["status"]["privacyStatus"] != a.privacy:
        print(f"NOTE: YouTube made it {got['status']['privacyStatus']}, not {a.privacy} (unaudited API project).")


def cmd_edit(a):
    if a.privacy:
        check_privacy(a)
    plan = {k: v for k, v in dict(title=a.title, description=a.description, tags=tags_of(a.tags), thumbnail=a.thumb, privacy=a.privacy).items() if v}
    if not plan:
        sys.exit("nothing to change: give --title/--description/--tags/--thumb/--privacy")
    if dry(a, f"edit video {a.video_id}", plan):
        return
    yt = service()
    cur = yt.videos().list(part="snippet,status", id=a.video_id).execute()["items"]
    if not cur:
        sys.exit("no such video on this channel")
    sn, stt = cur[0]["snippet"], cur[0]["status"]
    parts = []
    if a.title or a.description or a.tags:
        # videos.update replaces snippet fields it is sent and needs title + categoryId, so start from the current snippet
        new = {"title": a.title or sn["title"], "categoryId": sn["categoryId"], "description": a.description if a.description is not None else sn.get("description", ""),
               "tags": tags_of(a.tags) if a.tags else sn.get("tags", [])}
        yt.videos().update(part="snippet", body={"id": a.video_id, "snippet": new}).execute()
        parts.append("snippet")
    if a.privacy:
        stt["privacyStatus"] = a.privacy
        yt.videos().update(part="status", body={"id": a.video_id, "status": {k: stt[k] for k in ("privacyStatus", "embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids") if k in stt}}).execute()
        parts.append("status")
    if a.thumb:
        set_thumb(yt, a.video_id, a.thumb)
    got = yt.videos().list(part="snippet,status", id=a.video_id).execute()["items"][0]
    show("READ BACK", {"id": got["id"], "title": got["snippet"]["title"], "tags": got["snippet"].get("tags"), "privacy": got["status"]["privacyStatus"], "changed": parts})


def selftest():
    assert parse_start("+90m") > dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert parse_start("2026-11-01T20:00").endswith(".000Z")
    clean = strip_secrets({"id": "s1", "cdn": {"ingestionInfo": {"streamName": "KEY"}, "resolution": "1080p"}, "x": [{"streamName": "KEY2", "y": 1}]})
    assert "KEY" not in str(clean) and clean["x"][0] == {"y": 1}, clean
    assert tags_of("a, b,,c") == ["a", "b", "c"] and tags_of(None) is None
    assert SCOPES[0].endswith("/youtube") and TOKEN.endswith("youtube_api_token.json")
    class A: privacy, allow_public = "public", False
    try:
        check_privacy(A)
    except SystemExit:
        pass
    else:
        raise AssertionError("public without --allow-public must be refused")
    print("yt_api selftest ok")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth"), sub.add_parser("whoami"), sub.add_parser("selftest")
    live = sub.add_parser("live").add_subparsers(dest="sub", required=True)
    live.add_parser("list")
    c = live.add_parser("create")
    for n in ("--title", "--description", "--start", "--stream", "--thumb"):
        c.add_argument(n)
    u = sub.add_parser("upload")
    u.add_argument("file")
    for n in ("--title", "--description", "--tags", "--thumb"):
        u.add_argument(n)
    u.add_argument("--category", default="20")  # 20 = Gaming
    e = sub.add_parser("edit")
    e.add_argument("video_id")
    for n in ("--title", "--description", "--tags", "--thumb", "--privacy"):
        e.add_argument(n)
    for q in (c, u, e):
        q.add_argument("--confirm", action="store_true")
        q.add_argument("--allow-public", action="store_true")
    for q in (c, u):
        q.add_argument("--privacy", default="private")
    a = p.parse_args()
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "auth":
        credentials(interactive=True)
        return print("signed in; token saved to", TOKEN)
    {"whoami": cmd_whoami, "upload": cmd_upload, "edit": cmd_edit}.get(a.cmd, lambda a: {"list": cmd_live_list, "create": cmd_live_create}[a.sub](a))(a)


if __name__ == "__main__":
    main()
