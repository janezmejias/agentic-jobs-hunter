# agentic-jobs-hunter

Two programs that already existed, now chained: one **finds** AI postings that
carry a contact email, the other **writes** to them. In between sits a thin
bridge, a model that adapts your profile to each posting, and a local database
that remembers everything.

```
ai_job_hunter.py  ──►  ~/ai-job-hunter/jobs.csv
                             │
                        prepare.py       filter, merge duplicates, clean fields
                             │
                             ▼
                         state.db  ◄──────  run.sh + ui/   (review and edit)
                             ▲
                             │
                         draft.py         picks the card that fits (Haiku 4.5)
                             │
                  gmail-sender/recipients.csv   (regenerated from the database)
                             │
                       send_emails.py  ──►  Gmail
```

`state.db` is a single SQLite file holding contacts, drafts, sends and
unsubscribes. Because `sqlite3` is standard library, `send_emails.py` still has
zero external dependencies.

## Setup (once)

```bash
# 1. The hunter works
python3 ai-job-hunter/ai_job_hunter.py --selftest

# 2. The chain works
python3 test_integration.py

# 3. Your details in gmail-sender/config.ini
#    address, app_password (https://myaccount.google.com/apppasswords),
#    sender_name, and attachment = cv.pdf   (drop the CV in gmail-sender/)

# 4. Check profile.md — it is already built from profile/Profile.pdf
#    It is the ONLY thing the model may claim about you.

# 5. The API for drafting
pip install anthropic
#    The key can be an env var, or read from a .env file. ONLY ANTHROPIC_API_KEY
#    is read from that file — a shared .env full of production secrets never
#    gets sourced into this process or into cron.
python3 draft.py --diagnose --env-file ~/path/to/.env

# 5b. Preflight, before anything is sent (also the UI's first tab)
python3 gmail-sender/send_emails.py --check

# 6. Open the UI — everything from here happens in it
bash run.sh start

# 7. Schedule tab → "Search now". Finds postings, builds the list, writes drafts.
# 8. Preflight tab → read every draft, then "Verify Gmail login", then
#    "Send one test to myself".
# 9. When you're happy: Schedule tab → turn the two schedules on.
```

There is one shell script, `run.sh`, and it only starts and stops the UI.
Everything that runs on a schedule goes through `pipeline.py`, which the UI and
cron both call:

```bash
python3 pipeline.py refresh    # search, build the list, write the drafts
python3 pipeline.py send       # send the batch that is due
python3 pipeline.py status     # what is scheduled, when it last ran, what it cost
python3 pipeline.py schedule   # rewrite the cron entries from the saved settings
```

## Preflight — check everything before the first send

This is the first screen the UI opens on, and it is the thing to use before you
send anything at all. It runs **the same checks `send_emails.py` runs**, by
importing them — not a copy that can drift and quietly lie to you.

```bash
bash run.sh start          # then the Preflight tab
python3 gmail-sender/send_emails.py --check    # same thing in the terminal
```

It reports three levels — **blockers** stop the send, **warnings** are worth a
look, **ok** passed — and then shows you the exact messages that would go out:
From, Subject, attachment, unsubscribe header, full body.

**The send button lives here**, under the checks, and it is disabled while
anything above it is red. `POST /api/send` re-runs the preflight server-side and
refuses with a 409 if a blocker is standing, so the gate holds even if the page
is stale. Clicking it asks first: how many go out, how many of those are
follow-ups, roughly how long it takes, and how many are waiting behind the daily
cap. Sending happens in the background and lands in Activity.

To send more than the cap in one day, raise `max_per_day` in `config.ini` — that
is deliberately a config edit and not a button, because going from nothing to
dozens of cold emails in a day is the thing that gets a personal address
filtered.

### Picking recipients by hand

Contacts has a checkbox on every row, and a bar appears once you tick one:
**"N picked · Send these N"**. Only those get an email; everyone else stays
exactly where they were, still queued for later. The confirmation lists each
address with whether it is a first contact or which follow-up, because "send
these 6" should never be a guess.

