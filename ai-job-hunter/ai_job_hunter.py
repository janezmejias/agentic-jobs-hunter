#!/usr/bin/env python3
"""
ai_job_hunter.py — finds AI Engineer postings and returns only what you can act
on: whether it's remote, and which address to write to.

Sources (the only ones verified to expose a real email):
  1. Jobot — internal search API. Gives the recruiter's email.
  2. HN    — "Ask HN: Who is hiring?" threads via the public Algolia API.
             Gives the email of whoever is hiring.

No dependencies: Python 3.8+ standard library only.

Usage:
    python3 ai_job_hunter.py                  # normal run
    python3 ai_job_hunter.py --selftest       # validate the parser against real data
    python3 ai_job_hunter.py --scope yes      # only what's applicable from Colombia
    python3 ai_job_hunter.py --min-score 5    # demand more AI signals
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (compatible; ai-job-hunter/1.0)"
MAX_DESCRIPTION = 4000      # plenty for an HN post; keeps the CSV readable
HOME = os.path.expanduser("~")
DEFAULT_DIR = os.path.join(HOME, "ai-job-hunter")

JOBOT_SEARCH = "https://jobot-com-api.jobot.net/rest/jobs/search"
HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM = "https://hn.algolia.com/api/v1/items/"

QUERIES = [
    "AI Engineer", "Machine Learning Engineer", "LLM Engineer",
    "Generative AI Engineer", "AI Software Engineer", "MLOps Engineer",
    "AI Architect", "Applied AI Engineer",
]

AI_KW = re.compile(
    r"\b(AI|LLM|LLMs|ML|GenAI|machine learning|deep learning|NLP|RAG|agentic|"
    r"agents|inference|PyTorch|TensorFlow|transformer|embeddings|fine-tun\w*|"
    r"artificial intelligence|computer vision|MLOps)\b", re.I)

TITLE_AI = re.compile(
    r"\b(AI|ML|LLM|GenAI|machine learning|deep learning|artificial intelligence|"
    r"computer vision|NLP|MLOps|inference|data scien)\w*", re.I)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
OBFUSCATED_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:\[at\]|\(at\)|\sat\s)\s*([A-Za-z0-9.-]+)\s*"
    r"(?:\[dot\]|\(dot\)|\sdot\s)\s*([A-Za-z]{2,})", re.I)

# Domains that show up in legal boilerplate; not a hiring contact.
EMAIL_BLOCKLIST = re.compile(
    r"(accessibility|privacy|legal|abuse|postmaster|noreply|no-reply|"
    r"donotreply|benefits|support@|example\.com|sentry\.io|wixpress)", re.I)

GLOBAL_RE = re.compile(
    r"(worldwide|anywhere in the world|remote \(anywhere\)|globally remote|"
    r"global remote|remote \(global\)|any ?timezone|remote \(everywhere\)|"
    r"remote\(everywhere\)|fully remote, anywhere)", re.I)
LATAM_RE = re.compile(
    r"(LATAM|Latin America|South America|Americas|UTC[-–]?[3-6]|"
    r"GMT[-–]?[3-6]|Colombia|Argentina|Brazil|Mexico)", re.I)
US_ONLY_RE = re.compile(
    r"(US[- ]only|U\.S\. only|USA only|US[- ]based (?:candidates|only)|"
    r"must (?:be |live |reside )(?:located )?in the (?:US|United States)|"
    r"authorized to work in the (?:US|U\.S)|no visa sponsorship|"
    r"must live in canada|UK only|EU only|Canada only)", re.I)
REMOTE_RE = re.compile(r"\bremote\b|\bwork from home\b|\bdistributed team\b", re.I)


# ------------------------------------------------------------------- helpers

def fetch_json(url, params=None, method="GET", body=None, retries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                     # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    print("  ! failed %s (%s)" % (url.split("?")[0], last), file=sys.stderr)
    return None


def strip_html(raw):
    if not raw:
        return ""
    txt = re.sub(r"<p>", "\n", raw)
    txt = re.sub(r"<br\s*/?>", "\n", txt)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html.unescape(txt)
    return re.sub(r"[ \t]+", " ", txt).strip()


def find_email(text):
    """Returns the first usable email, or an empty string."""
    for m in EMAIL_RE.findall(text):
        if not EMAIL_BLOCKLIST.search(m):
            return m
    m = OBFUSCATED_RE.search(text)
    if m:
        candidate = "%s@%s.%s" % (m.group(1), m.group(2), m.group(3))
        if not EMAIL_BLOCKLIST.search(candidate):
            return candidate
    return ""


def ai_score(text):
    return len(AI_KW.findall(text or ""))


def classify_scope(text):
    """
    Returns (readable_scope, apply_from_co).
    apply_from_co: 'yes' | 'ask' | 'no'
    Based ONLY on what the posting says. If it doesn't say, it's 'ask'.
    """
    if GLOBAL_RE.search(text):
        return "Global / worldwide", "yes"
    if LATAM_RE.search(text) and REMOTE_RE.search(text):
        return "LATAM / Americas", "yes"
    if US_ONLY_RE.search(text):
        return "Restricted (US/UK/EU/CA)", "no"
    if REMOTE_RE.search(text):
        return "Remote, country unspecified", "ask"
    return "Doesn't say remote", "no"


# ------------------------------------------------------------------- sources

def source_jobot(queries=QUERIES, page_size_guard=400):
    """Jobot: pagination via 'from'. The email lives in documents[].recruiter.email"""
    out = {}
    for q in queries:
        start, total = 0, None
        while True:
            data = fetch_json(JOBOT_SEARCH, {"query": q, "from": start})
            if not data:
                break
            total = (data.get("hits", {}).get("total", {}) or {}).get("value", 0)
            docs = data.get("documents") or []
            if not docs:
                break
            for d in docs:
                rec = d.get("recruiter") or {}
                email = (rec.get("email") or "").strip()
                if not email:
                    continue
                loc = d.get("primaryLocation") or {}
                commute = (d.get("commuteType") or {}).get("name") or ""
                title = d.get("title") or ""
                blob = " ".join([title, d.get("header") or "", commute, loc.get("address") or ""])
                # Jobot's search API has no full posting body, so the description
                # is everything it does expose. Better than nothing to write from.
                pay = ""
                if d.get("compensationMin") or d.get("compensationMax"):
                    pay = "Compensation: %s - %s" % (d.get("compensationMin") or "?",
                                                     d.get("compensationMax") or "?")
                description = "\n".join(x for x in [
                    title, d.get("header") or "",
                    "Location: %s" % loc.get("address") if loc.get("address") else "",
                    "Level: %s" % d.get("experienceLevel") if d.get("experienceLevel") else "",
                    "Type: %s" % d.get("positionType") if d.get("positionType") else "",
                    pay,
                ] if x)[:MAX_DESCRIPTION]
                is_remote = bool(d.get("isRemote")) or commute.lower() == "remote"
                # Jobot is a US agency: "remote" there almost always means remote-US.
                scope = ("Remote (US)", "no") if is_remote else ("Onsite/Hybrid", "no")
                out[("jobot", d["id"])] = {
                    "source": "jobot",
                    "id": d["id"],
                    "company": "Jobot (confidential client)",
                    "contact": (rec.get("name") or "").strip(),
                    "email": email,
                    "role": title,
                    "remote": "yes" if is_remote else "no",
                    "scope": scope[0],
                    "apply_from_co": scope[1],
                    "location": loc.get("address") or "",
                    "description": description,
                    "url": d.get("detailsUrl") or "",
                    "posted": (d.get("created") or "")[:10],
                    "ai_score": ai_score(blob) + (5 if TITLE_AI.search(title) else 0),
                }
            start += len(docs)
            if total is not None and start >= min(total, page_size_guard):
                break
    return out


def hn_threads(limit=3):
    """IDs of the most recent 'Who is hiring' threads (skips 'Who wants to be hired')."""
    data = fetch_json(HN_SEARCH, {"tags": "story,author_whoishiring", "hitsPerPage": 12})
    if not data:
        return []
    hits = [h for h in data.get("hits", [])
            if "who is hiring" in (h.get("title") or "").lower()]
    return [(h["objectID"], h.get("title", "")) for h in hits[:limit]]


def source_hn(limit_threads=3):
    out = {}
    for tid, title in hn_threads(limit_threads):
        month = ""
        m = re.search(r"\(([^)]+)\)", title)
        if m:
            month = m.group(1)
        item = fetch_json(HN_ITEM + str(tid))
        if not item:
            continue
        for c in item.get("children") or []:
            txt = strip_html(c.get("text"))
            if not txt:
                continue
            email = find_email(txt)
            if not email:
                continue
            if not REMOTE_RE.search(txt):
                continue
            first = txt.split("\n")[0].strip()
            company = re.split(r"\||—|–| - ", first)[0].strip()[:60]
            scope, applies = classify_scope(txt)
            # The comment IS the posting. Keeping it is what lets the drafter
            # write about this job instead of about the headline.
            out[("hn", str(c["id"]))] = {
                "description": txt[:MAX_DESCRIPTION],
                "source": "hn",
                "id": str(c["id"]),
                "company": company,
                "contact": c.get("author") or "",
                "email": email,
                "role": first[:160],
                "remote": "yes",
                "scope": scope,
                "apply_from_co": applies,
                "location": "",
                "url": "https://news.ycombinator.com/item?id=%s" % c["id"],
                "posted": month,
                "ai_score": ai_score(txt),
            }
    return out


# --------------------------------------------------------------- persistence

COLS = ["source", "company", "contact", "email", "role", "remote", "scope",
        "apply_from_co", "location", "url", "posted", "ai_score", "seen",
        "description"]


def load_seen(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                          # noqa: BLE001
            pass
    return {}


def write_csv(path, rows):
    """Write to a temp file and rename: nobody ever reads a half-written CSV."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, path)


