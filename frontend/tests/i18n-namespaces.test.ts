import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Each page ships only the message namespaces its section declares (see
 * i18n/section-messages.tsx). A client component that reads a namespace the
 * page does not ship fails at runtime with MISSING_MESSAGE, so this test
 * walks every page's import closure and compares the namespaces its client
 * components read with what the layout chain provides.
 */

const ROOT = path.resolve(import.meta.dirname, "..");
const APP = path.join(ROOT, "app");
const EXT = [".ts", ".tsx"];
const SKIPPED = /\.(test|spec)\.(ts|tsx)$/;

type Report = { page: string; declared: string[]; used: string[]; dynamic: string[] };

function resolveSpec(from: string, spec: string): string | null {
  const base = spec.startsWith("@/")
    ? path.join(ROOT, spec.slice(2))
    : spec.startsWith(".")
      ? path.resolve(path.dirname(from), spec)
      : null;
  if (!base) return null;
  if (fs.existsSync(base) && fs.statSync(base).isFile()) return base;
  for (const ext of EXT) {
    if (fs.existsSync(base + ext)) return base + ext;
    const index = path.join(base, `index${ext}`);
    if (fs.existsSync(index)) return index;
  }
  throw new Error(`Cannot resolve import ${spec} from ${path.relative(ROOT, from)}`);
}

// Runtime imports only: `import type` lines carry no code across modules.
const IMPORT_RE =
  /(^|[^\w$.])(?:import|export)\s+(type\s+)?(?:[^"'`;]*?\s+from\s+)?["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)/g;
const LITERAL_USE_RE = /useTranslations\s*(?:<[^>]*>)?\s*\(\s*(["'`])([^"'`]+)\1\s*\)/g;
const DYNAMIC_USE_RE = /useTranslations\s*(?:<[^>]*>)?\(\s*([^)"'`\s][^)]*)\)/g;
const DECLARED_RE = /namespaces=\{\[([^\]]*)\]\}/g;

function readImports(file: string): string[] {
  const specs: string[] = [];
  for (const match of fs.readFileSync(file, "utf8").matchAll(IMPORT_RE)) {
    if (!match[2]) specs.push(match[3] ?? match[4]);
  }
  return specs;
}

/** Message namespaces read by client components reachable from the entry files. */
function usedNamespaces(entryFiles: string[]): { used: Set<string>; dynamic: string[] } {
  const seen = new Set<string>();
  const used = new Set<string>();
  const dynamic: string[] = [];
  const queue = [...entryFiles];
  while (queue.length) {
    const file = queue.pop();
    if (!file || seen.has(file) || SKIPPED.test(file)) continue;
    seen.add(file);
    const source = fs.readFileSync(file, "utf8");
    for (const match of source.matchAll(LITERAL_USE_RE)) used.add(match[2]);
    for (const match of source.matchAll(DYNAMIC_USE_RE)) {
      dynamic.push(`${path.relative(ROOT, file)}: ${match[1]}`);
    }
    for (const spec of readImports(file)) {
      const resolved = resolveSpec(file, spec);
      if (resolved) queue.push(resolved);
    }
  }
  return { used, dynamic };
}

function layoutChain(page: string): string[] {
  const chain: string[] = [];
  for (let dir = path.dirname(page); ; dir = path.dirname(dir)) {
    const layout = path.join(dir, "layout.tsx");
    if (fs.existsSync(layout)) chain.push(layout);
    if (dir === APP) return chain.reverse();
  }
}

function walkPages(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walkPages(full, out);
    else if (entry.name === "page.tsx") out.push(full);
  }
  return out;
}

const reports: Report[] = walkPages(APP)
  .sort()
  .map((page) => {
    const chain = layoutChain(page);
    // SectionMessages replaces parent messages rather than merging, so the
    // innermost layout in the chain that declares SectionMessages defines the
    // namespaces shipped to client components ("common" + its list).
    let declared = new Set(["common"]);
    for (const layout of chain) {
      const matches = [...fs.readFileSync(layout, "utf8").matchAll(DECLARED_RE)];
      if (matches.length === 0) continue;
      declared = new Set(["common"]);
      for (const match of matches) {
        for (const ns of JSON.parse(`[${match[1]}]`) as string[]) declared.add(ns);
      }
    }
    const { used, dynamic } = usedNamespaces([page, ...chain]);
    return {
      page: path.relative(APP, page),
      declared: [...declared].sort(),
      used: [...used].sort(),
      dynamic,
    };
  });

describe("client message namespaces", () => {
  it("covers every page", () => {
    expect(reports.length).toBeGreaterThan(20);
  });

  it.each(reports)("ships what $page reads", ({ declared, used, dynamic }) => {
    // A namespace chosen at runtime is invisible to this check.
    expect(dynamic).toEqual([]);
    expect(used.filter((ns) => !declared.includes(ns))).toEqual([]);
  });

  it("keeps the shell at common only", () => {
    const root = usedNamespaces([path.join(APP, "layout.tsx"), path.join(APP, "error.tsx")]);
    expect([...root.used].sort()).toEqual(["common"]);
  });

  it("declares no namespace that no page below it reads", () => {
    const stale: string[] = [];
    for (const layout of walkLayouts(APP)) {
      const source = fs.readFileSync(layout, "utf8");
      for (const match of source.matchAll(DECLARED_RE)) {
        for (const ns of JSON.parse(`[${match[1]}]`) as string[]) {
          const below = reports.filter((report) =>
            layoutChain(path.join(APP, report.page)).includes(layout),
          );
          if (!below.some((report) => report.used.includes(ns))) {
            stale.push(`${path.relative(APP, layout)}: "${ns}"`);
          }
        }
      }
    }
    expect(stale).toEqual([]);
  });
});

function walkLayouts(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walkLayouts(full, out);
    else if (entry.name === "layout.tsx") out.push(full);
  }
  return out;
}
