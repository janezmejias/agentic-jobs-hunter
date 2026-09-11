import { useEffect, useMemo, useState } from "react";
import { previewCron } from "../api";
import type { CronPreview } from "../types";
import { cn } from "./cn";

/**
 * Builds a cron expression without hiding it.
 *
 * The presets cover what people actually want — every N minutes, hourly, daily,
 * weekly, monthly, yearly — and the raw expression stays visible and editable
 * underneath. Type something the presets can't represent and it simply switches
 * to Custom rather than fighting you.
 *
 * The preview comes from the server, which uses the same module that installs
 * the crontab entry, so what it promises is what will happen.
 */

const MODES = [
  { id: "minutes", label: "Every N minutes" },
  { id: "hourly", label: "Hourly" },
  { id: "daily", label: "Daily" },
  { id: "weekly", label: "Weekly" },
  { id: "monthly", label: "Monthly" },
  { id: "yearly", label: "Yearly" },
  { id: "custom", label: "Custom expression" },
] as const;

type Mode = (typeof MODES)[number]["id"];

const DAYS = [
  { value: "1", short: "Mon" },
  { value: "2", short: "Tue" },
  { value: "3", short: "Wed" },
  { value: "4", short: "Thu" },
  { value: "5", short: "Fri" },
  { value: "6", short: "Sat" },
  { value: "0", short: "Sun" },
];

const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

interface Shape {
  mode: Mode;
  step: string;      // every N minutes
  minute: string;
  hour: string;
  dom: string;
  month: string;
  dows: string[];
}

const NUMBER = /^\d+$/;

/** Reads an expression back into the controls, or gives up and says "custom". */
function readExpression(expression: string): Shape {
  const base: Shape = {
    mode: "custom", step: "15", minute: "0", hour: "9", dom: "1", month: "1", dows: ["1"],
  };
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return base;
  const [minute, hour, dom, month, dow] = parts;

  if (/^\*\/\d+$/.test(minute) && hour === "*" && dom === "*" && month === "*" && dow === "*")
    return { ...base, mode: "minutes", step: minute.slice(2) };
  if (NUMBER.test(minute) && hour === "*" && dom === "*" && month === "*" && dow === "*")
    return { ...base, mode: "hourly", minute };
  if (NUMBER.test(minute) && NUMBER.test(hour) && month === "*") {
    if (dom === "*" && dow === "*") return { ...base, mode: "daily", minute, hour };
    if (dom === "*" && dow.split(",").every((d) => NUMBER.test(d)))
      return { ...base, mode: "weekly", minute, hour, dows: dow.split(",") };
    if (dow === "*" && NUMBER.test(dom)) return { ...base, mode: "monthly", minute, hour, dom };
  }
  if (NUMBER.test(minute) && NUMBER.test(hour) && NUMBER.test(dom)
      && NUMBER.test(month) && dow === "*")
    return { ...base, mode: "yearly", minute, hour, dom, month };
  return base;
}

function writeExpression(s: Shape, fallback: string): string {
  const m = s.minute || "0";
  const h = s.hour || "0";
  switch (s.mode) {
    case "minutes": return `*/${s.step || "15"} * * * *`;
    case "hourly": return `${m} * * * *`;
    case "daily": return `${m} ${h} * * *`;
    case "weekly": return `${m} ${h} * * ${(s.dows.length ? s.dows : ["1"]).join(",")}`;
    case "monthly": return `${m} ${h} ${s.dom || "1"} * *`;
    case "yearly": return `${m} ${h} ${s.dom || "1"} ${s.month || "1"} *`;
    default: return fallback;
  }
}

