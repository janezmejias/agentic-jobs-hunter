import { useEffect, useMemo, useState } from "react";
import { loadActivity } from "../api";
import type { Run, Send } from "../types";
import Badge from "../ui/Badge";
import { Empty, SectionHeading } from "../ui/Card";

const SEND_TONE: Record<string, "brand" | "bad" | "warn" | "neutral"> = {
  sent: "brand",
  refused: "bad",
  error: "bad",
  gmail_throttled: "warn",
};

const RUN_WORDS: Record<string, string> = {
  refresh: "searched for postings",
  send: "sent the batch",
  inbox: "checked the inbox",
};

interface Entry {
  at: string;
  kind: "send" | "run";
  what: string;
  who: string;
  tone: "brand" | "bad" | "warn" | "neutral";
  label: string;
  detail: string;
}

/**
 * Sends and runs in one timeline. Split across two screens, "why did nothing go
 * out at 10?" was a question you had to answer by correlating two lists.
 */
export default function ActivityView() {
  const [data, setData] = useState<{ sends: Send[]; runs: Run[] } | null>(null);

  useEffect(() => {
    void loadActivity()
      .then(setData)
      .catch(() => setData({ sends: [], runs: [] }));
  }, []);

  const entries = useMemo<Entry[]>(() => {
    if (!data) return [];
    const fromSends: Entry[] = data.sends.map((s) => ({
      at: s.sent_at,
      kind: "send",
      what: s.stage > 0 ? `follow-up ${s.stage}` : "first contact",
      who: s.email,
      tone: SEND_TONE[s.status] ?? "neutral",
      label: s.status,
      detail: s.detail || "",
    }));
    const fromRuns: Entry[] = data.runs.map((r) => ({
      at: r.started_at,
      kind: "run",
      what: RUN_WORDS[r.kind] ?? r.kind,
      who: r.trigger === "cron" ? "on schedule" : `you, from the ${r.trigger}`,
      tone: r.status === "ok" ? "neutral" : r.status === "failed" ? "bad" : "warn",
      label: r.status,
      detail: [r.cost_usd ? `$${r.cost_usd.toFixed(4)}` : "", r.detail]
        .filter(Boolean)
        .join(" · "),
    }));
    return [...fromSends, ...fromRuns].sort((a, z) => z.at.localeCompare(a.at));
  }, [data]);

  if (!data) return <div className="p-6"><Empty>Loading…</Empty></div>;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
      <SectionHeading aside={entries.length ? `· ${entries.length} most recent` : undefined}>
        Everything that has happened
      </SectionHeading>
      {entries.length === 0 ? (
        <Empty>Nothing yet. This fills in as searches, checks and batches run.</Empty>
      ) : (
        <table className="w-full max-w-[1500px] border-collapse text-[15px]">
          <thead>
            <tr className="border-b border-line text-left text-xs tracking-[0.06em] text-dim uppercase">
              <th className="py-2 pr-4 font-medium">When</th>
              <th className="py-2 pr-4 font-medium">What</th>
              <th className="py-2 pr-4 font-medium">Who</th>
              <th className="py-2 pr-4 font-medium">Result</th>
              <th className="py-2 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e, i) => (
              <tr
                key={`${e.at}-${e.who}-${i}`}
                className={e.kind === "run" ? "border-b border-line/60 bg-raised/40" : "border-b border-line/60"}
              >
                <td className="py-2.5 pr-4 font-mono text-[13px] whitespace-nowrap text-dim">
                  {e.at}
                </td>
                <td className="py-2.5 pr-4">{e.what}</td>
                <td className={e.kind === "send" ? "py-2.5 pr-4 font-mono text-[13px]" : "py-2.5 pr-4 text-dim"}>
                  {e.who}
                </td>
                <td className="py-2.5 pr-4">
                  <Badge tone={e.tone}>{e.label}</Badge>
                </td>
                <td className="py-2.5 text-dim">{e.detail || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
