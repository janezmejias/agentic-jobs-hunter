export const STATES = [
  "new",
  "drafted",
  "sent",
  "replied",
  "dismissed",
  "bounced",
] as const;

export type ContactStatus = (typeof STATES)[number];

export interface Contact {
  email: string;
  greeting: string;
  name: string;
  company: string;
  role: string;
  reference: string;
  scope: string;
  url: string;
  source: string;
  ai_score: number;
  original_headline: string;
  description: string;
  status: ContactStatus;
  note: string;
  first_seen: string;
  updated_at: string;
  unsubscribed: boolean;
  subject: string;
  body: string;
  origin: string;
  fingerprint: string;
  sent_at: string;
  emails_sent: number;
  next_stage: number;
  follow_ups_left: number;
  due_follow_up: boolean;
}

export interface Snapshot {
  summary: Record<string, number>;
  contacts: Contact[];
  follow_up_days: number;
  max_follow_ups: number;
  due_now: number;
  awaiting_reply: number;
  last_inbox_check: string;
  last_inbox_detail: string;
}

export const LABEL: Record<ContactStatus, string> = {
  new: "New",
  drafted: "Drafted",
  sent: "Sent",
  replied: "Replied",
  dismissed: "Dismissed",
  bounced: "Bounced",
};

export type CheckLevel = "ok" | "warn" | "block";

export interface Check {
  level: CheckLevel;
  title: string;
  detail: string;
}

export interface Batch {
  follow_ups_due: number;
  recipients: number;
  unsubscribed: number;
  already_handled: number;
  blocked: number;
  ready: number;
  would_send_now: number;
  waiting_follow_up: number;
  sent_today: number;
  max_per_day: number;
  sent_24h: number;
  limit_24h: number;
  minutes: number;
}

export interface Preview {
  to: string;
  from: string;
  subject: string;
  body: string;
  attachment: string;
  unsubscribe_header: string;
  text_source: string;
}

export interface PreflightReport {
  ok: boolean;
  campaign: string;
  checks: Check[];
  batch: Partial<Batch>;
  previews: Preview[];
}

export interface Draft {
  email: string;
  fingerprint: string;
  subject: string;
  body: string;
  origin: string;
  model: string;
  created_at: string;
}

export interface Send {
  id: number;
  sent_at: string;
  email: string;
  status: string;
  detail: string;
  campaign: string;
  stage: number;
  message_id: string;
}

export interface Run {
  id: number;
  kind: string;
  trigger: string;
  started_at: string;
  finished_at: string;
  status: string;
  found: number;
  new_contacts: number;
  drafted: number;
  cost_usd: number;
  detail: string;
}

export interface ScheduleSettings {
  refresh_enabled: string;
  refresh_cron: string;
  send_enabled: string;
  send_cron: string;
  inbox_enabled: string;
  inbox_cron: string;
}

export interface JobSchedule {
  expression: string;
  enabled: boolean;
  description: string;
  error: string;
  next_runs: string[];
}

export interface CronPreview {
  valid: boolean;
  description: string;
  error: string;
  next_runs: string[];
}

export interface Schedule {
  settings: ScheduleSettings;
  jobs: Record<string, JobSchedule>;
  cron_installed: number;
  cron_lines: string[];
  cron_available: boolean;
  next_refresh: string;
  next_send: string;
  runs: Run[];
  in_progress: Run | null;
}
