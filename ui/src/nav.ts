/** The sidebar and the routes are generated from this list. One source. */
export const VIEWS = [
  { id: "preflight", path: "/preflight", label: "Preflight", hint: "Check before you send" },
  { id: "contacts", path: "/contacts", label: "Contacts", hint: "Review and edit drafts" },
  { id: "followups", path: "/follow-ups", label: "Follow-ups", hint: "The second email" },
  { id: "schedule", path: "/schedule", label: "Schedule", hint: "When it runs, what it costs" },
  { id: "activity", path: "/activity", label: "Activity", hint: "What has gone out" },
] as const;

export type ViewId = (typeof VIEWS)[number]["id"];
