import { cn } from "./cn";

/**
 * A filter box for a list. Kept as a primitive because both contact lists want
 * the same one, and because the clear button and the empty-state wording are
 * easy to get subtly different if each view writes its own.
 */
export default function SearchInput({
  value,
  onChange,
  placeholder,
  count,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  /** Shown when a search is active, so "3 of 43" is visible without counting rows. */
  count?: { showing: number; total: number };
  className?: string;
}) {
  const active = value.trim() !== "";
  return (
    <div className={cn("relative flex items-center", className)}>
      <svg
        viewBox="0 0 24 24"
        aria-hidden
        className="pointer-events-none absolute left-3 h-4 w-4 text-dim"
        fill="currentColor"
      >
        <path d="M10 2a8 8 0 1 0 4.9 14.3l5.4 5.4 1.4-1.4-5.4-5.4A8 8 0 0 0 10 2Zm0 2a6 6 0 1 1 0 12 6 6 0 0 1 0-12Z" />
      </svg>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        aria-label={placeholder}
        className={cn(
          "w-full rounded-lg border border-line bg-surface py-2 pl-9 text-[15px] text-ink",
          "outline-none focus:outline-2 focus:outline-brand focus:-outline-offset-1",
          active ? "pr-24" : "pr-3",
        )}
      />
      {active && (
        <div className="absolute right-2 flex items-center gap-1.5">
          {count && (
            <span className="text-xs text-dim tabular-nums">
              {count.showing}/{count.total}
            </span>
          )}
          <button
            onClick={() => onChange("")}
            aria-label="Clear the search"
            className="cursor-pointer rounded px-1.5 text-lg leading-none text-dim hover:text-ink"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
