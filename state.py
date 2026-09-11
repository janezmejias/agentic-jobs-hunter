#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state.py — the local database holding ALL pipeline state.

A single SQLite file (state.db) replaces the three scattered stores this used to
have: the send log in CSV, the draft cache in JSON, and per-contact status. With
it, "who did I write to, and when?" stops being a guess and becomes a query.

Standard library only: sqlite3 ships with Python, so send_emails.py keeps its
zero-dependency property.

Used as a module. To poke at the database by hand:

    sqlite3 state.db "select status, count(*) from contacts group by status"
"""

import csv
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "state.db"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SCHEMA_VERSION = 1

# The states a contact moves through.
STATES = ("new", "drafted", "sent", "replied", "dismissed", "bounced")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    email             TEXT PRIMARY KEY,
    greeting          TEXT NOT NULL DEFAULT '',
    name              TEXT NOT NULL DEFAULT '',
    company           TEXT NOT NULL DEFAULT '',
    role              TEXT NOT NULL DEFAULT '',
    reference         TEXT NOT NULL DEFAULT '',
    scope             TEXT NOT NULL DEFAULT '',
    url               TEXT NOT NULL DEFAULT '',
    source            TEXT NOT NULL DEFAULT '',
    ai_score          INTEGER NOT NULL DEFAULT 0,
    original_headline TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'new',
    note              TEXT NOT NULL DEFAULT '',
    first_seen        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);

CREATE TABLE IF NOT EXISTS drafts (
    email       TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT 'ai',
    stage       INTEGER NOT NULL DEFAULT 0,
    reason      TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (email, fingerprint)
);

CREATE TABLE IF NOT EXISTS sends (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at    TEXT NOT NULL,
    email      TEXT NOT NULL,
    status     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    campaign   TEXT NOT NULL DEFAULT '',
    stage      INTEGER NOT NULL DEFAULT 0,
    message_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sends_email ON sends(email);
CREATE INDEX IF NOT EXISTS idx_sends_at ON sends(sent_at);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    trigger     TEXT NOT NULL DEFAULT 'manual',
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'running',
    found       INTEGER NOT NULL DEFAULT 0,
    new_contacts INTEGER NOT NULL DEFAULT 0,
    drafted     INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL NOT NULL DEFAULT 0,
    detail      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);

CREATE TABLE IF NOT EXISTS unsubscribed (
    email  TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT '',
    added  TEXT NOT NULL
);
"""

CSV_COLUMNS = ["email", "greeting", "name", "company", "role", "reference",
               "scope", "url", "source", "ai_score", "original_headline",
               "ai_subject", "ai_body", "text_source", "text_reason", "stage"]


def now():
    return datetime.now().strftime(TIME_FORMAT)


def connect(path=None):
    """
    WAL so the UI can read while cron writes, and a busy timeout so two
    processes that collide wait instead of blowing up.
    """
    path = Path(path) if path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),))
    # Databases created before the reason column existed: add it in place. A
    # fallback that doesn't say why is a dead end when you're trying to fix it.
    have = {r["name"] for r in con.execute("PRAGMA table_info(drafts)")}
    if "reason" not in have:
        con.execute("ALTER TABLE drafts ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
    have = {r["name"] for r in con.execute("PRAGMA table_info(contacts)")}
    if "description" not in have:
        con.execute("ALTER TABLE contacts ADD COLUMN description TEXT NOT NULL DEFAULT ''")
    # Stage 0 is the first email, 1 and 2 are the follow-ups. Older rows are all
    # first contacts, which is what the default says.
    for table in ("drafts", "sends"):
        have = {r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)}
        if "stage" not in have:
            con.execute("ALTER TABLE %s ADD COLUMN stage INTEGER NOT NULL DEFAULT 0" % table)
    # The Message-ID of what went out: it is what a reply quotes back, and the
    # only way to match one to a thread rather than guessing from the sender.
    have = {r["name"] for r in con.execute("PRAGMA table_info(sends)")}
    if "message_id" not in have:
        con.execute("ALTER TABLE sends ADD COLUMN message_id TEXT NOT NULL DEFAULT ''")
    con.commit()
    return con


