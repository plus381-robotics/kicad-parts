#!/usr/bin/env python3
"""Post the part previews made by render_previews.py to a Discord channel.

    DISCORD_WEBHOOK_URL=... python3 scripts/notify_discord.py --out previews/<dir> \
        --link <commit or PR URL> --headline "..." [--author name] [--message "..."]

The webhook URL comes from Discord: channel settings > Integrations >
Webhooks > New Webhook > Copy Webhook URL. Store it as the GitHub secret
DISCORD_WEBHOOK_URL. Only the standard library is used.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COLORS = {"new": 0x2EA043, "changed": 0x1F6FEB, "deleted": 0xCF222E}
FIELDS = ("MPN", "Manufacturer", "Footprint", "LCSC Part")


def multipart(payload, files):
    boundary = uuid.uuid4().hex
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
              f'Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n').encode()]
    for n, path in enumerate(files):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="files[{n}]"; '
                      f'filename="{path.name}"\r\nContent-Type: image/png\r\n\r\n').encode())
        parts.append(path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send(url, payload, files):
    body, ctype = multipart(payload, files)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": ctype, "User-Agent": "plus381-part-previews"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status
    except urllib.error.HTTPError as e:
        print("Discord refused the message:", e.code, e.read().decode(errors="replace")[:500])
        return e.code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder written by render_previews.py")
    ap.add_argument("--link", required=True)
    ap.add_argument("--headline", required=True)
    ap.add_argument("--author", default="")
    ap.add_argument("--message", default="", help="commit message / PR title")
    args = ap.parse_args()
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("DISCORD_WEBHOOK_URL is not set: nothing sent.")
        return 0
    out = Path(args.out)
    parts = json.loads((out / "parts.json").read_text(encoding="utf-8"))
    if not parts:
        return 0

    embeds, files = [], []
    for part in parts:
        e = {"title": part["title"], "url": args.link, "color": COLORS.get(part["status"], 0x8B949E),
             "description": part["status"].capitalize() + (f" by **{args.author}**" if args.author else ""),
             "fields": [{"name": k, "value": part["fields"][k][:1000], "inline": True}
                        for k in FIELDS if part["fields"].get(k)]}
        ds = part["fields"].get("Datasheet", "")
        if ds.startswith("http"):
            e["fields"].append({"name": "Datasheet", "value": f"[open]({ds})", "inline": True})
        if part.get("card") and (out / part["card"]).exists():
            files.append(out / part["card"])
            e["image"] = {"url": f"attachment://{part['card']}"}
        if args.message:
            e["footer"] = {"text": args.message.splitlines()[0][:200]}
        embeds.append(e)

    status = 0
    # Discord allows 10 embeds and 10 files per message.
    for start in range(0, len(embeds), 10):
        chunk = embeds[start:start + 10]
        chunk_files = [f for f in files if any(e.get("image", {}).get("url") == f"attachment://{f.name}"
                                               for e in chunk)]
        payload = {"username": "Plus381 parts", "content": args.headline if start == 0 else "",
                   "embeds": chunk, "allowed_mentions": {"parse": []}}
        code = send(url, payload, chunk_files)
        print("Discord:", code)
        status = status or (0 if code in (200, 204) else 1)
    return status


if __name__ == "__main__":
    sys.exit(main())