The gate adapts to the choice. A **global** blocker — bad credentials, a missing
attachment — stops everything, picked or not. A blocker about *particular rows*
only stops those rows: if you hand-picked six people and none of them is the one
with the unfinished draft, there is no reason to stop you. If one of your picks
*is* unsendable, the request is refused **by name** rather than quietly skipping
it. Every check carries a `scope` saying which kind it is.

Underneath it is one flag, so the terminal can do the same thing:

```bash
python3 gmail-sender/send_emails.py --only picked.txt   # one address per line
```

An empty file means nobody, not everybody.

Two buttons sit under it, in increasing order of commitment:

```bash
python3 gmail-sender/send_emails.py --check-login   # logs in, hangs up, sends NOTHING
python3 gmail-sender/send_emails.py --to-self       # one real email, to you only
```

`--check-login` is the one to reach for first: it turns "the credentials look
filled in" into "Gmail accepts them", without composing a message or touching a
single recipient. Run it as often as you like.

`--check` exits 1 when there are blockers, so cron or a script can gate on it.

What it catches, in the order it will bite you:

| Blocker | Why it matters |
|---|---|
| Unfinished template text (`>>>`, `{{…}}`) | The fallback template ships full of it. Sending that is the worst outcome there is. |
| Empty subject or body | Burns the address for nothing. |
| Example Gmail credentials | Nothing would send anyway. |
| Message uses fields the CSV lacks | You forgot `draft.py`. |
| Missing attachment file | `attachment = cv.pdf` with no cv.pdf. |
| Gmail throttled you recently | Sending now makes it worse. |

| Warning | Why |
|---|---|
| Emails on the fixed template | Identical bodies are the clearest bulk signal. |
| Identical bodies detected | Same, measured directly. |
| The email says "attached" but nothing is | Embarrassing and obvious. |
| Unsubscribe header on | Wrong for a job application. |
| `max_per_day` above 50 | Ramp from a personal address. |

> The placeholder blocker exists because it was a real hole: with no API key, the
> fallback template was going out **with `>>> REPLACE THIS PARAGRAPH` inside it**.
> `validate()` in `draft.py` only guards the model's drafts. Now the sender
> refuses these itself, right before the SMTP call, so no path reaches Gmail.

## The UI

```bash
bash run.sh start       # builds the UI the first time, then starts everything
bash run.sh stop
bash run.sh status
bash run.sh logs
```

A topbar (campaign, ready/blocked status, refresh) over a sidebar with the four
things this does. React + TypeScript + Tailwind v4; the sidebar is generated from
`ui/src/nav.ts`, so adding a section is one entry there plus one view file.

| Section | What it is for |
|---|---|
| **Preflight** | Every safety check, the batch numbers, and the exact emails that would go out. Opens here on purpose. |
| **Contacts** | Filter by status, read and edit any draft, mark replies. Saving regenerates `recipients.csv`. |
| **Follow-ups** | Who has passed the waiting period, the first email and the second side by side, and a button that runs `draft.py --follow-up`. |
| **Schedule** | When it last searched, when it runs next, what each run cost, and the on/off switches for both cron jobs. |
| **Activity** | The send log straight from the database: when, to whom, accepted or refused, which campaign. |

### Schedule, because searching costs money

Searching is the only step that spends tokens, so it is the one you want on a
leash. The Schedule tab shows the last run, the next run, and **what every run
cost**, with a running total. "Search now" starts one on demand and the page
follows it to completion.

Three switches write the cron entries for you — search, send, and check the
inbox — and each takes **any schedule cron can express** — every N minutes, hourly, daily, weekly on chosen days, monthly on
a day, yearly on a date, or a raw expression you type yourself:

