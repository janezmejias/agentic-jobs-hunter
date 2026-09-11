import { useState } from "react";
import { sendBatch, sendTestEmail, verifyLogin } from "../api";
import type { Check, PreflightReport } from "../types";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import StatTile from "../ui/StatTile";
import StatRow from "../ui/StatRow";
import { Card, Empty, SectionHeading } from "../ui/Card";
import Modal from "../ui/Modal";
import { cn } from "../ui/cn";
import EmailPreview from "../EmailPreview";

const MARK: Record<Check["level"], { glyph: string; dot: string; box: string }> = {
  ok: { glyph: "✓", dot: "bg-brand", box: "border-line" },
  warn: { glyph: "!", dot: "bg-warn", box: "border-warn bg-warn/8" },
  block: { glyph: "✕", dot: "bg-bad", box: "border-bad bg-bad/8" },
};

export default function PreflightView({
  report,
  busy,
  onRefresh,
}: {
  report: PreflightReport | null;
  busy: boolean;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [result, setResult] = useState("");
  const [working, setWorking] = useState(false);
  const [confirming, setConfirming] = useState(false);

  if (!report) return <div className="p-6"><Empty>Running the checks…</Empty></div>;

  const b = report.batch;
  const blockers = report.checks.filter((c) => c.level === "block").length;
  const current =
    report.previews.find((p) => p.to === open) ?? report.previews[0] ?? null;

  async function act(label: string, fn: () => Promise<unknown>, ok: string) {
    setWorking(true);
    setResult("");
    try {
      await fn();
      setResult(ok);
    } catch (e) {
      setResult(`${label} failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 p-6">
      <Card
        className={cn(
          "flex flex-shrink-0 flex-wrap items-center gap-4 p-5",
          report.ok ? "border-brand bg-brand/10" : "border-bad bg-bad/10",
        )}
      >
        <strong className={cn("text-xl", report.ok ? "text-brand" : "text-bad")}>
          {report.ok ? "Ready to send" : "Not ready"}
        </strong>
        <span className="min-w-[280px] flex-1 text-[15px] text-dim">
          {report.ok
            ? "No blockers. Verify the login, then send yourself a test before the real batch."
            : `${blockers} blocker${blockers === 1 ? "" : "s"}. Nothing goes out until they're fixed.`}
        </span>
        <Button size="sm" onClick={onRefresh} disabled={busy}>
          Re-run checks
        </Button>
      </Card>

      <div className="grid min-h-0 flex-1 gap-6 lg:grid-cols-[minmax(360px,34%)_1fr]">
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1.5">
          <SectionHeading>Checks</SectionHeading>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {report.checks.map((c, i) => (
              <li
                key={i}
                className={cn(
                  "flex items-start gap-3 rounded-lg border bg-surface p-3.5",
                  MARK[c.level].box,
                )}
              >
                <span
                  className={cn(
                    "grid h-[22px] w-[22px] flex-shrink-0 place-items-center rounded-full text-[13px] font-bold text-white",
                    MARK[c.level].dot,
                  )}
                >
                  {MARK[c.level].glyph}
                </span>
                <div>
                  <div className="text-[15px]">{c.title}</div>
                  {c.detail && <div className="mt-0.5 text-[13.5px] text-dim">{c.detail}</div>}
                </div>
              </li>
            ))}
          </ul>

          {b.recipients !== undefined && (
            <>
              <SectionHeading>The batch</SectionHeading>
              <StatRow>
                <StatTile value={b.would_send_now ?? 0} label="would go out now" tone="brand" />
                <StatTile value={b.ready ?? 0} label="ready" />
                <StatTile
                  value={b.blocked ?? 0}
                  label="blocked"
                  tone={(b.blocked ?? 0) > 0 ? "bad" : "neutral"}
                />
                <StatTile value={b.already_handled ?? 0} label="already handled" />
                <StatTile value={b.unsubscribed ?? 0} label="unsubscribed" />
                <StatTile value={`${b.sent_today ?? 0}/${b.max_per_day ?? 0}`} label="sent today" />
                <StatTile value={`${b.sent_24h ?? 0}/${b.limit_24h ?? 0}`} label="last 24 h" />
                <StatTile value={`~${Math.round(b.minutes ?? 0)} min`} label="estimated time" />
              </StatRow>
            </>
          )}

          <SectionHeading>Before the real batch</SectionHeading>
          <Card className="grid grid-cols-[max-content_1fr] items-center gap-x-4 gap-y-2.5 p-4">
            <Button
              disabled={working}
              onClick={() =>
                act("Login check", verifyLogin, "Gmail accepted the login. Nothing was sent.")
              }
            >
              Verify Gmail login
            </Button>
            <p className="m-0 text-[13.5px] text-dim">
              Logs in and hangs up. Sends nothing, touches no recipient.
            </p>
            <Button
              variant="primary"
              disabled={working}
              onClick={() => act("Test email", sendTestEmail, "Sent. Check your own inbox.")}
            >
              Send one test to myself
            </Button>
            <p className="m-0 text-[13.5px] text-dim">
              One real email, to your address and nobody else.
            </p>
          </Card>
          {result && (
            <p className="m-0 rounded-lg border border-line bg-raised p-3.5 text-[15px]">
              {result}
            </p>
          )}

          <SectionHeading>Send</SectionHeading>
          <Card
            className={cn(
              "flex flex-wrap items-center gap-4 p-4",
              report.ok && (b.would_send_now ?? 0) > 0 && "border-brand",
            )}
          >
            <div className="min-w-[220px] flex-1">
              <strong className="text-[15px]">
                {report.ok
                  ? `${b.would_send_now ?? 0} would go out now`
                  : "Blocked until the checks pass"}
              </strong>
              <p className="mt-0.5 text-[13.5px] text-dim">
                {report.ok
                  ? `${b.ready ?? 0} are ready; the daily cap is ${b.max_per_day ?? 0}, so the rest go out on later runs.`
                  : "The button is disabled on purpose while anything above is red."}
              </p>
            </div>
            <Button
              variant="primary"
              disabled={working || !report.ok || (b.would_send_now ?? 0) === 0}
              onClick={() => setConfirming(true)}
            >
              Send now
            </Button>
          </Card>
        </div>

        <div className="flex min-h-0 flex-col gap-3.5 overflow-y-auto pr-1.5">
          <SectionHeading aside={report.previews.length ? `· ${report.previews.length} queued` : undefined}>
            Exactly what would be sent
          </SectionHeading>
          {report.previews.length === 0 ? (
            <Empty>Nothing is queued right now.</Empty>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {report.previews.map((pv) => (
                  <button
                    key={pv.to}
                    onClick={() => setOpen(pv.to)}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 rounded-lg border bg-surface px-3.5 py-2 text-sm",
                      current?.to === pv.to ? "border-brand text-ink" : "border-line text-dim",
                    )}
                  >
                    <span className="font-mono text-[13px]">{pv.to}</span>
                    <Badge tone={pv.text_source === "fallback" ? "neutral" : "brand"}>
                      {pv.text_source || "?"}
                    </Badge>
                  </button>
                ))}
              </div>
              {current && (
                <EmailPreview
                  email={{
                    to: current.to,
                    from: current.from,
                    subject: current.subject,
                    body: current.body,
                    attachment: current.attachment,
                    unsubscribe: current.unsubscribe_header,
                  }}
                />
              )}
            </>
          )}
        </div>
      </div>

      <Modal
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Send ${b.would_send_now ?? 0} emails now`}
        description="These are real emails to real people. There is no undo."
        footer={
          <>
            <Button
              variant="primary"
              disabled={working}
              onClick={() => {
                setConfirming(false);
                void act("Send", sendBatch,
                  "Sending started. Watch it land in the Activity tab.")
                  .then(() => onRefresh());
              }}
            >
              Yes, send {b.would_send_now ?? 0}
            </Button>
            <Button variant="quiet" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </>
        }
      >
        <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[15px]">
          <li>
            <b>{Math.min(b.follow_ups_due ?? 0, b.would_send_now ?? 0)}</b> follow-ups
            to people who have not replied, and the rest first contacts. Follow-ups
            go first.
          </li>
          <li>
            About <b>{Math.round(b.minutes ?? 0)} minutes</b>, paced so they don't
            leave in a burst.
          </li>
          <li>
            <b>{b.ready ?? 0}</b> are ready in total. The rest wait because the cap
            is <b>{b.max_per_day ?? 0} a day</b> — raise{" "}
            <code className="font-mono">max_per_day</code> in{" "}
            <code className="font-mono">config.ini</code> to send more, but going
            from nothing to dozens in one day is what gets a personal address
            filtered.
          </li>
          <li className="text-dim">
            Anyone who replies should be marked in Contacts: that is what stops
            their follow-ups.
          </li>
        </ul>
      </Modal>
    </div>
  );
}
