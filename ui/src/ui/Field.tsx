import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { cn } from "./cn";

const BOX =
  "w-full min-w-0 rounded-lg border border-line bg-surface text-ink " +
  "px-4 py-3 text-base outline-none focus:outline-2 focus:outline-brand focus:-outline-offset-1";

function Label({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <span className="flex items-baseline gap-2 text-xs font-medium tracking-[0.06em] text-dim uppercase">
      {children}
      {note && <span className="normal-case tracking-normal">{note}</span>}
    </span>
  );
}

export function TextField({
  label,
  ...rest
}: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex w-full flex-col gap-2">
      <Label>{label}</Label>
      <input {...rest} className={BOX} />
    </label>
  );
}

export function TextArea({
  label,
  note,
  className,
  ...rest
}: { label: string; note?: ReactNode } & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <label className={cn("flex min-h-0 w-full flex-1 flex-col gap-2", className)}>
      <Label note={note}>{label}</Label>
      <textarea {...rest} className={cn(BOX, "flex-1 resize-none leading-[1.7]")} />
    </label>
  );
}