```
0 9 * * MON,THU          At 09:00, on Monday and Thursday
*/30 9-17 * * MON-FRI    Every 30 minutes between 09:00 and 17:59, on weekdays
30 6 1 * *               At 06:30, on the 1st
0 0 1 1 *                At 00:00, on the 1st in January
```

The editor offers presets but never hides the expression — it stays visible and
editable, and typing something the presets can't represent just switches it to
Custom. Under it sits a live preview: what the schedule means in words, and the
next three times it will actually fire. That preview is computed by `cron.py`,
the same module that writes the crontab line, so it cannot promise a time that
won't happen. An expression that doesn't parse is refused at save time rather
than installed as a job that silently never runs.

Saving rewrites only the lines this project owns; anything else in your crontab
is left alone. Turn both off and the entries are removed. Every run, whether you
clicked it or cron fired it, lands in the same run history with its trigger
recorded, so "why did I spend that" always has an answer.

Every view is a real route — `/preflight`, `/contacts/:email`, `/follow-ups/:email`,
`/schedule`, `/activity` — so a refresh lands you back where you were, including
the contact you had open and the status filter you had picked. The Python server
falls back to `index.html` for unknown paths, which is what makes that work, and
the built assets use absolute paths so a deep route still finds its JavaScript.

Shared pieces live in `ui/src/ui/` (Button, Card, Badge, StatTile, Field, Icon)
and `ui/src/ContactList.tsx` / `EmailPreview.tsx` — the contact list and the
email renderer are each written once and used by two views. Colours are semantic
tokens (`surface`, `line`, `ink`, `dim`, `brand`) defined once in
`ui/src/styles.css` and flipped by the OS theme, so no component carries a
hard-coded colour or a repeated `dark:` variant.

`start` leaves the backend serving the built UI at **http://127.0.0.1:8787**.
To work on the UI itself, `bash run.sh start dev` also starts vite with hot
reload on 5173 (proxying `/api` to the backend). `restart` takes `dev` the same
way. If a port is busy: `BACK_PORT=8888 bash run.sh start`.

Each service runs in its own process group and is stopped by the PID saved in
`.run/`, so stopping the front end also takes down vite, which is npm's child.
Logs land in `.run/backend.log` and `.run/front.log`.

It listens on 127.0.0.1 only: your contacts and drafts never leave your machine.
It does three things, and all three matter:

- **Review and edit every draft before it goes out.** Saving regenerates
  `recipients.csv` immediately, so what you see is exactly what will be sent. An
  edited draft is marked `edited` and the drafter leaves it alone.
- **Mark who replied.** SMTP gives you no way to know, and that was the hole in
  the follow-up: one button unsubscribes them so they don't get the second
  email. Same for "Bounced" and "Dismiss".
- **See the follow-up queue**: who has finished the waiting period.

The server refuses to save an email with no subject or no body, exactly like the
sender refuses to send one.

## The writing, and what actually protects your address

`draft.py` writes each email with **Claude Haiku 4.5** (`claude-haiku-4-5`). It
does not send a summary of you: **it reads the posting, picks from `profile.md`
the CARD that answers what that team is asking for, and writes about that.** You
adapt to the posting. Every run reports which cards it chose, which is a useful
signal: if everything comes back with the same one, either the filter is pulling
very similar postings or the profile is missing material.

### It writes from the posting, not from its title

The hunter keeps the **full text of the posting** — on Hacker News that is the
whole comment, which is where the actual requirements live. It reaches the model
in both the first email and the follow-up, so the email can answer what the team
asked for instead of guessing from a job title. The rule is symmetric with the
one about him: *everything you say about THEM must come from the posting text*,
never extrapolated from the company name.

For the follow-up this is the point. The model gets the posting **and** the email
that already went out, and is told to find something in the posting the first one
didn't address — a requirement, a constraint, a piece of their stack. That is
what makes the second email a different email rather than a nudge.

Jobot's search API exposes no posting body, so there the description is the title,
tagline, location, level and compensation — everything it does give.

