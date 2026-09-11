#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sends emails from Gmail to a list of recipients in a CSV.

  python3 send_emails.py            send today's batch
  python3 send_emails.py --dry-run  show what would go out, send nothing
  python3 send_emails.py --to-self  send ONE sample to your own Gmail
  python3 send_emails.py --force    send even if Gmail throttled you under 24h ago

Campaigns live in config.ini: "campaign" names the current one, and
"follow_ups" is how many follow-ups one person can ever get.

Standard library only (Python 3.8+, nothing to install). All configuration is in
config.ini; all state is in the project's SQLite database.
"""

import argparse
import configparser
import csv
import html
import io
import logging
import mimetypes
import os
import random
import re
import smtplib
import socket
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.ini"
UNSUBSCRIBED_FILE = HERE / "unsubscribed.txt"
LOG_FILE = HERE / "log.txt"

# State lives in the project's SQLite database (sqlite3 is standard library, so
# this script still has no external dependencies).
sys.path.insert(0, str(HERE.parent))
try:
    import state
except ImportError:                                              # pragma: no cover
    print("Can't find state.py next to the gmail-sender folder.", file=sys.stderr)
    raise

SMTP_HOST = "smtp.gmail.com"
EMAIL_COLUMNS = {"email", "e-mail", "mail", "correo", "address", "email address"}
EMAIL_PATTERN = re.compile(r'^[^@\s,;<>"]+@[^@\s,;<>"]+\.[^@\s,;<>".]{2,}$')
FIELD_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
MAX_ERRORS_IN_A_ROW = 5

# Text that means a human never finished this email. The fallback template is
# full of it on purpose, and validate() in draft.py only guards the model's
# drafts — so the last line of defence has to live here, right before sending.
PLACEHOLDER_MARKERS = (">>>", "{{", "REPLACE THIS", "TODO:", "LOREM IPSUM")
WAIT_AFTER_THROTTLE_HOURS = 24

AUTH_MESSAGE = (
    "Gmail rejected the login. Check that: (1) 'address' is your full Gmail and "
    "(2) you are using an APP PASSWORD, not your normal password. Create one at "
    "https://myaccount.google.com/apppasswords (needs 2-step verification on)."
)

log = logging.getLogger("gmail_sender")


class FatalError(Exception):
    """A problem that stops the run; shown to the user without a traceback."""


# ------------------------------------------------------------------- helpers

def setup_logging():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", "%Y-%m-%d %H:%M:%S")
    for handler in (logging.StreamHandler(sys.stdout),
                    logging.FileHandler(LOG_FILE, encoding="utf-8")):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def normalize(name):
    return " ".join(str(name).strip().lower().split())


def resolve(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else HERE / path


def read_text(path):
    """Accepts UTF-8 (with or without BOM) and the format Excel writes on Windows."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def open_csv(path):
    """Reads a CSV, detecting comma, semicolon or tab as the separator."""
    text = read_text(path)
    first_line = text.split("\n", 1)[0]
    separator = max((",", ";", "\t"), key=first_line.count)
    return csv.DictReader(io.StringIO(text, newline=""), delimiter=separator)


def fill(template, data, escape_html=False):
    def replace(match):
        value = data.get(normalize(match.group(1)), "")
        return html.escape(value) if escape_html else value
    return FIELD_PATTERN.sub(replace, template)


def fields_used(*texts):
    return {normalize(f) for text in texts for f in FIELD_PATTERN.findall(text)}


def is_gmail_throttle(text):
    text = text.lower()
    return any(p in text for p in ("5.4.5", "4.7.0", "limit", "quota"))


# -------------------------------------------------------------------- config

