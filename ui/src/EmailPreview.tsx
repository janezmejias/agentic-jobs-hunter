import type { ReactNode } from "react";
import { Card } from "./ui/Card";

/**
 * One renderer for "here is an email", used by Preflight and by Follow-ups.
 * Both need exactly this, so neither owns a copy of it.
 */
export interface EmailFields {
  to?: string;
  from?: string;
  subject: string;
  body: string;
  attachment?: string;
  unsubscribe?: string;
  extra?: Array<[string, ReactNode]>;
}

export default function EmailPreview({ email }: { email: EmailFields }) {
  const rows: Array<[string, ReactNode]> = [];
  if (email.to) rows.push(["To", <span className="font-mono text-sm">{email.to}</span>]);
  if (email.from) rows.push(["From", <span className="font-mono text-sm">{email.from}</span>]);
  rows.push(["Subject", <span className="font-semibold">{email.subject}</span>]);
  if (email.attachment !== undefined)
    rows.push(["Attachment", email.attachment || <span className="text-dim">none</span>]);
  if (email.unsubscribe !== undefined)
    rows.push([
      "Unsubscribe",
      <span className="font-mono text-sm">
        {email.unsubscribe || <span className="text-dim">no header</span>}
      </span>,
    ]);
  rows.push(...(email.extra ?? []));

  return (
    <Card className="p-5">
      <dl className="mb-4 grid grid-cols-[max-content_1fr] gap-x-5 gap-y-1.5 border-b border-line pb-4 text-[14.5px]">
        {rows.map(([k, v]) => (
          <Row key={k} label={k}>
            {v}
          </Row>
        ))}
      </dl>
      <pre className="m-0 max-w-[74ch] font-sans text-base leading-[1.7] break-words whitespace-pre-wrap">
        {email.body}
      </pre>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-dim">{label}</dt>
      <dd className="m-0 break-words">{children}</dd>
    </>
  );
}
