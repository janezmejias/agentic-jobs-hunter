import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { STATES, LABEL } from "../types";
import type { Contact, ContactStatus, Snapshot } from "../types";
import { sendBatch } from "../api";
import ContactList, { OriginBadge } from "../ContactList";
import Modal from "../ui/Modal";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import { Card, Empty, SectionHeading } from "../ui/Card";
import { TextArea, TextField } from "../ui/Field";
import { cn } from "../ui/cn";

type Filter = ContactStatus | "all";

export default function ContactsView({
  snapshot,
  onSave,
  onMark,
}: {
  snapshot: Snapshot;
  onSave: (c: Contact, subject: string, body: string) => Promise<void>;
  onMark: (c: Contact, status: ContactStatus) => Promise<void>;
}) {
  // Both live in the URL, so a refresh lands you back where you were.
  const { email } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = (params.get("status") as Filter) || "drafted";
  const selected = email ?? null;

  const setFilter = (next: Filter) =>
    setParams(next === "drafted" ? {} : { status: next }, { replace: true });
  const setSelected = (address: string) =>
    navigate(`/contacts/${encodeURIComponent(address)}?${params.toString()}`);

  // Who to send to on the next click. Deliberately not persisted: it is a
  // decision about this batch, not a property of the contact.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState("");

  function pick(email: string, on: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(email);
      else next.delete(email);
      return next;
    });
  }

  const visible = useMemo(
    () =>
      filter === "all"
        ? snapshot.contacts
        : snapshot.contacts.filter((c) => c.status === filter),
    [snapshot, filter],
  );
  const current = snapshot.contacts.find((c) => c.email === selected) ?? null;
  // You can only send to someone who is actually owed an email.
  const sendable = visible.filter((c) => !c.unsubscribed && c.follow_ups_left > 0);
  const pickedList = [...picked];
  const allPicked = sendable.length > 0 && sendable.every((c) => picked.has(c.email));

  async function onSendPicked() {
    setSending(true);
    setSendResult("");
    try {
      const r = await sendBatch(pickedList);
      setSendResult(`Sending ${r.would_send} now. Watch them land in Activity.`);
      setPicked(new Set());
    } catch (e) {
      setSendResult(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSending(false);
      setConfirming(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-shrink-0 flex-wrap gap-2 border-b border-line px-6 py-3">
        {STATES.map((s) => (
          <FilterChip
            key={s}
            on={filter === s}
            onClick={() => setFilter(s)}
            count={snapshot.summary[s] ?? 0}
          >
            {LABEL[s]}
          </FilterChip>
        ))}
        <FilterChip on={filter === "all"} onClick={() => setFilter("all")} count={snapshot.contacts.length}>
          All
        </FilterChip>
      </div>

      {picked.size > 0 && (
        <div className="flex flex-shrink-0 flex-wrap items-center gap-3 border-b border-line bg-brand/10 px-6 py-3">
          <strong className="text-[15px]">{picked.size} picked</strong>
          <span className="flex-1 text-[13.5px] text-dim">
            Only these get an email. Everyone else stays exactly where they are.
          </span>
          <Button size="sm" variant="quiet" onClick={() => setPicked(new Set())}>
            Clear
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={sending}
            onClick={() => setConfirming(true)}
          >
            Send these {picked.size}
          </Button>
        </div>
      )}
      {sendResult && (
        <div className="flex-shrink-0 border-b border-line px-6 py-2.5 text-[15px]">
          {sendResult}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex w-[30%] max-w-[440px] min-w-[300px] flex-shrink-0 flex-col border-r border-line">
          <label className="flex flex-shrink-0 cursor-pointer items-center gap-2.5 border-b border-line bg-surface px-3 py-2 text-[13.5px] text-dim">
            <input
              type="checkbox"
              checked={allPicked}
              onChange={(e) =>
                setPicked(e.target.checked ? new Set(sendable.map((c) => c.email)) : new Set())
              }
              className="h-4 w-4 cursor-pointer accent-[var(--brand)]"
            />
            {allPicked ? "Unpick all" : `Pick all ${sendable.length} in this filter`}
          </label>
          <ContactList
            className="min-h-0 flex-1"
            contacts={visible}
            selected={selected}
            onSelect={setSelected}
            picked={picked}
            onPick={pick}
            empty="Nothing in this filter."
            meta={(c) => (
            <>
              {c.due_follow_up && <Badge tone="warn">follow up</Badge>}
              <OriginBadge origin={c.origin} />
            </>
          )}
          />
        </div>
        {current ? (
          <Editor key={current.email} contact={current} onSave={onSave} onMark={onMark} />
        ) : (
          <div className="flex-1 p-6">
            <Empty>
              Pick a contact on the left. What you save regenerates recipients.csv,
              which is exactly what the sender will send.
            </Empty>
          </div>
        )}
      </div>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Send to ${picked.size} picked ${picked.size === 1 ? "person" : "people"}`}
        description="Real emails, no undo. Nobody outside this list is touched."
        footer={
          <>
            <Button variant="primary" disabled={sending} onClick={() => void onSendPicked()}>
              Yes, send {picked.size}
            </Button>
            <Button variant="quiet" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </>
        }
      >
        <ul className="m-0 flex max-h-72 list-none flex-col gap-1.5 overflow-y-auto p-0 text-[15px]">
          {pickedList.map((email) => {
            const c = snapshot.contacts.find((x) => x.email === email);
            return (
              <li key={email} className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[13px]">{email}</span>
                <span className="text-dim">
                  {c?.company || "—"} ·{" "}
                  {c && c.emails_sent > 0
                    ? `follow-up ${c.next_stage}`
                    : "first contact"}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 mb-0 text-[13.5px] text-dim">
          The daily cap still applies. If you pick more than is left for today, the
          rest go out on a later run.
        </p>
      </Modal>
    </div>
  );
}

function FilterChip({
  on, count, onClick, children,
}: { on: boolean; count: number; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "cursor-pointer rounded-full border px-4 py-1.5 text-sm transition-colors",
        on ? "border-brand bg-brand/12 text-ink" : "border-line text-dim hover:border-dim",
      )}
    >
      <b className="mr-1.5 text-[15px] text-ink tabular-nums">{count}</b>
      {children}
    </button>
  );
}

function Editor({
  contact, onSave, onMark,
}: {
  contact: Contact;
  onSave: (c: Contact, subject: string, body: string) => Promise<void>;
  onMark: (c: Contact, status: ContactStatus) => Promise<void>;
}) {
  const [subject, setSubject] = useState(contact.subject);
  const [body, setBody] = useState(contact.body);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");

  const dirty = subject !== contact.subject || body !== contact.body;
  const blank = subject.trim() === "" || body.trim() === "";
  const words = body.trim() ? body.trim().split(/\s+/).length : 0;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setFailure("");
    try {
      await action();
    } catch (e) {
      setFailure(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
      <div className="flex items-start justify-between gap-5">
        <div>
          <h2 className="m-0 text-[22px] font-semibold tracking-tight">
            {contact.company || contact.email}
          </h2>
          <p className="mt-1 text-[13.5px] text-dim">{contact.role || contact.reference}</p>
        </div>
        <Badge tone={contact.status === "sent" ? "brand" : "neutral"}>
          {LABEL[contact.status]}
        </Badge>
      </div>

      {contact.due_follow_up && (
        <div className="rounded-r-lg border-l-[3px] border-warn bg-warn/12 px-4 py-3 text-[15px]">
          The waiting period is over. If they replied, mark it below before the
          follow-up goes out.
        </div>
      )}

      <div className="grid min-h-0 flex-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(280px,340px)]">
        <div className="flex h-full min-w-0 flex-col gap-4">
          <TextField
            label="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="No subject, no send"
          />
          <TextArea
            label="Body"
            note={`${words} words`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            spellCheck={false}
            placeholder="No body, no send"
            className="min-h-[340px]"
          />
          {failure && <p className="m-0 text-[15px] text-bad">{failure}</p>}
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              variant="primary"
              disabled={busy || !dirty || blank}
              onClick={() => run(() => onSave(contact, subject, body))}
            >
              {dirty ? "Save changes" : "No changes"}
            </Button>
            <span className="flex-1" />
            <Button variant="good" disabled={busy} onClick={() => run(() => onMark(contact, "replied"))}>
              Replied
            </Button>
            <Button disabled={busy} onClick={() => run(() => onMark(contact, "bounced"))}>
              Bounced
            </Button>
            <Button disabled={busy} onClick={() => run(() => onMark(contact, "dismissed"))}>
              Dismiss
            </Button>
          </div>
          <p className="m-0 text-[13.5px] text-dim">
            “Replied”, “Bounced” and “Dismiss” all unsubscribe the address: it won’t
            get the follow-up.
          </p>
        </div>

        <PostingCard contact={contact} />
      </div>
    </section>
  );
}

export function PostingCard({ contact }: { contact: Contact }) {
  const rows: Array<[string, React.ReactNode]> = [
    ["To", <span className="font-mono text-sm">{contact.email}</span>],
    ["Company", contact.company || <span className="text-dim">not stated</span>],
    ["Role", contact.role || <span className="text-dim">not stated</span>],
    ["Remote scope", contact.scope],
    ["AI signals", contact.ai_score],
    ["Source", contact.source],
    ["Text", contact.origin || <span className="text-dim">none yet</span>],
  ];
  if (contact.sent_at) rows.push(["Sent", contact.sent_at]);
  if (contact.note) rows.push(["Note", contact.note]);

  return (
    <Card className="sticky top-0 flex flex-col gap-3 p-5">
      <SectionHeading>The posting</SectionHeading>
      <dl className="m-0 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={String(k)} className="contents">
            <dt className="text-dim">{k}</dt>
            <dd className="m-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>
      {contact.original_headline && (
        <>
          <SectionHeading>Original headline</SectionHeading>
          <p className="m-0 rounded-lg bg-raised px-3.5 py-3 text-sm leading-relaxed break-words text-dim">
            {contact.original_headline}
          </p>
        </>
      )}
      {contact.description && (
        <>
          <SectionHeading aside={`· ${contact.description.length} chars`}>
            The posting
          </SectionHeading>
          <pre className="m-0 max-h-72 overflow-y-auto rounded-lg bg-raised px-3.5 py-3 font-sans text-sm leading-relaxed break-words whitespace-pre-wrap text-dim">
            {contact.description}
          </pre>
          <p className="m-0 text-xs text-dim">
            This is what the model writes from — the first email and the follow-up
            both get it.
          </p>
        </>
      )}
      {contact.url && (
        <a
          className="text-[14.5px] text-brand hover:underline"
          href={contact.url}
          target="_blank"
          rel="noreferrer"
        >
          Open the original posting →
        </a>
      )}
    </Card>
  );
}
