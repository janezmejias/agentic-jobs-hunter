#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
draft.py — writes each email with Claude Haiku 4.5.

It does not send a summary of you. It reads the posting, picks from profile.md
the CARD that answers what that team is asking for, and writes about that. You
adapt to the posting, not the other way round.

  python3 draft.py                 draft whatever is missing
  python3 draft.py --redo          draft everything again
  python3 draft.py --diagnose      measure the prefix and check caching
  python3 draft.py --show          print what is stored, without calling the API
  python3 draft.py --follow-up     write the SECOND email to people already contacted
  python3 draft.py --language es   English by default

CACHING
  The stable block (instructions + the whole of profile.md) is marked with
  cache_control, so from the second email on that prefix is billed at ~0.1x.
  Careful: Haiku 4.5 only caches prefixes of 4096 tokens or more, and below that
  it does NOT warn — it simply doesn't cache. That's why every run reports its
  cache tokens, and --diagnose measures the prefix before you spend anything.

Needs:  pip install anthropic   and   export ANTHROPIC_API_KEY=...
If either is missing, or a draft fails validation, that row falls back to
gmail-sender/fallback_template.txt.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402

PROFILE = ROOT / "profile.md"
RECIPIENTS_CSV = ROOT / "gmail-sender" / "recipients.csv"
FALLBACK = ROOT / "gmail-sender" / "fallback_template.txt"
REVIEW = ROOT / "gmail-sender" / "drafts.md"

MODEL = "claude-haiku-4-5"
CACHE_MINIMUM = 4096         # tokens; below this Haiku 4.5 silently skips caching
PRICE_INPUT = 1.00 / 1_000_000
PRICE_OUTPUT = 5.00 / 1_000_000
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10

FIELD = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
URL_RE = re.compile(r"https?://[^\s<>\")]+", re.I)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "card": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["card", "subject", "body"],
    "additionalProperties": False,
}

LANGUAGES = {"en": ("English", "About %s"), "es": ("Spanish", "Sobre %s")}

# Everything here is STABLE: together with profile.md it forms the cached prefix.
# Any change invalidates the cache, so never put dates or counters in it.
INSTRUCTIONS = """You write cold job-application emails on behalf of one real person,
in {language}. Below is that person's complete profile corpus.

YOUR JOB IS SELECTION, NOT SUMMARY.
The reader posted one specific opening. Your task is to find the part of this
person's background that answers THAT posting, and write about it. He adapts to
the posting; the posting does not adapt to him.

Work in this order:
1. Read the posting. What does this team actually need — a domain, a stack, or a
   problem shape (latency, cost, evals, scale, compliance, greenfield, legacy)?
2. Pick ONE card from the corpus that answers it. Two only if both clearly apply.
3. Write the email around that card's concrete result.
4. Report which card you used in the "card" field, by its CARD-... name.

ABSOLUTE RULES
- Every factual claim about HIM must come from the corpus. Never invent an
  employer, a client, a number, a technology, a title or a certification.
- Everything you say about THEM must come from the posting text you are given.
  Quote or paraphrase what it actually says; never extrapolate from the company
  name or fill in what a company like that "probably" needs.
- If the posting asks for something the corpus does not show, do not claim it and
  do not apologize for it. Just write about what is there.
- Never write a URL that is not in the corpus or in the posting.
- NEVER characterize the reader's company, industry, product, customers or
  stage. If the posting does not say they are fintech, healthcare, infra or
  anything else, you do not know it. Sentences that start "You're building...",
  "Since you're a...", "Your team is..." or "Given your focus on..." are
  forbidden even when they feel like rapport. Getting this wrong is worse than
  saying nothing: it tells the reader the email was generated.
- Never aggregate, round or re-date his experience. Use the spans exactly as the
  corpus states them, attached to the role they belong to. "Twelve years" is the
  only total that exists. Do not write "the last N years" for anything except
  what the corpus explicitly places in the present.
- Obey the corpus sections "Phrases that must never appear", "How to open" and
  "Shape of a good email". They are binding, not suggestions.
- No placeholders, no brackets, no unfilled template text, no markdown.

VARIETY
These emails go out as a batch. Two of them reading alike is the single thing
that makes a mail provider treat them as bulk. Rotate the opener patterns from
the corpus and vary sentence rhythm between emails.

THE SUBJECT
Goes in the "subject" field, never inside the body. Four to nine words, concrete
about the role, no emoji, no exclamation marks, no "Application for".

--- PROFILE CORPUS ---
{corpus}
--- END PROFILE CORPUS ---"""


