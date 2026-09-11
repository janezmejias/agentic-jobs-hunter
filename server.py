#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
server.py — the UI backend. Standard library only.

    python3 server.py             http://127.0.0.1:8787
    python3 server.py --port 9000

Serves the built UI (ui/dist) and a JSON API over state.db. Listens on 127.0.0.1
ONLY: the database holds your contacts and your drafts, and it does not leave
your machine.

Every time you save a draft or change a status, recipients.csv is regenerated —
that file is what send_emails.py reads. So what you see in the UI is exactly what
will go out.
"""

import argparse
import importlib.util
import json
import mimetypes
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402
import pipeline                                                  # noqa: E402
import cron                                                      # noqa: E402
import inbox                                                     # noqa: E402

DIST = ROOT / "ui" / "dist"
RECIPIENTS_CSV = ROOT / "gmail-sender" / "recipients.csv"
UNSUBSCRIBED_TXT = ROOT / "gmail-sender" / "unsubscribed.txt"
DEFAULT_FOLLOW_UP_DAYS = 7


DEFAULT_MAX_FOLLOW_UPS = 2


def sequence_rules():
    """
    Read from config.ini, not hardcoded here: the sender is what actually holds
    the batch back, and two different numbers would make the UI lie about when
    a follow-up goes out.
    """
    try:
        cfg = sender_module().load_config()
        return int(cfg["wait_days"]), int(cfg["follow_ups"])
    except Exception:                                            # noqa: BLE001
        return DEFAULT_FOLLOW_UP_DAYS, DEFAULT_MAX_FOLLOW_UPS
SENDER_PY = ROOT / "gmail-sender" / "send_emails.py"

_sender = None


def sender_module():
    """
    The preflight checks live in the sender, because they have to use the exact
    same config parsing, template filling and message building that the real
    send uses. A reimplementation here would drift and quietly lie to you.
    Loaded by path: 'gmail-sender' has a hyphen, so it isn't importable normally.
    """
    global _sender
    if _sender is None:
        spec = importlib.util.spec_from_file_location("send_emails", SENDER_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _sender = module
    return _sender


class Handler(BaseHTTPRequestHandler):
    server_version = "agentic-jobs-hunter"

    # ---------------------------------------------------------------- helpers
    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def reply(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def db(self):
        return state.connect(self.server.db_path)

    def re_export(self, con):
        """The UI and the sender must never disagree: regenerate the CSV on save."""
        return state.export_csv(con, self.server.csv_path)

    # ----------------------------------------------------------------- routes
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self.api_state(parse_qs(urlparse(self.path).query))
        if path == "/api/preflight":
            return self.api_preflight()
        if path == "/api/activity":
            return self.api_activity()
        if path == "/api/schedule":
            return self.api_schedule()
        parts = [p for p in path.split("/") if p]
        if parts[:2] == ["api", "contact"] and len(parts) == 4 and parts[3] == "drafts":
            return self.api_drafts(unquote(parts[2]))
        if path.startswith("/api/"):
            return self.reply({"error": "unknown route"}, 404)
        return self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        body = self.read_json()
        try:
            if parts[:2] == ["api", "contact"] and len(parts) == 4 and parts[3] == "status":
                return self.api_set_status(unquote(parts[2]), body)
            if parts[:2] == ["api", "draft"] and len(parts) == 3:
                return self.api_save_draft(unquote(parts[2]), body)
            if parts == ["api", "schedule", "preview"]:
                return self.api_preview(body)
            if parts == ["api", "schedule"]:
                return self.api_save_schedule(body)
            if parts == ["api", "refresh"]:
                return self.api_refresh()
            if parts == ["api", "inbox"]:
                return self.api_inbox()
            if parts == ["api", "send"]:
                return self.api_send(body)
            if parts == ["api", "draft-follow-ups"]:
                return self.api_draft_follow_ups()
            if parts == ["api", "verify-login"]:
                return self.api_verify_login()
            if parts == ["api", "test-email"]:
                return self.api_test_email()
            if parts == ["api", "export"]:
                con = self.db()
                n = self.re_export(con)
                con.close()
                return self.reply({"exported": n})
        except ValueError as ex:
            return self.reply({"error": str(ex)}, 400)
        return self.reply({"error": "unknown route"}, 404)

    # -------------------------------------------------------------------- api
    def api_state(self, query):
        con = self.db()
        wanted = query.get("status", [None])[0]
        states = (wanted,) if wanted and wanted != "all" else None
        rows = state.contacts(con, states=states, include_unsubscribed=True)
        dropped = state.unsubscribed(con, UNSUBSCRIBED_TXT)
        sends = state.sends_for(con)
        days, max_follow_ups = sequence_rules()
        # The very queue the sender will use, so "due" in the UI means due.
        due, _fresh = state.sequence_queue(con, days, max_follow_ups, UNSUBSCRIBED_TXT)
        due_stage = {c["email"]: stage for c, stage in due}
        counts = state.stages(con)

        out = []
        for c in rows:
            email = c["email"]
            stage = counts.get(email, 0)
            d = state.draft_for_stage(con, email, stage) or state.latest_draft(con, email)
            sent = sends.get(email)
            out.append({
                **c,
                "unsubscribed": email in dropped,
                "subject": d["subject"] if d else "",
                "body": d["body"] if d else "",
                "origin": d["origin"] if d else "",
                "fingerprint": d["fingerprint"] if d else "",
                "sent_at": sent.strftime(state.TIME_FORMAT) if sent else "",
                "emails_sent": stage,
                "next_stage": due_stage.get(email, stage),
                "follow_ups_left": max(0, max_follow_ups - max(0, stage - 1)) if stage else max_follow_ups,
                "due_follow_up": email in due_stage and due_stage[email] > 0,
            })
        # The number that answers "how many people owe me a reply", and when we
        # last actually looked. Both were only visible from the terminal before.
        awaiting = state.contacted(con) - dropped
        last_check = next((r for r in state.recent_runs(con, 40)
                           if r["kind"] == "inbox" and r["status"] == "ok"), None)
        data = {
            "summary": state.summary(con),
            "contacts": out,
            "follow_up_days": days,
            "max_follow_ups": max_follow_ups,
            "due_now": len(due),
            "awaiting_reply": len(awaiting),
            "last_inbox_check": last_check["started_at"] if last_check else "",
            "last_inbox_detail": last_check["detail"] if last_check else "",
        }
        con.close()
        return self.reply(data)

    def api_preflight(self):
        """Every check that stands between the user and a bad first send."""
        try:
            sender = sender_module()
        except Exception as ex:                                  # noqa: BLE001
            return self.reply({"ok": False, "checks": [
                {"level": "block", "title": "Can't load send_emails.py", "detail": str(ex)}],
                "batch": {}, "previews": [], "campaign": ""})
        try:
            report = sender.preflight(max_previews=8, db_path=self.server.db_path)
        except Exception as ex:                                  # noqa: BLE001
            return self.reply({"ok": False, "checks": [
                {"level": "block", "title": "The preflight itself failed",
                 "detail": "%s: %s" % (type(ex).__name__, ex)}],
                "batch": {}, "previews": [], "campaign": ""})
        return self.reply(report)

    def api_schedule(self):
        con = self.db()
        snap = pipeline.schedule_snapshot(con)
        con.close()
        return self.reply(snap)

    def api_preview(self, body):
        """
        What an expression means and when it would fire — answered by the very
        module that installs it, so the preview cannot drift from reality.
        """
        expression = (body.get("expression") or "").strip()
        try:
            runs = cron.next_runs(expression, count=5)
            return self.reply({
                "valid": True,
                "description": cron.describe(expression),
                "next_runs": [d.strftime(state.TIME_FORMAT) for d in runs],
                "error": "",
            })
        except cron.CronError as ex:
            return self.reply({"valid": False, "description": "", "next_runs": [],
                               "error": str(ex)})

    def api_save_schedule(self, body):
        """Saves the settings and rewrites the cron entries to match them."""
        con = self.db()
        # Never install something that doesn't parse: the job would silently
        # never run, and cron wouldn't tell anyone.
        for key in ("refresh_cron", "send_cron"):
            if key in (body or {}):
                try:
                    cron.parse(body[key])
                except cron.CronError as ex:
                    con.close()
                    return self.reply({"ok": False, "error": "%s: %s" % (key, ex)}, 400)
        state.save_settings(con, body or {})
        try:
            if pipeline.which_crontab():
                pipeline.apply_schedule(con)
        except Exception as ex:                                  # noqa: BLE001
            snap = pipeline.schedule_snapshot(con)
            con.close()
            return self.reply({"ok": False, "error": str(ex), **snap}, 400)
        snap = pipeline.schedule_snapshot(con)
        con.close()
        return self.reply({"ok": True, **snap})

    def api_refresh(self):
        """
        Starts a refresh and returns immediately. It costs money and takes
        minutes, so the UI polls /api/schedule to watch it rather than holding
        the request open.
        """
        import threading
        con = self.db()
        if state.running(con, "refresh"):
            con.close()
            return self.reply({"ok": False, "error": "a refresh is already running"}, 409)
        con.close()

        cmd = [sys.executable, str(ROOT / "pipeline.py"), "refresh",
               "--db", str(self.server.db_path), "--trigger", "ui"]
        log_path = ROOT / ".run" / "refresh.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def worker():
            with open(log_path, "a", encoding="utf-8") as f:
                subprocess.run(cmd, stdout=f, stderr=f)

        threading.Thread(target=worker, daemon=True).start()
        return self.reply({"ok": True, "started": True})

    def api_inbox(self):
        """Reads the inbox and marks whoever replied or bounced. Read-only on the mailbox."""
        con = self.db()
        try:
            result = inbox.scan(con)
        except inbox.InboxError as ex:
            con.close()
            return self.reply({"ok": False, "error": str(ex)}, 400)
        except Exception as ex:                                  # noqa: BLE001
            con.close()
            return self.reply({"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}, 400)
        con.close()
        return self.reply({"ok": True, "scanned": result["scanned"],
                           "replies": list(result["replies"]),
                           "bounces": list(result["bounces"])})

    def api_send(self, body=None):
        """
        Sends the batch that is due, or only the addresses you picked.

        Refuses while a GLOBAL blocker stands — bad credentials, a missing
        attachment — because nothing can go out under those. A blocker about
        particular rows only stops those rows: if you hand-picked recipients and
        none of them is the broken one, there is no reason to stop you. Any
        unsendable address in your selection is refused by name rather than
        skipped quietly.
        """
        import threading, tempfile
        body = body or {}
        picked = [str(e).strip().lower() for e in (body.get("emails") or []) if str(e).strip()]

        try:
            report = sender_module().preflight(max_previews=0, db_path=self.server.db_path)
        except Exception as ex:                                  # noqa: BLE001
            return self.reply({"ok": False, "error": "preflight failed: %s" % ex}, 400)

        blocking = [c for c in report["checks"] if c["level"] == "block"]
        globals_ = [c for c in blocking if c.get("scope", "global") == "global"]
        if globals_:
            return self.reply({"ok": False, "error": "Preflight is blocking: "
                               + "; ".join(c["title"] for c in globals_)}, 409)
        unsafe = set(report.get("unsafe_emails") or [])
        if picked:
            bad = [e for e in picked if e in unsafe]
            if bad:
                return self.reply({"ok": False, "error":
                                   "These are not safe to send: " + ", ".join(bad[:5])}, 409)
        elif blocking:
            return self.reply({"ok": False, "error": "Preflight is blocking: "
                               + "; ".join(c["title"] for c in blocking)}, 409)

        con = self.db()
        if state.running(con, "send"):
            con.close()
            return self.reply({"ok": False, "error": "a send is already running"}, 409)
        con.close()

        cmd = [sys.executable, str(ROOT / "pipeline.py"), "send",
               "--db", str(self.server.db_path), "--trigger", "ui"]
        if picked:
            handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                                 encoding="utf-8")
            handle.write("\n".join(picked))
            handle.close()
            cmd += ["--only", handle.name]
        log_path = ROOT / ".run" / "send.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        def worker():
            with open(log_path, "a", encoding="utf-8") as f:
                subprocess.run(cmd, stdout=f, stderr=f)

        threading.Thread(target=worker, daemon=True).start()
        return self.reply({"ok": True, "started": True,
                           "would_send": len(picked) or report["batch"].get("would_send_now", 0),
                           "picked": len(picked)})

    def api_activity(self):
        """Sends and runs together: what the machine did, in one place."""
        con = self.db()
        data = {"sends": state.recent_sends(con), "runs": state.recent_runs(con, 40)}
        con.close()
        return self.reply(data)

    def api_drafts(self, email):
        con = self.db()
        data = {"drafts": state.drafts_for(con, email)}
        con.close()
        return self.reply(data)

    def api_draft_follow_ups(self):
        """
        Runs draft.py --follow-up, the same command the terminal uses. Writing a
        second implementation of the drafting loop here would drift from it, so
        this shells out to the one that is already tested.
        """
        cmd = [sys.executable, str(ROOT / "draft.py"), "--follow-up",
               "--db", str(self.server.db_path), "--csv", str(self.server.csv_path)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return self.reply({"ok": False, "error": "drafting timed out after 15 minutes"}, 400)
        tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
        if r.returncode != 0:
            return self.reply({"ok": False, "error": tail or "draft.py failed"}, 400)
        return self.reply({"ok": True, "output": tail})

    def api_verify_login(self):
        """Proves the Gmail credentials work. Sends nothing, touches no recipient."""
        sender = sender_module()
        try:
            problem = sender.verify_login(sender.load_config())
        except Exception as ex:                                  # noqa: BLE001
            return self.reply({"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}, 400)
        if problem:
            return self.reply({"ok": False, "error": problem}, 400)
        return self.reply({"ok": True})

    def api_test_email(self):
        """
        Sends ONE real email, to the user's own address. It is the only check
        that proves Gmail will actually accept the login and the message.
        """
        sender = sender_module()
        try:
            cfg = sender.load_config()
            templates = sender.load_templates(cfg)
            recipients, _ = sender.read_recipients(cfg["csv_file"])
            attachment = sender.load_attachment(cfg["attachment"])
            sender.send_sample(cfg, recipients, templates, attachment)
        except sender.FatalError as ex:
            return self.reply({"ok": False, "error": str(ex)}, 400)
        except Exception as ex:                                  # noqa: BLE001
            return self.reply({"ok": False, "error": "%s: %s" % (type(ex).__name__, ex)}, 400)
        return self.reply({"ok": True, "sent_to": cfg["address"]})

    def api_set_status(self, email, body):
        wanted = (body.get("status") or "").strip()
        if wanted not in state.STATES:
            raise ValueError("invalid status: %r" % wanted)
        con = self.db()
        state.set_status(con, email, wanted, body.get("note"))
        n = self.re_export(con)
        con.close()
        return self.reply({"ok": True, "exported": n})

    def api_save_draft(self, email, body):
        subject = (body.get("subject") or "").strip()
        text = (body.get("body") or "").strip()
        if not subject or not text:
            raise ValueError("an email with no subject or no body is not saved")
        con = self.db()
        previous = state.latest_draft(con, email)
        fp = body.get("fingerprint") or (previous["fingerprint"] if previous else "manual")
        state.save_draft(con, email, fp, subject, text, "edited",
                         previous["model"] if previous else "")
        n = self.re_export(con)
        con.close()
        return self.reply({"ok": True, "exported": n})

    # ----------------------------------------------------------------- static
    def serve_static(self, path):
        if not DIST.exists():
            return self.no_ui()
        rel = path.lstrip("/") or "index.html"
        target = (DIST / rel).resolve()
        if not str(target).startswith(str(DIST.resolve())) or not target.is_file():
            target = DIST / "index.html"          # SPA: everything else to index
        if not target.is_file():
            return self.no_ui()
        data = target.read_bytes()
        kind, _ = mimetypes.guess_type(target.name)
        self.send_response(200)
        self.send_header("Content-Type", kind or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def no_ui(self):
        msg = ("<h1>The UI isn't built yet</h1><pre>bash run.sh start</pre>"
               "<p>The API does work in the meantime: "
               "<a href='/api/state'>/api/state</a></p>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)


def main():
    p = argparse.ArgumentParser(description="Local UI for the job pipeline.")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--db", default=str(state.DB_PATH))
    p.add_argument("--csv", default=str(RECIPIENTS_CSV))
    p.add_argument("--open", action="store_true", dest="open_browser",
                   help="open the browser")
    args = p.parse_args()

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    httpd.db_path = args.db
    httpd.csv_path = args.csv
    url = "http://127.0.0.1:%d" % args.port
    print("UI at %s   (Ctrl+C to quit)" % url)
    print("Database: %s" % args.db)
    if not DIST.exists():
        print("\n! The UI isn't built yet:  bash run.sh start")
    if args.open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