def load_config():
    if not CONFIG_FILE.exists():
        raise FatalError(f"Can't find config.ini in {HERE}")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(read_text(CONFIG_FILE))
        if "gmail" not in parser or "sending" not in parser:
            raise FatalError("config.ini needs the [gmail] and [sending] sections")
        gmail, sending = parser["gmail"], parser["sending"]
        cfg = {
            "address": gmail.get("address", "").strip(),
            "password": os.environ.get("GMAIL_APP_PASSWORD") or gmail.get("app_password", ""),
            "sender_name": gmail.get("sender_name", "").strip(),
            "csv_file": resolve(sending.get("csv_file", "recipients.csv").strip()),
            "db": resolve(sending.get("db", "../state.db").strip()),
            "subject": sending.get("subject", "").strip(),
            "text_template": sending.get("text_template", "").strip(),
            "html_template": sending.get("html_template", "").strip(),
            "attachment": sending.get("attachment", "").strip(),
            "max_per_day": sending.getint("max_per_day", 300),
            "limit_24h": sending.getint("limit_24h", 450),
            "pause_min": max(0.0, sending.getfloat("pause_min", 8)),
            "pause_max": max(0.0, sending.getfloat("pause_max", 20)),
            "campaign": sending.get("campaign", "").strip(),
            "follow_ups": max(0, sending.getint("follow_ups", 2)),
            "wait_days": max(0, sending.getint("wait_days", 3)),
            "include_unsubscribe": normalize(sending.get("include_unsubscribe", "yes")) in
                                   {"yes", "si", "sí", "true", "1"},
        }
    except (configparser.Error, ValueError) as ex:
        raise FatalError(f"Check config.ini: {ex}")

    cfg["password"] = cfg["password"].replace(" ", "").strip()
    if not cfg["subject"]:
        raise FatalError("'subject' is missing from config.ini")
    if not cfg["text_template"] and not cfg["html_template"]:
        raise FatalError("Set at least 'text_template' or 'html_template' in config.ini")
    if max(cfg["max_per_day"], cfg["limit_24h"]) > 500:
        log.warning("max_per_day or limit_24h is above 500: a free Gmail account can get blocked.")
    if cfg["pause_min"] > cfg["pause_max"]:
        cfg["pause_min"], cfg["pause_max"] = cfg["pause_max"], cfg["pause_min"]
    if cfg["follow_ups"] > 5:
        log.warning("follow_ups above 5 is a lot of unanswered email to one person.")
    return cfg


def check_credentials(cfg):
    if "@" not in cfg["address"] or cfg["address"].lower().startswith("youraddress@"):
        raise FatalError("Put your Gmail address in config.ini (address = ...)")
    if set(cfg["password"].lower()) <= {"x"}:
        raise FatalError("Put your app password in config.ini. "
                         "Create one at https://myaccount.google.com/apppasswords")


def load_templates(cfg):
    templates = {"text": "", "html": ""}
    for key in ("text", "html"):
        name = cfg[key + "_template"]
        if name:
            path = resolve(name)
            if not path.exists():
                raise FatalError(f"Can't find the template {path}")
            templates[key] = read_text(path)
    if not templates["text"]:
        # HTML only: build a plain-text version for clients that don't render HTML
        stripped = re.sub(r"(?is)<(script|style)\b.*?</\1>|<[^>]+>", "", templates["html"])
        templates["text"] = re.sub(r"\n\s*\n+", "\n\n", html.unescape(stripped)).strip()
    return templates


def load_attachment(value):
    if not value:
        return None
    path = resolve(value)
    if not path.exists():
        raise FatalError(f"Can't find the attachment {path}")
    content = path.read_bytes()
    if len(content) > 18 * 1024 * 1024:
        raise FatalError("The attachment is over 18 MB; Gmail caps messages at 25 MB total.")
    kind, _ = mimetypes.guess_type(path.name)
    main, sub = (kind or "application/octet-stream").split("/", 1)
    return path.name, content, main, sub


# ---------------------------------------------------------------- recipients

def read_recipients(path):
    if not path.exists():
        raise FatalError(f"Can't find the recipients file {path}")
    reader = open_csv(path)
    columns = [c for c in (reader.fieldnames or []) if c and c.strip()]
    email_column = next((c for c in columns if normalize(c) in EMAIL_COLUMNS), None)
    if not email_column:
        raise FatalError("The CSV needs a column called 'email'. "
                         f"Columns found: {', '.join(columns) or 'none'}")

    recipients, seen = [], set()
    for row in reader:
        email = (row.get(email_column) or "").strip().lower()
        if not email:
            continue
        if not EMAIL_PATTERN.match(email):
            log.warning(f"CSV line {reader.line_num}: '{email}' doesn't look like a valid "
                        "address, skipping.")
            continue
        if email in seen:
            continue
        seen.add(email)
        data = {normalize(k): (v or "").strip() for k, v in row.items()
                if isinstance(k, str) and k.strip()}
        data["email"] = email
        recipients.append((email, data))
    return recipients, {normalize(c) for c in columns} | {"email"}