# ------------------------------------------------------------------- contacts

def save_contacts(con, rows):
    """
    Insert new contacts and refresh the posting details on existing ones. NEVER
    overwrites 'status' or 'note': that is human work, and the hunter has no
    business knowing that someone already replied.
    """
    added = refreshed = 0
    for r in rows:
        email = (r.get("email") or "").strip().lower()
        if not email:
            continue
        f = {c: str(r.get(c, "") or "").strip() for c in
             ("greeting", "name", "company", "role", "reference",
              "scope", "url", "source", "original_headline", "description")}
        try:
            score = int(float(r.get("ai_score") or 0))
        except (TypeError, ValueError):
            score = 0
        if con.execute("SELECT 1 FROM contacts WHERE email = ?", (email,)).fetchone():
            con.execute(
                """UPDATE contacts SET greeting=?, name=?, company=?, role=?,
                   reference=?, scope=?, url=?, source=?, ai_score=?,
                   original_headline=?, description=?, updated_at=? WHERE email=?""",
                (f["greeting"], f["name"], f["company"], f["role"], f["reference"],
                 f["scope"], f["url"], f["source"], score, f["original_headline"],
                 f["description"], now(), email))
            refreshed += 1
        else:
            con.execute(
                """INSERT INTO contacts(email, greeting, name, company, role,
                   reference, scope, url, source, ai_score, original_headline,
                   description, status, first_seen, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'new',?,?)""",
                (email, f["greeting"], f["name"], f["company"], f["role"],
                 f["reference"], f["scope"], f["url"], f["source"], score,
                 f["original_headline"], f["description"], now(), now()))
            added += 1
    con.commit()
    return added, refreshed


def contacts(con, states=None, include_unsubscribed=False):
    sql = "SELECT * FROM contacts"
    args, where = [], []
    if states:
        where.append("status IN (%s)" % ",".join("?" * len(states)))
        args.extend(states)
    if not include_unsubscribed:
        where.append("email NOT IN (SELECT email FROM unsubscribed)")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ai_score DESC, email"
    return [dict(r) for r in con.execute(sql, args)]


def set_status(con, email, status, note=None):
    if status not in STATES:
        raise ValueError("unknown status: %s (valid: %s)" % (status, ", ".join(STATES)))
    email = email.strip().lower()
    if note is None:
        con.execute("UPDATE contacts SET status=?, updated_at=? WHERE email=?",
                    (status, now(), email))
    else:
        con.execute("UPDATE contacts SET status=?, note=?, updated_at=? WHERE email=?",
                    (status, note, now(), email))
    # Anyone who replied or bounced must not get the follow-up: unsubscribe them.
    if status in ("replied", "bounced", "dismissed"):
        unsubscribe(con, email, reason=status)
    con.commit()


def summary(con):
    rows = con.execute("SELECT status, COUNT(*) n FROM contacts GROUP BY status").fetchall()
    data = {s: 0 for s in STATES}
    data.update({r["status"]: r["n"] for r in rows})
    data["unsubscribed"] = con.execute(
        "SELECT COUNT(*) n FROM unsubscribed").fetchone()["n"]
    return data


# --------------------------------------------------------------------- drafts

def save_draft(con, email, fingerprint, subject, body, origin="ai", model="",
               reason="", stage=0):
    """
    `reason` records why a draft fell back, so the UI can say what to fix.
    `stage` is which email this is: 0 the first, 1 and 2 the follow-ups.
    """
    con.execute(
        """INSERT INTO drafts(email, fingerprint, subject, body, origin, stage,
                              reason, model, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(email, fingerprint) DO UPDATE SET
             subject=excluded.subject, body=excluded.body,
             origin=excluded.origin, stage=excluded.stage, reason=excluded.reason,
             model=excluded.model, created_at=excluded.created_at""",
        (email.strip().lower(), fingerprint, subject, body, origin, stage,
         reason, model, now()))
    con.commit()


