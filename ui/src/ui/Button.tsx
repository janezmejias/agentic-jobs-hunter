import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "good" | "quiet";
type Size = "md" | "sm";

const VARIANT: Record<Variant, string> = {
  primary: "bg-brand border-brand text-brand-ink hover:opacity-90",
  secondary: "bg-surface border-line text-ink hover:border-dim",
  good: "bg-surface border-brand text-brand hover:bg-brand/10",
  quiet: "bg-transparent border-transparent text-dim hover:text-ink hover:bg-raised",
};

const SIZE: Record<Size, string> = {
  md: "px-5 py-2.5 text-[15px]",
  sm: "px-3 py-1.5 text-sm",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export default function Button({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: Props) {
  return (
    <button
      {...rest}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border font-medium whitespace-nowrap",
        "transition-colors cursor-pointer",
        "disabled:opacity-45 disabled:cursor-default disabled:hover:border-line",
        VARIANT[variant],
        SIZE[size],
        className,
      )}
    />
  );
}
