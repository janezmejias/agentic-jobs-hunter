SENDING EMAILS WITH GMAIL  (Ubuntu)
===================================

Nothing to install: Python 3 already ships with Ubuntu.

This folder is one stage of a larger pipeline. The list it sends to is generated
by the project root (prepare.py + draft.py). See ../README.md for the whole thing.


1) APP PASSWORD  (once)
   a. Turn on 2-step verification:  https://myaccount.google.com/security
   b. Go to  https://myaccount.google.com/apppasswords
      Give it any name ("job emails") and copy the 16-letter code.


2) CONFIGURE
   config.ini              your address, the 16-letter code, the daily maximum
   ../profile.md           your facts; the only thing the model may claim
   fallback_template.txt   the fixed text, used when there is no model


3) TRY IT  (open a terminal here: right click > "Open in Terminal")
   python3 send_emails.py --dry-run   shows what would go out, sends nothing
   python3 send_emails.py --to-self   sends one sample to your own address


4) AUTOMATE IT
   Open the UI (bash run.sh start from the project root) and use the Schedule
   tab. It writes the cron entries, shows the next run, and keeps the cost of
   every run. The machine must be on and not suspended while it sends.

   From a terminal the same thing is:  python3 ../pipeline.py status


FILES THAT APPEAR ON THEIR OWN
   recipients.csv    regenerated from the database; do not edit by hand
   drafts.md         every draft in one file, to read before sending
   log.txt           what the sender has done. Live:  tail -f log.txt
   cron-errors.txt   normally empty; if it has text, something failed unexpectedly


WHEN SOMEONE ASKS TO BE REMOVED
   Add their address to unsubscribed.txt, one per line. Or click "Replied" in the
   UI, which does the same thing through the database.


A NEW CAMPAIGN FOR THE SAME LIST
   Change "campaign" in config.ini. History is kept; nothing is deleted.
