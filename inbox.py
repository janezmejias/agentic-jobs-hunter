#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inbox.py — reads your inbox over IMAP to find out who replied.

SMTP can tell you an email left. It cannot tell you anything came back, which is
why "did they answer?" was the one thing the pipeline could not close on its own.
IMAP can, with the same app password you already use to send.

    python3 inbox.py            scan and mark
    python3 inbox.py --dry-run  say what it would mark, change nothing

The mailbox is opened READ-ONLY. Nothing is marked as read, moved, flagged or
deleted — this only looks.

What it recognises:

  a reply   a message whose In-Reply-To or References quotes the Message-ID of
            something we sent, or simply one that arrives from an address we
            wrote to. The first is exact; the second catches replies from people
            whose client rewrites headers, and replies to the emails sent before
            we started recording Message-IDs.

  a bounce  a message from a mailer-daemon or postmaster that names one of our
            addresses in its body. Gmail accepts almost everything at send time
            and bounces later, so this is the only place a dead address shows up.

Marking someone replied or bounced unsubscribes them, which is what stops their
follow-ups. That is the whole point: the sequence ends by itself.

Standard library only.
"""

import argparse
import email
import imaplib
import re
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402

CONFIG = ROOT / "gmail-sender" / "config.ini"
IMAP_HOST = "imap.gmail.com"
DEFAULT_DAYS = 30
LAST_SCAN_KEY = "last_inbox_scan"

DAEMON = re.compile(
    r"(mailer-daemon|postmaster|mail delivery|delivery status|"
    r"delivery subsystem|returned mail|undeliverable)", re.I)
EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class InboxError(Exception):
    """Something the user has to fix; shown without a traceback."""


def read_config():
    """Address and app password, from the file the sender already uses."""
    if not CONFIG.exists():
        raise InboxError("No config.ini at %s" % CONFIG)
    text = CONFIG.read_text(encoding="utf-8", errors="replace")
    values = {}
    for key in ("address", "app_password"):
        m = re.search(r"^\s*%s\s*=\s*(.+)$" % key, text, re.M)
        if m:
            values[key] = m.group(1).strip()
    address = values.get("address", "")
    password = (values.get("app_password") or "").replace(" ", "")
    if "@" not in address or address.lower().startswith("youraddress@"):
        raise InboxError("Put your Gmail address in config.ini first.")
    if not password or set(password.lower()) <= {"x"}:
        raise InboxError("Put your app password in config.ini first.")
    return address, password


def decoded(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:                                            # noqa: BLE001
        return str(value)


def addresses_in(value):
    return {addr.lower() for _name, addr in getaddresses([value or ""]) if addr}


def ids_in(*values):
    """Message-IDs mentioned in In-Reply-To / References, angle brackets and all."""
    found = set()
    for value in values:
        for token in re.findall(r"<[^<>@\s]+@[^<>\s]+>", value or ""):
            found.add(token.strip())
    return found


def since_date(con, days):
    """Scan from the last scan, with overlap, or from `days` ago on a first run."""
    row = con.execute("SELECT value FROM meta WHERE key=?", (LAST_SCAN_KEY,)).fetchone()
    default = datetime.now() - timedelta(days=days)
    if not row:
        return default
    try:
        # A day of overlap: a message that arrived mid-scan is better seen twice
        # than missed once. Marking is idempotent.
        return max(datetime.strptime(row["value"], state.TIME_FORMAT) - timedelta(days=1),
                   default)
    except ValueError:
        return default


def connect(address, password):
    try:
        client = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    except OSError as ex:
        raise InboxError("Couldn't reach Gmail over IMAP: %s" % ex)
    try:
        client.login(address, password)
    except imaplib.IMAP4.error as ex:
        raise InboxError(
            "Gmail refused the IMAP login (%s). The app password is the same one "
            "you send with, but IMAP also has to be switched on: Gmail settings → "
            "Forwarding and POP/IMAP → Enable IMAP." % ex)
    return client


def fetch_messages(client, since):
    """Headers and body of everything in INBOX since a date. Read-only."""
    status, _ = client.select("INBOX", readonly=True)
    if status != "OK":
        raise InboxError("Couldn't open the INBOX.")
    status, data = client.search(None, "SINCE", since.strftime("%d-%b-%Y"))
    if status != "OK":
        raise InboxError("The IMAP search failed.")
    ids = (data[0] or b"").split()
    for chunk_start in range(0, len(ids), 50):
        chunk = ids[chunk_start:chunk_start + 50]
        status, parts = client.fetch(b",".join(chunk), "(RFC822)")
        if status != "OK":
            continue
        for part in parts:
            if isinstance(part, tuple) and part[1]:
                try:
                    yield email.message_from_bytes(part[1])
                except Exception:                                # noqa: BLE001
                    continue


def body_text(message, limit=20000):
    chunks = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
        except Exception:                                        # noqa: BLE001
            continue
        chunks.append(payload.decode("utf-8", "replace"))
        if sum(len(c) for c in chunks) > limit:
            break
    return "\n".join(chunks)[:limit]


def classify(message, our_ids, contacted, own_address):
    """
    Returns (kind, address) where kind is "reply", "bounce" or "".

    Exact matching first: a quoted Message-ID is proof. The sender-address check
    is the fallback, and it is what catches replies to the emails sent before we
    began recording Message-IDs.
    """
    sender = addresses_in(message.get("From", ""))
    if own_address in sender and len(sender) == 1:
        return "", ""                                  # our own copy

    quoted = ids_in(message.get("In-Reply-To"), message.get("References"))
    for mid in quoted:
        if mid in our_ids:
            return "reply", our_ids[mid]

    is_daemon = bool(DAEMON.search(decoded(message.get("From", ""))
                                   + " " + decoded(message.get("Subject", ""))))
    if is_daemon:
        text = body_text(message)
        for candidate in EMAIL_IN_TEXT.findall(text):
            candidate = candidate.lower()
            if candidate in contacted:
                return "bounce", candidate
        return "", ""

    for addr in sender:
        if addr in contacted:
            return "reply", addr
    return "", ""


def scan(con, days=DEFAULT_DAYS, dry_run=False, client=None, now_=None):
    """
    Looks through the inbox and marks whoever replied or bounced.

    `client` is injectable so this can be tested without a mailbox.
    """
    address, password = read_config()
    already = state.unsubscribed(con, ROOT / "gmail-sender" / "unsubscribed.txt")
    # Only the people we are still waiting on. Someone already marked as replied,
    # bounced or dismissed is not interesting any more, and leaving them in the
    # watch list only invites re-marking them every scan.
    watching = state.contacted(con) - already
    our_ids = {mid: who for mid, who in state.message_ids(con).items() if who in watching}
    start = since_date(con, days)

    owned = client is None
    if owned:
        client = connect(address, password)

    replies, bounces, seen = {}, {}, 0
    try:
        for message in fetch_messages(client, start):
            seen += 1
            kind, who = classify(message, our_ids, watching, address.lower())
            if not who or who in already:
                continue
            when = ""
            try:
                when = parsedate_to_datetime(message.get("Date")).strftime(state.TIME_FORMAT)
            except Exception:                                    # noqa: BLE001
                pass
            note = "%s on %s: %s" % (kind, when or "an unknown date",
                                     decoded(message.get("Subject", ""))[:120])
            (replies if kind == "reply" else bounces)[who] = note
    finally:
        if owned:
            try:
                client.logout()
            except Exception:                                    # noqa: BLE001
                pass

    if not dry_run:
        for who, note in replies.items():
            state.set_status(con, who, "replied", note=note)
        for who, note in bounces.items():
            state.set_status(con, who, "bounced", note=note)
        con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                    (LAST_SCAN_KEY, (now_ or datetime.now()).strftime(state.TIME_FORMAT)))
        con.commit()

    return {"scanned": seen, "since": start.strftime(state.TIME_FORMAT),
            "watching": len(watching), "replies": replies, "bounces": bounces}


def main():
    p = argparse.ArgumentParser(description="Find out who replied, over IMAP.")
    p.add_argument("--db", default=str(state.DB_PATH))
    p.add_argument("--days", type=int, default=DEFAULT_DAYS,
                   help="how far back to look on a first scan")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="say what would be marked, change nothing")
    args = p.parse_args()

    con = state.connect(args.db)
    try:
        result = scan(con, args.days, args.dry_run)
    except InboxError as ex:
        print(ex, file=sys.stderr)
        return 1
    finally:
        con.close()

    print("Read %d messages since %s, watching %d people who have not answered."
          % (result["scanned"], result["since"], result["watching"]))
    for who, note in result["replies"].items():
        print("  REPLIED  %-34s %s" % (who, note))
    for who, note in result["bounces"].items():
        print("  BOUNCED  %-34s %s" % (who, note))
    if not result["replies"] and not result["bounces"]:
        print("  Nothing new: nobody has replied and nothing bounced.")
    elif args.dry_run:
        print("\n(--dry-run: nothing was marked)")
    else:
        print("\nMarked. Anyone above is unsubscribed, so their follow-ups stop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
