import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "brand" | "warn" | "bad" | "info";

const TONE: Record<Tone, string> = {
  neutral: "border-line text-dim",
  brand: "border-brand text-brand",
  warn: "border-warn text-warn",
  bad: "border-bad text-bad",
  info: "border-sky-500/60 text-sky-500",
};

export default function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px]",
        "uppercase tracking-[0.05em] whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
