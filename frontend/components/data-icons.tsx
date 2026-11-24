import type * as React from "react";

export type LockState = "closed" | "ajar" | "open" | "wide";

const SHACKLE_TRANSFORM: Record<LockState, string | undefined> = {
  closed: undefined,
  ajar: "translate(0 0.4) rotate(-12 3 6.6)",
  open: "translate(0 0.7) rotate(-25 3 6.6)",
  wide: "translate(0 1.3) rotate(-42 3 6.6)",
};

const SHACKLE_POSE: Record<LockState, { rot: string; ty: string; d: string }> = {
  closed: { rot: "0deg", ty: "0px", d: "0s" },
  ajar: { rot: "-12deg", ty: "0.4px", d: "-1.4s" },
  open: { rot: "-25deg", ty: "0.7px", d: "-2.8s" },
  wide: { rot: "-42deg", ty: "1.3px", d: "-4.2s" },
};

/** Icon-only access-type colors, shared across badges, filters, and detail views. */
export const ACCESS_TEXT = {
  gold: "text-(--oa-gold)",
  diamond: "text-(--oa-diamond)",
  generic: "text-(--oa-generic)",
  hybrid: "text-(--oa-hybrid)",
  closed: "text-(--oa-closed)",
  deal: "text-emerald-700 dark:text-emerald-300",
  doaj: "text-teal-700 dark:text-teal-300",
  brand: "text-[var(--primary-text)]",
} as const;

function sparklePath(cx: number, cy: number, r: number) {
  return (
    `M${cx} ${cy - r} Q${cx} ${cy} ${cx + r} ${cy} Q${cx} ${cy} ${cx} ${cy + r}` +
    ` Q${cx} ${cy} ${cx - r} ${cy} Q${cx} ${cy} ${cx} ${cy - r}Z`
  );
}

const SPARKLES: Record<LockState, [number, number, number][]> = {
  closed: [],
  ajar: [[12.6, 3.4, 1.1]],
  open: [
    [12.8, 2.2, 1.2],
    [11.0, 4.6, 0.8],
  ],
  wide: [
    [12.9, 1.8, 1.4],
    [10.9, 3.4, 0.9],
    [12.9, 5.6, 0.8],
  ],
};

/** Small standalone wrapper to render any data glyph inside KPI tiles or pills. */
export function DataIcon({
  children,
  className = "size-3.5 shrink-0",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden focusable="false">
      {children}
    </svg>
  );
}

export function LockIcon({ state }: { state: LockState }) {
  const pose = SHACKLE_POSE[state];
  return (
    <>
      <rect x={1} y={7} width={10} height={7} rx={1.8} fill="currentColor" />
      <g
        className={`jb-shackle${state === "closed" ? " jb-shackle-locked" : ""}`}
        style={{ "--rot": pose.rot, "--ty": pose.ty, "--d": pose.d } as React.CSSProperties}
      >
        <path
          d="M3 6.6 V4.2 a3 3 0 0 1 6 0 V6.6"
          transform={SHACKLE_TRANSFORM[state]}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
        />
      </g>
      {SPARKLES[state].map(([cx, cy, r], i) => (
        <path
          key={`${cx},${cy}`}
          className="jb-sparkle"
          style={
            {
              "--d": pose.d,
              animationDelay: `calc(${pose.d} - ${i * 0.05}s)`,
            } as React.CSSProperties
          }
          d={sparklePath(cx, cy, r)}
          fill="currentColor"
        />
      ))}
    </>
  );
}

/** Author copy in a repository: document tray with an arrow dropping in. */
export function GreenGlyph() {
  return (
    <>
      <path
        d="M2 10.5 V12.6 a1.4 1.4 0 0 0 1.4 1.4 h7.2 a1.4 1.4 0 0 0 1.4 -1.4 V10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 3 V9.5 M4.5 7 L7 9.5 L9.5 7"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  );
}

/** Free to read at the publisher: an eye. */
export function BronzeGlyph() {
  return (
    <>
      <path
        d="M1 8 C3 4.5 5 3 7 3 C9 3 11 4.5 13 8 C11 11.5 9 13 7 13 C5 13 3 11.5 1 8 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinejoin="round"
      />
      <circle cx={7} cy={8} r={2} fill="currentColor" />
    </>
  );
}

/** UT open access deal: signed agreement with a check. */
export function DealGlyph() {
  return (
    <>
      <rect
        x={1.6}
        y={2.6}
        width={9.4}
        height={11}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path
        d="M4.2 8.2 L6.1 10.1 L9.4 5.9"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  );
}

/** No deal: the agreement document with a slash through it. */
export function NoDealGlyph() {
  return (
    <>
      <rect
        x={1.6}
        y={2.6}
        width={9.4}
        height={11}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path
        d="M3.8 4.4 L9.8 13.2"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
    </>
  );
}

/** Journal rank podium: ascending bars. */
export function QuartileGlyph() {
  return (
    <>
      <rect x={1.2} y={9.8} width={2.8} height={4.2} rx={1} fill="currentColor" />
      <rect x={5.1} y={7.4} width={2.8} height={6.6} rx={1} fill="currentColor" />
      <rect x={9} y={4.6} width={2.8} height={9.4} rx={1} fill="currentColor" />
    </>
  );
}

/** DOAJ: the directory volume it is registered in. */
export function DoajGlyph() {
  return (
    <>
      <rect
        x={2.2}
        y={2.2}
        width={9.6}
        height={11.6}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path d="M5.4 2.2 V13.8" stroke="currentColor" strokeWidth={1.8} />
    </>
  );
}

/** APC: the fee note. */
export function ApcGlyph() {
  return (
    <>
      <rect
        x={1.2}
        y={4.6}
        width={13.6}
        height={6.8}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <circle cx={8} cy={8} r={1.7} fill="currentColor" />
    </>
  );
}

/** Works / publications sheet. */
export function WorksGlyph() {
  return (
    <>
      <rect
        x={2.8}
        y={1.6}
        width={10.4}
        height={12.8}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path
        d="M5.6 5.4h4.8M5.6 8h4.8M5.6 10.6h3"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
    </>
  );
}
