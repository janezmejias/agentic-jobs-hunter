import { cn } from "./cn";

export default function StatTile({
  value,
  label,
  tone = "neutral",
}: {
  value: number | string;
  label: string;
  tone?: "neutral" | "brand" | "bad";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-surface px-3.5 py-2.5",
        tone === "brand" && "border-brand",
        tone === "bad" && "border-bad",
        tone === "neutral" && "border-line",
      )}
    >
      <b
        className={cn(
          "block text-2xl leading-tight font-semibold tracking-tight",
          tone === "brand" && "text-brand",
          tone === "bad" && "text-bad",
        )}
      >
        {value}
      </b>
      <span className="text-[12.5px] text-dim">{label}</span>
    </div>
  );
}