def tidy(t):
    return " ".join(str(t or "").split()).strip()


def fill(template, row):
    return FIELD.sub(lambda m: str(row.get(tidy(m.group(1)).lower(), "")), template)


def fallback_for(row, template, language="en"):
    return (LANGUAGES[language][1] % (row.get("reference") or "your opening"),
            fill(template, row))


def stable_block(corpus, language):
    return INSTRUCTIONS.format(language=LANGUAGES[language][0], corpus=corpus)


def fingerprint_for(contact, corpus, language, stage=0):
    """Changes when the profile, the posting, the language or the stage changes."""
    raw = "|".join([contact.get("original_headline", ""), contact.get("reference", ""),
                    contact.get("description", ""),
                    contact.get("url", ""), language, MODEL, "stage%d" % int(stage),
                    hashlib.sha1(corpus.encode("utf-8")).hexdigest()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ validation

BANNED = (
    "as an ai", "as an assistant", "language model", "i hope this email finds you",
    "i hope you're doing well", "lorem ipsum", "your name here",
    "passionate about", "cutting-edge", "state-of-the-art", "great fit",
    "please find my resume", "thank you for your time and consideration",
    "[", "]", "{{", ">>>",
)


# The failure mode worth catching is the model ASSERTING what the reader's
# company does — "You're building in fintech." — when the posting never said so.
#
# It is not "If you're building X…", "what you're working on", or "your post
# didn't say what you're building". Those are conditionals and questions, and an
# unanchored pattern rejected three of them for every real catch. So: only match
# a declarative that STARTS a sentence.
SENTENCE_START = r"(?:^|(?<=[.!?])\s+|\n\s*)"
ABOUT_THE_READER = (
    re.compile(SENTENCE_START + r"you(?:'re|’re| are)\s+"
               r"(?:building|working|a\b|an\b|the\b|in\b|scaling|solving|tackling|"
               r"focused|clearly|obviously)[^.!?]{0,70}", re.I),
    re.compile(SENTENCE_START + r"your (?:team|company|product|stack|platform|business) "
               r"(?:is|are|has|does)\b[^.!?]{0,70}", re.I),
    re.compile(r"\bgiven your (?:focus|work|mission|scale)\b[^.!?]{0,70}", re.I),
    re.compile(r"\bsince you(?:'re|’re| are)\s+(?:building|a\b|an\b|the\b|in\b)"
               r"[^.!?]{0,70}", re.I),
)


# "the last N years" is the shape re-dating takes. The corpus states exactly one
# such span ("the last two years" on LLM agents); anything else is the model
# inventing a timeline. So the rule is simple and grounded: the phrase has to
# appear in the corpus verbatim, or it doesn't go out.
UNIT = r"(?:year|month|decade)s?"
TIMESPAN = re.compile(
    r"\b(?:the\s+|over\s+the\s+|for\s+the\s+|in\s+the\s+)?(?:last|past)\s+"
    # A bare "last month" is ordinary English, so a quantity is required —
    # either words before the unit ("two years") or the half form.
    r"((?:[A-Za-z0-9.\-]+\s+){1,3}?" + UNIT + r"(?:\s+and\s+a\s+half)?"
    r"|" + UNIT + r"\s+and\s+a\s+half)", re.I)


def unsupported_timespan(body, corpus):
    """Returns the offending phrase, or "" when every span is one the corpus states."""
    haystack = " ".join(corpus.lower().split())
    for match in TIMESPAN.finditer(body):
        span = " ".join(match.group(1).lower().split())
        whole = " ".join(match.group(0).lower().split())
        if span in haystack or whole in haystack:
            continue
        return match.group(0).strip()
    return ""


def validate(subject, body, contact, corpus="", min_body=350):
    subject, body = tidy(subject), (body or "").strip()
    if not 15 <= len(subject) <= 90:
        return "subject is %d characters" % len(subject)
    if not min_body <= len(body) <= 1600:
        return "body is %d characters" % len(body)
    lowered = (subject + "\n" + body).lower()
    for phrase in BANNED:
        if phrase in lowered:
            return "contains %r" % phrase
    # Cheap net for the failure mode a corpus check can't see: the model telling
    # the reader what their own company does. It reads like rapport and it is the
    # clearest tell that an email was generated.
    for pattern in ABOUT_THE_READER:
        hit = pattern.search(body)
        if hit:
            return "claims something about the reader's company: %r" % hit.group(0)[:60]
    stretched = unsupported_timespan(body, corpus) if corpus else ""
    if stretched:
        return "re-dates his experience: %r is not in the profile" % stretched
    allowed = {u.rstrip("/.,);") for u in
               URL_RE.findall(contact.get("url", "") + " " + corpus)}
    for url in URL_RE.findall(body):
        if url.rstrip("/.,);") not in allowed:
            return "invented the URL %s" % url
    return ""


def tidy_body(body):
    return re.sub(r"\n{3,}", "\n\n", (body or "").replace("\r\n", "\n").strip())


# --------------------------------------------------------------------- the key

def read_key_from_env_file(path, name="ANTHROPIC_API_KEY"):
    """
    Pulls ONE variable out of a .env file and returns it.

    Deliberately not `source`-ing the file: a shared .env can hold dozens of
    unrelated production secrets, and none of them have any business being in
    this process or in cron. We read the single line we need and ignore the rest.
    The value is never printed anywhere.
    """
    path = Path(path).expanduser()
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep or key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value.strip()
    return ""


def ensure_api_key(env_file):
    """
    Order: an already-exported ANTHROPIC_API_KEY wins, then the .env file.
    Returns a short description of where it came from, for the log.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "environment"
    for candidate in (env_file, os.environ.get("ANTHROPIC_ENV_FILE"), ROOT / ".env"):
        if not candidate:
            continue
        key = read_key_from_env_file(candidate)
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            return str(candidate)
    return ""


# ----------------------------------------------------------------------- model

def client_or_none():
    try:
        import anthropic
    except ImportError:
        print("! SDK missing. Install it with:  pip install anthropic", file=sys.stderr)
        return None, None
    try:
        return anthropic.Anthropic(), anthropic
    except Exception as ex:                                      # noqa: BLE001
        print("! Couldn't build the client (%s). Is ANTHROPIC_API_KEY set?" % ex,
              file=sys.stderr)
        return None, None


MAX_POSTING = 3500


def posting_text(contact):
    """The posting as it was published, trimmed. Empty when there wasn't one."""
    body = (contact.get("description") or "").strip()
    if not body:
        return ""
    if len(body) > MAX_POSTING:
        body = body[:MAX_POSTING].rsplit(" ", 1)[0] + " …"
    return "\n".join(["", "--- THE POSTING, AS PUBLISHED ---", body, "--- END POSTING ---"])


def posting_for(contact, previous=None, stage=0, max_stage=2):
    """
    `previous` is every email already sent to this person, oldest first. A
    follow-up gets all of them, not just the last: repeating the argument of the
    first email in the second follow-up is just as bad as repeating the last.
    """
    if previous:
        history = []
        for i, earlier in enumerate(previous, 1):
            history += ["--- EMAIL %d ALREADY SENT ---" % i,
                        "Subject: %s" % earlier.get("subject", ""),
                        earlier.get("body", ""), ""]
        return "\n".join([
            "THIS IS FOLLOW-UP %d, the last one you will write for this person."
            % stage if stage >= max_stage else
            "THIS IS FOLLOW-UP %d of at most %d." % (stage, max_stage),
            "It is not the first email again.",
            "Obey the corpus section 'Shape of a follow-up'. 40-80 words.",
            "",
            "They have not replied to any of the emails below. Do not repeat the",
            "argument or the sentences of any of them; add one thing that is in",
            "none of them.",
            "",
        ] + history + [
            "THE POSTING it was about",
            "Company: %s" % (contact.get("company") or "not stated"),
            "Role: %s" % (contact.get("role") or "not stated"),
            "Link: %s" % contact.get("url", ""),
            posting_text(contact),
            "",
            "The posting is above. Find something in it none of the earlier",
            "emails addressed — a requirement, a constraint, a piece of their",
            "stack — and make that the one new thing. Only what it actually says.",
            "Never mention how many times you have written, never apologise for",
            "writing again, and never imply they were rude not to reply.",
            "",
            "Start the body with this exact greeting, followed by a comma: %s"
            % (contact.get("greeting") or "Hi"),
        ])
    return "\n".join([
        "THE POSTING",
        "Company: %s" % (contact.get("company") or "not stated in the posting"),
        "Role: %s" % (contact.get("role") or "not stated in the posting"),
        "Remote scope: %s" % contact.get("scope", ""),
        "Link: %s" % contact.get("url", ""),
        "Original headline, exactly as posted: %s" % contact.get("original_headline", ""),
        posting_text(contact),
        "",
        "Start the body with this exact greeting, followed by a comma: %s"
        % (contact.get("greeting") or "Hi"),
    ])


def request_draft(client, stable, contact, previous=None, stage=0, max_stage=2):
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        # The stable block is marked: from the second call on it bills at ~0.1x.
        system=[{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user",
                   "content": posting_for(contact, previous, stage, max_stage)}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return data["subject"], data["body"], data.get("card", ""), response.usage


class Spend:
    """Accumulates tokens and turns them into dollars with the cache factors."""

    def __init__(self):
        self.input = self.output = self.cache_write = self.cache_read = 0

    def add(self, usage):
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def dollars(self):
        billed_input = (self.input
                        + self.cache_write * CACHE_WRITE_FACTOR
                        + self.cache_read * CACHE_READ_FACTOR)
        return billed_input * PRICE_INPUT + self.output * PRICE_OUTPUT

    @property
    def without_cache(self):
        """What it would have cost sending the full prefix every time."""
        return ((self.input + self.cache_write + self.cache_read) * PRICE_INPUT
                + self.output * PRICE_OUTPUT)


def with_retry(client, sdk, stable, contact, corpus, attempts=2, previous=None,
               stage=0, max_stage=2):
    spend, last = [], ""
    minimum = 180 if previous else 350       # a follow-up is deliberately short
    for _ in range(attempts):
        try:
            subject, body, card, usage = request_draft(
                client, stable, contact, previous, stage, max_stage)
            spend.append(usage)
            reason = validate(subject, body, contact, corpus, minimum)
            if not reason:
                return tidy(subject), tidy_body(body), card, spend, ""
            last = reason
        except (sdk.AuthenticationError, sdk.PermissionDeniedError) as ex:
            return "", "", "", spend, "AUTH: %s" % getattr(ex, "message", ex)
        except TypeError as ex:
            # The client doesn't validate credentials on construction, only on request.
            return "", "", "", spend, "AUTH: no credentials (%s)" % ex
        except sdk.RateLimitError as ex:
            wait = 20
            try:
                wait = int(ex.response.headers.get("retry-after", "20"))
            except Exception:                                    # noqa: BLE001
                pass
            print("   (rate limited; waiting %ds)" % wait)
            time.sleep(wait)
            last = "rate limited"
        except sdk.APIStatusError as ex:
            last = "API error %s: %s" % (ex.status_code, getattr(ex, "message", ex))
            if ex.status_code < 500:
                break
        except sdk.APIConnectionError:
            last = "no network"
            time.sleep(2)
        except (KeyError, ValueError, StopIteration) as ex:
            last = "unreadable response: %s" % ex
    return "", "", "", spend, last or "unknown"


# ----------------------------------------------------------------- diagnostics

def diagnose(stable):
    client, _ = client_or_none()
    if client is None:
        return 1
    print("Measuring the stable prefix with the token-counting API...")
    try:
        r = client.messages.count_tokens(
            model=MODEL,
            system=[{"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": "x"}],
        )
    except Exception as ex:                                      # noqa: BLE001
        print("! Couldn't count tokens: %s" % ex, file=sys.stderr)
        return 1
    n = r.input_tokens
    print("\nStable prefix: %d tokens" % n)
    print("%s minimum:  %d tokens" % (MODEL, CACHE_MINIMUM))
    if n >= CACHE_MINIMUM:
        saving = (n - n * CACHE_READ_FACTOR) * PRICE_INPUT
        print("\nOK: caching WILL kick in.")
        print("Saving per email, from the second one on: ~USD %.5f" % saving)
    else:
        print("\nPROBLEM: the prefix is %d tokens short." % (CACHE_MINIMUM - n))
        print("Haiku 4.5 does not cache short prefixes and raises NO error: it just")
        print("bills everything, every time. Add real material to profile.md (another")
        print("card, another example email) until you clear %d, then run this again."
              % CACHE_MINIMUM)
    return 0


# ----------------------------------------------------------------------- flow

def main():
    p = argparse.ArgumentParser(description="Write each email with Claude Haiku 4.5.")
    p.add_argument("--db", default=str(state.DB_PATH))
    p.add_argument("--profile", default=str(PROFILE))
    p.add_argument("--fallback", default=str(FALLBACK))
    p.add_argument("--csv", default=str(RECIPIENTS_CSV))
    p.add_argument("--review", default=str(REVIEW))
    p.add_argument("--language", default="en", choices=["en", "es"])
    p.add_argument("--redo", action="store_true", help="draft everything again")
    p.add_argument("--show", action="store_true", help="print what is stored, no API call")
    p.add_argument("--diagnose", action="store_true", help="measure the prefix and caching")
    p.add_argument("--limit", type=int, default=0, help="most emails to draft right now")
    p.add_argument("--env-file", default="", dest="env_file",
                   help="file to read ANTHROPIC_API_KEY from (only that variable is read)")
    p.add_argument("--follow-up", action="store_true", dest="follow_up",
                   help="write the next follow-up for everyone who is due one")
    p.add_argument("--wait-days", type=int, default=3, dest="wait_days",
                   help="days without a reply before a follow-up is due")
    p.add_argument("--max-follow-ups", type=int, default=2, dest="max_follow_ups",
                   help="how many follow-ups a person can ever get")
    p.add_argument("--stats-out", default="", dest="stats_out",
                   help="write a JSON summary of this run here (the pipeline reads it)")
    p.add_argument("--fix", action="store_true",
                   help="re-draft only what needs it: the fixed-template fallbacks, plus "
                        "any stored draft that no longer passes the current rules")
    args = p.parse_args()

    source = ensure_api_key(args.env_file)
    if source and source != "environment":
        print("ANTHROPIC_API_KEY loaded from %s (only that variable was read)" % source)
    elif not source:
        print("! No ANTHROPIC_API_KEY found, in the environment or in a .env file.",
              file=sys.stderr)

    profile_path = Path(args.profile).expanduser()
    corpus = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    stable = stable_block(corpus, args.language)

    if args.diagnose:
        return diagnose(stable)

    fallback_path = Path(args.fallback).expanduser()
    if not fallback_path.exists():
        print("Can't find the fallback template %s" % fallback_path, file=sys.stderr)
        return 1
    template = fallback_path.read_text(encoding="utf-8")

    con = state.connect(args.db)
    stage_of = {}
    if args.follow_up:
        # Exactly the queue the sender will use, so the drafts that get written
        # are the ones that are about to be needed — no more, no fewer.
        due, _ = state.sequence_queue(con, args.wait_days, args.max_follow_ups,
                                      ROOT / "gmail-sender" / "unsubscribed.txt")
        pending = [c for c, _stage in due]
        stage_of = {c["email"]: stage for c, stage in due}
        print("Follow-ups: %d people are due one (%d days without a reply, "
              "at most %d per person).\n" % (len(pending), args.wait_days,
                                             args.max_follow_ups))
    elif args.fix:
        # Only what is actually broken. Re-running everything would pay again for
        # the drafts that are already good — and the rules tighten over time, so
        # a draft written last week can stop passing today.
        pending, fallbacks, stale = [], 0, 0
        for c in state.contacts(con, states=("new", "drafted")):
            d = state.latest_draft(con, c["email"])
            if not d:
                continue
            if d["origin"] == "fallback":
                fallbacks += 1
                pending.append(c)
            elif validate(d["subject"], d["body"], c, corpus):
                stale += 1
                pending.append(c)
        print("Fixing %d drafts: %d fell back to the template, %d no longer pass the "
              "current rules.\n" % (len(pending), fallbacks, stale))
    else:
        pending = state.contacts(con, states=("new", "drafted"))

    if args.show:
        for c in pending:
            d = state.latest_draft(con, c["email"])
            print("\n" + "=" * 70 + "\n%s  [%s]" % (c["email"], d["origin"] if d else "no draft"))
            if d:
                print("Subject: %s\n\n%s" % (d["subject"], d["body"]))
        print("\n(--show: no API call, nothing written)")
        return 0

    unfilled = corpus.count(">>>")
    client = sdk = None
    if corpus.strip() and unfilled == 0:
        client, sdk = client_or_none()
    elif not corpus.strip():
        print("! profile.md is empty: not calling the model.", file=sys.stderr)
    else:
        print("! profile.md still has %d lines with '>>>' unfilled: not calling the "
              "model, because it would write an email with nothing concrete to say."
              % unfilled, file=sys.stderr)

    spend = Spend()
    written = reused = fell_back = 0
    failures, cards = [], {}

    for i, c in enumerate(pending, 1):
        if args.limit and written >= args.limit:
            break
        stage = stage_of.get(c["email"], 0) if args.follow_up else 0
        fp = fingerprint_for(c, corpus, args.language, stage)
        if state.draft(con, c["email"], fp) and not (args.redo or args.fix):
            reused += 1
            continue
        # In follow-up mode every earlier email is an input to the prompt.
        previous = None
        if args.follow_up:
            earlier = [state.draft_for_stage(con, c["email"], n) for n in range(stage)]
            previous = [d for d in earlier if d]
            if not previous:
                continue                 # nothing was ever sent; nothing to follow up
        if client is None:
            subject, body = fallback_for(c, template, args.language)
            state.save_draft(con, c["email"], fp, subject, body, "fallback",
                             reason="no model available", stage=stage)
            fell_back += 1
            continue

        subject, body, card, usages, reason = with_retry(
            client, sdk, stable, c, corpus, previous=previous,
            stage=stage, max_stage=args.max_follow_ups)
        for u in usages:
            spend.add(u)
        if reason.startswith("AUTH"):
            # No point retrying the same thing 150 times: switch the model off.
            print("! %s\n  Falling back to the fixed template for everyone." % reason,
                  file=sys.stderr)
            client = None
            subject, body = fallback_for(c, template, args.language)
            state.save_draft(con, c["email"], fp, subject, body, "fallback",
                             reason=reason, stage=stage)
            fell_back += 1
            continue
        if reason:
            failures.append((c["email"], reason))
            subject, body = fallback_for(c, template, args.language)
            origin = "fallback"
            fell_back += 1
        else:
            origin = ("ai-follow-up-%d" % stage) if args.follow_up else "ai"
            written += 1
            cards[card] = cards.get(card, 0) + 1
        state.save_draft(con, c["email"], fp, subject, body, origin, MODEL, reason, stage)
        if not args.follow_up:
            state.set_status(con, c["email"], "drafted")
        print("  [%d/%d] %-32s stage %d · %s · %s"
              % (i, len(pending), c["email"], stage, origin,
                 card if not reason else reason))

    exported = state.export_csv(con, args.csv)
    write_review(con, Path(args.review))

    print("\n%d written with %s, %d reused, %d on the fixed template"
          % (written, MODEL, reused, fell_back))
    if cards:
        print("Cards chosen: %s"
              % ", ".join("%s x%d" % (c or "?", n)
                          for c, n in sorted(cards.items(), key=lambda x: -x[1])))
    if spend.input or spend.cache_write or spend.cache_read:
        print("\nTokens: %d fresh, %d written to cache, %d read from cache, %d output"
              % (spend.input, spend.cache_write, spend.cache_read, spend.output))
        print("Cost: USD %.4f   (without caching it would have been USD %.4f)"
              % (spend.dollars, spend.without_cache))
        if spend.cache_write == 0 and spend.cache_read == 0 and written > 1:
            print("\n!! Caching did NOT kick in. The stable prefix falls short of the %d"
                  "\n   tokens %s requires, and below that it neither caches nor warns."
                  "\n   Run:  python3 draft.py --diagnose" % (CACHE_MINIMUM, MODEL))
    if failures:
        print("\nFell back to the template:")
        tally = {}
        for email, why in failures:
            tally[why] = tally.get(why, 0) + 1
        for email, why in failures[:12]:
            print("   %-38s %s" % (email, why))
        if len(tally) > 1:
            print("\n   by reason: %s" % ", ".join(
                "%s x%d" % (w, n) for w, n in sorted(tally.items(), key=lambda x: -x[1])))
    if args.stats_out:
        Path(args.stats_out).write_text(json.dumps({
            "written": written, "reused": reused, "fell_back": fell_back,
            "input_tokens": spend.input, "output_tokens": spend.output,
            "cache_write_tokens": spend.cache_write, "cache_read_tokens": spend.cache_read,
            "cost_usd": round(spend.dollars, 6),
            "cost_without_cache_usd": round(spend.without_cache, 6),
            "cards": cards,
            "failures": [{"email": e, "reason": r} for e, r in failures],
        }, indent=1), encoding="utf-8")

    print("\n%d rows in %s" % (exported, args.csv))
    print("Review the drafts:  %s" % args.review)
    return 0


def write_review(con, path):
    rows = state.contacts(con, states=("new", "drafted", "sent"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Drafts — %s\n\n" % datetime.now().strftime("%Y-%m-%d %H:%M"))
        f.write("Read these before sending. The model is forbidden from inventing, but\n"
                "a plausible invention is something only you can catch.\n")
        for c in rows:
            d = state.latest_draft(con, c["email"])
            if not d:
                continue
            f.write("\n---\n\n## %s · %s · %s\n\n**Subject:** %s\n\n```\n%s\n```\n"
                    % (c["email"], c.get("company") or "?", d["origin"],
                       d["subject"], d["body"]))


if __name__ == "__main__":
    sys.exit(main())
