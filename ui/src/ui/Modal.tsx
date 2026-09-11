import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { cn } from "./cn";

/**
 * A native <dialog>, so Esc, the backdrop and focus handling come from the
 * platform instead of being reimplemented — badly — in JavaScript.
 */
export default function Modal({
  open,
  onClose,
  title,
  description,
  footer,
  width = "max-w-3xl",
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  footer?: ReactNode;
  width?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        // Clicks land on the dialog itself only when they hit the backdrop.
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "m-auto w-[92vw] rounded-xl border border-line bg-surface p-0 text-ink",
        "backdrop:bg-black/55 backdrop:backdrop-blur-[2px]",
        width,
      )}
    >
      <div className="flex items-start justify-between gap-6 border-b border-line px-6 py-5">
        <div>
          <h2 className="m-0 text-[19px] font-semibold tracking-tight">{title}</h2>
          {description && <p className="mt-1 text-[14px] text-dim">{description}</p>}
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="cursor-pointer rounded-lg border border-transparent px-2.5 py-1 text-xl leading-none text-dim hover:border-line hover:text-ink"
        >
          ×
        </button>
      </div>
      <div className="px-6 py-5">{children}</div>
      {footer && (
        <div className="flex flex-wrap items-center gap-3 border-t border-line px-6 py-4">
          {footer}
        </div>
      )}
    </dialog>
  );
}
