import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { checkInbox, draftFollowUps, loadDrafts } from "../api";
import type { Contact, ContactStatus, Draft, Snapshot } from "../types";
import ContactList, { OriginBadge } from "../ContactList";
import EmailPreview from "../EmailPreview";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import StatTile from "../ui/StatTile";
import StatRow from "../ui/StatRow";
import { Empty, SectionHeading } from "../ui/Card";
import { PostingCard } from "./ContactsView";

function daysSince(stamp: string): number | null {
  if (!stamp) return null;
  const then = new Date(stamp.replace(" ", "T")).getTime();
  if (Number.isNaN(then)) return null;
  return Math.floor((Date.now() - then) / 86_400_000);
}

export default function FollowUpsView({
  snapshot,
  onMark,
  onChanged,
}: {
  snapshot: Snapshot;
  onMark: (c: Contact, status: ContactStatus) => Promise<void>;
  onChanged: () => void;
}) {
  const { email } = useParams();
  const navigate = useNavigate();
  const selected = email ?? null;
  const setSelected = (address: string) =>
    navigate(`/follow-ups/${encodeURIComponent(address)}`);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [checking, setChecking] = useState(false);

  const sent = useMemo(
    () => snapshot.contacts.filter((c) => c.emails_sent > 0 && !c.unsubscribed),
    [snapshot],
  );
  const due = useMemo(() => sent.filter((c) => c.due_follow_up), [sent]);
  const waiting = useMemo(
    () => sent.filter((c) => !c.due_follow_up && c.follow_ups_left > 0),
    [sent],
  );
  const finished = useMemo(() => sent.filter((c) => c.follow_ups_left === 0), [sent]);
  const withSecond = useMemo(
    () => due.filter((c) => c.origin.startsWith("ai-follow-up") || c.origin === "edited").length,
    [due],
  );
  const current = snapshot.contacts.find((c) => c.email === selected) ?? null;

  useEffect(() => {
    if (!selected) {
      setDrafts([]);
      return;
    }
    let live = true;
    void loadDrafts(selected)
      .then((r) => live && setDrafts(r.drafts))
      .catch(() => live && setDrafts([]));
    return () => {
      live = false;
    };
  }, [selected, snapshot]);

  async function onCheckInbox() {
    setChecking(true);
    setResult("");
    try {
      const r = await checkInbox();
      const found = [...r.replies, ...r.bounces];
      setResult(
        found.length
          ? `Read ${r.scanned} messages. ${r.replies.length} replied, ${r.bounces.length} bounced: ${found.join(", ")}. They are out of the sequence now.`
          : `Read ${r.scanned} messages. Nobody has replied and nothing bounced.`,
      );
      onChanged();
    } catch (e) {
      setResult(`Inbox check failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setChecking(false);
    }
  }

  async function onDraft() {
    setBusy(true);
    setResult("");
    try {
      const r = await draftFollowUps();
      setResult(r.output || "Done.");
      onChanged();
    } catch (e) {
      setResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  const ordered = [...due, ...waiting, ...finished];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-3 border-b border-line px-6 py-4">
        <div className="flex-1"><StatRow>
          <StatTile
            value={due.length}
            label={`due after ${snapshot.follow_up_days} days`}
            tone={due.length ? "brand" : "neutral"}
          />
          <StatTile value={waiting.length} label="still waiting" />
          <StatTile value={withSecond} label="next email written" />
          <StatTile value={finished.length} label={`had all ${snapshot.max_follow_ups}`} />
          <StatTile
            value={snapshot.awaiting_reply}
            label="owe you a reply"
            tone={snapshot.awaiting_reply ? "brand" : "neutral"}
          />
          <StatTile value={snapshot.summary.replied ?? 0} label="replied" />
        </StatRow></div>
        <Button disabled={checking} onClick={() => void onCheckInbox()}>
          {checking ? "Reading…" : "Check for replies"}
        </Button>
        <Button variant="primary" disabled={busy || due.length === 0} onClick={() => void onDraft()}>
          {busy ? "Writing…" : "Write the ones that are due"}
        </Button>
      </div>

      <p className="m-0 flex-shrink-0 border-b border-line px-6 py-2 text-[13.5px] text-dim">
        {snapshot.last_inbox_check
          ? `Inbox last checked ${snapshot.last_inbox_check} — ${snapshot.last_inbox_detail}. Whoever replies drops out of the sequence on their own.`
          : "The inbox has not been checked yet. Turn it on in Schedule, or press the button above."}
      </p>
      {result && (
        <pre className="m-0 flex-shrink-0 overflow-x-auto border-b border-line bg-raised px-6 py-3 font-mono text-[13px] whitespace-pre-wrap">
          {result}
        </pre>
      )}

      <div className="flex min-h-0 flex-1">
        <ContactList
          contacts={ordered}
          selected={selected}
          onSelect={setSelected}
          empty="Nobody has been sent a first email yet."
          meta={(c) => {
            const d = daysSince(c.sent_at);
            return (
              <>
                {c.due_follow_up ? (
                  <Badge tone="warn">{d === null ? "due" : `${d}d ago`}</Badge>
                ) : (
                  <Badge>{d === null ? "sent" : `${d}d ago`}</Badge>
                )}
                <OriginBadge origin={c.origin} />
              </>
            );
          }}
        />

        {current ? (
          <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
            <div className="flex items-start justify-between gap-5">
              <div>
                <h2 className="m-0 text-[22px] font-semibold tracking-tight">
                  {current.company || current.email}
                </h2>
                <p className="mt-1 text-[13.5px] text-dim">
                  {current.emails_sent} sent · last {current.sent_at || "—"} ·{" "}
                  {current.follow_ups_left === 0
                    ? "sequence finished"
                    : current.due_follow_up
                      ? "due now"
                      : `waits ${snapshot.follow_up_days} days`}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="good" onClick={() => void onMark(current, "replied")}>
                  They replied
                </Button>
                <Button onClick={() => void onMark(current, "dismissed")}>Dismiss</Button>
              </div>
            </div>

            <div className="rounded-r-lg border-l-[3px] border-warn bg-warn/12 px-4 py-3 text-[15px]">
              {current.follow_ups_left === 0 ? (
                <>
                  This person has had all {snapshot.max_follow_ups} follow-ups. They
                  will not be written to again.
                </>
              ) : (
                <>
                  Follow-up {current.next_stage} of {snapshot.max_follow_ups}, due{" "}
                  {snapshot.follow_up_days} days after the last email. The model gets
                  every email already sent and is forbidden from repeating any of
                  their arguments — 40–80 words, one new thing, an easy way out.
                </>
              )}
            </div>

            <div className="grid min-h-0 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]">
              <div className="flex min-w-0 flex-col gap-4">
                {drafts.length === 0 && <Empty>No drafts stored for this contact.</Empty>}
                {drafts.map((d, i) => (
                  <div key={d.fingerprint} className="flex flex-col gap-2">
                    <SectionHeading aside={`· ${d.origin} · ${d.created_at}`}>
                      {i === 0 && drafts.length > 1
                        ? "Most recent"
                        : i === drafts.length - 1
                          ? "The email that went out"
                          : "Draft"}
                    </SectionHeading>
                    <EmailPreview email={{ subject: d.subject, body: d.body }} />
                  </div>
                ))}
              </div>
              <PostingCard contact={current} />
            </div>
          </section>
        ) : (
          <div className="flex-1 p-6">
            <Empty>
              Pick someone on the left to see the email that went out and the
              follow-up beside it.
            </Empty>
          </div>
        )}
      </div>
    </div>
  );
}
