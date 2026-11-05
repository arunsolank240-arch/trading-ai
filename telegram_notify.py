#!/usr/bin/env python3
"""Full-Text Telegram Bot Notification Sender (telegram_notify.py).
Guarantees:
1. Auto-discovers TELEGRAM_CHAT_ID from `/getUpdates` if not set in Secrets.
2. NEVER cuts off or truncates messages at 1,000 characters!
   - When `image_path` is provided:
     Step A: Sends the high-res PNG image via `sendPhoto` with a short 1-line title caption.
     Step B: Immediately sends the FULL, UNTRUNCATED explanation text via `sendMessage`
             (splitting cleanly by line if >3,800 chars), so not a single word is ever lost!
"""
import json
import mimetypes
import os
import time
import urllib.parse
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
CHAT_CACHE_FILE = os.path.join(ROOT, "trader", "state", "telegram_chat.json")


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "NSE-Trader-Bot/3.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _post_json(url, payload, headers=None):
    hdrs = {"Content-Type": "application/json", "User-Agent": "NSE-Trader-Bot/3.0"}
    if headers:
        hdrs.update(headers)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _post_multipart(url, fields, file_field, file_path):
    boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))

    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(filename)[0] or "image/png"
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "NSE-Trader-Bot/3.0",
    }
    req = urllib.request.Request(url, data=bytes(body), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def discover_chat_id(bot_token: str) -> str:
    if os.path.exists(CHAT_CACHE_FILE):
        try:
            with open(CHAT_CACHE_FILE, encoding="utf-8") as f:
                cached = (json.load(f) or {}).get("chat_id")
                if cached:
                    return str(cached)
        except Exception:
            pass

    try:
        data = _get_json(f"https://api.telegram.org/bot{bot_token}/getUpdates")
        results = data.get("result") or []
        group_id = None
        fallback_id = None
        for upd in reversed(results):
            for key in ("message", "my_chat_member", "channel_post", "edited_message"):
                obj = upd.get(key) or {}
                chat = obj.get("chat") or {}
                cid = chat.get("id")
                ctype = chat.get("type", "")
                if cid is not None:
                    if ctype in ("group", "supergroup", "channel"):
                        group_id = str(cid)
                        break
                    elif fallback_id is None:
                        fallback_id = str(cid)
            if group_id:
                break
        chosen = group_id or fallback_id
        if chosen:
            print(f"Auto-discovered Telegram Chat ID from getUpdates: {chosen}")
            os.makedirs(os.path.dirname(CHAT_CACHE_FILE), exist_ok=True)
            with open(CHAT_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({"chat_id": chosen}, f, indent=2)
            return chosen
    except Exception as e:
        print(f"Telegram getUpdates auto-discovery note: {e}")
    return ""


def _split_chunks(text: str, max_len: int = 3800) -> list:
    """Splits long text along line boundaries so no sentence is ever truncated."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    cur = []
    cur_len = 0
    for line in text.splitlines():
        if cur_len + len(line) + 1 > max_len and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_len = len(line) + 1
        else:
            cur.append(line)
            cur_len += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def send_telegram(message: str, image_path: str = None) -> bool:
    """Sends image + FULL untruncated message to Telegram."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        return False

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat_id:
        chat_id = discover_chat_id(bot_token)
    if not chat_id:
        print("WARNING: TELEGRAM_CHAT_ID is empty and no chat found in /getUpdates yet.")
        return False

    base = f"https://api.telegram.org/bot{bot_token}"
    ok = False

    if image_path and os.path.exists(image_path):
        # Always send the image with a crisp 2-line header, then send the FULL text message separately
        # so Telegram's 1024-char photo caption limit NEVER cuts off the explanation!
        lines = [l.strip() for l in (message or "").splitlines() if l.strip()]
        short_hdr = "\n".join(lines[:2])[:250] if lines else "📊 NSE Intraday Chart"
        st_img, _ = _post_multipart(
            f"{base}/sendPhoto",
            {"chat_id": chat_id, "caption": short_hdr},
            "photo",
            image_path,
        )
        ok = 200 <= st_img < 300
        time.sleep(0.4)

    if message and message.strip():
        for chunk in _split_chunks(message.strip(), max_len=3800):
            st_txt, _ = _post_json(
                f"{base}/sendMessage",
                {"chat_id": chat_id, "text": chunk},
            )
            ok = (200 <= st_txt < 300) or ok
            time.sleep(0.3)

    return ok


def notify_all(message: str, image_path: str = None) -> bool:
    sent = False
    try:
        if send_telegram(message, image_path):
            print("Sent full notification via Telegram!")
            sent = True
    except Exception as e:
        print(f"Telegram send error: {e}")

    if not sent:
        print("NOTE: Telegram credentials not active in local env. Full message below:")
        print(message)
        if image_path:
            print("Chart image path:", image_path)
    return sent
