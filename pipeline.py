#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — the one entry point for everything that runs on a schedule.

    python3 pipeline.py refresh        find postings, build the list, write drafts
    python3 pipeline.py send           send the batch that is due
    python3 pipeline.py inbox          read the inbox: who replied, what bounced
    python3 pipeline.py status         what is scheduled and when it last ran
    python3 pipeline.py schedule       write the cron entries from the saved settings

This replaces the loose shell scripts that used to do the same thing. cron calls
it, the UI calls it, and both record what happened in the same place — so "when
did this last run and what did it cost" is a question the UI can answer.

`run.sh` stays the only shell script: it starts and stops the UI.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402
import cron                                                      # noqa: E402
import inbox                                                     # noqa: E402

RUNDIR = ROOT / ".run"
HUNTER = ROOT / "ai-job-hunter" / "ai_job_hunter.py"
JOBS_CSV = Path.home() / "ai-job-hunter" / "jobs.csv"
SENDER = ROOT / "gmail-sender" / "send_emails.py"
CONFIG = ROOT / "gmail-sender" / "config.ini"
MARKER = "# agentic-jobs-hunter"
SCOPE = "yes,ask"


def log(msg):
    print("%s  %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def sender_setting(name, default):
    """One value out of gmail-sender/config.ini, without importing the sender."""
    if not CONFIG.exists():
        return default
    for line in CONFIG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*%s\s*=\s*(.+)" % re.escape(name), line)
        if m:
            return m.group(1).strip()
    return default


def own_address():
    if not CONFIG.exists():
        return ""
    for line in CONFIG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*address\s*=\s*(.+)", line)
        if m:
            return m.group(1).strip()
    return ""


def env_file_setting():
    """Where ANTHROPIC_API_KEY lives, if it isn't already in the environment."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ""
    for candidate in (os.environ.get("ANTHROPIC_ENV_FILE"), ROOT / ".env"):
        if candidate and Path(candidate).expanduser().exists():
            return str(candidate)
    return ""


def run_step(name, cmd):
    log("→ %s" % name)
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    for line in out.splitlines():
        print("   " + line, flush=True)
    if r.returncode != 0:
        raise RuntimeError("%s failed (exit %d)" % (name, r.returncode))
    return out


# ------------------------------------------------------------------- refresh

def cmd_refresh(args):
    con = state.connect(args.db)
    busy = state.running(con, "refresh")
    if busy and not args.force:
        log("A refresh started at %s is still marked running. Use --force to override."
            % busy["started_at"])
        con.close()
        return 1

    run_id = state.start_run(con, "refresh", args.trigger)
    before = len(state.contacts(con, include_unsubscribed=True))
    stats_path = Path(tempfile.gettempdir()) / ("draft-stats-%d.json" % run_id)
    try:
        check_inbox(args.db, "before drafting")
        run_step("searching Jobot and Hacker News", [sys.executable, str(HUNTER)])

        prepare = [sys.executable, str(ROOT / "prepare.py"), "--scope", SCOPE, "--db", args.db]
        address = own_address()
        if address:
            prepare += ["--own-email", address]
        run_step("building the contact list", prepare)

        env_file = env_file_setting()
        common = ["--language", "en", "--db", args.db]
        if env_file:
            common += ["--env-file", env_file]

        draft = [sys.executable, str(ROOT / "draft.py")] + common + \
                ["--stats-out", str(stats_path)]
        run_step("writing the first emails", draft)
        stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.exists() else {}

        # The follow-ups people are due, written in the same run so they are
        # ready when the sender gets to them. Nobody has to remember a step.
        wait_days = sender_setting("wait_days", "3")
        max_follow_ups = sender_setting("follow_ups", "2")
        if int(max_follow_ups) > 0:
            follow_stats = stats_path.with_name(stats_path.name + ".follow")
            run_step("writing the follow-ups that are due",
                     [sys.executable, str(ROOT / "draft.py"), "--follow-up"] + common
                     + ["--wait-days", str(wait_days),
                        "--max-follow-ups", str(max_follow_ups),
                        "--stats-out", str(follow_stats)])
            if follow_stats.exists():
                extra = json.loads(follow_stats.read_text(encoding="utf-8"))
                stats["written"] = stats.get("written", 0) + extra.get("written", 0)
                stats["fell_back"] = stats.get("fell_back", 0) + extra.get("fell_back", 0)
                stats["cost_usd"] = round(stats.get("cost_usd", 0) + extra.get("cost_usd", 0), 6)
                stats["follow_ups_written"] = extra.get("written", 0)
                follow_stats.unlink(missing_ok=True)
        con2 = state.connect(args.db)
        after = len(state.contacts(con2, include_unsubscribed=True))
        detail = "%d written (%d follow-ups), %d reused, %d fell back" % (
            stats.get("written", 0), stats.get("follow_ups_written", 0),
            stats.get("reused", 0), stats.get("fell_back", 0))
        state.finish_run(con2, run_id, "ok",
                         found=after, new_contacts=max(0, after - before),
                         drafted=stats.get("written", 0),
                         cost_usd=stats.get("cost_usd", 0.0), detail=detail)
        log("done — %s, USD %.4f" % (detail, stats.get("cost_usd", 0.0)))
        con2.close()
        return 0
    except Exception as ex:                                      # noqa: BLE001
        con2 = state.connect(args.db)
        state.finish_run(con2, run_id, "failed", detail=str(ex)[:280])
        con2.close()
        log("FAILED: %s" % ex)
        return 1
    finally:
        stats_path.unlink(missing_ok=True)
        con.close()


def check_inbox(db, label="before sending"):
    """
    Who replied, read straight from the inbox. Runs before every send: a reply
    that arrived an hour ago has to stop the follow-up that would go out now,
    and nobody is around to notice it by hand.

    A mailbox that can't be reached is not a reason to stop sending — it is a
    reason to say so and carry on.
    """
    con = state.connect(db)
    try:
        result = inbox.scan(con)
    except inbox.InboxError as ex:
        log("could not check the inbox %s: %s" % (label, ex))
        return {}
    except Exception as ex:                                      # noqa: BLE001
        log("inbox check failed %s: %s" % (label, ex))
        return {}
    finally:
        con.close()
    if result["replies"] or result["bounces"]:
        for who in result["replies"]:
            log("REPLIED  %s — dropped from the sequence" % who)
        for who in result["bounces"]:
            log("BOUNCED  %s — dropped from the sequence" % who)
    else:
        log("inbox checked (%d messages): no replies, no bounces" % result["scanned"])
    return result


def cmd_inbox(args):
    dry = getattr(args, "dry_run", False)
    con = state.connect(args.db)
    run_id = None if dry else state.start_run(con, "inbox", args.trigger)
    try:
        result = inbox.scan(con, dry_run=dry)
    except inbox.InboxError as ex:
        if run_id:
            state.finish_run(con, run_id, "failed", detail=str(ex)[:280])
        con.close()
        print(ex, file=sys.stderr)
        return 1
    found = list(result["replies"]) + list(result["bounces"])
    if run_id:
        state.finish_run(con, run_id, "ok", found=result["scanned"],
                         new_contacts=len(found),
                         detail="%d read, %d replied, %d bounced"
                         % (result["scanned"], len(result["replies"]), len(result["bounces"])))
    con.close()
    print("Read %d messages since %s, watching %d people who have not answered."
          % (result["scanned"], result["since"], result["watching"]))
    for who, note in list(result["replies"].items()) + list(result["bounces"].items()):
        print("  %-34s %s" % (who, note))
    if not found:
        print("  Nothing new.")
    return 0


def cmd_send(args):
    # Before anything goes out. A reply that landed since the last run must
    # remove that person from today's batch.
    check_inbox(args.db)
    con = state.connect(args.db)
    # cron wraps this in flock; a click in the UI does not, and two senders
    # running at once would send the same batch twice.
    busy = state.running(con, "send")
    if busy and not getattr(args, "force", False):
        log("A send started at %s is still marked running. Use --force to override."
            % busy["started_at"])
        con.close()
        return 1
    run_id = state.start_run(con, "send", args.trigger)
    con.close()
    cmd = [sys.executable, str(SENDER)]
    if getattr(args, "only", ""):
        cmd += ["--only", args.only]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    print(out, flush=True)
    sent = len(re.findall(r"Sent to ", out))
    con = state.connect(args.db)
    state.finish_run(con, run_id, "ok" if r.returncode == 0 else "failed",
                     drafted=sent, detail=out.splitlines()[-1][:280] if out else "")
    con.close()
    return r.returncode


# ------------------------------------------------------------------ schedule

def crontab_lines():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout.splitlines() if r.returncode == 0 else []


def write_crontab(lines):
    body = "\n".join(l for l in lines if l.strip()).strip()
    if not body:
        # An empty crontab is removed, not written as a blank line.
        subprocess.run(["crontab", "-r"], capture_output=True, text=True)
        return
    r = subprocess.run(["crontab", "-"], input=body + "\n", capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "crontab failed").strip())


JOBS = (("refresh", "refresh_enabled", "refresh_cron"),
        ("send", "send_enabled", "send_cron"),
        ("inbox", "inbox_enabled", "inbox_cron"))


def build_lines(cfg):
    """
    The cron entries this project owns, one per enabled job, built from the
    saved expression. Whatever the user typed is what cron gets — no second
    interpretation of the schedule anywhere.
    """
    RUNDIR.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    out = []
    for name, enabled_key, cron_key in JOBS:
        if cfg.get(enabled_key) != "1":
            continue
        expression = cfg.get(cron_key, "").strip()
        cron.parse(expression)          # refuse to install something invalid
        out.append(
            '%s cd "%s" && flock -n "%s/%s.lock" "%s" pipeline.py %s '
            '--trigger cron >> "%s/%s.log" 2>&1 %s:%s'
            % (expression, ROOT, RUNDIR, name, python, name, RUNDIR, name, MARKER, name))
    return out


def apply_schedule(con):
    cfg = state.settings(con)
    keep = [l for l in crontab_lines() if MARKER not in l]
    write_crontab(keep + build_lines(cfg))
    return cfg


def upcoming(cfg, key_enabled, key_cron, now=None, count=1):
    """The next run times for one job, or [] when it is off or misconfigured."""
    if cfg.get(key_enabled) != "1":
        return []
    try:
        return cron.next_runs(cfg.get(key_cron, ""), now, count)
    except cron.CronError:
        return []


def next_refresh(cfg, now=None):
    runs = upcoming(cfg, "refresh_enabled", "refresh_cron", now)
    return runs[0] if runs else None


def next_send(cfg, now=None):
    runs = upcoming(cfg, "send_enabled", "send_cron", now)
    return runs[0] if runs else None


def describe_job(cfg, key_enabled, key_cron, count=3):
    """What one job's schedule means, and when it fires next."""
    expression = cfg.get(key_cron, "")
    out = {"expression": expression, "enabled": cfg.get(key_enabled) == "1",
           "description": "", "error": "", "next_runs": []}
    try:
        out["description"] = cron.describe(expression)
    except cron.CronError as ex:
        out["error"] = str(ex)
        return out
    out["next_runs"] = [d.strftime(state.TIME_FORMAT)
                        for d in upcoming(cfg, key_enabled, key_cron, count=count)]
    return out


def schedule_snapshot(con):
    cfg = state.settings(con)
    nr, ns = next_refresh(cfg), next_send(cfg)
    installed = [l for l in crontab_lines() if MARKER in l]
    return {
        "settings": cfg,
        "jobs": {name: describe_job(cfg, enabled, expr) for name, enabled, expr in JOBS},
        "cron_installed": len(installed),
        "cron_lines": installed,
        "cron_available": bool(which_crontab()),
        "next_refresh": nr.strftime(state.TIME_FORMAT) if nr else "",
        "next_send": ns.strftime(state.TIME_FORMAT) if ns else "",
        "runs": state.recent_runs(con, 15),
        "in_progress": state.running(con),
    }


def which_crontab():
    from shutil import which
    return which("crontab")


def cmd_schedule(args):
    con = state.connect(args.db)
    if not which_crontab():
        print("crontab isn't installed. On Ubuntu:  sudo apt install cron", file=sys.stderr)
        con.close()
        return 1
    apply_schedule(con)
    snap = schedule_snapshot(con)
    for name, _e, _c in JOBS:
        job = snap["jobs"][name]
        print("%-8s %s" % (name + ":", job["description"] if job["enabled"] else "off"))
        if job["enabled"] and job["next_runs"]:
            print("         next: %s" % ", ".join(job["next_runs"]))
    print("cron entries installed: %d" % snap["cron_installed"])
    con.close()
    return 0


def cmd_status(args):
    con = state.connect(args.db)
    snap = schedule_snapshot(con)
    cfg = snap["settings"]
    print("\nSCHEDULE")
    for name, _e, _c in JOBS:
        job = snap["jobs"][name]
        print("  %-8s %s" % (name, job["description"] if job["enabled"] else "off"))
        if job["enabled"]:
            print("           %s" % (job["expression"]))
            print("           next: %s" % (", ".join(job["next_runs"]) or "—"))
        if job["error"]:
            print("           PROBLEM: %s" % job["error"])
    print("  cron entries: %d" % snap["cron_installed"])
    print("\nRECENT RUNS")
    if not snap["runs"]:
        print("  none yet")
    for r in snap["runs"][:10]:
        print("  %-19s %-8s %-8s %-7s %s" % (
            r["started_at"], r["kind"], r["status"],
            ("$%.4f" % r["cost_usd"]) if r["cost_usd"] else "—", r["detail"][:60]))
    con.close()
    return 0


def main():
    p = argparse.ArgumentParser(description="Scheduled work for the job pipeline.")
    p.add_argument("--db", default=str(state.DB_PATH))
    p.add_argument("--trigger", default="manual", choices=["manual", "cron", "ui"])
    sub = p.add_subparsers(dest="command")
    for name in ("refresh", "send", "inbox", "schedule", "status"):
        sp = sub.add_parser(name)
        sp.add_argument("--db", default=str(state.DB_PATH))
        sp.add_argument("--trigger", default="manual", choices=["manual", "cron", "ui"])
        if name in ("refresh", "send"):
            sp.add_argument("--force", action="store_true",
                            help="run even if another %s is marked running" % name)
        if name == "inbox":
            sp.add_argument("--dry-run", action="store_true", dest="dry_run",
                            help="say what would be marked, change nothing")
        if name == "send":
            sp.add_argument("--only", default="",
                            help="a file of addresses, one per line: send to nobody else")
    args = p.parse_args()
    if not args.command:
        p.print_help()
        return 1
    return {"refresh": cmd_refresh, "send": cmd_send, "inbox": cmd_inbox,
            "schedule": cmd_schedule, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