def read_unsubscribed(con):
    """unsubscribed.txt (hand-editable) unioned with the database table (the UI writes that)."""
    return state.unsubscribed(con, UNSUBSCRIBED_FILE)


class SendLog:
    """
    What went out, backed by SQLite. Same interface it had over CSV, so the rest
    of the program never notices the change.

    Gmail's caps (today, last 24h) are GLOBAL: they count every campaign
    together, because Gmail doesn't care how you organize your batches.
    """

    def __init__(self, con, campaign=""):
        self.con = con
        self.campaign = campaign
        self.handled = state.handled_in(con, campaign)
        self.sent_today = state.sent_today(con)
        self.count_today = len(self.sent_today)
        self.count_24h = state.count_since(con, datetime.now() - timedelta(hours=24))
        self.last_throttle = state.last_throttle(con)

    def hours_since_throttle(self):
        if self.last_throttle is None:
            return None
        return (datetime.now() - self.last_throttle).total_seconds() / 3600

    def record(self, email, status, detail="", stage=0, message_id=""):
        state.record_send(self.con, email, status, detail, self.campaign, stage, message_id)
        if status in ("sent", "refused"):
            self.handled.add(email)
        if status == "sent":
            self.sent_today.add(email)
            self.count_today += 1
            self.count_24h += 1

    def close(self):
        self.con.close()


# --------------------------------------------------------------------- email

def message_problem(cfg, templates, data):
    """
    Returns "" if this email is safe to send, or why it isn't.

    Two things must never go out: an empty email (it burns the address), and one
    still carrying template placeholders (that's the fallback text nobody
    finished). Both are silent disasters, so they are blocked here rather than
    trusted to the person clicking send.
    """
    subject = " ".join(fill(cfg["subject"], data).split())
    body = fill(templates["text"], data).strip()
    if not subject:
        return "no subject"
    if not body:
        return "no body"
    blob = (subject + "\n" + body).upper()
    for marker in PLACEHOLDER_MARKERS:
        if marker.upper() in blob:
            return "unfilled placeholder %r" % marker
    return ""


def build_message(cfg, to, data, templates, attachment, subject_prefix=""):
    sender = cfg["address"]
    msg = EmailMessage()
    msg["From"] = formataddr((cfg["sender_name"], sender)) if cfg["sender_name"] else sender
    msg["To"] = to
    msg["Subject"] = subject_prefix + " ".join(fill(cfg["subject"], data).split())
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1] if "@" in sender else None)
    if sender and cfg["include_unsubscribe"]:
        # With include_unsubscribe = no the email carries no unsubscribe header:
        # a job application should read as a personal email, not as a campaign.
        msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=UNSUBSCRIBE>"
    msg.set_content(fill(templates["text"], data))
    if templates["html"]:
        msg.add_alternative(fill(templates["html"], data, escape_html=True), subtype="html")
    if attachment:
        name, content, main, sub = attachment
        msg.add_attachment(content, maintype=main, subtype=sub, filename=name)
    return msg


class GmailConnection:
    def __init__(self, address, password):
        self.address, self.password, self.smtp = address, password, None

    def connect(self):
        self.close()
        context = ssl.create_default_context()
        try:
            smtp = smtplib.SMTP_SSL(SMTP_HOST, 465, context=context, timeout=30)
        except OSError:
            # Some networks block port 465: fall back to 587 with STARTTLS
            smtp = smtplib.SMTP(SMTP_HOST, 587, timeout=30)
            smtp.starttls(context=context)
        smtp.login(self.address, self.password)
        self.smtp = smtp

    def send(self, msg):
        if self.smtp is None:
            self.connect()
        try:
            self.smtp.send_message(msg)
        except (smtplib.SMTPServerDisconnected, ConnectionError, socket.timeout, TimeoutError):
            log.info("Lost the connection to Gmail, reconnecting...")
            self.connect()
            self.smtp.send_message(msg)

    def close(self):
        if self.smtp is not None:
            try:
                self.smtp.quit()
            except Exception:                                    # noqa: BLE001
                pass
            self.smtp = None


# ------------------------------------------------------------------ preflight

def _check(level, title, detail="", scope="global"):
    """
    `scope` says what a blocker stops. "global" means nothing can be sent at
    all — bad credentials, a missing attachment. "rows" means specific emails
    are unsendable while the rest are fine, which matters when you pick a few
    recipients by hand.
    """
    return {"level": level, "title": title, "detail": detail, "scope": scope}


