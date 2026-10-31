import { ExternalLink } from "lucide-react";

/** Small external-link affordance to the author's ORCID record. */
export function OrcidLink({ orcid }: { orcid: string }) {
  return (
    <a
      href={`https://orcid.org/${orcid}`}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
      title={orcid}
      aria-label={`ORCID profile ${orcid}`}
    >
      ORCID <ExternalLink aria-hidden className="size-3.5 shrink-0" />
    </a>
  );
}
