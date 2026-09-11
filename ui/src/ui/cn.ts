/** Joins class names, dropping anything falsy. The whole conditional-class story. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