def preflight(max_previews=5, db_path=None):
    """
    Everything that stands between you and a bad first send, in one report.

    Levels: "block" stops the send, "warn" is worth a look, "ok" passed.
    Raises nothing: a configuration error comes back as a block, because the
    whole point is to see all the problems at once instead of one per run.
    """
    report = {"ok": False, "checks": [], "batch": {}, "previews": [], "campaign": "",
              "unsafe_emails": []}
    checks = report["checks"]

    try:
        cfg = load_config()
    except FatalError as ex:
        checks.append(_check("block", "config.ini can't be read", str(ex)))
        return report
    report["campaign"] = cfg["campaign"]

    try:
        check_credentials(cfg)
        checks.append(_check("ok", "Gmail credentials are filled in",
                             "%s — run the login check to prove Gmail accepts them"
                             % cfg["address"]))
    except FatalError as ex:
        checks.append(_check("block", "Gmail credentials are still the example ones", str(ex)))

    try:
        templates = load_templates(cfg)
    except FatalError as ex:
        checks.append(_check("block", "The message template can't be read", str(ex)))
        return report

    try:
        attachment = load_attachment(cfg["attachment"])
    except FatalError as ex:
        checks.append(_check("block", "The attachment is missing", str(ex)))
        attachment = None
    if attachment:
        checks.append(_check("ok", "Attachment found",
                             "%s, %.1f MB" % (attachment[0], len(attachment[1]) / 1e6)))

    try:
        recipients, columns = read_recipients(cfg["csv_file"])
    except FatalError as ex:
        checks.append(_check("block", "The recipients file can't be read", str(ex)))
        return report

    missing = fields_used(cfg["subject"], templates["text"], templates["html"]) - columns
    if missing:
        checks.append(_check("block", "The message uses fields the CSV doesn't have",
                             ", ".join("{{" + f + "}}" for f in sorted(missing))
                             + " — did you run draft.py?"))
    if not recipients:
        checks.append(_check("block", "There are no recipients",
                             "Search for postings first: the Schedule tab, or python3 pipeline.py refresh"))
        return report

    con = state.connect(db_path or cfg["db"])
    try:
        dropped = read_unsubscribed(con)
        send_log = SendLog(con, cfg["campaign"])
        queue, due_count, stale, missing = build_queue(cfg, con, recipients)
        if stale:
            checks.append(_check("warn", "%d rows are for the wrong email in the sequence"
                                 % len(stale),
                                 "The list is stale — run a search, or python3 "
                                 "../pipeline.py refresh, to rebuild it."))
        if missing:
            checks.append(_check("warn", "%d people are due an email but have no draft yet"
                                 % missing,
                                 "Run: python3 draft.py --follow-up"))
        pending = [(e, d) for e, d, _ in queue]

        # The one that matters most: text nobody finished writing.
        # The send-time symptom is usually ">>>", but what you need in order to fix
        # it is why the drafter gave up — which draft.py now records per row.
        unsafe = []
        for email, data in pending:
            why = message_problem(cfg, templates, data)
            if not why:
                continue
            cause = (data.get("text_reason") or "").strip()
            unsafe.append((email, "%s — %s" % (why, cause) if cause else why))
        if unsafe:
            causes = {}
            for _, why in unsafe:
                key = why.split(" — ")[-1]
                causes[key] = causes.get(key, 0) + 1
            summary_line = ", ".join("%s (x%d)" % (k, n) for k, n in
                                     sorted(causes.items(), key=lambda x: -x[1])[:3])
            checks.append(_check(
                "block", "%d emails are not safe to send" % len(unsafe),
                "Why: %s. These are blocked and will never go out. "
                "Fix them with:  python3 draft.py --fix" % summary_line,
                scope="rows"))
            report["unsafe_emails"] = [email for email, _why in unsafe]
        else:
            checks.append(_check("ok", "Every pending email has a subject and a finished body"))
        blocked = {e for e, _ in unsafe}
        pending = [(e, d) for e, d in pending if e not in blocked]

        sources = {}
        for _, d in pending:
            sources[d.get("text_source", "")] = sources.get(d.get("text_source", ""), 0) + 1
        if sources.get("fallback"):
            checks.append(_check("warn", "%d emails use the fixed template" % sources["fallback"],
                                 "Identical bodies are the clearest bulk signal there is. "
                                 "Set ANTHROPIC_API_KEY and run draft.py so each one differs."))
        if sources.get("ai") or sources.get("ai-follow-up"):
            checks.append(_check("ok", "%d emails were written per posting"
                                 % (sources.get("ai", 0) + sources.get("ai-follow-up", 0))))
        if sources.get("edited"):
            checks.append(_check("ok", "%d emails you edited by hand" % sources["edited"]))

        bodies = {}
        for e, d in pending:
            bodies.setdefault(fill(templates["text"], d).strip(), []).append(e)
        repeated = [v for v in bodies.values() if len(v) > 1]
        if repeated:
            worst = max(repeated, key=len)
            checks.append(_check("warn", "%d emails share an identical body" % sum(map(len, repeated)),
                                 "Largest group: %d (%s …)" % (len(worst), worst[0])))

        # Only worth flagging when it actually cost something: if every pending
        # email is already model-written, the key clearly worked when it mattered.
        if sources.get("fallback") and not os.environ.get("ANTHROPIC_API_KEY"):
            checks.append(_check("warn", "No ANTHROPIC_API_KEY in this environment",
                                 "That is why those emails fell back. Point draft.py at "
                                 "your .env:  --env-file /path/to/.env"))

        if cfg["include_unsubscribe"]:
            checks.append(_check("warn", "The email carries an unsubscribe header",
                                 "Fine for marketing, wrong for a job application. "
                                 "Set include_unsubscribe = no."))
        if cfg["max_per_day"] > 50:
            checks.append(_check("warn", "max_per_day is %d" % cfg["max_per_day"],
                                 "From a personal address, ramp up: 15, then 30, then 50."))
        else:
            checks.append(_check("ok", "Daily cap is %d" % cfg["max_per_day"]))

        hours = send_log.hours_since_throttle()
        if hours is not None and hours < WAIT_AFTER_THROTTLE_HOURS:
            checks.append(_check("block", "Gmail throttled you %.1f hours ago" % hours,
                                 "Sending is on hold for another %.1f hours."
                                 % (WAIT_AFTER_THROTTLE_HOURS - hours)))

        waiting = 0
        checks.append(_check(
            "ok", "Follow-ups are automatic",
            "Up to %d per person, %d days after the last email, and only while they "
            "have not replied. %d due right now, %d first contacts waiting."
            % (cfg["follow_ups"], cfg["wait_days"], due_count, len(queue) - due_count)))

        day_room = max(0, cfg["max_per_day"] - send_log.count_today)
        room_24h = max(0, cfg["limit_24h"] - send_log.count_24h)
        batch = queue[:min(day_room, room_24h)]
        report["batch"] = {
            "follow_ups_due": due_count,
            "recipients": len(recipients),
            "unsubscribed": len(dropped),
            "already_handled": len(recipients) - len(queue),
            "blocked": len(unsafe),
            "ready": len(pending),
            "would_send_now": len(batch),
            "waiting_follow_up": waiting,
            "sent_today": send_log.count_today,
            "max_per_day": cfg["max_per_day"],
            "sent_24h": send_log.count_24h,
            "limit_24h": cfg["limit_24h"],
            "minutes": len(batch) * (cfg["pause_min"] + cfg["pause_max"]) / 2 / 60,
        }

        for email, data, stage in batch[:max_previews]:
            msg = build_message(cfg, email, data, templates, attachment)
            report["previews"].append({
                "to": email,
                "stage": stage,
                "stage_label": stage_label(stage),
                "from": msg["From"],
                "subject": msg["Subject"],
                "body": fill(templates["text"], data),
                "attachment": attachment[0] if attachment else "",
                "unsubscribe_header": msg["List-Unsubscribe"] or "",
                "text_source": data.get("text_source", ""),
            })

        mentions_attachment = [e for e, d in pending
                               if re.search(r"\battach", fill(templates["text"], d), re.I)]
        if mentions_attachment and not attachment:
            checks.append(_check("warn", "%d emails say something is attached, but nothing is"
                                 % len(mentions_attachment),
                                 "Set attachment = cv.pdf in config.ini (drop the CV in this "
                                 "folder), or remove that sentence from the template."))

        if not batch and not unsafe:
            if not queue:
                why = ("Nobody is due: everyone has been written to recently, replied, "
                       "or had all %d follow-ups." % cfg["follow_ups"])
            elif day_room == 0:
                why = ("Today's cap of %d is already used (%d sent). %d are waiting; "
                       "they go out on the next run after midnight."
                       % (cfg["max_per_day"], send_log.count_today, len(queue)))
            elif room_24h == 0:
                why = ("The 24-hour safety cap of %d is reached. Sending resumes as "
                       "the oldest ones age out." % cfg["limit_24h"])
            else:
                why = "Everyone is done, unsubscribed, or still waiting."
            checks.append(_check("warn", "Nothing would go out right now", why))
    finally:
        con.close()

    report["ok"] = not any(c["level"] == "block" for c in checks)
    return report


