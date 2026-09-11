import type { Contact, ContactStatus } from "./types";
import { LABEL } from "./types";
import Badge from "./ui/Badge";
import { Empty } from "./ui/Card";
import { cn } from "./ui/cn";

const DOT: Record<ContactStatus, string> = {
  new: "bg-dim",
  drafted: "bg-sky-500",
  sent: "bg-brand",
  replied: "bg-amber-500",
  dismissed: "bg-dim",
  bounced: "bg-bad",
};

/** The left-hand contact list. Contacts and Follow-ups both need it. */
export default function ContactList({
  contacts,
  selected,
  onSelect,
  empty,
  meta,
  picked,
  onPick,
  className,
}: {
  contacts: Contact[];
  selected: string | null;
  onSelect: (email: string) => void;
  empty: string;
  meta?: (c: Contact) => React.ReactNode;
  /** When given, every row gets a checkbox for picking who to send to. */
  picked?: Set<string>;
  onPick?: (email: string, on: boolean) => void;
  /** Overrides the default sizing when the caller wraps the list in its own column. */
  className?: string;
}) {
  return (
    <nav
      className={cn(
        "overflow-y-auto bg-surface",
        className ?? "w-[30%] max-w-[440px] min-w-[300px] flex-shrink-0 border-r border-line",
      )}
    >
      {contacts.length === 0 ? (
        <div className="p-5">
          <Empty>{empty}</Empty>
        </div>
      ) : (
        contacts.map((c) => (
          <div
            key={c.email}
            className={cn(
              "flex items-start border-b border-line transition-colors",
              selected === c.email ? "bg-brand/12" : "hover:bg-raised",
            )}
          >
            {onPick && (
              // Outside the button: a checkbox nested in a button is invalid
              // markup and the click would fight the row selection.
              <label className="flex cursor-pointer items-start py-4 pr-1 pl-3">
                <input
                  type="checkbox"
                  checked={picked?.has(c.email) ?? false}
                  onChange={(e) => onPick(c.email, e.target.checked)}
                  className="h-4 w-4 cursor-pointer accent-[var(--brand)]"
                  aria-label={`Pick ${c.email}`}
                />
              </label>
            )}
            <button
              onClick={() => onSelect(c.email)}
              className="min-w-0 flex-1 cursor-pointer px-4 py-3.5 text-left"
            >
              <div className="flex items-center justify-between gap-2.5">
                <span className="truncate font-semibold">{c.company || c.email}</span>
                <span
                  className={cn("h-2.5 w-2.5 flex-shrink-0 rounded-full", DOT[c.status])}
                  title={LABEL[c.status]}
                />
              </div>
              <div className="mt-0.5 truncate text-[14.5px] text-dim">
                {c.role || c.reference}
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-dim">
                <span className="truncate font-mono text-[13px]">{c.email}</span>
                {meta ? meta(c) : null}
              </div>
            </button>
          </div>
        ))
      )}
    </nav>
  );
}

export function OriginBadge({ origin }: { origin: string }) {
  if (!origin) return null;
  if (origin === "edited") return <Badge tone="brand">edited</Badge>;
  if (origin === "fallback") return <Badge>fallback</Badge>;
  if (origin === "ai-follow-up") return <Badge tone="info">follow-up</Badge>;
  return <Badge tone="brand">ai</Badge>;
}