`profile.md` comes from `profile/Profile.pdf` and is organized as tagged cards
(`CARD-VOICE-LATENCY`, `CARD-BANKING`, `CARD-EVAL-LOOP`, …), each with a concrete
result. If you update the PDF, update the `.md` by hand: the PDF's raw text is
fine for reading, not for a model to select from.

### Where the API key comes from

`draft.py` looks for `ANTHROPIC_API_KEY` in this order: the environment, then
`--env-file`, then `ANTHROPIC_ENV_FILE`, then `.env` in the project root. It
parses out **that one variable and nothing else** — it never `source`s the file,
because a shared `.env` can carry dozens of unrelated production secrets that
have no business in this process or in cron. The value is never printed.

`pipeline.py` passes it through when it calls the drafter, so a scheduled run
finds the key the same way a manual one does.

### The sequence, and how it ends

Sending works in stages, and a contact's stage is simply how many emails they
have already been sent:

```
stage 0  →  first email
   ↓ wait_days without a reply
stage 1  →  follow-up 1
   ↓ wait_days without a reply
stage 2  →  follow-up 2
   ↓
        done — that person is never written to again
```

Every run of the sender handles **both lanes at once**: the follow-ups that came
due and the people who have never been written to. Follow-ups go first, because
someone who already waited should not wait longer just because the day's quota
went to strangers.

"Only if they still haven't answered" is not a flag anyone has to remember to
set. Marking someone Replied, Bounced or Dismissed unsubscribes the address, and
the queue is built from whoever is left — so a reply removes them from both lanes
by construction.

And you do not have to do the marking either. **`inbox.py` reads your inbox over
IMAP**, with the same app password you send with, and marks whoever replied or
bounced. It runs on its own schedule, and again before every send and every drafting
pass, because a reply that arrived an hour ago has to stop the follow-up that
would go out now and nobody is around to catch it by hand. The default is every
30 minutes between 07:00 and 23:00 — it costs nothing, so it can be frequent.

Each scan only watches **the people who have not answered yet**. Someone already
marked replied, bounced or dismissed leaves the watch list, so a later email from
them is ignored rather than re-marked on every pass. The run prints how many it
is watching, which is a useful number on its own: it is exactly how many people
still owe you an answer.

```bash
python3 pipeline.py inbox            # scan and mark
python3 inbox.py --dry-run           # say what it would mark, change nothing
```

The mailbox is opened **read-only**: nothing is marked read, moved, flagged or
deleted. It only looks. What it recognises:

- **A reply** — a message whose `In-Reply-To` or `References` quotes the
  `Message-ID` of something we sent. That is exact. The fallback is a message
  arriving from an address we wrote to, which catches clients that rewrite
  headers and replies to anything sent before Message-IDs were recorded.
- **A bounce** — a message from a mailer-daemon or postmaster that names one of
  our addresses in its body. Gmail accepts almost everything at send time and
  bounces later, so this is the only place a dead address ever shows up. A
  bounce about somebody else's address is ignored.

Scans are incremental with a day of overlap: seeing a message twice is harmless
because marking is idempotent, missing one is not. If the mailbox can't be
reached, the run says so and carries on — an unreachable inbox is not a reason
to stop sending.

If IMAP is switched off in Gmail the login is refused, and the error says where
to turn it on (Settings → Forwarding and POP/IMAP → Enable IMAP).

`pipeline.py refresh` writes the due follow-ups in the same run that searches, so
the text is ready before the sender needs it. Each follow-up is given **every**
email already sent, not just the last, and is forbidden from repeating any of
their arguments, from mentioning that it is writing again, and from implying the
reader was rude not to reply.

The CSV the sender reads carries a `stage` column. If it disagrees with the
database about which email someone is owed, that row is skipped rather than sent
— a stale list can't send the wrong email to the right person.

