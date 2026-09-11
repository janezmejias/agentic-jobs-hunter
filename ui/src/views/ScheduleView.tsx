import { useCallback, useEffect, useState } from "react";
import { loadSchedule, saveSchedule, startRefresh } from "../api";
import type { JobSchedule, Run, Schedule, ScheduleSettings } from "../types";
import Button from "../ui/Button";
import Badge from "../ui/Badge";
import StatTile from "../ui/StatTile";
import StatRow from "../ui/StatRow";
import Modal from "../ui/Modal";
import CronEditor from "../ui/CronEditor";
import { Card, Empty, SectionHeading } from "../ui/Card";
import { cn } from "../ui/cn";

const money = (n: number) => `$${n.toFixed(4)}`;

export default function ScheduleView({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<Schedule | null>(null);
  const [draft, setDraft] = useState<ScheduleSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [configuring, setConfiguring] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await loadSchedule();
      setData(d);
      setDraft((prev) => prev ?? d.settings);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While a run is going, keep polling so the page shows it finish.
  useEffect(() => {
    if (!data?.in_progress) return;
    const t = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(t);
  }, [data?.in_progress, refresh]);

  if (!data || !draft) return <div className="p-6"><Empty>Loading…</Empty></div>;

  const running = data.in_progress;
  const dirty = JSON.stringify(draft) !== JSON.stringify(data.settings);
  const lastRefresh = data.runs.find((r) => r.kind === "refresh" && r.status === "ok");
  const spent = data.runs.reduce((n, r) => n + (r.cost_usd || 0), 0);

  function set<K extends keyof ScheduleSettings>(key: K, value: string) {
    setDraft({ ...draft!, [key]: value });
  }

  function closeModal() {
    setDraft(data!.settings);
    setConfiguring(false);
  }

  async function onSave() {
    setBusy(true);
    setMessage("");
    try {
      const d = await saveSchedule(draft!);
      setData(d);
      setDraft(d.settings);
      setMessage("Saved. The cron entries now match what's above.");
      setConfiguring(false);
    } catch (e) {
      setMessage(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function onRunNow() {
    setBusy(true);
    setMessage("");
    try {
      await startRefresh();
      setMessage("Started. It searches, builds the list and writes the drafts — a few minutes.");
      await refresh();
      onChanged();
    } catch (e) {
      setMessage(`Failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6">
      <StatRow>
        <StatTile
          value={data.next_refresh || "off"}
          label="next search"
          tone={data.next_refresh ? "brand" : "neutral"}
        />
        <StatTile value={data.next_send || "off"} label="next send window" />
        <StatTile
          value={data.jobs.inbox?.next_runs[0] || "off"}
          label="next inbox check"
        />
        <StatTile value={lastRefresh?.started_at || "never"} label="last search" />
        <StatTile value={money(spent)} label="spent on drafting" />
      </StatRow>

      <Card className={cn("flex flex-wrap items-center gap-4 p-5", running && "border-brand bg-brand/10")}>
        <div className="min-w-[280px] flex-1">
          <strong className="text-[17px]">
            {running ? "Searching right now…" : "Search for new postings"}
          </strong>
          <p className="mt-1 text-[14px] text-dim">
            {running
              ? `Started ${running.started_at}. This page updates on its own.`
              : lastRefresh
                ? `Finds postings, builds the list and writes each email. The last run cost ${money(lastRefresh.cost_usd)} and took care of ${lastRefresh.drafted} drafts.`
                : "Finds postings, builds the list and writes each email with the model. This is the step that costs tokens."}
          </p>
        </div>
        <Button variant="primary" disabled={busy || !!running} onClick={() => void onRunNow()}>
          {running ? "Running…" : "Search now"}
        </Button>
      </Card>

      <Card className="flex flex-wrap items-start gap-4 p-5">
        <div className="min-w-[320px] flex-1 space-y-2">
          <strong className="text-[17px]">Run it automatically</strong>
          <JobLine label="Search" job={data.jobs.refresh} />
          <JobLine label="Send" job={data.jobs.send} />
          <JobLine label="Check replies" job={data.jobs.inbox} />
          <p className="m-0 text-[13px] text-dim">
            {data.cron_installed} cron {data.cron_installed === 1 ? "entry" : "entries"} installed
          </p>
        </div>
        <Button onClick={() => setConfiguring(true)}>Configure schedule</Button>
      </Card>

      {message && (
        <p className="m-0 rounded-lg border border-line bg-raised p-3.5 text-[15px]">{message}</p>
      )}

      <SectionHeading aside={data.runs.length ? `· ${data.runs.length} most recent` : undefined}>
        Run history
      </SectionHeading>
      {data.runs.length === 0 ? (
        <Empty>Nothing has run yet.</Empty>
      ) : (
        <table className="w-full max-w-[1500px] border-collapse text-[15px]">
          <thead>
            <tr className="border-b border-line text-left text-xs tracking-[0.06em] text-dim uppercase">
              <th className="py-2 pr-4 font-medium">Started</th>
              <th className="py-2 pr-4 font-medium">What</th>
              <th className="py-2 pr-4 font-medium">Trigger</th>
              <th className="py-2 pr-4 font-medium">Result</th>
              <th className="py-2 pr-4 font-medium">Cost</th>
              <th className="py-2 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => <RunRow key={r.id} run={r} />)}
          </tbody>
        </table>
      )}

      <Modal
        open={configuring}
        onClose={closeModal}
        width="max-w-4xl"
        title="Run it automatically"
        description="Any schedule cron can express. Saving rewrites only the entries this project owns; anything else in your crontab is left alone."
        footer={
          <>
            <Button variant="primary" disabled={busy || !dirty} onClick={() => void onSave()}>
              {dirty ? "Save schedule" : "Saved"}
            </Button>
            <Button variant="quiet" onClick={closeModal}>Close</Button>
            <span className="text-[13.5px] text-dim">
              {data.cron_installed} cron {data.cron_installed === 1 ? "entry" : "entries"} installed
            </span>
          </>
        }
      >
        {!data.cron_available && (
          <div className="mb-5 rounded-r-lg border-l-[3px] border-warn bg-warn/12 px-4 py-3 text-[15px]">
            cron isn't installed, so nothing can be scheduled. On Ubuntu:{" "}
            <code className="font-mono">sudo apt install cron</code>
          </div>
        )}
        <div className="flex flex-col gap-6">
          <JobEditor
            on={draft.refresh_enabled === "1"}
            onToggle={(v) => set("refresh_enabled", v ? "1" : "0")}
            title="Search for postings"
            hint="The only step that spends tokens. Daily is plenty — Hacker News posts a new thread on the 1st of the month."
            expression={draft.refresh_cron}
            onExpression={(v) => set("refresh_cron", v)}
          />
          <div className="h-px bg-line" />
          <JobEditor
            on={draft.inbox_enabled === "1"}
            onToggle={(v) => set("inbox_enabled", v ? "1" : "0")}
            title="Check the inbox for replies"
            hint="Costs nothing and touches nothing — the mailbox is opened read-only. Whoever replied or bounced drops out of the sequence, so their follow-ups stop. Run it often; it only looks at people who have not answered yet."
            expression={draft.inbox_cron}
            onExpression={(v) => set("inbox_cron", v)}
          />
          <div className="h-px bg-line" />
          <JobEditor
            on={draft.send_enabled === "1"}
            onToggle={(v) => set("send_enabled", v ? "1" : "0")}
            title="Send the day's batch"
            hint="Costs nothing. Once the daily cap is reached the later runs do nothing, so running it often is harmless."
            expression={draft.send_cron}
            onExpression={(v) => set("send_cron", v)}
          />
        </div>
      </Modal>
    </div>
  );
}

function JobLine({ label, job }: { label: string; job?: JobSchedule }) {
  if (!job) return null;
  return (
    <p className="m-0 text-[14px] text-dim">
      {label}:{" "}
      {job.enabled ? (
        <>
          <b className="text-ink">{job.description}</b>
          {job.next_runs[0] && <> · next {job.next_runs[0]}</>}
        </>
      ) : (
        <b className="text-ink">off</b>
      )}
    </p>
  );
}

function JobEditor({
  on, onToggle, title, hint, expression, onExpression,
}: {
  on: boolean;
  onToggle: (v: boolean) => void;
  title: string;
  hint: string;
  expression: string;
  onExpression: (v: string) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-4">
        <button
          onClick={() => onToggle(!on)}
          role="switch"
          aria-checked={on}
          className={cn(
            "mt-1 h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border transition-colors",
            on ? "border-brand bg-brand" : "border-line bg-raised",
          )}
        >
          <span
            className={cn(
              "block h-4 w-4 rounded-full bg-white transition-transform",
              on ? "translate-x-6" : "translate-x-1",
            )}
          />
        </button>
        <div className="flex-1">
          <div className="text-[15px] font-medium">{title}</div>
          <p className="mt-0.5 text-[13.5px] text-dim">{hint}</p>
        </div>
      </div>
      <div className="pl-15">
        <CronEditor value={expression} onChange={onExpression} disabled={!on} />
      </div>
    </div>
  );
}

function RunRow({ run }: { run: Run }) {
  return (
    <tr className="border-b border-line/60">
      <td className="py-2.5 pr-4 font-mono text-[13px] whitespace-nowrap text-dim">
        {run.started_at}
      </td>
      <td className="py-2.5 pr-4">{run.kind}</td>
      <td className="py-2.5 pr-4 text-dim">{run.trigger}</td>
      <td className="py-2.5 pr-4">
        <Badge tone={run.status === "ok" ? "brand" : run.status === "failed" ? "bad" : "warn"}>
          {run.status}
        </Badge>
      </td>
      <td className="py-2.5 pr-4 tabular-nums">{run.cost_usd ? money(run.cost_usd) : "—"}</td>
      <td className="py-2.5 text-dim">{run.detail || "—"}</td>
    </tr>
  );
}
