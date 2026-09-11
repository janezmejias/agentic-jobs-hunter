#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare.py — the bridge between ai-job-hunter and the sender.

Reads jobs.csv (what ai_job_hunter.py produces), filters by how applicable the
posting is, merges repeated recruiters, cleans the fields into something you can
actually write around, and loads it all into state.db.

  python3 prepare.py                  # default scope: yes,ask
  python3 prepare.py --scope yes      # only explicitly applicable postings
  python3 prepare.py --show           # print what would load, write nothing

It modifies neither program: it only translates between their formats.
Standard library only.

FIELDS IT PREPARES FOR THE TEMPLATE
    {{greeting}}   "Hi Albert" or "Hi"  (never leaves "Hi ,")
    {{reference}}  "the Fullstack SWE role at Quill"
    {{role}}       "Fullstack SWE"      (may be empty)
    {{company}}    "Quill"              (may be empty)
    {{url}}        link to the original posting
"""

import argparse
import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import state                                                     # noqa: E402

SOURCE_CSV = Path.home() / "ai-job-hunter" / "jobs.csv"
RECIPIENTS_CSV = ROOT / "gmail-sender" / "recipients.csv"

# How Hacker News separates the fields of a headline:
# "Company | Role | Full-time | REMOTE"
SEPARATOR = re.compile(r"\s*(?:\||—|–|\s-\s|•)\s*")

# Chunks of a headline that are NOT the job title.
NOISE = re.compile(
    r"https?://|www\.|\$|\b(remote|full[\s-]?time|part[\s-]?time|contract|"
    r"contractor|onsite|on[\s-]?site|hybrid|intern|internship|visa|equity|usd|eur|"
    r"salary|timezone|utc|gmt|anywhere|worldwide|hiring|apply|new york|san francisco|"
    r"london|berlin|seattle|austin|boston|denver)\b", re.I)

# Words that give away that a chunk IS a job title.
ROLE_WORDS = re.compile(
    r"\b(engineer|engineering|developer|scientist|architect|designer|manager|lead|"
    r"founding|research|researcher|analyst|devops|sre|fullstack|full[\s-]?stack|"
    r"backend|back[\s-]?end|frontend|front[\s-]?end|infrastructure|platform|product)\w*",
    re.I)

VALID_EMAIL = re.compile(r'^[^@\s,;<>"]+@[^@\s,;<>"]+\.[^@\s,;<>".]{2,}$')
VALID_NAME = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]{2,20}$")

# Jobot and Hacker News are US-based, so emails go out in English by default.
PHRASES = {
    "en": {"greeting": "Hi",
           "role_and_company": "the %s role at %s",
           "role_only": "the %s role",
           "company_only": "the role you posted at %s",
           "hn": "your Hacker News post",
           "generic": "your opening"},
    "es": {"greeting": "Hola",
           "role_and_company": "el puesto de %s en %s",
           "role_only": "el puesto de %s",
           "company_only": "la vacante que publicaron en %s",
           "hn": "su publicacion en Hacker News",
           "generic": "su vacante"},
}


def tidy(text):
    return " ".join(str(text or "").split()).strip()


def read_csv(path):
    """Reads the hunter's CSV, accepting a BOM and , ; or tab as separator."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    first = text.split("\n", 1)[0]
    sep = max((",", ";", "\t"), key=first.count)
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter=sep))


def first_name(contact):
    """
    Only uses the name when it is a real one (two words, as Jobot gives:
    "Albert Simons" -> "Albert"). A Hacker News handle ("scottcha", "R_R") is not
    a first name: there we'd rather greet without one than sound like a robot.
    """
    parts = tidy(contact).split()
    if len(parts) < 2:
        return ""
    head = parts[0]
    if not VALID_NAME.match(head):
        return ""
    return head if head[:1].isupper() else head.capitalize()


def clean_company(company, source):
    name = tidy(company)
    if source == "jobot" or name.lower().startswith("jobot"):
        return ""          # "Jobot (confidential client)" is not a company
    name = re.sub(r"https?://\S+|www\.\S+", "", name).strip(" -–—|·,")
    if len(name) < 2 or len(name) > 45 or NOISE.match(name):
        return ""
    return name


def extract_role(headline, source):
    """
    Jobot already gives a clean title. On HN the role has to be pulled out of the
    headline: "Quill | Fullstack SWE | Full-time | Remote | $150-210K".
    """
    title = tidy(headline)
    if not title:
        return ""
    if source == "jobot":
        return title[:70]

    parts = [p for p in SEPARATOR.split(title) if p.strip()]
    candidates = parts[1:] or parts          # parts[0] is usually the company
    # First, the chunk that clearly names a role and carries no noise.
    for part in candidates:
        if ROLE_WORDS.search(part) and not NOISE.search(part) and 3 <= len(part) <= 60:
            return part.strip(" -–—|·,")[:70]
    # Otherwise, any short clean chunk.
    for part in candidates:
        if not NOISE.search(part) and 3 <= len(part) <= 45 and len(part.split()) <= 6:
            return part.strip(" -–—|·,")[:70]
    # Last resort: a role word anywhere in the headline.
    hit = ROLE_WORDS.search(title)
    return hit.group(0)[:70] if hit else ""