def draft_for_stage(con, email, stage):
    """The draft written for one particular email in the sequence."""
    r = con.execute("SELECT * FROM drafts WHERE email=? AND stage=? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (email.strip().lower(), int(stage))).fetchone()
    return dict(r) if r else None


def draft(con, email, fingerprint):
    r = con.execute("SELECT * FROM drafts WHERE email=? AND fingerprint=?",
                    (email.strip().lower(), fingerprint)).fetchone()
    return dict(r) if r else None


def recent_openers(con, limit=40):
    """
    The first sentence of the drafts already written, so the next one can be
    told not to echo them. Repetition across a batch is the single clearest
    signal that a pile of mail was generated.
    """
    out = []
    for r in con.execute("SELECT body FROM drafts ORDER BY created_at DESC, rowid DESC "
                         "LIMIT ?", (int(limit),)):
        body = (r["body"] or "").strip()
        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
        if len(paragraphs) < 2:
            continue
        first = paragraphs[1].split(". ")[0].strip()
        if first:
            out.append(first[:120])
    return out


def latest_draft(con, email):
    # rowid breaks the tie: created_at only has second resolution, and an edit
    # from the UI can land in the same second as the draft it replaces. Without
    # this, which one wins is arbitrary — and it would be the one that gets sent.
    r = con.execute("SELECT * FROM drafts WHERE email=? "
                    "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (email.strip().lower(),)).fetchone()
    return dict(r) if r else None


def drafts_for(con, email):
    """Every draft written for one address, newest first.

    The follow-up view needs both the email that went out and the second one, so
    it can show them side by side; latest_draft() alone can't do that.
    """
    return [dict(r) for r in con.execute(
        "SELECT * FROM drafts WHERE email=? ORDER BY created_at DESC, rowid DESC",
        (email.strip().lower(),))]


# ---------------------------------------------------------------------- sends

def record_send(con, email, status, detail="", campaign="", stage=0, message_id=""):
    con.execute("INSERT INTO sends(sent_at, email, status, detail, campaign, stage, message_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (now(), email.strip().lower(), status,
                 " ".join(str(detail).split())[:300], campaign, int(stage),
                 (message_id or "").strip()))
    if status == "sent":
        con.execute("UPDATE contacts SET status='sent', updated_at=? "
                    "WHERE email=? AND status IN ('new','drafted')",
                    (now(), email.strip().lower()))
    elif status == "refused":
        con.execute("UPDATE contacts SET status='bounced', updated_at=? WHERE email=?",
                    (now(), email.strip().lower()))
        unsubscribe(con, email, reason="refused by Gmail")
    con.commit()


def sends_for(con, campaign=None):
    """{email: last send time} for one campaign, or across all of them."""
    if campaign is None:
        rows = con.execute("SELECT email, MAX(sent_at) t FROM sends "
                           "WHERE status='sent' GROUP BY email")
    else:
        rows = con.execute("SELECT email, MAX(sent_at) t FROM sends "
                           "WHERE status='sent' AND campaign=? GROUP BY email", (campaign,))
    out = {}
    for r in rows:
        try:
            out[r["email"]] = datetime.strptime(r["t"], TIME_FORMAT)
        except (TypeError, ValueError):
            pass
    return out


def handled_in(con, campaign):
    """Emails already dealt with (sent or refused) in that campaign."""
    return {r["email"] for r in con.execute(
        "SELECT DISTINCT email FROM sends WHERE campaign=? AND status IN "
        "('sent','refused')", (campaign,))}


def count_since(con, since):
    return con.execute("SELECT COUNT(*) n FROM sends WHERE status='sent' AND sent_at >= ?",
                       (since.strftime(TIME_FORMAT),)).fetchone()["n"]


def sent_today(con):
    today = datetime.now().strftime("%Y-%m-%d")
    rows = con.execute("SELECT DISTINCT email FROM sends WHERE status='sent' "
                       "AND sent_at LIKE ?", (today + "%",))
    return {r["email"] for r in rows}


def recent_sends(con, limit=80):
    """The send log, newest first, for the activity view."""
    return [dict(r) for r in con.execute(
        "SELECT * FROM sends ORDER BY sent_at DESC, id DESC LIMIT ?", (int(limit),))]


def last_throttle(con):
    r = con.execute("SELECT MAX(sent_at) t FROM sends WHERE status='gmail_throttled'").fetchone()
    if not r or not r["t"]:
        return None
    try:
        return datetime.strptime(r["t"], TIME_FORMAT)
    except ValueError:
        return None


def message_ids(con):
    """{Message-ID: address} for everything that actually went out."""
    return {r["message_id"]: r["email"] for r in con.execute(
        "SELECT message_id, email FROM sends WHERE status='sent' AND message_id != ''")}


def contacted(con):
    """Every address that has been written to at least once."""
    return {r["email"] for r in con.execute(
        "SELECT DISTINCT email FROM sends WHERE status='sent'")}


def stage_of(con, email):
    """
    How many emails this person has already been sent — which is also the stage
    of the next one. 0 means they have never been written to.
    """
    r = con.execute("SELECT COUNT(*) n FROM sends WHERE email=? AND status='sent'",
                    (email.strip().lower(),)).fetchone()
    return r["n"] if r else 0


def stages(con):
    """{email: emails already sent} for everyone, in one query."""
    return {r["email"]: r["n"] for r in con.execute(
        "SELECT email, COUNT(*) n FROM sends WHERE status='sent' GROUP BY email")}


def sequence_queue(con, wait_days, max_follow_ups, txt_path=None, now_=None):
    """
    Who is due for their next email, and which one it is.

    Two lanes: people who already got something and have waited long enough for
    the next follow-up, and people who have never been written to. Follow-ups
    come first — someone who has already waited should not wait longer because
    the day's quota went to strangers.

    Anyone who replied, bounced or was dismissed is unsubscribed, so they never
    appear here at all. That is the whole "if they still haven't answered" rule:
    it is enforced by absence, not by a flag anyone has to remember to set.
    """
    dropped = unsubscribed(con, txt_path)
    sent_counts = stages(con)
    last = sends_for(con)
    cutoff = (now_ or datetime.now()) - timedelta(days=int(wait_days))

    follow_ups, first_contacts = [], []
    for c in contacts(con, states=("new", "drafted", "sent")):
        email = c["email"]
        if email in dropped:
            continue
        done = sent_counts.get(email, 0)
        if done == 0:
            first_contacts.append((c, 0))
            continue
        if done > int(max_follow_ups):
            continue                      # first email plus every follow-up: finished
        when = last.get(email)
        if when and when <= cutoff:
            follow_ups.append((c, done))
    follow_ups.sort(key=lambda pair: last.get(pair[0]["email"]) or datetime.max)
    return follow_ups, first_contacts


# --------------------------------------------------------------- unsubscribes

def unsubscribe(con, email, reason=""):
    con.execute("INSERT OR IGNORE INTO unsubscribed(email, reason, added) VALUES (?,?,?)",
                (email.strip().lower(), reason, now()))
    con.commit()


def unsubscribed(con, txt_path=None):
    """
    Union of the table and unsubscribed.txt. The file stays hand-editable — it is
    the fastest way to drop someone — and the table is what the UI writes.
    """
    out = {r["email"] for r in con.execute("SELECT email FROM unsubscribed")}
    if txt_path and Path(txt_path).exists():
        for line in Path(txt_path).read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                out.add(line)
    return out


# --------------------------------------------------------------------- export

def export_csv(con, path):
    """
    Regenerate recipients.csv from the database. The sender still reads a CSV
    (simple, inspectable, already tested); the database is the source of truth.
    """
    rows = []
    counts = stages(con)
    for c in contacts(con, states=("new", "drafted", "sent")):
        # The draft that belongs to the email this person is next owed, not
        # simply the newest one — otherwise a follow-up written today would be
        # handed out to someone who has not had their first email yet.
        stage = counts.get(c["email"], 0)
        d = draft_for_stage(con, c["email"], stage)
        rows.append({
            "email": c["email"], "greeting": c["greeting"], "name": c["name"],
            "company": c["company"], "role": c["role"], "reference": c["reference"],
            "scope": c["scope"], "url": c["url"], "source": c["source"],
            "ai_score": c["ai_score"], "original_headline": c["original_headline"],
            "ai_subject": d["subject"] if d else "",
            "ai_body": d["body"] if d else "",
            "text_source": d["origin"] if d else "",
            "text_reason": (d["reason"] if d else "") or "",
            "stage": stage,
        })
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)
    return len(rows)