export default function CronEditor({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (expression: string) => void;
  disabled?: boolean;
}) {
  const shape = useMemo(() => readExpression(value), [value]);
  const [preview, setPreview] = useState<CronPreview | null>(null);

  // Debounced so typing a raw expression doesn't fire a request per keystroke.
  useEffect(() => {
    const t = window.setTimeout(() => {
      void previewCron(value)
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 250);
    return () => window.clearTimeout(t);
  }, [value]);

  function update(patch: Partial<Shape>) {
    const next = { ...shape, ...patch };
    onChange(writeExpression(next, value));
  }

  const box = "rounded-lg border border-line bg-surface px-3 py-1.5 text-base text-ink disabled:opacity-45";

  return (
    <div className={cn("flex flex-col gap-3", disabled && "opacity-55")}>
      <div className="flex flex-wrap items-center gap-2.5">
        <select
          value={shape.mode}
          disabled={disabled}
          onChange={(e) => update({ mode: e.target.value as Mode })}
          className={box}
        >
          {MODES.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>

        {shape.mode === "minutes" && (
          <Row label="every">
            <select value={shape.step} disabled={disabled}
                    onChange={(e) => update({ step: e.target.value })} className={box}>
              {["1", "2", "5", "10", "15", "20", "30"].map((n) => (
                <option key={n} value={n}>{n} minutes</option>
              ))}
            </select>
          </Row>
        )}

        {shape.mode === "hourly" && (
          <Row label="at minute">
            <NumberBox value={shape.minute} min={0} max={59} disabled={disabled}
                       onChange={(v) => update({ minute: v })} />
          </Row>
        )}

        {shape.mode !== "minutes" && shape.mode !== "hourly" && shape.mode !== "custom" && (
          <Row label="at">
            <input
              type="time"
              disabled={disabled}
              value={`${shape.hour.padStart(2, "0")}:${shape.minute.padStart(2, "0")}`}
              onChange={(e) => {
                const [h, m] = e.target.value.split(":");
                update({ hour: String(Number(h)), minute: String(Number(m)) });
              }}
              className={box}
            />
          </Row>
        )}

        {shape.mode === "monthly" && (
          <Row label="on day">
            <NumberBox value={shape.dom} min={1} max={31} disabled={disabled}
                       onChange={(v) => update({ dom: v })} />
          </Row>
        )}

        {shape.mode === "yearly" && (
          <>
            <Row label="on">
              <select value={shape.month} disabled={disabled}
                      onChange={(e) => update({ month: e.target.value })} className={box}>
                {MONTHS.map((name, i) => (
                  <option key={name} value={String(i + 1)}>{name}</option>
                ))}
              </select>
            </Row>
            <NumberBox value={shape.dom} min={1} max={31} disabled={disabled}
                       onChange={(v) => update({ dom: v })} />
          </>
        )}
      </div>

      {shape.mode === "weekly" && (
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((d) => {
            const on = shape.dows.includes(d.value);
            return (
              <button
                key={d.value}
                disabled={disabled}
                onClick={() => {
                  const dows = on
                    ? shape.dows.filter((x) => x !== d.value)
                    : [...shape.dows, d.value];
                  update({ dows: dows.length ? dows : [d.value] });
                }}
                className={cn(
                  "cursor-pointer rounded-lg border px-3 py-1.5 text-sm transition-colors",
                  on ? "border-brand bg-brand/15 text-ink" : "border-line text-dim hover:border-dim",
                )}
              >
                {d.short}
              </button>
            );
          })}
        </div>
      )}

      <label className="flex flex-wrap items-center gap-2 text-[13px] text-dim">
        expression
        <input
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className={cn(
            "min-w-[220px] flex-1 rounded-lg border bg-surface px-3 py-1.5 font-mono text-[14px] text-ink",
            preview && !preview.valid ? "border-bad" : "border-line",
          )}
        />
      </label>

      {preview && (
        <div
          className={cn(
            "rounded-lg border px-3.5 py-3 text-[14px]",
            preview.valid ? "border-line bg-raised" : "border-bad bg-bad/10",
          )}
        >
          {preview.valid ? (
            <>
              <div className="text-ink">{preview.description}</div>
              {preview.next_runs.length > 0 && (
                <div className="mt-1.5 text-dim">
                  Next: {preview.next_runs.slice(0, 3).join(" · ")}
                </div>
              )}
            </>
          ) : (
            <span className="text-bad">{preview.error}</span>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-2 text-sm text-dim">
      {label}
      {children}
    </span>
  );
}

function NumberBox({
  value, min, max, disabled, onChange,
}: {
  value: string; min: number; max: number; disabled?: boolean;
  onChange: (v: string) => void;
}) {
  return (
    <input
      type="number"
      min={min}
      max={max}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-20 rounded-lg border border-line bg-surface px-3 py-1.5 text-base text-ink"
    />
  );
}
