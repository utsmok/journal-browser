import { getTranslations } from "next-intl/server";

import { GROUP_LABEL_KEYS, TABLE_GROUPS } from "@/lib/data-pipeline/table-groups";

const VIEW_W = 1000;
const VIEW_H = 650;

// Hand-positioned group boxes: [x, y, w, h] per group name.
const BOX: Record<string, { x: number; y: number; w: number; h: number }> = {
  "Journal universe": { x: 40, y: 60, w: 300, h: 142 },
  Works: { x: 620, y: 60, w: 300, h: 142 },
  "People and orgs": { x: 620, y: 300, w: 300, h: 116 },
  Deals: { x: 40, y: 300, w: 280, h: 78 },
  "Funders and policy": { x: 360, y: 470, w: 280, h: 170 },
  "Landing and bookkeeping": { x: 40, y: 430, w: 280, h: 90 },
  "Site and configuration": { x: 700, y: 470, w: 260, h: 142 },
};

function GroupBox({ name, label }: { name: string; label: string }) {
  const box = BOX[name];
  const tables = TABLE_GROUPS.find((group) => group.name === name)?.tables ?? [];
  return (
    <g key={name}>
      <rect
        x={box.x}
        y={box.y}
        width={box.w}
        height={box.h}
        rx={6}
        className="fill-[var(--card)] stroke-[var(--border)]"
      />
      <text
        x={box.x + 12}
        y={box.y + 20}
        fontSize={12}
        fontWeight={600}
        className="fill-[var(--foreground)]"
      >
        {label}
      </text>
      {tables.map((table, i) => (
        <text
          key={table}
          x={box.x + 12}
          y={box.y + 38 + i * 13}
          fontSize={10}
          className="fill-[var(--muted-foreground)] font-mono"
        >
          {table}
        </text>
      ))}
    </g>
  );
}

export async function DomainMap() {
  const t = await getTranslations("dataPipeline");
  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      className="w-full"
      role="img"
      aria-label={t("domain.ariaLabel")}
    >
      <defs>
        <marker
          id="dp-domain-arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" className="fill-[var(--muted-foreground)]" />
        </marker>
      </defs>

      {/* Works -> Journal universe */}
      <path
        d="M 620 134 L 340 134"
        fill="none"
        strokeWidth={1.5}
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text
        x={480}
        y={126}
        fontSize={10}
        textAnchor="middle"
        className="fill-[var(--muted-foreground)]"
      >
        journal_issn_l
      </text>

      {/* People and orgs <-> Works */}
      <path
        d="M 770 300 L 770 202"
        fill="none"
        strokeWidth={1.5}
        markerStart="url(#dp-domain-arrow)"
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text x={778} y={258} fontSize={10} className="fill-[var(--muted-foreground)]">
        author_works, work_pure_authors
      </text>

      {/* Deals -> Journal universe, solid FK half */}
      <path
        d="M 176 300 L 176 202"
        fill="none"
        strokeWidth={1.5}
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text x={182} y={262} fontSize={10} className="fill-[var(--muted-foreground)]">
        publisher_id
      </text>

      {/* Deals -> Journal universe, denormalized half */}
      <path
        d="M 196 300 L 196 202"
        fill="none"
        strokeWidth={1.5}
        strokeDasharray="4 3"
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text x={202} y={280} fontSize={10} className="fill-[var(--muted-foreground)]">
        deal_covered (denorm)
      </text>

      {/* Journal universe -> Landing */}
      <path
        d="M 40 150 C 24 160 24 430 40 460"
        fill="none"
        strokeWidth={1.5}
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text
        x={18}
        y={320}
        fontSize={10}
        textAnchor="middle"
        transform="rotate(-90 18 320)"
        className="fill-[var(--muted-foreground)]"
      >
        apc_evidence.source_record_id
      </text>

      {/* Works -> Landing */}
      <path
        d="M 660 202 C 660 228 645 240 620 240 L 360 240 C 342 240 340 258 340 316 L 340 436 C 340 449 332 456 320 456"
        fill="none"
        strokeWidth={1.5}
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text
        x={480}
        y={234}
        fontSize={10}
        textAnchor="middle"
        className="fill-[var(--muted-foreground)]"
      >
        first_seen_run
      </text>

      {/* Funders -> Journal universe */}
      <path
        d="M 360 520 C 340 520 335 498 335 448 L 335 236 C 335 222 331 210 322 202"
        fill="none"
        strokeWidth={1.5}
        strokeDasharray="4 3"
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text
        x={341}
        y={380}
        fontSize={10}
        textAnchor="middle"
        transform="rotate(-90 341 380)"
        className="fill-[var(--muted-foreground)]"
      >
        journals.jisc_* columns
      </text>

      {/* Works -> Funders */}
      <path
        d="M 920 190 C 948 190 948 280 948 380 L 948 430 C 948 448 930 448 900 448 L 670 448 C 652 448 640 462 640 500"
        fill="none"
        strokeWidth={1.5}
        strokeDasharray="4 3"
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text
        x={785}
        y={442}
        fontSize={10}
        textAnchor="middle"
        className="fill-[var(--muted-foreground)]"
      >
        funder_openalex_id (no FK)
      </text>

      {/* Landing internal: harvest_state -> harvest_runs */}
      <path
        d="M 40 505 C 26 505 22 500 22 496 C 22 492 26 492 40 492"
        fill="none"
        strokeWidth={1.5}
        markerEnd="url(#dp-domain-arrow)"
        className="stroke-[var(--muted-foreground)]"
      />
      <text x={52} y={517} fontSize={9} className="fill-[var(--muted-foreground)]">
        last_run_id
      </text>

      {Object.keys(BOX).map((name) => (
        <GroupBox key={name} name={name} label={t(GROUP_LABEL_KEYS[name] ?? name)} />
      ))}
    </svg>
  );
}
