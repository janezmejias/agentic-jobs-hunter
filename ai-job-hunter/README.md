# ai-job-hunter

Finds AI Engineer postings and returns two things only: **is it remote**, and
**which address do I write to**. Runs on your machine, no dependencies
(Python 3.8+, standard library).

## Why only two sources

Greenhouse, Lever, Ashby, RemoteOK, Remotive, Arbeitnow, Jobicy, Get on Board,
WeWorkRemotely, Torre, Dice, CyberCoders and Motion Recruitment were all tested
live. They all respond, but **none of them exposes an email**. They're good for
browsing postings, not for writing to someone. The two that do give an address:

| Source | What it gives | Verified |
|---|---|---|
| **Jobot** | the recruiter's email (`recruiter.email`) | 48 AI postings, 45 recruiters |
| **Hacker News** | the email of whoever is hiring | 4 threads, 319 comments with an email |

## Usage

```bash
python3 ai_job_hunter.py --selftest     # validate the parser (do this first)
python3 ai_job_hunter.py                # normal run
python3 ai_job_hunter.py --scope yes    # only what's applicable from Colombia
python3 ai_job_hunter.py --min-score 5  # demand more AI signals
```

Output in `~/ai-job-hunter/`:

- `jobs.csv` — everything current, sorted by how applicable it is
- `new-YYYY-MM-DD.csv` — **only what showed up today**, the file you actually read
- `seen.json` — state; delete it to make everything look new again

## The column that matters: `apply_from_co`

Derived from the text of the posting, not from a guess:

- **yes** — explicitly says worldwide/global/LATAM/Americas
- **ask** — says remote but doesn't restrict a country
- **no** — says US-only, UK, EU, Canada, or "no visa sponsorship"

Jobot is always `no`: it's a US agency and its "Remote" means remote within the
US. The addresses are still worth having, to ask about contractor work.

## Automating it

This folder is one stage of a larger pipeline — see `../README.md`. The root
`pipeline.py` runs this and then builds the day's list; the UI's Schedule tab
puts it on cron.

To run just this one on its own, `crontab -e`, 08:30 Bogotá time:

```
30 8 * * * /usr/bin/python3 /path/to/ai_job_hunter.py >> ~/ai-job-hunter/log.txt 2>&1
```

To be notified only when something applicable shows up:

```bash
python3 ai_job_hunter.py --scope yes && \
  [ -f ~/ai-job-hunter/new-$(date +%F).csv ] && \
  notify-send "New remote AI postings"
```

## Maintenance

`ai_job_hunter.py` uses Jobot's internal API, which isn't public and can change
without notice. If Jobot stops returning rows, run `--selftest`: if it passes,
the problem is the endpoint, not the code. The HN API (Algolia) is public and
stable. A new HN thread appears on the 1st of every month.

Realistic pace: HN gives ~80 new addresses a month, nearly all on day one. Jobot
rotates a few postings a week.
