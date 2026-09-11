import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { VIEWS } from "./nav";
import type { ViewId } from "./nav";
import Icon from "./ui/Icon";
import { cn } from "./ui/cn";

export interface NavCount {
  value: number;
  tone: "neutral" | "brand" | "warn" | "bad";
}

const COUNT_TONE: Record<NavCount["tone"], string> = {
  neutral: "border-line text-dim",
  brand: "border-brand text-brand",
  warn: "border-warn text-warn",
  bad: "border-bad text-bad",
};

interface Props {
  counts: Partial<Record<ViewId, NavCount>>;
  campaign: string;
  status: { label: string; tone: "brand" | "bad" | "neutral" };
  actions?: ReactNode;
  notice?: string;
  children: ReactNode;
}

export default function AppShell({ counts, campaign, status, actions, notice, children }: Props) {
  const statusTone =
    status.tone === "brand"
      ? "border-brand text-brand bg-brand/10"
      : status.tone === "bad"
        ? "border-bad text-bad bg-bad/10"
        : "border-line text-dim";

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-16 flex-shrink-0 items-center gap-5 border-b border-line bg-surface px-6">
        <span className="text-[17px] font-semibold tracking-tight">Job pipeline</span>
        <span className={cn("rounded-full border px-3 py-1 text-[13px] font-medium", statusTone)}>
          {status.label}
        </span>
        <span className="font-mono text-[13px] text-dim">campaign: {campaign || "unnamed"}</span>
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-60 flex-shrink-0 flex-col gap-1 border-r border-line bg-surface p-3">
          {VIEWS.map((v) => {
            const count = counts[v.id];
            return (
              <NavLink
                key={v.id}
                to={v.path}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-left no-underline transition-colors",
                    isActive ? "bg-brand/12 text-ink" : "text-dim hover:bg-raised hover:text-ink",
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <Icon
                      id={v.id}
                      className={cn("h-[18px] w-[18px] flex-shrink-0", isActive && "text-brand")}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[15px] font-medium">{v.label}</span>
                      <span className="block truncate text-xs text-dim">{v.hint}</span>
                    </span>
                    {count && count.value > 0 && (
                      <span
                        className={cn(
                          "rounded-md border px-1.5 py-0.5 text-xs tabular-nums",
                          COUNT_TONE[count.tone],
                        )}
                      >
                        {count.value}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            );
          })}
        </nav>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {notice && (
            <div className="flex-shrink-0 border-b border-line bg-brand/12 px-6 py-2.5 text-[15px] text-brand">
              {notice}
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