# ----------------------------------------------------------------------- runs

def start_run(con, kind, trigger="manual"):
    cur = con.execute("INSERT INTO runs(kind, trigger, started_at) VALUES (?,?,?)",
                      (kind, trigger, now()))
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id, status, **fields):
    allowed = ("found", "new_contacts", "drafted", "cost_usd", "detail")
    sets = ", ".join("%s=?" % k for k in fields if k in allowed)
    args = [fields[k] for k in fields if k in allowed]
    sql = "UPDATE runs SET status=?, finished_at=?" + (", " + sets if sets else "") + " WHERE id=?"
    con.execute(sql, [status, now()] + args + [run_id])
    con.commit()


def recent_runs(con, limit=25):
    return [dict(r) for r in con.execute(
        "SELECT * FROM runs ORDER BY started_at DESC, id DESC LIMIT ?", (int(limit),))]


def running(con, kind=None):
    """A run still marked 'running' — used to stop two from overlapping."""
    sql = "SELECT * FROM runs WHERE status='running'"
    args = []
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    r = con.execute(sql + " ORDER BY id DESC LIMIT 1", args).fetchone()
    return dict(r) if r else None


# -------------------------------------------------------------------- settings

DEFAULT_SETTINGS = {
    "refresh_enabled": "0",
    "refresh_cron": "40 7 * * *",
    "send_enabled": "0",
    "send_cron": "0 8-20 * * *",
    "inbox_enabled": "0",
    "inbox_cron": "*/30 7-22 * * *",
}