RANK = {"yes": 0, "ask": 1, "no": 2}


def run(args):
    os.makedirs(args.out, exist_ok=True)
    seen_path = os.path.join(args.out, "seen.json")
    seen = load_seen(seen_path)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    found = {}
    if "jobot" in args.sources:
        print("-> Jobot...")
        found.update(source_jobot())
    if "hn" in args.sources:
        print("-> Hacker News...")
        found.update(source_hn(args.hn_threads))

    rows, fresh = [], []
    for key, row in found.items():
        if row["ai_score"] < args.min_score:
            continue
        if args.scope != "all" and row["apply_from_co"] != args.scope:
            continue
        k = "%s:%s" % key
        row["seen"] = seen.get(k, today)
        rows.append(row)
        if k not in seen:
            seen[k] = today
            fresh.append(row)

    rows.sort(key=lambda r: (RANK.get(r["apply_from_co"], 3), -r["ai_score"]))
    fresh.sort(key=lambda r: (RANK.get(r["apply_from_co"], 3), -r["ai_score"]))

    write_csv(os.path.join(args.out, "jobs.csv"), rows)
    if fresh:
        write_csv(os.path.join(args.out, "new-%s.csv" % today), fresh)
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1)

    print("\n%d postings with an email (%d new today)" % (len(rows), len(fresh)))
    for label in ("yes", "ask", "no"):
        n = sum(1 for r in rows if r["apply_from_co"] == label)
        print("   apply_from_co=%-6s %d" % (label, n))
    if fresh:
        print("\nNew:")
        for r in fresh[:15]:
            print("  [%s] %s — %s (%s)" % (r["apply_from_co"], r["company"],
                                           r["email"], r["scope"]))
    print("\n-> %s" % os.path.join(args.out, "jobs.csv"))
    return 0


