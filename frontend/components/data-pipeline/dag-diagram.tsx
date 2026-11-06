import type { SourceKey } from "@/lib/data-pipeline/dag";
import {
  DAG_BANDS,
  DAG_EDGES,
  DAG_STEPS,
  NODE_H,
  NODE_W,
  VIEW_H,
  VIEW_W,
} from "@/lib/data-pipeline/dag";

const DOT_CLASS: Record<SourceKey, string> = {
  openalex: "fill-orange-500 dark:fill-orange-400",
  crossref: "fill-sky-600 dark:fill-sky-400",
  openaire: "fill-teal-600 dark:fill-teal-400",
  pure: "fill-violet-600 dark:fill-violet-400",
  register: "fill-slate-500 dark:fill-slate-400",
  db: "",
};

const LEGEND: { label: string; className: string; hollow?: boolean }[] = [
  { label: "OpenAlex", className: DOT_CLASS.openalex },
  { label: "Crossref", className: DOT_CLASS.crossref },
  { label: "OpenAIRE", className: DOT_CLASS.openaire },
  { label: "Pure", className: DOT_CLASS.pure },
  { label: "Register or file", className: DOT_CLASS.register },
  { label: "Database-only", className: "", hollow: true },
];

function SourceDot({ source, cx, cy }: { source: SourceKey; cx: number; cy: number }) {
  if (source === "db") {
    return (
      <circle
        cx={cx}
        cy={cy}
        r={4}
        fill="none"
        strokeWidth={1.2}
        strokeDasharray="2 1.5"
        className="stroke-[var(--muted-foreground)]"
      />
    );
  }
  return <circle cx={cx} cy={cy} r={4} className={DOT_CLASS[source]} />;
}

export function DagDiagram() {
  return (
    <div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="w-full"
        role="img"
        aria-label="Bootstrap harvest DAG: global band, per-institution band, and the final embeddings step"
      >
        <defs>
          <marker
            id="dp-dag-arrow"
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

        {DAG_BANDS.map((band) => (
          <g key={band.id}>
            <rect
              x={band.x}
              y={band.y}
              width={band.w}
              height={band.h}
              rx={8}
              className="fill-[var(--muted)] opacity-40"
            />
            <text
              x={band.x + 12}
              y={band.y + 20}
              fontSize={10}
              className="fill-[var(--muted-foreground)] tracking-wide"
            >
              {band.label}
            </text>
          </g>
        ))}

        {DAG_EDGES.map((edge) => (
          <path
            key={`${edge.from}-${edge.to}`}
            d={edge.d}
            fill="none"
            strokeWidth={1.5}
            opacity={0.7}
            markerEnd="url(#dp-dag-arrow)"
            className="stroke-[var(--muted-foreground)]"
          />
        ))}

        {DAG_STEPS.map((step) => (
          <g key={step.id}>
            <rect
              x={step.x}
              y={step.y}
              width={NODE_W}
              height={NODE_H}
              rx={6}
              className="fill-[var(--card)] stroke-[var(--border)]"
            />
            {step.sources.map((source, i) => (
              <SourceDot key={source} source={source} cx={step.x + 14 + i * 13} cy={step.y + 11} />
            ))}
            <text
              x={step.x + 10}
              y={step.y + 27}
              fontSize={12.5}
              className="fill-[var(--foreground)]"
            >
              {step.label}
            </text>
            <text
              x={step.x + 10}
              y={step.y + 38}
              fontSize={10}
              className="fill-[var(--muted-foreground)]"
            >
              {step.job}
            </text>
          </g>
        ))}
      </svg>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
        {LEGEND.map((item) => (
          <span key={item.label} className="flex items-center gap-1.5">
            <svg width={12} height={12} aria-hidden>
              <circle
                cx={6}
                cy={6}
                r={4}
                fill={item.hollow ? "none" : undefined}
                strokeWidth={item.hollow ? 1.2 : undefined}
                strokeDasharray={item.hollow ? "2 1.5" : undefined}
                className={item.hollow ? "stroke-[var(--muted-foreground)]" : item.className}
              />
            </svg>
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