def build_reference(role, company, source, language="en"):
    """A natural phrase for the email body. Never comes out half-finished."""
    p = PHRASES[language]
    if role and company:
        return p["role_and_company"] % (role, company)
    if role:
        return p["role_only"] % role
    if company:
        return p["company_only"] % company
    return p["hn"] if source == "hn" else p["generic"]


def transform(rows, scopes, own_email="", language="en"):
    out, seen, dropped = [], set(), {"scope": 0, "email": 0, "duplicate": 0}
    for row in rows:
        # The hunter already sorted by (applicability, ai_score), so keeping the
        # FIRST occurrence of each address keeps that recruiter's best posting.
        if tidy(row.get("apply_from_co")) not in scopes:
            dropped["scope"] += 1
            continue
        email = tidy(row.get("email")).lower()
        if not VALID_EMAIL.match(email) or email == own_email.lower():
            dropped["email"] += 1
            continue
        if email in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(email)

        source = tidy(row.get("source")).lower()
        name = first_name(row.get("contact"))
        company = clean_company(row.get("company"), source)
        role = extract_role(row.get("role"), source)
        out.append({
            "email": email,
            "greeting": ("%s %s" % (PHRASES[language]["greeting"], name)) if name
                        else PHRASES[language]["greeting"],
            "name": name,
            "company": company,
            "role": role,
            "reference": build_reference(role, company, source, language),
            "scope": tidy(row.get("scope")),
            "url": tidy(row.get("url")),
            "source": source,
            "ai_score": tidy(row.get("ai_score")),
            "original_headline": tidy(row.get("role"))[:200],
            # The posting itself. Not used in the CSV the sender reads — it is
            # what lets the drafter write about this job rather than its title.
            "description": (row.get("description") or "").strip()[:4000],
        })
    return out, dropped


def main():
    parser = argparse.ArgumentParser(
        description="Turn the hunter's jobs.csv into contacts in state.db.")
    parser.add_argument("--source", default=str(SOURCE_CSV), help="the hunter's jobs.csv")
    parser.add_argument("--out", default=str(RECIPIENTS_CSV), help="recipients.csv for the sender")
    parser.add_argument("--db", default=str(state.DB_PATH), help="state database")
    parser.add_argument("--scope", default="yes,ask",
                        help="which apply_from_co values to accept (yes,ask,no)")
    parser.add_argument("--own-email", default="", help="your own address, so you don't write to yourself")
    parser.add_argument("--language", default="en", choices=["en", "es"],
                        help="language of the greeting and reference (default en)")
    parser.add_argument("--show", action="store_true", help="print the result, write nothing")
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    if not source.exists():
        print("Can't find %s.\nRun this first:  python3 ai-job-hunter/ai_job_hunter.py"
              % source, file=sys.stderr)
        return 1

    scopes = {s.strip() for s in args.scope.split(",") if s.strip()}
    rows = read_csv(source)
    recipients, dropped = transform(rows, scopes, args.own_email, args.language)

    print("%d rows read from %s" % (len(rows), source))
    print("   dropped by scope:      %d" % dropped["scope"])
    print("   dropped by address:    %d" % dropped["email"])
    print("   duplicates merged:     %d" % dropped["duplicate"])
    print("-> %d recipients" % len(recipients))

    if args.show:
        for r in recipients[:10]:
            print("\n  %s\n    %s, ... %s\n    [%s]" %
                  (r["email"], r["greeting"], r["reference"], r["scope"]))
        if len(recipients) > 10:
            print("\n  ... and %d more" % (len(recipients) - 10))
        print("\n(--show: nothing was written)")
        return 0

    con = state.connect(args.db)
    added, refreshed = state.save_contacts(con, recipients)
    legacy = state.import_legacy_log(con, ROOT / "gmail-sender" / "registro_envios.csv")
    exported = state.export_csv(con, Path(args.out).expanduser())

    print("\nIn the database: %d new contacts, %d refreshed" % (added, refreshed))
    if legacy:
        print("   (imported %d sends from the old CSV log)" % legacy)
    print("Pipeline: %s"
          % ", ".join("%s=%d" % (k, v) for k, v in state.summary(con).items() if v))
    print("\n%d rows exported to %s" % (exported, args.out))
    print("Next:  python3 draft.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