# Settings from before the schedule became a full cron expression.
LEGACY_SETTINGS = ("refresh_at", "send_from", "send_to")


def _migrate_settings(stored):
    """Turns the old fixed-shape settings into the cron expressions they meant."""
    if "refresh_cron" not in stored and "refresh_at" in stored:
        try:
            hour, minute = stored["refresh_at"].split(":")
            stored["refresh_cron"] = "%d %d * * *" % (int(minute), int(hour))
        except (ValueError, AttributeError):
            pass
    if "send_cron" not in stored and "send_from" in stored:
        try:
            stored["send_cron"] = "0 %d-%d * * *" % (int(stored["send_from"]),
                                                     int(stored.get("send_to", 20)))
        except (ValueError, TypeError):
            pass
    return {k: v for k, v in stored.items() if k not in LEGACY_SETTINGS}


def settings(con):
    prefix = "setting:"
    stored = {r["key"][len(prefix):]: r["value"] for r in
              con.execute("SELECT key, value FROM meta WHERE key LIKE ?", (prefix + "%",))}
    out = dict(DEFAULT_SETTINGS)
    out.update(_migrate_settings(stored))
    return out


def save_settings(con, values):
    for key, value in values.items():
        if key in DEFAULT_SETTINGS:
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)",
                        ("setting:" + key, str(value)))
    con.commit()
    return settings(con)


# ------------------------------------------------------------------ migration

def import_legacy_log(con, path):
    """Pull in the old CSV send log, if one is still lying around. Idempotent."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return 0
    if con.execute("SELECT value FROM meta WHERE key='legacy_log_imported'").fetchone():
        return 0
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    n = 0
    for row in csv.DictReader(text.splitlines()):
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue
        con.execute("INSERT INTO sends(sent_at, email, status, detail, campaign) "
                    "VALUES (?,?,?,?,?)",
                    ((row.get("fecha_hora") or row.get("sent_at") or now()).strip(), email,
                     (row.get("estado") or row.get("status") or "sent").strip(),
                     (row.get("detalle") or row.get("detail") or "").strip(),
                     (row.get("campana") or row.get("campaign") or "").strip()))
        n += 1
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('legacy_log_imported', ?)",
                (now(),))
    con.commit()
    return n