def print_preflight(report):
    symbol = {"ok": "OK  ", "warn": "WARN", "block": "STOP"}
    print("\nPREFLIGHT — campaign '%s'\n" % (report["campaign"] or "(unnamed)"))
    for c in report["checks"]:
        print("  %s  %s" % (symbol[c["level"]], c["title"]))
        if c["detail"]:
            print("        %s" % c["detail"])
    b = report["batch"]
    if b:
        print("\n  %d in the CSV | %d unsubscribed | %d already handled | %d blocked"
              % (b["recipients"], b["unsubscribed"], b["already_handled"], b["blocked"]))
        print("  %d ready | %d would go out now (~%.0f min) | today %d/%d | 24h %d/%d"
              % (b["ready"], b["would_send_now"], b["minutes"],
                 b["sent_today"], b["max_per_day"], b["sent_24h"], b["limit_24h"]))
    for pv in report["previews"][:2]:
        print("\n" + "=" * 64)
        print("To:      %s\nFrom:    %s\nSubject: %s" % (pv["to"], pv["from"], pv["subject"]))
        if pv["attachment"]:
            print("Attach:  %s" % pv["attachment"])
        print("-" * 64)
        print(pv["body"][:700])
    print("\n%s\n" % ("READY: no blockers. Send a test to yourself next: "
                        "python3 send_emails.py --to-self"
                        if report["ok"] else
                        "NOT READY: fix the STOP items above. Nothing will be sent."))
    return 0 if report["ok"] else 1


