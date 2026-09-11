import type { ViewId } from "../nav";

const PATHS: Record<ViewId, string> = {
  preflight: "M12 3l8 4v5c0 4.4-3.1 8.3-8 9-4.9-.7-8-4.6-8-9V7l8-4Zm-1.2 12.2 5-5-1.4-1.4-3.6 3.6-1.8-1.8-1.4 1.4 3.2 3.2Z",
  contacts: "M4 5h16v2H4V5Zm0 6h16v2H4v-2Zm0 6h10v2H4v-2Z",
  followups: "M12 5V2L8 6l4 4V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7Z",
  schedule: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm1-13h-2v6l5 3 1-1.7-4-2.3V7Z",
  activity: "M3 12h3l2.5-6 3 13L14 9l2 3h5v2h-6l-1-1.5L11.5 20 8.5 8 7 12H3v-2Z",
};

export default function Icon({ id, className }: { id: ViewId; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} fill="currentColor">
      <path d={PATHS[id]} />
    </svg>
  );
}
