import type { ReactNode } from "react";

/**
 * auto-FIT, not auto-fill: empty tracks collapse and the tiles that exist
 * stretch across the whole width. With auto-fill, four tiles on a wide screen
 * sit bunched at the left with eight empty columns beside them.
 */
export default function StatRow({ children }: { children: ReactNode }) {
  return (
    <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2">
      {children}
    </div>
  );
}
