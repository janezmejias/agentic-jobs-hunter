import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { loadPreflight, loadSnapshot, saveDraft, setStatus } from "./api";
import type { Contact, ContactStatus, PreflightReport, Snapshot } from "./types";
import type { ViewId } from "./nav";
import AppShell from "./AppShell";
import type { NavCount } from "./AppShell";
import Button from "./ui/Button";
import { Empty } from "./ui/Card";
import PreflightView from "./views/PreflightView";
import ContactsView from "./views/ContactsView";
import FollowUpsView from "./views/FollowUpsView";
import ScheduleView from "./views/ScheduleView";
import ActivityView from "./views/ActivityView";

/**
 * The topbar used to say "Ready to send" whether or not anything could actually
 * go out. With the daily cap used up that is a lie, and the one place you look
 * first should not be the one place that misleads you.
 */
function statusLabel(report: PreflightReport | null): {
  label: string;
  tone: "brand" | "bad" | "neutral";
} {
  if (!report) return { label: "Checking…", tone: "neutral" };
  const blockers = report.checks.filter((c) => c.level === "block").length;
  if (!report.ok)
    return { label: `${blockers} blocker${blockers === 1 ? "" : "s"}`, tone: "bad" };
  const b = report.batch;
  if ((b.would_send_now ?? 0) > 0)
    return { label: `${b.would_send_now} ready to send`, tone: "brand" };
  if ((b.ready ?? 0) > 0 && (b.sent_today ?? 0) >= (b.max_per_day ?? 0))
    return { label: `Daily cap used — ${b.sent_today}/${b.max_per_day}`, tone: "neutral" };
  if ((b.ready ?? 0) > 0) return { label: `${b.ready} waiting`, tone: "neutral" };
  return { label: "Nobody due", tone: "neutral" };
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [report, setReport] = useState<PreflightReport | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const reload = useCallback(async () => {
    setBusy(true);
    try {
      const [s, p] = await Promise.all([loadSnapshot(), loadPreflight()]);
      setSnapshot(s);
      setReport(p);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  function announce(text: string) {
    setNotice(text);
    window.setTimeout(() => setNotice(""), 3000);
  }

  async function onSave(c: Contact, subject: string, body: string) {
    const r = await saveDraft(c.email, subject, body, c.fingerprint);
    await reload();
    announce(`Saved. recipients.csv regenerated (${r.exported} rows).`);
  }

  async function onMark(c: Contact, status: ContactStatus) {
    await setStatus(c.email, status);
    await reload();
    announce(
      status === "replied"
        ? `${c.email} marked as replied: dropped from the follow-up.`
        : `${c.email} → ${status}.`,
    );
  }

  if (error)
    return (
      <div className="p-14">
        <h1 className="m-0 text-2xl font-semibold">Can't reach the server</h1>
        <p className="mt-3 font-mono text-sm text-dim">{error}</p>
        <p className="mt-3 text-[15px]">
          Start it with <code className="font-mono">bash run.sh start</code>
        </p>
      </div>
    );

  const pending =
    snapshot?.contacts.filter((c) => c.status === "new" || c.status === "drafted").length ?? 0;
  const due = snapshot?.contacts.filter((c) => c.due_follow_up).length ?? 0;
  const blockers = report?.checks.filter((c) => c.level === "block").length ?? 0;

  const counts: Partial<Record<ViewId, NavCount>> = {
    preflight: { value: blockers, tone: "bad" },
    contacts: { value: pending, tone: "neutral" },
    followups: { value: due, tone: "warn" },
    activity: { value: report?.batch.sent_today ?? 0, tone: "neutral" },
  };

  const loading = <div className="p-6"><Empty>Loading…</Empty></div>;

  return (
    <AppShell
      counts={counts}
      campaign={report?.campaign ?? ""}
      status={statusLabel(report)}
      actions={
        <Button size="sm" variant="quiet" onClick={() => void reload()} disabled={busy}>
          {busy ? "Refreshing…" : "Refresh"}
        </Button>
      }
      notice={notice}
    >
      <Routes>
        <Route path="/" element={<Navigate to="/preflight" replace />} />
        <Route
          path="/preflight"
          element={<PreflightView report={report} busy={busy} onRefresh={() => void reload()} />}
        />
        {["/contacts", "/contacts/:email"].map((path) => (
          <Route
            key={path}
            path={path}
            element={
              snapshot ? (
                <ContactsView snapshot={snapshot} onSave={onSave} onMark={onMark} />
              ) : (
                loading
              )
            }
          />
        ))}
        {["/follow-ups", "/follow-ups/:email"].map((path) => (
          <Route
            key={path}
            path={path}
            element={
              snapshot ? (
                <FollowUpsView snapshot={snapshot} onMark={onMark} onChanged={() => void reload()} />
              ) : (
                loading
              )
            }
          />
        ))}
        <Route path="/schedule" element={<ScheduleView onChanged={() => void reload()} />} />
        <Route path="/activity" element={<ActivityView />} />
        <Route path="*" element={<Navigate to="/preflight" replace />} />
      </Routes>
    </AppShell>
  );
}