# --------------------------------------------------------------------- tests

def selftest():
    """Validates the parser against REAL captured responses from each API."""
    fx = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "fixtures.json"), encoding="utf-8"))
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        ok = ok and good
        print("  %s %-34s got=%r" % ("PASS" if good else "FAIL", name, got))

    print("\n[Jobot] real shape of /rest/jobs/search")
    docs = fx["jobot"]["documents"]
    d0 = docs[0]
    check("recruiter.email", (d0["recruiter"]).get("email"), "dana.reyes@jobot.example")
    check("recruiter.name", (d0["recruiter"]).get("name"), "Dana Reyes")
    check("isRemote -> remote", bool(d0.get("isRemote")), True)
    check("commuteType.name", d0["commuteType"]["name"], "Remote")
    check("primaryLocation.address", d0["primaryLocation"]["address"], "Rollingwood, TX")
    check("AI detected in title", bool(TITLE_AI.search(d0["title"])), True)
    d1 = docs[1]
    check("isRemote null -> not remote", bool(d1.get("isRemote")), False)
    check("pagination: total", fx["jobot"]["total"], 48)

    print("\n[HN] parsing real comments")
    kids = fx["hn"]["children"]
    t0 = strip_html(kids[0]["text"])
    check("entities decoded", "&#x2F;" not in t0 and "/" in t0, True)
    check("plain email", find_email(t0), "rishi@quill.example")
    check("remote detected", bool(REMOTE_RE.search(t0)), True)
    check("company from headline", re.split(r"\||—|–| - ", t0.split("\n")[0])[0].strip(), "Quill")

    t1 = strip_html(kids[1]["text"])
    check("email from 'To apply:'", find_email(t1), "hiring@neuralwatt.example")
    check("'no visa sponsorship' -> no", classify_scope(t1)[1], "no")
    check("ai_score > 0", ai_score(t1) > 0, True)

    t2 = strip_html(kids[2]["text"])
    check("obfuscated [at]/[dot] email", find_email(t2), "jobs@acme-ai.com")
    check("'REMOTE (worldwide)' -> yes", classify_scope(t2)[1], "yes")

    print("\n[Filters] boilerplate email blocklist")
    check("drops accessibility@", find_email("contact accessibility@motionrp.example"), "")
    check("drops Benefits@", find_email("write Benefits@cybercoders.example"), "")
    check("accepts a real one after", find_email("accessibility@x.com and jobs@real.ai"),
          "jobs@real.ai")

    print("\n%s" % ("ALL OK" if ok else "THERE ARE FAILURES"))
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description="AI postings that are remote and have an email.")
    p.add_argument("--out", default=DEFAULT_DIR, help="output folder")
    p.add_argument("--sources", default="jobot,hn", help="jobot,hn")
    p.add_argument("--min-score", type=int, default=1, help="minimum AI signals")
    p.add_argument("--scope", default="all", choices=["all", "yes", "ask", "no"])
    p.add_argument("--hn-threads", type=int, default=3, help="how many HN threads to read")
    p.add_argument("--selftest", action="store_true", help="validate the parser and exit")
    a = p.parse_args()
    if a.selftest:
        return selftest()
    a.sources = [s.strip() for s in a.sources.split(",")]
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
