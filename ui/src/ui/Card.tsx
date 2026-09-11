import type { ReactNode } from "react";
import { cn } from "./cn";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-xl border border-line bg-surface", className)}>
      {children}
    </div>
  );
}

export function SectionHeading({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="flex items-baseline gap-2 text-xs font-semibold tracking-[0.08em] text-dim uppercase">
      {children}
      {aside && <span className="font-normal normal-case tracking-normal">{aside}</span>}
    </h3>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[15px] text-dim">{children}</p>;
}
