import json, os, shutil, types, csv
import ai_job_hunter as H

HERE = os.path.dirname(os.path.abspath(__file__))
fx = json.load(open(os.path.join(HERE, "fixtures.json")))
calls = []


def fake_fetch(url, params=None, method="GET", body=None, retries=3):
    calls.append((url, dict(params or {})))
    if url == H.JOBOT_SEARCH:
        start = int(params.get("from", 0))
        # mimics real pagination: 48 total, 24 per page, real docs on page 1
        if start == 0:
            docs = fx["jobot"]["documents"] * 12          # 24 docs
        elif start == 24:
            docs = fx["jobot"]["documents"] * 12
        else:
            docs = []
        return {"hits": {"total": {"value": 48}}, "documents": docs[:24]}
    if url == H.HN_SEARCH:
        return {"hits": [
            {"objectID": "49522897", "title": "Ask HN: Who is hiring? (September 2026)"},
            {"objectID": "49522896", "title": "Ask HN: Who wants to be hired? (September 2026)"},
        ]}
    if url.startswith(H.HN_ITEM):
        return {"children": fx["hn"]["children"]}
    raise AssertionError("unexpected URL: " + url)


H.fetch_json = fake_fetch

print("== source_jobot (real pagination)")
j = H.source_jobot(queries=["AI Engineer"])
print("   unique rows:", len(j), "| pages requested:",
      sum(1 for u, p in calls if u == H.JOBOT_SEARCH))
assert len(j) == 2, "must dedupe by id"
r = j[("jobot", "f1f1484906")]
assert r["email"] == "dana.reyes@jobot.example" and r["remote"] == "yes", r
assert j[("jobot", "449def7e06")]["remote"] == "no"
print("   OK dedupe + email + remote")

print("\n== source_hn (skips 'Who wants to be hired')")
h = H.source_hn(limit_threads=3)
print("   rows:", len(h))
assert len(h) == 3, h
assert not any("wants to be hired" in str(c) for c in calls)
emails = sorted(v["email"] for v in h.values())
assert emails == ["hiring@neuralwatt.example", "jobs@acme-ai.com", "rishi@quill.example"], emails
scopes = {v["email"]: v["apply_from_co"] for v in h.values()}
assert scopes["jobs@acme-ai.com"] == "yes" and scopes["hiring@neuralwatt.example"] == "no"
print("   OK emails:", emails)

print("\n== full run(): CSV + state + 'new'")
out = "/tmp/hunter-test"
shutil.rmtree(out, ignore_errors=True)
args = types.SimpleNamespace(out=out, sources=["jobot", "hn"], min_score=0,
                             scope="all", hn_threads=3)
H.run(args)
rows = list(csv.DictReader(open(os.path.join(out, "jobs.csv"), encoding="utf-8-sig")))
print("   jobs.csv:", len(rows), "rows | columns:", len(rows[0]))
assert all(r["email"] for r in rows), "every row must carry an email"
assert rows[0]["apply_from_co"] == "yes", "applicable ones must sort first"
fresh = [f for f in os.listdir(out) if f.startswith("new-")]
assert fresh, "the first run must produce a 'new' file"
print("   first run ->", fresh[0])

print("\n== second run (nothing new)")
for f in fresh:
    os.remove(os.path.join(out, f))
H.run(args)
assert not [f for f in os.listdir(out) if f.startswith("new-")], \
    "must not report the same postings as new twice"
print("   OK: state prevents re-reporting postings already seen")
print("\nALL E2E TESTS PASSED")
