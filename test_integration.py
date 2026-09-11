#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_integration.py — checks that the hunter, the bridge, the drafter, the
database and the sender work together.

Everything happens in a temporary folder with its own database. NOTHING is sent:
the sender runs with --dry-run, which never opens a connection to Gmail.

    python3 test_integration.py
"""

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402

HUNTER_COLS = ["source", "company", "contact", "email", "role", "remote", "scope",
               "apply_from_co", "location", "url", "posted", "ai_score", "seen",
               "description"]
POSTING = ("Quill | Fullstack SWE | Remote\nWe are a fullstack SDK for customer-facing "
           "analytics. You would own Postgres query planning and the React embed.")
JOBS = [
    ["hn", "Acme AI", "someone", "jobs@acme-ai.com",
     "Acme AI | Senior LLM Engineer | REMOTE (worldwide) | Full-time",
     "yes", "Global / worldwide", "yes", "", "https://news.ycombinator.com/item?id=1", "2026-09", "6", "2026-09-11", ""],
    ["hn", "Quill", "R_R", "rishi@quill.example",
     "Quill | Fullstack SWE | Full-time | Remote, PT/ET hours | $150 - 210K USD | https://quill.example/",
     "yes", "Remote, country unspecified", "ask", "", "https://news.ycombinator.com/item?id=2", "2026-09", "0", "2026-09-11", POSTING],
    ["hn", "Neuralwatt", "scottcha", "hiring@neuralwatt.example",
     "Neuralwatt | REMOTE | Seattle | Full-time",
     "yes", "Restricted (US/UK/EU/CA)", "no", "", "https://news.ycombinator.com/item?id=3", "2026-09", "3", "2026-09-11", ""],
    ["jobot", "Jobot (confidential client)", "Dana Reyes", "dana.reyes@jobot.example",
     "Software/AI Engineer (Fullstack)", "yes", "Remote (US)", "no", "Rollingwood, TX",
     "https://jobot.com/x", "2026-07-22", "6", "2026-09-11", ""],
    ["hn", "Acme AI", "someone", "jobs@acme-ai.com",
     "Acme AI | Data Entry | REMOTE (worldwide)", "yes", "Global / worldwide", "yes", "",
     "https://news.ycombinator.com/item?id=4", "2026-09", "1", "2026-09-11", ""],
]

failures = []


def check(name, condition, detail=""):
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "  <- " + str(detail)[:220]))
    if not condition:
        failures.append(name)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def config(folder, db, **extra):
    fields = {"campaign": "test-run", "follow_ups": "2", "wait_days": "3",
              "include_unsubscribe": "no"}
    fields.update(extra)
    subject = fields.pop("subject", "{{ai_subject}}")
    max_per_day = fields.pop("max_per_day", "60")
    template = fields.pop("template", "message.txt")
    rest = "\n".join("%s = %s" % (k, v) for k, v in fields.items())
    (folder / "config.ini").write_text(f"""[gmail]
address = me@gmail.com
app_password = abcdabcdabcdabcd
sender_name = Juan