```ini
follow_ups = 2      ; how many follow-ups one person can ever get; 0 turns them off
wait_days = 3       ; days without a reply before the next one is due
```

### Caching, and a trap that costs money silently

The stable block — instructions plus the whole of `profile.md` — is marked with
`cache_control`, so from the second email on that prefix bills at ~0.1x.

**But Haiku 4.5 only caches prefixes of 4096 tokens or more, and below that it
raises no error: it simply bills everything, every time.** It's one of the
highest minimums in the family (Opus 5 caches from 512). So:

```bash
python3 draft.py --diagnose   # measures the prefix before you spend anything
```

It tells you the token count and whether it clears the minimum. **Measured
against the real API: the stable prefix is 4,979 tokens, so caching does kick in,
with 883 tokens of headroom.** A live two-email run confirmed it — 5,157 tokens
written to cache on the first call, 5,157 read back on the second. Every run
reports its real cache tokens and warns loudly if caching ever stops working. If
you come up short after editing `profile.md`, the fix is adding real material
(another card, another example email), not padding.

Set your expectations: across ~150 contacts, caching takes the cost from about
**USD 0.93 to about USD 0.33**. That's sixty cents. It's right to have it, but
the money isn't there.

What actually burns a personal address, in order:

| Lever | Weight | Where it lives |
|---|---|---|
| Spam complaints | the biggest | recipient relevance — the `yes,ask` filter |
| Bounces | very high | HN addresses come from a regex; some are dead |
| Ramping volume too fast | high | `max_per_day`, which starts at 15 |
| Identical bodies | medium | **this is what Haiku solves** |
| Reply rate | medium, in your favour | also Haiku |

**Bounces land in your inbox, not in the script.** Gmail accepts almost
everything at send time and bounces later, so `send_emails.py` can't see them.
When a bounce arrives, add that address to `unsubscribed.txt` (or click
"Bounced" in the UI). It's the manual work that protects the account most.

### What the model is forbidden from doing

The prompt lets it state **only** what's in `profile.md`: no invented years,
employers, numbers or technologies. On top of that, every draft goes through
`validate()`, which rejects it if the subject or body falls outside its size
range, if unfilled template text survives, or if a URL appears that was in
neither your profile nor the posting. A failing draft is retried once; if it
fails again, that row falls back to `fallback_template.txt` and sending carries
on.

Two rules exist because the model broke them on live runs: it told one reader
**"You're building in fintech"** when the posting said no such thing, and it
described a 3-year-7-month job as **"the last year and a half"**. Both are
forbidden in the prompt, and both are now checked mechanically:

- **Claims about the reader.** Only a declarative that *starts a sentence*
  counts — "You're building in fintech." The first version of this check wasn't
  anchored, and it rejected three good drafts for every real catch: "If you're
  building something real…", "what you're working on", "your post didn't say
  what you're building". Conditionals and questions are not claims.