# ---------------------------------------------------------------------- flow

def verify_login(cfg):
    """
    Proves the address and app password work, WITHOUT sending anything.

    Connects over TLS, authenticates, and hangs up. No message is composed, no
    recipient is touched, nothing leaves your account. It is the one check that
    turns "the credentials look filled in" into "Gmail accepts them", and it is
    safe to run as many times as you like.

    Returns "" on success, or a human-readable reason.
    """
    try:
        check_credentials(cfg)
    except FatalError as ex:
        return str(ex)
    connection = GmailConnection(cfg["address"], cfg["password"])
    try:
        connection.connect()
    except smtplib.SMTPAuthenticationError:
        return AUTH_MESSAGE
    except (smtplib.SMTPException, OSError) as ex:
        return "Couldn't reach Gmail: %s" % ex
    finally:
        connection.close()
    return ""


def send_sample(cfg, recipients, templates, attachment):
    check_credentials(cfg)
    data = recipients[0][1] if recipients else {}
    msg = build_message(cfg, cfg["address"], data, templates, attachment,
                        subject_prefix="[TEST] ")
    connection = GmailConnection(cfg["address"], cfg["password"])
    try:
        connection.send(msg)
    except smtplib.SMTPAuthenticationError:
        raise FatalError(AUTH_MESSAGE)
    except (smtplib.SMTPException, OSError) as ex:
        raise FatalError(f"Couldn't send the sample: {ex}")
    finally:
        connection.close()
    log.info(f"Sample sent to {cfg['address']} using the first row of the CSV. Check your inbox.")


STAGE_LABEL = {0: "first-contact"}


def stage_label(stage):
    return STAGE_LABEL.get(stage, "follow-up-%d" % stage)


def read_only_list(path):
    """Addresses to restrict a run to, one per line. Empty file means nobody."""
    if not path:
        return None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return {line.strip().lower() for line in text.splitlines() if line.strip()}


