"""Hand a small, repetitive task to the local LLM (Ollama on this PC) instead of spending Claude usage on it.

Usage: python ask_local.py "<task>" [--file in.txt ...] [--big] [--json] [--out result.txt]

- The task is the instruction; each --file is appended as context (transcripts, captions.json, notes...).
- Default model is the fast one that fits on the GPU; --big uses the larger, slower, smarter one (for judgment-ish
  first passes like "list funny-moment candidates in this transcript").
- --json asks Ollama for valid JSON output.
- Everything stays on this PC: it only talks to Ollama at localhost.

Good for: metadata/title drafts, summaries, reformatting, keyword lists, first-pass scans that a person or Claude
then reviews. Not for: final picks, code changes, anything that must be right without review.
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:11434/api/chat"
FAST = ["qwen3.5:9b", "qwen3:8b"]   # first one that's installed wins
BIG = ["qwen3:30b"]
MAX_FILE_CHARS = 60000              # keep context inside what the model handles well


def installed():
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
        return {m["name"] for m in json.load(r)["models"]}


def pick(wanted, have):
    for name in wanted:
        if name in have or name + ":latest" in have:
            return name
    return None


def build_prompt(task, files):
    parts = [task]
    for path in files:
        text = open(path, encoding="utf-8", errors="replace").read()
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n[...truncated]"
        parts.append(f"--- {path} ---\n{text}")
    return "\n\n".join(parts)


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # replies often contain emoji; the Windows console default would crash
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    files = [args[i + 1] for i, a in enumerate(args) if a == "--file"]
    out = args[args.index("--out") + 1] if "--out" in args else None
    skip = {i + 1 for i, a in enumerate(args) if a in ("--file", "--out")}
    task = " ".join(a for i, a in enumerate(args) if i not in skip and not a.startswith("--"))
    try:
        have = installed()
    except OSError:
        sys.exit("Ollama isn't running - start the Ollama app (or `ollama serve`).")
    model = pick(BIG if "--big" in args else FAST, have) or pick(FAST + BIG, have)
    if not model:
        sys.exit("No model installed - run: ollama pull qwen3:8b")
    body = {"model": model, "stream": False, "think": False,
            "messages": [{"role": "user", "content": build_prompt(task, files)}],
            "options": {"num_ctx": 16384, "temperature": 0.4}}
    if "--json" in args:
        body["format"] = "json"
    req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        reply = json.load(r)["message"]["content"].strip()
    if out:
        open(out, "w", encoding="utf-8").write(reply + "\n")
        print(f"[{model}] wrote {out}")
    else:
        print(reply)


if __name__ == "__main__":
    assert pick(["a", "b"], {"b:latest"}) == "b" and pick(["x"], set()) is None
    main()