- **Re-dating.** Any "the last N years / the past N months" phrase must appear
  in `profile.md` verbatim. The corpus states exactly one ("the last two
  years"), so an invented timeline has nowhere to hide. A bare "last month" or
  "last week" is ordinary English and is left alone.

When a draft fails, the reason is **stored with it** and shown by the preflight,
so you see the cause rather than just the `>>>` symptom. To re-draft only what
needs it — the fallbacks, plus anything a tightened rule now rejects:

```bash
python3 draft.py --fix
```

It skips the drafts that are already good, so tightening a rule costs cents
rather than a whole re-run.

What no check can catch is a *plausible* invention. That's what
`gmail-sender/drafts.md` is for: every draft in one file, to read in one sitting
before sending. Once cron is on, emails go out without you seeing them — that's
your call, which is why step 7 comes before step 10.

### Language

English by default, which is correct: Jobot and Hacker News are US-based. To
change it, `--language es` when you call `prepare.py` and `draft.py`.

## Fields you can use in the message

The bridge and the drafter leave these ready so one template works for every
posting. The first four never arrive empty, so an email never reads "Hi ," or
stops mid-sentence.

| Field | Example | Can be empty |
|---|---|---|
| `{{ai_subject}}` | `About the Fullstack SWE role at Quill` | no |
| `{{ai_body}}` | the whole email Haiku wrote | no |
| `{{greeting}}` | `Hi Albert` / `Hi` | no |
| `{{reference}}` | `the Fullstack SWE role at Quill` | no |
| `{{role}}` | `Fullstack SWE` | yes |
| `{{company}}` | `Quill` | yes |
| `{{url}}` | link to the original posting | no |
| `{{scope}}` | `Global / worldwide` | no |

The first two are filled by `draft.py`, the rest by `prepare.py`. `message.txt`
is just `{{ai_body}}`. To never use the model, set
`subject = About {{reference}}` and `text_template = fallback_template.txt`.

It only greets by name when there is a real one (Jobot gives "Albert Simons").
A Hacker News handle like `scottcha` is not a first name: there it greets without
one, which reads better than "Hi scottcha".

## Who gets written to

By default, scope `yes,ask`: everything that says worldwide/global/LATAM, plus
anything that says remote without restricting a country. Everything marked `no`
is out — including all of Jobot, which is a US agency. To change it, edit the
`SCOPE` constant in `pipeline.py`, or try it without writing anything:

```bash
python3 prepare.py --scope yes --show
```

When the same address appears in several postings, it's merged into one row and
**the best one wins**: the hunter sorts by applicability and AI signals, and the
bridge keeps the first. Your 80 Jobot postings are 45 recruiters.

## Follow-ups at 7 days

The second email is the one that converts, and sending it no longer means wiping
history. Every send is recorded with its campaign name. For the follow-up, in
`config.ini`:

```ini
campaign = follow-up-1
follow_up_of = first-contact
wait_days = 3
```

The UI reads `wait_days` from that same file, so the Follow-ups tab and the sender
always agree on who is due.

That run goes **only** to people who got `first-contact` 7 or more days ago.
Write the second email first:

```bash
python3 draft.py --follow-up
```

A follow-up **is not the first email again**: the model is handed what already
went out and forbidden from repeating its argument. 40–80 words, one new thing,
an easy out ("if the role is filled, no problem"). It's stored under a different
fingerprint, so it never overwrites the first.

> **Who replied.** SMTP gives you no way to know. Mark it in the UI with the
> "Replied" button — that unsubscribes them automatically — or add them to
> `unsubscribed.txt` by hand. Otherwise the follow-up goes out anyway.

## Files

| File | What it is |
|---|---|
| `ai-job-hunter/` | the hunter, with its own tests |
| `gmail-sender/` | the sender, with campaigns and follow-ups |
| `prepare.py` | the bridge between them |
| `state.py` / `state.db` | the SQLite database: contacts, drafts, sends, unsubscribes |
| `draft.py` | picks the fitting card and writes (Haiku 4.5) |
| `server.py` + `ui/` | the local UI: review, edit, mark replies |
| `run.sh` | the only shell script: starts and stops the UI |
| `pipeline.py` | everything that runs on a schedule; the UI and cron both call it |
| `inbox.py` | reads the inbox over IMAP: who replied, what bounced |
| `cron.py` | parses cron expressions, says what they mean, works out the next runs |
| `profile.md` | your cards; the only thing the model may claim |
| `profile/Profile.pdf` | the source profile.md is built from |
| `test_integration.py` | exercises the whole chain, sending nothing |

`config.ini` is in `.gitignore` because it holds your Gmail app password.

## Realistic scale

Hacker News gives ~80 new addresses a month, nearly all on day one. Jobot rotates
a few a week. That's ~150 contacts in total, so `max_per_day` starts at 15 and
there is no rush to raise it: your limit is how many people there are to write
to, not Gmail's quota. Raise it by hand, 15 → 30 → 50, over a couple of weeks.
