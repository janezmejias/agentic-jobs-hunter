import type {
  ContactStatus, CronPreview, Draft, PreflightReport, Run, Schedule, ScheduleSettings,
  Send, Snapshot,
} from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data as { error?: string }).error ?? `HTTP ${r.status}`);
  return data as T;
}

export const loadSnapshot = () => request<Snapshot>("/api/state");

export const setStatus = (email: string, status: ContactStatus, note?: string) =>
  request<{ ok: boolean }>(`/api/contact/${encodeURIComponent(email)}/status`, {
    method: "POST",
    body: JSON.stringify({ status, note }),
  });

export const saveDraft = (
  email: string,
  subject: string,
  body: string,
  fingerprint: string,
) =>
  request<{ ok: boolean; exported: number }>(
    `/api/draft/${encodeURIComponent(email)}`,
    { method: "POST", body: JSON.stringify({ subject, body, fingerprint }) },
  );

export const loadPreflight = () => request<PreflightReport>("/api/preflight");

export const sendTestEmail = () =>
  request<{ ok: boolean; sent_to: string }>("/api/test-email", { method: "POST" });

export const verifyLogin = () =>
  request<{ ok: boolean }>("/api/verify-login", { method: "POST" });

export const loadDrafts = (email: string) =>
  request<{ drafts: Draft[] }>(`/api/contact/${encodeURIComponent(email)}/drafts`);

export const loadActivity = () =>
  request<{ sends: Send[]; runs: Run[] }>("/api/activity");

export const draftFollowUps = () =>
  request<{ ok: boolean; output: string }>("/api/draft-follow-ups", { method: "POST" });

export const loadSchedule = () => request<Schedule>("/api/schedule");

export const saveSchedule = (settings: Partial<ScheduleSettings>) =>
  request<Schedule & { ok: boolean }>("/api/schedule", {
    method: "POST",
    body: JSON.stringify(settings),
  });

export const startRefresh = () =>
  request<{ ok: boolean; started: boolean }>("/api/refresh", { method: "POST" });

export const previewCron = (expression: string) =>
  request<CronPreview>("/api/schedule/preview", {
    method: "POST",
    body: JSON.stringify({ expression }),
  });

export const sendBatch = (emails?: string[]) =>
  request<{ ok: boolean; started: boolean; would_send: number; picked: number }>(
    "/api/send",
    { method: "POST", body: JSON.stringify(emails ? { emails } : {}) },
  );

export const checkInbox = () =>
  request<{ ok: boolean; scanned: number; replies: string[]; bounces: string[] }>(
    "/api/inbox",
    { method: "POST" },
  );