def build_queue(cfg, con, recipients, only=None):
    """
    Who gets an email in this run, in the order they should get it.

    Two lanes. Follow-ups first: someone who has already waited their days
    should not wait longer because the quota went to people who have never been
    written to. Anyone who replied, bounced or was dismissed is unsubscribed and
    never reaches this function — that is how "only if they still haven't
    answered" is enforced.

    The row from the CSV has to agree with the database about which email in the
    sequence this is. If it doesn't, the list is stale and we skip rather than
    send the wrong one.
    """
    by_email = dict(recipients)
    due, fresh = state.sequence_queue(con, cfg["wait_days"], cfg["follow_ups"],
                                      UNSUBSCRIBED_FILE)
    queue, stale, missing = [], [], 0
    for contact, stage in list(due) + list(fresh):
        email = contact["email"]
        if only is not None and email not in only:
            continue
        data = by_email.get(email)
        if data is None:
            missing += 1
            continue
        try:
            row_stage = int(data.get("stage") or 0)
        except (TypeError, ValueError):
            row_stage = 0
        if row_stage != stage:
            stale.append((email, row_stage, stage))
            continue
        queue.append((email, data, stage))
    return queue, len(due), stale, missing


def main():
    parser = argparse.ArgumentParser(description="Send emails from Gmail.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", dest="dry_run",
                      help="simulate the send without sending anything")
    mode.add_argument("--to-self", action="store_true", dest="to_self",
                      help="send one sample to your own Gmail")
    mode.add_argument("--force", action="store_true",
                      help="send even if Gmail throttled you less than 24h ago")
    mode.add_argument("--check", action="store_true",
                      help="preflight: run every safety check and show what would go out")
    mode.add_argument("--check-login", action="store_true", dest="check_login",
                      help="log in to Gmail to prove the credentials work, sending nothing")
    parser.add_argument("--only", default="",
                        help="a file of addresses, one per line: send to nobody else")
    args = parser.parse_args()

    if args.check:
        return print_preflight(preflight())

    if args.check_login:
        problem = verify_login(load_config())
        if problem:
            log.error("Gmail did NOT accept the credentials.\n%s" % problem)
            return 1
        log.info("Gmail accepted the login. No email was sent.")
        return 0

    cfg = load_config()
    templates = load_templates(cfg)
    recipients, columns = read_recipients(cfg["csv_file"])
    missing = fields_used(cfg["subject"], templates["text"], templates["html"]) - columns
    if missing:
        raise FatalError("The subject or the message uses fields that are not CSV columns: "
                         + ", ".join("{{" + f + "}}" for f in sorted(missing))
                         + "\nDid you run draft.py?")
    attachment = load_attachment(cfg["attachment"])

    if args.to_self:
        return send_sample(cfg, recipients, templates, attachment)

    con = state.connect(cfg["db"])
    state.import_legacy_log(con, HERE / "registro_envios.csv")
    send_log = SendLog(con, cfg["campaign"])
    only = read_only_list(args.only)
    if only is not None:
        log.info(f"Restricted to {len(only)} addresses you picked.")
    queue, due_count, stale, missing = build_queue(cfg, con, recipients, only)
    if stale:
        log.warning(f"{len(stale)} rows in the CSV are for the wrong email in the sequence "
                    f"and were skipped (first: {stale[0][0]}, csv stage {stale[0][1]}, "
                    f"expected {stale[0][2]}). Run: python3 ../pipeline.py refresh")
    if missing:
        log.info(f"{missing} people are due an email but have no row in the CSV yet.")

    unsafe = [(e, message_problem(cfg, templates, d)) for e, d, _ in queue]
    unsafe = [(e, why) for e, why in unsafe if why]
    if unsafe:
        log.warning(f"{len(unsafe)} recipients are not safe to send: skipping them. "
                    f"Did you run draft.py? First: {unsafe[0][0]} ({unsafe[0][1]})")
        blocked = {e for e, _ in unsafe}
        queue = [item for item in queue if item[0] not in blocked]

    pending = [(e, d) for e, d, _ in queue]
    waiting = 0

    day_room = max(0, cfg["max_per_day"] - send_log.count_today)
    room_24h = max(0, cfg["limit_24h"] - send_log.count_24h)
    room = min(day_room, room_24h)
    batch = queue[:room]
    minutes = len(batch) * (cfg["pause_min"] + cfg["pause_max"]) / 2 / 60
    throttled_hours = send_log.hours_since_throttle()
    holding = (throttled_hours is not None
               and throttled_hours < WAIT_AFTER_THROTTLE_HOURS and not args.force)

    follow_ups_in_batch = sum(1 for _, _, stage in batch if stage > 0)
    log.info(f"Due now: {len(queue)} ({due_count} follow-ups, {len(queue) - due_count} first "
             f"contacts) | this batch: {len(batch)}, of which {follow_ups_in_batch} follow-ups | "
             f"CSV: {len(recipients)} recipients | "
             f"sent today: {send_log.count_today}/{cfg['max_per_day']} | "
             f"last 24h: {send_log.count_24h}/{cfg['limit_24h']} | can send now: {room}")

    if args.dry_run:
        log.info(f"[DRY RUN] {len(batch)} emails would go out now (~{minutes:.0f} min). "
                 "Nothing was sent.")
        for email, data, stage in batch[:2]:
            msg = build_message(cfg, email, data, templates, attachment)
            print("\n" + "=" * 64 + f"\nTo:      {email}\n"
                  f"Which:   {stage_label(stage)}\nSubject: {msg['Subject']}\n" + "-" * 64)
            print(fill(templates["text"], data)[:800])
        print()
        if holding:
            log.warning(f"Heads up: Gmail throttled you {throttled_hours:.1f}h ago; the real "
                        "send will wait until 24h have passed.")
        try:
            check_credentials(cfg)
        except FatalError as ex:
            log.warning(f"Before sending for real: {ex}")
        send_log.close()
        return

    if holding:
        left = WAIT_AFTER_THROTTLE_HOURS - throttled_hours
        log.info(f"Gmail throttled the send {throttled_hours:.1f}h ago. To be safe I won't "
                 f"send for another {left:.1f}h (to retry now: python3 send_emails.py --force).")
        send_log.close()
        return
    if not batch:
        if not queue:
            reason = ("Nobody is due: everyone has either been written to recently, "
                      "replied, or had all %d follow-ups." % cfg["follow_ups"])
        elif day_room == 0:
            reason = "Today's maximum has already been sent."
        else:
            reason = "Hit the 24-hour safety cap; will continue on a later run."
        log.info(f"Nothing to send right now. {reason}")
        send_log.close()
        return

    check_credentials(cfg)
    connection = GmailConnection(cfg["address"], cfg["password"])
    sent = refused = errors = in_a_row = 0
    connected = False
    try:
        try:
            connection.connect()
        except smtplib.SMTPAuthenticationError:
            raise FatalError(AUTH_MESSAGE)
        except (smtplib.SMTPException, OSError) as ex:
            raise FatalError(f"Couldn't connect to Gmail: {ex}")
        connected = True

        log.info(f"Sending {len(batch)} emails (estimated ~{minutes:.0f} min)...")
        for i, (email, data, stage) in enumerate(batch, 1):
            message = build_message(cfg, email, data, templates, attachment)
            try:
                connection.send(message)
            except smtplib.SMTPAuthenticationError:
                raise FatalError(AUTH_MESSAGE)
            except smtplib.SMTPRecipientsRefused as ex:
                send_log.record(email, "refused", ex.recipients, stage)
                refused += 1
                log.warning(f"[{i}/{len(batch)}] Gmail refused the address {email}")
            except (smtplib.SMTPException, OSError) as ex:
                throttled = is_gmail_throttle(str(ex))
                send_log.record(email, "gmail_throttled" if throttled else "error", ex, stage)
                errors += 1
                in_a_row += 1
                log.error(f"[{i}/{len(batch)}] Error sending to {email}: {ex}")
                if throttled:
                    log.error(f"Gmail says a sending limit was reached. Stopping, and not "
                              f"retrying for {WAIT_AFTER_THROTTLE_HOURS} hours; the rest waits.")
                    break
                if in_a_row >= MAX_ERRORS_IN_A_ROW:
                    log.error(f"{in_a_row} errors in a row. Stopping to protect your account.")
                    break
            else:
                send_log.record(email, "sent", stage=stage,
                                message_id=message["Message-ID"] or "")
                sent += 1
                in_a_row = 0
                log.info(f"[{i}/{len(batch)}] Sent to {email} ({stage_label(stage)})")
            if i < len(batch):
                time.sleep(random.uniform(cfg["pause_min"], cfg["pause_max"]))
    except KeyboardInterrupt:
        log.warning("Send interrupted by the user.")
    finally:
        connection.close()
        send_log.close()
        if connected:
            log.info(f"Summary: {sent} sent, {refused} addresses refused, {errors} errors, "
                     f"{len(pending) - sent - refused} left for later runs.")


if __name__ == "__main__":
    setup_logging()
    try:
        sys.exit(main() or 0)
    except FatalError as ex:
        log.error(str(ex))
        sys.exit(1)