[sending]
csv_file = recipients.csv
db = {db}
subject = {subject}
text_template = {template}
max_per_day = {max_per_day}
limit_24h = 450
pause_min = 0
pause_max = 0
{rest}
""", encoding="utf-8")


def send(folder):
    r = subprocess.run([PY, "send_emails.py", "--dry-run"], cwd=folder,
                       capture_output=True, text=True)
    return r.stdout + r.stderr


def main():
    tmp = Path(tempfile.mkdtemp(prefix="integration-"))
    db = tmp / "state.db"
    try:
        hunter = tmp / "hunter"
        hunter.mkdir()
        with open(hunter / "jobs.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(HUNTER_COLS)
            w.writerows(JOBS)

        out = tmp / "sender"
        out.mkdir()
        shutil.copy(ROOT / "gmail-sender" / "send_emails.py", out)
        shutil.copy(ROOT / "state.py", out.parent)      # send_emails looks next door
        # A finished fallback, because the shipped one carries >>> markers on
        # purpose and the sender now (correctly) refuses to send those.
        (out / "fallback_template.txt").write_text(
            "{{greeting}},\n\nI'm writing about {{reference}}.\n\n"
            "I build production LLM systems and I'd like to be considered.\n\n"
            "I'm based in Colombia (UTC-5), full overlap with US hours.\n\n"
            "Here's the posting: {{url}}\n\nJuan Anez\n", encoding="utf-8")
        (out / "unsubscribed.txt").write_text("# empty\n", encoding="utf-8")
        (out / "message.txt").write_text("{{ai_body}}\n", encoding="utf-8")

        print("\n[1] The bridge loads the database and exports the CSV")
        r = subprocess.run([PY, str(ROOT / "prepare.py"),
                            "--source", str(hunter / "jobs.csv"),
                            "--out", str(out / "recipients.csv"),
                            "--db", str(db), "--scope", "yes,ask",
                            "--own-email", "me@gmail.com"], capture_output=True, text=True)
        check("the bridge runs without error", r.returncode == 0, r.stderr)
        con = state.connect(db)
        emails = [c["email"] for c in state.contacts(con)]
        check("drops scope 'no'", "dana.reyes@jobot.example" not in emails
              and "hiring@neuralwatt.example" not in emails, emails)
        check("merges the repeated recruiter", emails.count("jobs@acme-ai.com") == 1, emails)
        acme = next(c for c in state.contacts(con) if c["email"] == "jobs@acme-ai.com")
        check("keeps the BEST posting of the duplicate",
              acme["role"] == "Senior LLM Engineer", acme["role"])
        check("everyone starts as 'new'", state.summary(con)["new"] == 2, state.summary(con))

        print("\n[2] Running the bridge twice neither duplicates nor overwrites status")
        state.set_status(con, "rishi@quill.example", "sent")
        con.close()
        subprocess.run([PY, str(ROOT / "prepare.py"),
                        "--source", str(hunter / "jobs.csv"),
                        "--out", str(out / "recipients.csv"), "--db", str(db)],
                       capture_output=True, text=True)
        con = state.connect(db)
        check("still 2 contacts", len(state.contacts(con)) == 2)
        quill = next(c for c in state.contacts(con) if c["email"] == "rishi@quill.example")
        check("does not overwrite advanced status", quill["status"] == "sent", quill["status"])
        state.set_status(con, "rishi@quill.example", "new")
        con.close()

        print("\n[3] With no API the drafter falls back, and the sender uses it")
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        r = subprocess.run([PY, str(ROOT / "draft.py"), "--db", str(db),
                            "--csv", str(out / "recipients.csv"),
                            "--fallback", str(out / "fallback_template.txt"),
                            "--review", str(out / "drafts.md")],
                           capture_output=True, text=True, env=env)
        check("the drafter finishes without credentials", r.returncode == 0, r.stderr[-300:])
        check("switches the model off after the auth failure", "AUTH" in r.stderr, r.stderr[-200:])
        check("leaves the review file", (out / "drafts.md").exists())
        rows = list(csv.DictReader(
            (out / "recipients.csv").read_text(encoding="utf-8-sig").splitlines()))
        check("the CSV carries a subject and a body",
              all(x["ai_subject"] and x["ai_body"] for x in rows),
              [(x["email"], x["text_source"]) for x in rows])
        config(out, db)
        output = send(out)
        check("the sender reads 2 recipients", "CSV: 2 recipients" in output, output[:200])
        check("uses the drafted text", "I'm based in Colombia" in output, output[-400:])
        check("no placeholder markers survive into the send", ">>>" not in output)
        check("never produces 'Hi ,'", "Hi ," not in output)
        check("no unfilled fields left", "{{" not in output)

        print("\n[4] An email with no subject or body never goes out")
        con = state.connect(db)
        con.execute("DELETE FROM drafts WHERE email='rishi@quill.example'")
        con.commit()
        state.export_csv(con, out / "recipients.csv")
        con.close()
        output = send(out)
        check("skips the one left without text", "1 recipients are not safe to send" in output,
              [l for l in output.splitlines() if "safe to send" in l])
        check("and only 1 is left in the batch", "this batch: 1" in output,
              [l for l in output.splitlines() if "batch" in l])
        subprocess.run([PY, str(ROOT / "draft.py"), "--db", str(db),
                        "--csv", str(out / "recipients.csv"),
                        "--fallback", str(out / "fallback_template.txt"),
                        "--review", str(out / "drafts.md")],
                       capture_output=True, text=True, env=env)

        print("\n[5] The sequence: first email, then up to 2 follow-ups")
        con = state.connect(db)
        long_ago = (datetime.now() - timedelta(days=4)).strftime(state.TIME_FORMAT)
        today = datetime.now().strftime(state.TIME_FORMAT)
        a, b = "jobs@acme-ai.com", "rishi@quill.example"

        due, fresh = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("with nothing sent, everyone is a first contact",
              due == [] and len(fresh) == 2, (len(due), len(fresh)))

        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                    "VALUES (?,?,'sent','r',0)", (long_ago, a))
        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                    "VALUES (?,?,'sent','r',0)", (today, b))
        con.commit()
        due, fresh = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("the one from 4 days ago is due for follow-up 1",
              [(c["email"], st) for c, st in due] == [(a, 1)], due)
        check("the one sent today is not due, and is no longer a first contact",
              fresh == [], fresh)

        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                    "VALUES (?,?,'sent','r',1)", (long_ago, a))
        con.commit()
        due, _ = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("after follow-up 1, follow-up 2 becomes due",
              [(c["email"], st) for c, st in due] == [(a, 2)], due)

        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                    "VALUES (?,?,'sent','r',2)", (long_ago, a))
        con.commit()
        due, _ = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("after all 2 follow-ups the sequence is over", due == [], due)
        # Even with no waiting period at all, an exhausted person stays out.
        no_wait = state.sequence_queue(con, 0, 2, out / "unsubscribed.txt")[0]
        check("and a third is never due, however long you wait",
              a not in [c["email"] for c, _ in no_wait],
              [(c["email"], st) for c, st in no_wait])
        check("raising the limit lets one more through",
              [(c["email"], st) for c, st in
               state.sequence_queue(con, 3, 3, out / "unsubscribed.txt")[0]] == [(a, 3)])

        print("\n[6] A reply ends the sequence, without anyone remembering to stop it")
        con.execute("DELETE FROM sends WHERE email=? AND stage>0", (a,))
        con.commit()
        due, _ = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("before replying, they are due", len(due) == 1, due)
        state.set_status(con, a, "replied", note="asked for a call")
        due, fresh = state.sequence_queue(con, 3, 2, out / "unsubscribed.txt")
        check("after replying they are in neither lane",
              due == [] and fresh == [], (due, fresh))
        check("because marking a reply unsubscribes them",
              a in state.unsubscribed(con, out / "unsubscribed.txt"))
        check("the summary counts the reply", state.summary(con)["replied"] == 1)

        print("\n[7] Follow-ups go first when the daily cap is tight")
        cwd = os.getcwd()
        con.execute("DELETE FROM unsubscribed")
        con.execute("UPDATE contacts SET status='drafted'")
        con.execute("DELETE FROM sends")
        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                    "VALUES (?,?,'sent','r',0)", (long_ago, a))
        con.commit()
        # The draft for the email each person is actually owed.
        state.save_draft(con, a, "f1", "Following up on the role",
                         "Hi,\n\n" + ("One thing I left out. " * 12) + "\n\nJuan Anez",
                         "ai-follow-up-1", stage=1)
        state.export_csv(con, out / "recipients.csv")
        con.close()

        rows3 = list(csv.DictReader(
            (out / "recipients.csv").read_text(encoding="utf-8-sig").splitlines()))
        by_email = {r["email"]: r for r in rows3}
        check("the CSV carries the stage each person is owed",
              by_email[a]["stage"] == "1" and by_email[b]["stage"] == "0",
              {k: v["stage"] for k, v in by_email.items()})
        check("and the follow-up text, not the first email",
              "One thing I left out" in by_email[a]["ai_body"], by_email[a]["ai_body"][:60])

        config(out, db, campaign="tight")
        os.chdir(out)
        try:
            sys.modules.pop("seq", None)
            seq = load("seq", out / "send_emails.py")
            cfg = seq.load_config()
            con = state.connect(db)
            recipients, _cols = seq.read_recipients(cfg["csv_file"])
            queue, due_count, stale, missing = seq.build_queue(cfg, con, recipients)
            con.close()
        finally:
            os.chdir(cwd)
        check("the follow-up is first in the queue", queue[0][0] == a, [q[0] for q in queue])
        check("the first contact comes after", queue[1][0] == b, [q[0] for q in queue])
        check("the queue reports how many are follow-ups", due_count == 1, due_count)
        check("nothing is stale and nothing is missing",
              stale == [] and missing == 0, (stale, missing))
        check("each entry carries its stage",
              [st for _e, _d, st in queue] == [1, 0], [st for _e, _d, st in queue])

        print("\n[8] The unsubscribe footer can be turned off")
        sender = load("sender", out / "send_emails.py")
        base = {"address": "me@gmail.com", "sender_name": "Juan", "subject": "hi"}
        templates = {"text": "hi", "html": ""}
        without = sender.build_message({**base, "include_unsubscribe": False},
                                       "a@b.com", {}, templates, None)
        with_ = sender.build_message({**base, "include_unsubscribe": True},
                                     "a@b.com", {}, templates, None)
        check("include_unsubscribe = no removes List-Unsubscribe",
              without["List-Unsubscribe"] is None)
        check("include_unsubscribe = yes keeps it", with_["List-Unsubscribe"] is not None)

        print("\n[9] Validation rejects what must not go out")
        drafter = load("drafter", ROOT / "draft.py")
        c = {"url": "https://news.ycombinator.com/item?id=2", "reference": "the role"}
        subject_ok = "About the Fullstack SWE role at Quill"
        body_ok = "Hi,\n\n" + ("I build LLM systems in production. " * 14) + "\n\nJuan Anez"
        check("accepts a correct draft", drafter.validate(subject_ok, body_ok, c) == "",
              drafter.validate(subject_ok, body_ok, c))
        check("rejects a short body", "body is" in drafter.validate(subject_ok, "Hi, short.", c))
        check("rejects a short subject", "subject is" in drafter.validate("Hi", body_ok, c))
        check("rejects unfilled template text",
              ">>>" in drafter.validate(subject_ok, body_ok.replace("Juan Anez", ">>> sig"), c))
        check("rejects template filler phrases",
              "hope this email finds you" in drafter.validate(
                  subject_ok, "Hi,\n\nI hope this email finds you well. " + body_ok, c))
        check("rejects an invented URL",
              "invented the URL" in drafter.validate(
                  subject_ok, body_ok + "\nhttps://evil.example.com", c))
        check("accepts the posting's own URL",
              drafter.validate(subject_ok, body_ok + "\n" + c["url"], c) == "")
        check("accepts a URL that is in the corpus",
              drafter.validate(subject_ok, body_ok + "\nhttps://linkedin.com/in/janezmejias", c,
                               corpus="see https://linkedin.com/in/janezmejias") == "")

        print("\n[10] Retry, and the cache accounting")

        def fake_client(payloads, cached=True):
            class Messages:
                def __init__(self): self.n = 0
                def create(self, **kw):
                    d = payloads[min(self.n, len(payloads) - 1)]
                    first = self.n == 0
                    self.n += 1
                    return types.SimpleNamespace(
                        content=[types.SimpleNamespace(type="text", text=json.dumps(d))],
                        usage=types.SimpleNamespace(
                            input_tokens=180, output_tokens=300,
                            cache_creation_input_tokens=5000 if (first and cached) else 0,
                            cache_read_input_tokens=0 if (first or not cached) else 5000))
            return types.SimpleNamespace(messages=Messages())

        sdk = types.SimpleNamespace(
            RateLimitError=type("RateLimitError", (Exception,), {}),
            APIStatusError=type("APIStatusError", (Exception,), {}),
            APIConnectionError=type("APIConnectionError", (Exception,), {}),
            AuthenticationError=type("AuthenticationError", (Exception,), {}),
            PermissionDeniedError=type("PermissionDeniedError", (Exception,), {}))
        bad = {"card": "CARD-X", "subject": "Hi", "body": "too short"}
        good = {"card": "CARD-VOICE-LATENCY", "subject": subject_ok, "body": body_ok}
        s, _, card, usages, reason = drafter.with_retry(
            fake_client([bad, good]), sdk, "stable", dict(c), "")
        check("the second attempt saves the draft", reason == "" and s == subject_ok, reason)
        check("reports the card it chose", card == "CARD-VOICE-LATENCY", card)
        s, _, _, _, reason = drafter.with_retry(fake_client([bad]), sdk, "stable", dict(c), "")
        check("two bad ones in a row give up", reason != "" and s == "", reason)

        spend = drafter.Spend()
        for u in usages:
            spend.add(u)
        # 2 calls: the 1st writes 5000 to cache, the 2nd reads 5000.
        expected = ((180 * 2 + 5000 * 1.25 + 5000 * 0.10) * drafter.PRICE_INPUT
                    + 600 * drafter.PRICE_OUTPUT)
        check("bills the cache with its factors (1.25x and 0.1x)",
              abs(spend.dollars - expected) < 1e-9, (spend.dollars, expected))
        check("caching is cheaper than not caching", spend.dollars < spend.without_cache,
              (spend.dollars, spend.without_cache))
        print("       (with these numbers caching saves %.0f%%)"
              % (100 * (1 - spend.dollars / spend.without_cache)))

        print("\n[11] Each follow-up sees every email already sent")
        email1 = {"subject": subject_ok, "body": body_ok}
        email2 = {"subject": "Following up", "body": "Hi,\n\nOne thing about the eval loop.\n\nJuan"}
        prompt_first = drafter.posting_for(dict(c, greeting="Hi"))
        prompt_f1 = drafter.posting_for(dict(c, greeting="Hi"), previous=[email1], stage=1)
        prompt_f2 = drafter.posting_for(dict(c, greeting="Hi"),
                                        previous=[email1, email2], stage=2)
        check("the follow-up prompt declares itself as one",
              "FOLLOW-UP" in prompt_f1 and "FOLLOW-UP" not in prompt_first)
        check("follow-up 1 gets the first email",
              body_ok[:40] in prompt_f1 and "EMAIL 1 ALREADY SENT" in prompt_f1)
        check("follow-up 2 gets BOTH earlier emails",
              "EMAIL 1 ALREADY SENT" in prompt_f2 and "EMAIL 2 ALREADY SENT" in prompt_f2
              and "eval loop" in prompt_f2, prompt_f2[:200])
        check("and knows it is the last one",
              "the last one" in prompt_f2 and "the last one" not in prompt_f1)
        check("it is told never to mention that it is writing again",
              "never apologise for" in prompt_f1)
        stage_prints = [drafter.fingerprint_for(dict(c), "corpus", "en", st) for st in (0, 1, 2)]
        check("every stage has its own fingerprint",
              len(set(stage_prints)) == 3, stage_prints)
        short = "Hi,\n\n" + ("One thing I left out: the eval loop. " * 5) + "\n\nJuan Anez"
        check("a follow-up length would be rejected as a first email",
              drafter.validate(subject_ok, short, c) != "")
        check("but passes with the follow-up minimum",
              drafter.validate(subject_ok, short, c, min_body=180) == "",
              drafter.validate(subject_ok, short, c, min_body=180))

        print("\n[12] Preflight blocks a bad first send")
        sender = load("sender2", out / "send_emails.py")
        check("blocks unfinished template text",
              "placeholder" in sender.message_problem(
                  {"subject": "{{ai_subject}}"}, {"text": "{{ai_body}}"},
                  {"ai_subject": "About the role",
                   "ai_body": "Hi,\n\n>>> REPLACE THIS PARAGRAPH\n\nJuan"}),
              sender.message_problem({"subject": "{{ai_subject}}"}, {"text": "{{ai_body}}"},
                                     {"ai_subject": "x", "ai_body": ">>> x"}))
        check("blocks an empty body",
              sender.message_problem({"subject": "{{ai_subject}}"}, {"text": "{{ai_body}}"},
                                     {"ai_subject": "About the role", "ai_body": ""}) == "no body")
        check("lets a finished email through",
              sender.message_problem({"subject": "{{ai_subject}}"}, {"text": "{{ai_body}}"},
                                     {"ai_subject": "About the role at Quill",
                                      "ai_body": "Hi,\n\nReal text.\n\nJuan Anez"}) == "")

        # The unfinished fallback template is what would actually have gone out.
        con = state.connect(db)
        template = (ROOT / "gmail-sender" / "fallback_template.txt").read_text(encoding="utf-8")
        check("the shipped fallback really is unfinished", ">>>" in template)
        # It has to be the draft for the email this person is actually owed next,
        # or the export quite rightly ignores it.
        counts = state.stages(con)
        victim = next(c["email"] for c in state.contacts(con) if counts.get(c["email"], 0) == 0)
        state.save_draft(con, victim, "unfinished", "About the role", template,
                         "fallback", stage=0)
        state.export_csv(con, out / "recipients.csv")
        con.close()
        config(out, db, campaign="preflight-test")
        os.chdir(out)
        try:
            sys.modules.pop("sender3", None)
            fresh = load("sender3", out / "send_emails.py")
            report = fresh.preflight(db_path=str(db))
        finally:
            os.chdir(cwd)
        titles = " | ".join(c["title"] for c in report["checks"])
        check("the report says NOT ready", report["ok"] is False, titles)
        check("it names the unfinished email as blocked", "not safe to send" in titles, titles)
        check("and that one is excluded from the batch",
              report["batch"]["blocked"] >= 1, report["batch"])
        check("it still shows what WOULD go out",
              len(report["previews"]) == report["batch"]["would_send_now"],
              (len(report["previews"]), report["batch"]["would_send_now"]))
        check("it checks the Gmail credentials", any("credentials" in c["title"]
                                                    for c in report["checks"]), titles)
        check("every check carries a level the UI understands",
              all(c["level"] in ("ok", "warn", "block") for c in report["checks"]))
        output = send(out)
        check("the real send refuses it too, not just the report",
              "not safe to send" in output,
              [l for l in output.splitlines() if "safe" in l])

        print("\n[13] Verifying the Gmail login never sends anything")
        # Example credentials fail before a socket is even opened.
        config(out, db, campaign="login-test")
        os.chdir(out)
        try:
            sys.modules.pop("sender4", None)
            mod = load("sender4", out / "send_emails.py")
            cfg = mod.load_config()
            cfg["address"] = "youraddress@gmail.com"
            check("bad credentials are caught before connecting",
                  "config.ini" in mod.verify_login(cfg), mod.verify_login(cfg))
            sent = []
            original = mod.GmailConnection.send
            mod.GmailConnection.send = lambda self, msg: sent.append(msg)
            connected = []
            mod.GmailConnection.connect = lambda self: connected.append(1)
            problem = mod.verify_login(mod.load_config())
            mod.GmailConnection.send = original
            check("it does connect", connected == [1], connected)
            check("and it sends nothing at all", sent == [], sent)
            check("a clean connection reports success", problem == "", problem)
        finally:
            os.chdir(cwd)

        print("\n[14] The two guards that cost real drafts, and their false positives")
        corpus = (ROOT / "profile.md").read_text(encoding="utf-8")

        # Claims about the reader's company. The unanchored version of this
        # rejected three good drafts for every real catch, so it now only fires
        # on a declarative that starts a sentence.
        reader_cases = [
            ("Hi,\n\nYou're building in fintech, and I've spent six years there.", True),
            ("Hi,\n\nI read the post. You're a payments company, so this fits.", True),
            ("Hi,\n\nYour product is clearly aimed at enterprises.", True),
            ("Hi,\n\nIf you're building something real, I'd like to talk.", False),
            ("Hi,\n\nI'd like to hear what you're working on.", False),
            ("Hi,\n\nYour post didn't say what you're building, so I'll be direct.", False),
            ("Hi,\n\nHappy to talk whenever you're ready.", False),
        ]
        for text, should in reader_cases:
            hit = any(p.search(text) for p in drafter.ABOUT_THE_READER)
            check("reader-claim guard: %s" % ("catches" if should else "allows")
                  + " %r" % text.split("\n\n")[1][:38],
                  hit == should, text)

        # Re-dating. Grounded in the corpus: the span has to appear there.
        span_cases = [
            ("For the last two years I've been putting agents in production.", False),
            ("I've spent the last year and a half building systems at Enghouse.", True),
            ("I've spent the past six years moving through that stack.", True),
            ("Over the last three years I ran that platform.", True),
            ("Twelve years of Java and Spring behind that.", False),
            ("I wrote last week about the role.", False),
            ("I shipped that last month.", False),
        ]
        for text, should in span_cases:
            hit = drafter.unsupported_timespan(text, corpus)
            check("timespan guard: %s %r" % ("flags" if should else "allows", text[:40]),
                  bool(hit) == should, hit)

        check("'the last two years' is genuinely in the profile",
              "the last two years" in " ".join(corpus.lower().split()))

        print("\n[15] A blocked email says WHY it was blocked")
        con = state.connect(db)
        counts = state.stages(con)
        victim = next(c["email"] for c in state.contacts(con) if counts.get(c["email"], 0) == 0)
        state.save_draft(con, victim, "broken", "About the role",
                         (ROOT / "gmail-sender" / "fallback_template.txt").read_text(encoding="utf-8"),
                         "fallback", reason="claims something about the reader's company",
                         stage=0)
        stored = state.latest_draft(con, victim)
        check("the reason is stored with the draft",
              stored["reason"] == "claims something about the reader's company", stored["reason"])
        state.export_csv(con, out / "recipients.csv")
        con.close()
        rows2 = list(csv.DictReader(
            (out / "recipients.csv").read_text(encoding="utf-8-sig").splitlines()))
        check("and it reaches the CSV",
              any(r["text_reason"] == "claims something about the reader's company"
                  for r in rows2), [r["text_reason"] for r in rows2])
        config(out, db, campaign="reason-test")
        os.chdir(out)
        try:
            sys.modules.pop("sender5", None)
            mod2 = load("sender5", out / "send_emails.py")
            rep2 = mod2.preflight(db_path=str(db))
        finally:
            os.chdir(cwd)
        blocked = [c for c in rep2["checks"] if c["level"] == "block" and "not safe" in c["title"]]
        check("the preflight surfaces the cause, not just the symptom",
              bool(blocked) and "reader's company" in blocked[0]["detail"],
              blocked[0]["detail"] if blocked else "no block")
        check("and it names the command that fixes it",
              bool(blocked) and "draft.py --fix" in blocked[0]["detail"],
              blocked[0]["detail"] if blocked else "")

        print("\n[16] Runs, settings and the cron the UI writes")
        pipeline = load("pipeline", ROOT / "pipeline.py")
        con = state.connect(db)

        # Settings round-trip. The first version of this sliced the key prefix
        # one character too far, so nothing ever read back.
        state.save_settings(con, {"refresh_enabled": "1", "refresh_cron": "15 6 * * *"})
        got = state.settings(con)
        check("settings survive a round-trip",
              got["refresh_enabled"] == "1" and got["refresh_cron"] == "15 6 * * *", got)
        check("unknown keys are ignored",
              "nonsense" not in state.save_settings(con, {"nonsense": "x"}))

        # A database written before the schedule became a cron expression.
        con.execute("DELETE FROM meta WHERE key LIKE 'setting:%'")
        for k, v in (("refresh_at", "06:15"), ("send_from", "9"), ("send_to", "19")):
            con.execute("INSERT INTO meta(key, value) VALUES (?,?)", ("setting:" + k, v))
        con.commit()
        migrated = state.settings(con)
        check("an old daily time migrates to an expression",
              migrated["refresh_cron"] == "15 6 * * *", migrated)
        check("an old send window migrates too",
              migrated["send_cron"] == "0 9-19 * * *", migrated)
        check("the legacy keys do not survive",
              "refresh_at" not in migrated and "send_from" not in migrated, migrated)

        rid = state.start_run(con, "refresh", "ui")
        check("a run starts as running", state.running(con, "refresh") is not None)
        state.finish_run(con, rid, "ok", drafted=7, cost_usd=0.1234, detail="7 written")
        check("and stops being running once finished", state.running(con, "refresh") is None)
        last = state.recent_runs(con, 1)[0]
        check("the run records its cost and trigger",
              abs(last["cost_usd"] - 0.1234) < 1e-9 and last["trigger"] == "ui", last)

        now = datetime(2026, 9, 11, 12, 0, 0)
        cfg = {"refresh_enabled": "1", "refresh_cron": "15 6 * * *",
               "send_enabled": "1", "send_cron": "0 9-19 * * *"}
        check("next search rolls to tomorrow when today's time has passed",
              pipeline.next_refresh(cfg, now) == datetime(2026, 9, 12, 6, 15),
              pipeline.next_refresh(cfg, now))
        check("next send is the next hour inside the window",
              pipeline.next_send(cfg, now) == datetime(2026, 9, 11, 13, 0),
              pipeline.next_send(cfg, now))
        check("nothing scheduled means no next run",
              pipeline.next_refresh({**cfg, "refresh_enabled": "0"}, now) is None)
        check("a broken expression means no next run, not a crash",
              pipeline.next_refresh({**cfg, "refresh_cron": "99 * * * *"}, now) is None)

        weekly = {"refresh_enabled": "1", "refresh_cron": "0 9 * * MON,THU",
                  "send_enabled": "1", "send_cron": "*/30 9-17 * * MON-FRI",
                  "inbox_enabled": "1", "inbox_cron": "*/15 * * * *"}
        lines = pipeline.build_lines(weekly)
        check("all three cron entries are generated", len(lines) == 3, lines)
        check("the inbox has its own entry",
              any("pipeline.py inbox" in l for l in lines), lines)
        check("each job can be scheduled on its own",
              len(pipeline.build_lines({**weekly, "send_enabled": "0"})) == 2)
        check("every entry carries the project marker",
              all(pipeline.MARKER in l for l in lines), lines)
        check("the expression goes into cron verbatim",
              lines[0].startswith("0 9 * * MON,THU ") and lines[1].startswith("*/30 9-17 * * MON-FRI "),
              [l[:26] for l in lines])
        check("entries call pipeline.py, not a shell script",
              all("pipeline.py" in l for l in lines))
        try:
            pipeline.build_lines({**weekly, "refresh_cron": "99 * * * *"})
            check("an invalid expression is never installed", False, "no error raised")
        except Exception as ex:                                  # noqa: BLE001
            check("an invalid expression is never installed", "minute" in str(ex), str(ex))

        job = pipeline.describe_job(weekly, "refresh_enabled", "refresh_cron")
        check("the snapshot explains the schedule in words",
              job["description"] == "At 09:00, on Monday and Thursday", job)
        check("and lists the next runs", len(job["next_runs"]) == 3, job)

        # The one that matters: saving must not eat anything else in the crontab.
        foreign = ["0 3 * * * /usr/bin/backup.sh", "@reboot /home/me/thing"]
        written = {}
        pipeline.crontab_lines = lambda: foreign + [pipeline.build_lines(weekly)[0]]
        pipeline.write_crontab = lambda ls: written.setdefault("lines", list(ls))
        state.save_settings(con, weekly)
        pipeline.apply_schedule(con)
        check("other people's cron lines are preserved",
              all(f in written["lines"] for f in foreign), written.get("lines"))
        check("and ours are replaced, not duplicated",
              sum(1 for l in written["lines"] if pipeline.MARKER in l) == 3,
              written.get("lines"))

        written.clear()
        state.save_settings(con, {"refresh_enabled": "0", "send_enabled": "0",
                                  "inbox_enabled": "0"})
        pipeline.apply_schedule(con)
        check("turning everything off leaves only the foreign lines",
              written["lines"] == foreign, written.get("lines"))
        con.close()

        print("\n[17] The posting text travels all the way to the prompt")
        con = state.connect(db)
        quill = next(c for c in state.contacts(con, include_unsubscribed=True)
                     if c["email"] == "rishi@quill.example")
        check("the bridge stored the posting", POSTING[:40] in quill["description"],
              quill["description"][:80])
        check("a contact without one is simply empty",
              next(c for c in state.contacts(con, include_unsubscribed=True)
                   if c["email"] == "jobs@acme-ai.com")["description"] == "")
        con.close()

        first = drafter.posting_for(quill)
        follow = drafter.posting_for(quill, previous=[{"subject": "s", "body": "b"}], stage=1)
        check("the first email prompt carries it",
              "AS PUBLISHED" in first and "Postgres query planning" in first)
        check("the follow-up prompt carries it too",
              "AS PUBLISHED" in follow and "Postgres query planning" in follow)
        check("and the follow-up is told to find a NEW angle in it",
              "none of the earlier" in follow, follow[-500:])
        check("no posting means no empty block",
              drafter.posting_text({"description": ""}) == "")
        long_one = drafter.posting_text({"description": "word " * 2000})
        check("a very long posting is trimmed, with the cut marked",
              len(long_one) < 4000 and "…" in long_one
              and long_one.rstrip().endswith("END POSTING ---"), len(long_one))

        f_without = drafter.fingerprint_for({**quill, "description": ""}, "c", "en")
        f_with = drafter.fingerprint_for(quill, "c", "en")
        check("the fingerprint covers the posting, so drafts redo when it arrives",
              f_without != f_with, (f_without, f_with))

        print("\n[18] Routes the UI can be refreshed on")
        index = (ROOT / "ui" / "dist" / "index.html")
        if index.exists():
            html = index.read_text(encoding="utf-8")
            check("assets are absolute, not relative to the route",
                  'src="/assets/' in html and 'src="./assets/' not in html, html[:200])
        nav = (ROOT / "ui" / "src" / "nav.ts").read_text(encoding="utf-8")
        for path in ("/preflight", "/contacts", "/follow-ups", "/schedule", "/activity"):
            check("nav declares %s" % path, '"%s"' % path in nav)

        print("\n[19] The send button cannot fire past a blocker")
        con = state.connect(db)
        counts = state.stages(con)
        target = next(c["email"] for c in state.contacts(con)
                      if counts.get(c["email"], 0) == 0)
        state.save_draft(con, target, "unsafe-for-send", "About the role",
                         (ROOT / "gmail-sender" / "fallback_template.txt").read_text(encoding="utf-8"),
                         "fallback", stage=0)
        state.export_csv(con, out / "recipients.csv")
        con.close()
        config(out, db, campaign="send-gate")
        os.chdir(out)
        try:
            sys.modules.pop("gate", None)
            gate = load("gate", out / "send_emails.py")
            blocked_report = gate.preflight(max_previews=0, db_path=str(db))
        finally:
            os.chdir(cwd)
        check("an unfinished draft blocks the preflight", blocked_report["ok"] is False,
              [c["title"] for c in blocked_report["checks"]])
        check("which is exactly what /api/send refuses on",
              any(c["level"] == "block" for c in blocked_report["checks"]))

        # And with it removed, the preflight opens the gate again.
        con = state.connect(db)
        # Every deliberately-unfinished draft this run planted, not just mine.
        con.execute("DELETE FROM drafts WHERE body LIKE '%>>>%'")
        con.commit()
        state.export_csv(con, out / "recipients.csv")
        con.close()
        os.chdir(out)
        try:
            sys.modules.pop("gate2", None)
            gate2 = load("gate2", out / "send_emails.py")
            clear_report = gate2.preflight(max_previews=0, db_path=str(db))
        finally:
            os.chdir(cwd)
        check("with it gone, the gate opens", clear_report["ok"] is True,
              [c["title"] for c in clear_report["checks"] if c["level"] == "block"])
        check("and the batch says how many would actually go",
              clear_report["batch"]["would_send_now"] > 0, clear_report["batch"])
        check("the batch reports how many of those are follow-ups",
              "follow_ups_due" in clear_report["batch"], clear_report["batch"])

        print("\n[20] Picking who gets an email, one by one")
        con = state.connect(db)
        everyone = [c["email"] for c in state.contacts(con)]
        con.close()
        os.chdir(out)
        try:
            sys.modules.pop("pick", None)
            pick = load("pick", out / "send_emails.py")
            cfg = pick.load_config()
            only_file = tmp / "only.txt"
            only_file.write_text(everyone[0] + "\n", encoding="utf-8")

            check("the list is read as addresses",
                  pick.read_only_list(str(only_file)) == {everyone[0]},
                  pick.read_only_list(str(only_file)))
            check("no list at all means no restriction",
                  pick.read_only_list("") is None)
            blank = tmp / "blank.txt"
            blank.write_text("\n  \n", encoding="utf-8")
            check("an empty list means nobody, not everybody",
                  pick.read_only_list(str(blank)) == set())

            con = state.connect(db)
            recipients, _ = pick.read_recipients(cfg["csv_file"])
            full, _due, _stale, _missing = pick.build_queue(cfg, con, recipients)
            one, _d2, _s2, _m2 = pick.build_queue(cfg, con, recipients, {everyone[0]})
            none_, _d3, _s3, _m3 = pick.build_queue(cfg, con, recipients, set())
            con.close()
            check("without a restriction everyone due is queued", len(full) > 1, len(full))
            check("with one address, only that one is queued",
                  [e for e, _d, _s in one] == [everyone[0]], [e for e, _d, _s in one])
            check("with an empty restriction, nobody is", none_ == [], none_)

            report = pick.preflight(max_previews=0, db_path=str(db))
        finally:
            os.chdir(cwd)

        scopes = {c["title"]: c.get("scope") for c in report["checks"]}
        check("every check declares what it would stop",
              all(v in ("global", "rows") for v in scopes.values()), scopes)
        check("credentials are a global blocker",
              any("credentials" in t and scopes[t] == "global" for t in scopes), scopes)
        check("the report names which addresses are unsafe",
              isinstance(report.get("unsafe_emails"), list), report.get("unsafe_emails"))

        print("\n[21] Reading the inbox to find out who replied")
        mailbox = load("mailbox", ROOT / "inbox.py")

        def message(frm, subject, body="", in_reply_to=None):
            raw = ["From: %s" % frm, "To: me@gmail.com", "Subject: %s" % subject,
                   "Date: Fri, 11 Sep 2026 10:00:00 -0500"]
            if in_reply_to:
                raw.append("In-Reply-To: %s" % in_reply_to)
            raw += ["", body]
            return "\r\n".join(raw).encode("utf-8")

        class FakeIMAP:
            """Just enough IMAP to prove the matching, without a mailbox."""
            def __init__(self, messages):
                self.messages = messages
                self.readonly = None
            def select(self, _box, readonly=False):
                self.readonly = readonly
                return "OK", None
            def search(self, _charset, *_criteria):
                return "OK", [b" ".join(str(i).encode() for i in range(len(self.messages)))]
            def fetch(self, ids, _spec):
                wanted = [int(x) for x in ids.split(b",")]
                return "OK", [(b"", self.messages[i]) for i in wanted]
            def logout(self):
                pass

        con = state.connect(db)
        con.execute("DELETE FROM sends")
        con.execute("DELETE FROM unsubscribed")
        con.execute("UPDATE contacts SET status='drafted', note=''")
        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage,message_id) "
                    "VALUES (?,?,'sent','r',0,?)",
                    (datetime.now().strftime(state.TIME_FORMAT), a, "<abc123@gmail.com>"))
        con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage,message_id) "
                    "VALUES (?,?,'sent','r',0,'')",
                    (datetime.now().strftime(state.TIME_FORMAT), b))
        con.commit()

        check("the Message-ID of a send is stored and looked up",
              state.message_ids(con) == {"<abc123@gmail.com>": a}, state.message_ids(con))
        check("and both addresses count as contacted",
              state.contacted(con) == {a, b}, state.contacted(con))

        # Unrelated mail must not be mistaken for a reply.
        noise = FakeIMAP([message("newsletter@somewhere.test", "Weekly digest"),
                          message("me@gmail.com", "A note to myself")])
        result = mailbox.scan(con, client=noise, dry_run=True)
        check("ordinary mail is not a reply",
              result["replies"] == {} and result["bounces"] == {}, result)

        threaded = FakeIMAP([message("Someone <%s>" % a, "Re: the role",
                                     in_reply_to="<abc123@gmail.com>")])
        result = mailbox.scan(con, client=threaded, dry_run=True)
        check("a quoted Message-ID is an exact match",
              list(result["replies"]) == [a], result["replies"])

        plain = FakeIMAP([message("Someone Else <%s>" % b, "Re: your email")])
        result = mailbox.scan(con, client=plain, dry_run=True)
        check("a reply from a contacted address counts even with no thread headers",
              list(result["replies"]) == [b], result["replies"])

        bounced = FakeIMAP([message("Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                                    "Delivery Status Notification (Failure)",
                                    "Your message to %s could not be delivered." % b)])
        result = mailbox.scan(con, client=bounced, dry_run=True)
        check("a daemon message naming one of ours is a bounce",
              list(result["bounces"]) == [b] and result["replies"] == {}, result)

        daemon_noise = FakeIMAP([message("mailer-daemon@googlemail.com", "Failure",
                                         "Your message to stranger@nowhere.test failed.")])
        result = mailbox.scan(con, client=daemon_noise, dry_run=True)
        check("a bounce for somebody else is ignored",
              result["bounces"] == {}, result)

        check("a dry run marks nothing",
              state.summary(con)["replied"] == 0, state.summary(con))

        # For real this time.
        mailbox.scan(con, client=FakeIMAP([
            message("Someone <%s>" % a, "Re: the role", in_reply_to="<abc123@gmail.com>")]))
        fresh_a = next(c for c in state.contacts(con, include_unsubscribed=True)
                       if c["email"] == a)
        check("marking it sets the status", fresh_a["status"] == "replied", fresh_a["status"])
        check("and records what the reply was", "Re: the role" in fresh_a["note"], fresh_a["note"])
        check("and unsubscribes them, which is what stops the follow-ups",
              a in state.unsubscribed(con, out / "unsubscribed.txt"))
        due, fresh = state.sequence_queue(con, 0, 2, out / "unsubscribed.txt")
        check("so they are in neither lane any more",
              a not in [c["email"] for c, _ in due] + [c["email"] for c, _ in fresh])

        check("the mailbox was opened read-only", threaded.readonly is True)

        print("\n[22] The scan only watches people who have not answered")
        watched = mailbox.scan(con, client=FakeIMAP([]), dry_run=True)
        check("someone already marked replied is no longer watched",
              watched["watching"] == 1, watched["watching"])
        # A second message from them must not be re-marked or re-counted.
        again = mailbox.scan(con, client=FakeIMAP([
            message("Someone <%s>" % a, "Re: the role again",
                    in_reply_to="<abc123@gmail.com>")]), dry_run=True)
        check("and a further email from them is ignored",
              again["replies"] == {} and again["bounces"] == {}, again)
        check("while the one still pending stays on the list",
              b in state.contacted(con) and b not in
              state.unsubscribed(con, out / "unsubscribed.txt"))
        con.close()

        print("\n[23] The UI is told the things that were terminal-only")
        con = state.connect(db)
        con.execute("DELETE FROM sends")
        con.execute("DELETE FROM unsubscribed")
        con.execute("UPDATE contacts SET status='drafted'")
        now_s = datetime.now().strftime(state.TIME_FORMAT)
        for who in (a, b):
            con.execute("INSERT INTO sends(sent_at,email,status,campaign,stage) "
                        "VALUES (?,?,'sent','r',0)", (now_s, who))
        con.commit()
        awaiting = state.contacted(con) - state.unsubscribed(con, out / "unsubscribed.txt")
        check("awaiting a reply counts everyone written to", len(awaiting) == 2, awaiting)
        state.set_status(con, a, "replied")
        awaiting = state.contacted(con) - state.unsubscribed(con, out / "unsubscribed.txt")
        check("and drops them the moment they answer", awaiting == {b}, awaiting)

        rid = state.start_run(con, "inbox", "cron")
        state.finish_run(con, rid, "ok", detail="28 read, 1 replied, 0 bounced")
        last = next(r for r in state.recent_runs(con, 10) if r["kind"] == "inbox")
        check("the last inbox check is retrievable for the UI",
              last["detail"] == "28 read, 1 replied, 0 bounced", last["detail"])
        check("the activity timeline carries runs as well as sends",
              len(state.recent_runs(con, 40)) > 0 and len(state.recent_sends(con)) > 0)
        con.close()

        # The reason nothing is going out has to be the true one. Here there IS a
        # queue — it is the cap that stops it, and that is what it must say.
        con = state.connect(db)
        con.execute("DELETE FROM sends")
        con.execute("DELETE FROM unsubscribed")
        con.execute("UPDATE contacts SET status='drafted'")
        con.commit()
        state.export_csv(con, out / "recipients.csv")
        con.close()
        config(out, db, campaign="reason", max_per_day="0")
        os.chdir(out)
        try:
            sys.modules.pop("why", None)
            why_mod = load("why", out / "send_emails.py")
            capped = why_mod.preflight(max_previews=0, db_path=str(db))
        finally:
            os.chdir(cwd)
        nothing = [c for c in capped["checks"] if c["title"] == "Nothing would go out right now"]
        check("a used-up cap is named as the reason, not 'everyone is done'",
              bool(nothing) and "cap" in nothing[0]["detail"],
              nothing[0]["detail"] if nothing else "no such check")

        print("\n[24] The rules that stop a batch from reading as generated")
        quill = {"company": "Quill", "role": "Fullstack SWE", "url": "https://q"}
        good_body = "Hi,\n\n" + ("I built the eval loop behind it. " * 12) + "\n\nJuan Anez"

        check("a subject naming the role passes",
              drafter.subject_is_clear("Fullstack SWE at Quill", quill))
        check("naming only the company passes",
              drafter.subject_is_clear("Application: engineering at Quill", quill))
        check("a subject describing the sender is refused",
              not drafter.subject_is_clear(
                  "Multi-tenant agent platform, AWS serverless, live customers", quill))
        check("and validate() says so",
              "has to contain" in drafter.validate(
                  "Multi-tenant agent platform, AWS serverless", good_body, quill))
        check("with nothing to anchor to, any subject is allowed",
              drafter.subject_is_clear("About your posting", {"company": "", "role": ""}))

        long_body = "Hi,\n\n" + ("word " * 200) + "\n\nJuan Anez"
        check("an email over 150 words is refused",
              "over the 150" in drafter.validate("Fullstack SWE at Quill", long_body, quill),
              drafter.validate("Fullstack SWE at Quill", long_body, quill))
        short_body = "Hi,\n\n" + ("a short follow-up sentence. " * 9) + "\n\nJuan Anez"
        check("and one under 65 words is too",
              "only" in drafter.validate("Fullstack SWE at Quill", short_body, quill))
        check("a follow-up is allowed to be short",
              drafter.validate("Fullstack SWE at Quill", short_body, quill, min_body=180) == "")

        line = "I am remote from Bogota with full overlap with your hours"
        body_with = "Hi,\n\n" + ("I built the eval loop behind it. " * 11) + line + ".\n\nJuan Anez"
        check("the first email may use any sentence it likes",
              drafter.validate("Fullstack SWE at Quill", body_with, quill) == "",
              drafter.validate("Fullstack SWE at Quill", body_with, quill))
        check("but a second email repeating it word for word is refused",
              "repeats a sentence" in drafter.validate(
                  "Fullstack SWE at Quill", body_with, quill,
                  used={line.lower()}),
              drafter.validate("Fullstack SWE at Quill", body_with, quill,
                               used={line.lower()}))
        check("saying the same thing differently is fine",
              drafter.validate("Fullstack SWE at Quill", body_with, quill,
                               used={"i work from colombia and overlap your afternoons"}) == "")
        check("short sentences are not worth deduplicating",
              drafter.sentences_of("Hi. Thanks. I built the whole eval loop behind it.")
              == ["i built the whole eval loop behind it"],
              drafter.sentences_of("Hi. Thanks. I built the whole eval loop behind it."))

        opener = "The turn-latency line is what made me write about this"
        echoed = ("Hi,\n\n" + opener + ". "
                  + ("I built the eval loop behind it. " * 11) + "\n\nJuan Anez")
        check("an email opening like an earlier one is refused",
              "opens the same way" in drafter.validate(
                  "Fullstack SWE at Quill", echoed, quill, openers=[opener]),
              drafter.validate("Fullstack SWE at Quill", echoed, quill, openers=[opener]))
        check("a different opening is fine",
              drafter.validate("Fullstack SWE at Quill", echoed, quill,
                               openers=["Something else entirely happened here today"]) == "")

        print("\n[24b] The closer, and the punctuation that gives a machine away")
        closing = "Worth a conversation"
        with_closer = ("Hi,\n\n" + ("I built the eval loop behind it. " * 11)
                       + "\n\n" + closing + "?\n\nJuan Anez")
        check("the closing question is found however short it is",
              drafter.closer_of(with_closer) == "worth a conversation",
              drafter.closer_of(with_closer))
        check("the signature is not mistaken for the closer",
              drafter.closer_of("Hi,\n\nI built the eval loop behind it.\n\nJuan Anez")
              == "i built the eval loop behind it")
        check("a short closer still dedupes, though sentences_of ignores it",
              drafter.sentences_of(with_closer) and
              "worth a conversation" not in drafter.sentences_of(with_closer))
        check("a second email ending the same way is refused",
              "ends the same way" in drafter.validate(
                  "Fullstack SWE at Quill", with_closer, quill,
                  used={"worth a conversation"}),
              drafter.validate("Fullstack SWE at Quill", with_closer, quill,
                               used={"worth a conversation"}))
        check("ending differently is fine",
              drafter.validate("Fullstack SWE at Quill", with_closer, quill,
                               used={"happy to send over the write-up"}) == "")

        check("a dash between two standing clauses becomes a full stop",
              drafter.tidy_body("I carry the pager myself \u2014 that teaches you what matters.")
              == "I carry the pager myself. That teaches you what matters.",
              drafter.tidy_body("I carry the pager myself \u2014 that teaches you what matters."))
        check("a dash after a list becomes a colon",
              drafter.tidy_body("Lambda, DynamoDB, SQS \u2014 the stack that survives.")
              == "Lambda, DynamoDB, SQS: the stack that survives.",
              drafter.tidy_body("Lambda, DynamoDB, SQS \u2014 the stack that survives."))
        check("a pair of dashes becomes a pair of commas",
              drafter.tidy_body("The slow half \u2014 auth, audit trails \u2014 is what sticks.")
              == "The slow half, auth, audit trails, is what sticks.",
              drafter.tidy_body("The slow half \u2014 auth, audit trails \u2014 is what sticks."))
        check("a short head keeps a comma",
              drafter.tidy_body("Founding Engineer \u2013 remote.") == "Founding Engineer, remote.")
        check("paragraphs survive the rewrite",
              drafter.tidy_body("Hi,\n\nYour post \u2014 the Rust one \u2014 was clear.\n\nJuan")
              == "Hi,\n\nYour post, the Rust one, was clear.\n\nJuan",
              drafter.tidy_body("Hi,\n\nYour post \u2014 the Rust one \u2014 was clear.\n\nJuan"))
        check("so a draft is never rejected for punctuation it can be cured of",
              drafter.validate("Fullstack SWE at Quill",
                               drafter.tidy_body("Hi,\n\n" + ("I built the eval loop \u2014 the slow "
                                                 "half \u2014 behind it. " * 9) + "\n\nJuan Anez"),
                               quill) == "")

        dashed = "Hi,\n\n" + ("I built the eval loop, the slow half, behind it. " * 9) + "\n\nJuan Anez"
        check("commas are fine", drafter.validate("Fullstack SWE at Quill", dashed, quill) == "",
              drafter.validate("Fullstack SWE at Quill", dashed, quill))
        for dash, label in (("\u2014", "em dash"), ("\u2013", "en dash")):
            broken = dashed.replace("loop, the slow half,", "loop %s the slow half %s" % (dash, dash), 1)
            check("the %s is refused in the body" % label,
                  "long dash" in drafter.validate("Fullstack SWE at Quill", broken, quill),
                  drafter.validate("Fullstack SWE at Quill", broken, quill))
        check("the subject may still use one",
              drafter.validate("Fullstack SWE \u2014 Quill", dashed, quill) == "",
              drafter.validate("Fullstack SWE \u2014 Quill", dashed, quill))
        check("the corpus does not model the punctuation it forbids",
              "\u2014" not in (ROOT / "profile.md").read_text()
              and "\u2013" not in (ROOT / "profile.md").read_text())
        heads = [l for l in (ROOT / "profile.md").read_text().splitlines()
                 if l.startswith("## ")]
        check("and it carries no section twice", len(heads) == len(set(heads)),
              [h for h in heads if heads.count(h) > 1])

        check("the retry is told what was rejected",
              "PREVIOUS ATTEMPT WAS REJECTED" in drafter.posting_for(
                  quill, rejected="body is 198 words, over the 150 it is allowed"))
        check("and a first attempt is not",
              "REJECTED" not in drafter.posting_for(quill))
        check("used openers reach the prompt",
              "do not echo any of them" in drafter.posting_for(quill, openers=[opener]))

        con = state.connect(db)
        state.save_draft(con, a, "opener-check", "Role at Co",
                         "Hi,\n\nA quite distinctive opening sentence here.\n\nJuan", "ai")
        got = state.recent_openers(con, 5)
        con.close()
        check("openers are read back from what was already written",
              any("quite distinctive opening" in o for o in got), got)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%s" % ("ALL INTEGRATION TESTS PASSED"
                    if not failures else "FAILED: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
