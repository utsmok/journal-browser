"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useFormatter, useTranslations } from "next-intl";
import * as React from "react";
import type {
  ExpressionSpecification,
  GeoJSONSource,
  LngLatBounds,
  Map as MapLibreMap,
  MapLayerMouseEvent,
  Marker as MapLibreMarker,
  Popup as MapLibrePopup,
  StyleSpecification,
} from "maplibre-gl";

import { useCollabLabels } from "@/components/collaborations/labels";
import { Button } from "@/components/ui/button";
import type { CollaborationMapPoint } from "@/lib/api";

const SOURCE = "partners";
const HALO = "partner-halo";
const CIRCLES = "partner-circles";
/** OpenFreeMap's public instance serves both styles without a key or cookies
 * (openfreemap.org); its style files carry the map attribution. */
const STYLE = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
} as const;
/** MapLibre 6 loads its worker from a file of its own. The script
 * scripts/copy-maplibre-worker.mjs copies it into public/ before every
 * build and dev start. */
const WORKER_URL = "/maplibre-gl-worker.mjs";
/** The populated land masses; the poles stay out of view. */
const WORLD: [[number, number], [number, number]] = [
  [-168, -57],
  [178, 71],
];
/** Deepest zoom, and the deepest zoom that still groups partners. Grouping
 * up to the last zoom keeps partners that share one place (ROR often gives
 * a city's coordinates) as one group that lists them, never as circles
 * drawn on top of each other. */
const MAX_ZOOM = 12;
/** Partners closer than this many pixels form one group. */
const CLUSTER_RADIUS = 46;
/** Give up waiting for the tiles after this long; the retry starts a new
 * attempt, so a slow tile host costs a click and nothing else. */
const LOAD_TIMEOUT_MS = 20_000;
/** The organisation types with a colour of their own, in legend order;
 * every other value draws in the colour of "other". */
const TYPES = [
  "education",
  "facility",
  "healthcare",
  "company",
  "government",
  "nonprofit",
  "funder",
  "archive",
  "other",
] as const;

type OrgType = (typeof TYPES)[number];

function orgType(value: string | null | undefined): OrgType {
  return (TYPES as readonly string[]).includes(value ?? "") ? (value as OrgType) : "other";
}

type PartnerProperties = { ror: string; name: string; works: number; org_type: OrgType };

function partnerFeatures(points: CollaborationMapPoint[]) {
  return {
    type: "FeatureCollection" as const,
    features: points.map((p) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [p.lng, p.lat] },
      properties: {
        ror: p.ror,
        name: p.name,
        works: p.works,
        org_type: orgType(p.org_type),
      } satisfies PartnerProperties,
    })),
  };
}

/** Per group, the number of partners of each type: `n_<type>`. */
const CLUSTER_PROPERTIES = Object.fromEntries(
  TYPES.map((type) => [`n_${type}`, ["+", ["case", ["==", ["get", "org_type"], type], 1, 0]]]),
) as Record<string, [unknown, unknown]>;

/** Circle radius follows the logarithm of the shared works: a partner with
 * the most shared works draws at `max` px, one with a single work at `min` px. */
function radiusExpression(
  points: CollaborationMapPoint[],
  min: number,
  max: number,
): ExpressionSpecification {
  const top = Math.log(points.reduce((most, p) => Math.max(most, p.works), 2));
  return ["interpolate", ["linear"], ["ln", ["get", "works"]], 0, min, top, max];
}

/** A CSS custom property as a color MapLibre accepts, whichever notation the
 * stylesheet uses for it. */
function tokenColor(name: string): string {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return "#000000";
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return ctx.fillStyle;
}

/** Paint that follows the theme tokens; set at start and on every theme
 * switch. The group markers are DOM and follow the tokens by themselves. */
function applyThemeColors(map: MapLibreMap) {
  if (!map.getLayer(CIRCLES)) return;
  const surface = tokenColor("--card");
  map.setPaintProperty(HALO, "circle-color", surface);
  map.setPaintProperty(CIRCLES, "circle-color", [
    "match",
    ["get", "org_type"],
    ...TYPES.flatMap((type) => [type, tokenColor(`--org-${type}`)]),
    tokenColor("--org-other"),
  ] as unknown as ExpressionSpecification);
  map.setPaintProperty(CIRCLES, "circle-stroke-color", surface);
}

/** The partner source and its layers of the outgoing style, added to the
 * incoming one, so a style switch keeps the partners and their data. */
function withPartners(
  previous: StyleSpecification | undefined,
  next: StyleSpecification,
): StyleSpecification {
  const source = previous?.sources[SOURCE];
  if (!source) return next;
  return {
    ...next,
    sources: { ...next.sources, [SOURCE]: source },
    layers: [
      ...next.layers,
      ...previous.layers.filter((layer) => "source" in layer && layer.source === SOURCE),
    ],
  };
}

function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function swatch(type: OrgType): HTMLSpanElement {
  const dot = element("span", "jb-map-swatch");
  dot.style.backgroundColor = `var(--org-${type})`;
  dot.setAttribute("aria-hidden", "true");
  return dot;
}

type TypeCounts = Partial<Record<OrgType, number>>;

function groupCounts(properties: Record<string, unknown>): [OrgType, number][] {
  return TYPES.map((type) => [type, Number(properties[`n_${type}`] ?? 0)] as [OrgType, number])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
}

const SVG = "http://www.w3.org/2000/svg";

/** A group marker: a ring split by organisation type around the number of
 * partners. Its size climbs with that number. */
function groupMarker(count: number, label: string, counts: [OrgType, number][]): HTMLDivElement {
  const size = count < 10 ? 30 : count < 50 ? 36 : count < 250 ? 44 : 52;
  const ring = size < 40 ? 5 : 7;
  const radius = (size - ring) / 2;
  const circumference = 2 * Math.PI * radius;
  const button = element("button", "jb-map-group");
  button.type = "button";
  button.setAttribute("aria-label", label);
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("width", String(size));
  svg.setAttribute("height", String(size));
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("aria-hidden", "true");
  const center = size / 2;
  const disc = document.createElementNS(SVG, "circle");
  disc.setAttribute("cx", String(center));
  disc.setAttribute("cy", String(center));
  disc.setAttribute("r", String(radius + ring / 2));
  disc.setAttribute("class", "jb-map-group-disc");
  svg.append(disc);
  let offset = 0;
  for (const [type, n] of counts) {
    const length = (n / count) * circumference;
    const arc = document.createElementNS(SVG, "circle");
    arc.setAttribute("cx", String(center));
    arc.setAttribute("cy", String(center));
    arc.setAttribute("r", String(radius));
    arc.setAttribute("fill", "none");
    arc.setAttribute("stroke", `var(--org-${type})`);
    arc.setAttribute("stroke-width", String(ring));
    arc.setAttribute("stroke-dasharray", `${length} ${circumference - length}`);
    arc.setAttribute("stroke-dashoffset", String(-offset));
    arc.setAttribute("transform", `rotate(-90 ${center} ${center})`);
    svg.append(arc);
    offset += length;
  }
  const text = document.createElementNS(SVG, "text");
  text.setAttribute("x", String(center));
  text.setAttribute("y", String(center));
  text.setAttribute("class", "jb-map-group-count");
  text.textContent =
    count >= 1000 ? `${(count / 1000).toFixed(count >= 10_000 ? 0 : 1)}k` : String(count);
  svg.append(text);
  button.append(svg);
  // MapLibre positions the marker element by its transform, so the button
  // that grows on hover sits inside a wrapper of its own.
  const wrapper = element("div", "");
  wrapper.append(button);
  return wrapper;
}

type InView = { total: number; byType: TypeCounts };

function countInView(points: CollaborationMapPoint[], bounds: LngLatBounds | null): InView {
  const byType: TypeCounts = {};
  let total = 0;
  for (const p of points) {
    if (bounds && !bounds.contains([p.lng, p.lat])) continue;
    const type = orgType(p.org_type);
    byType[type] = (byType[type] ?? 0) + 1;
    total += 1;
  }
  return { total, byType };
}

/**
 * World map of the partners. Each partner is a circle in the colour of its
 * organisation type, sized by shared works. Partners close together on screen
 * form a group: a ring split by type around the number of partners. Selecting
 * a group zooms in, or lists its partners when they share one place. Below the
 * map a legend counts the partners in view per type. The map library loads in
 * the browser only; the partner table carries the same links for keyboard and
 * screen reader users, so a map that fails to load shows a sentence and
 * nothing else is lost.
 */
export function PartnerMap({
  points,
  description,
  failedText,
  retryText,
  onSelect,
}: {
  points: CollaborationMapPoint[];
  /** Screen reader description of what the map shows. */
  description: string;
  failedText: string;
  retryText: string;
  onSelect: (ror: string) => void;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const format = useFormatter();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<MapLibreMap | null>(null);
  const pointsRef = React.useRef(points);
  const onSelectRef = React.useRef(onSelect);
  // The texts the map's own popups use, kept current for its event handlers.
  const textRef = React.useRef({ t, labels });
  // Group markers by group id; a new data set makes new groups.
  const markersRef = React.useRef(new Map<number, MapLibreMarker>());
  // The base style in use, set before the map starts and on every switch.
  const styleRef = React.useRef<string>(STYLE.light);
  // The site theme, once known.
  const [dark, setDark] = React.useState<boolean | null>(null);
  const [failed, setFailed] = React.useState(false);
  // Counts the retries of a map that did not load.
  const [attempt, setAttempt] = React.useState(0);
  const [inView, setInView] = React.useState<InView>(() => countInView(points, null));

  const updateInView = React.useCallback(() => {
    setInView(countInView(pointsRef.current, mapRef.current?.getBounds() ?? null));
  }, []);

  /** The current partners into the loaded source. A style switch leaves a
   * moment without one, which the next style.load event covers. */
  const applyPoints = React.useCallback(() => {
    updateInView();
    const map = mapRef.current;
    const source = map?.getSource(SOURCE) as GeoJSONSource | undefined;
    if (!map || !source) return;
    const current = pointsRef.current;
    for (const marker of markersRef.current.values()) marker.remove();
    markersRef.current.clear();
    source.setData(partnerFeatures(current));
    map.setPaintProperty(CIRCLES, "circle-radius", radiusExpression(current, 4, 15));
    map.setPaintProperty(HALO, "circle-radius", radiusExpression(current, 6, 17));
  }, [updateInView]);

  React.useEffect(() => {
    pointsRef.current = points;
    applyPoints();
  }, [points, applyPoints]);

  React.useEffect(() => {
    onSelectRef.current = onSelect;
    textRef.current = { t, labels };
  }, [onSelect, t, labels]);

  React.useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains("dark"));
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  // A theme change swaps the base style in place. The partners move along.
  // A new style may carry its own center and zoom, so the viewport the user
  // left is put back once the style has loaded.
  React.useEffect(() => {
    const map = mapRef.current;
    const style = dark ? STYLE.dark : STYLE.light;
    if (!map || dark === null || styleRef.current === style) return;
    styleRef.current = style;
    const camera = {
      center: map.getCenter(),
      zoom: map.getZoom(),
      bearing: map.getBearing(),
      pitch: map.getPitch(),
    };
    map.setStyle(style, { transformStyle: withPartners });
    map.once("style.load", () => {
      map.jumpTo(camera);
      applyThemeColors(map);
      applyPoints();
    });
  }, [dark, applyPoints]);

  React.useEffect(() => {
    if (failed) return;
    const container = containerRef.current;
    if (!container) return;
    const markers = markersRef.current;
    let disposed = false;
    let cleanup: (() => void) | undefined;
    let timer: number | undefined;
    // The theme is read from the document here, not from state: the library
    // below can finish loading after a theme toggle, and the map must start
    // in the theme of that moment.
    styleRef.current = document.documentElement.classList.contains("dark")
      ? STYLE.dark
      : STYLE.light;

    (async () => {
      try {
        // Dynamic import on purpose: maplibre-gl is a very large dependency
        // that needs WebGL, so it stays out of every other route's bundle and
        // of the server render; it loads only when a partner map is shown.
        const { Map, Marker, NavigationControl, Popup, setWorkerUrl } = await import("maplibre-gl");
        if (disposed) return;
        setWorkerUrl(WORKER_URL);
        const map = new Map({
          container,
          style: styleRef.current,
          bounds: WORLD,
          fitBoundsOptions: { padding: 16 },
          maxZoom: MAX_ZOOM,
          attributionControl: { compact: false },
          dragRotate: false,
          pitchWithRotate: false,
        });
        mapRef.current = map;
        map.addControl(new NavigationControl({ showCompass: false }), "top-right");

        const hover = new Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 16,
          maxWidth: "18rem",
        });
        let list: MapLibrePopup | null = null;
        const source = () => map.getSource(SOURCE) as GeoJSONSource;

        map.on("load", () => {
          window.clearTimeout(timer);
          if (map.getSource(SOURCE)) return;
          map.addSource(SOURCE, {
            type: "geojson",
            data: partnerFeatures(pointsRef.current),
            cluster: true,
            clusterRadius: CLUSTER_RADIUS,
            clusterMaxZoom: MAX_ZOOM,
            clusterProperties: CLUSTER_PROPERTIES,
          });
          const partner: ExpressionSpecification = ["!", ["has", "point_count"]];
          // A surface-colored ring separates touching circles from each other.
          map.addLayer({
            id: HALO,
            type: "circle",
            source: SOURCE,
            filter: partner,
            paint: {
              "circle-radius": radiusExpression(pointsRef.current, 6, 17),
              "circle-opacity": 0.9,
            },
          });
          map.addLayer({
            id: CIRCLES,
            type: "circle",
            source: SOURCE,
            filter: partner,
            paint: {
              "circle-radius": radiusExpression(pointsRef.current, 4, 15),
              "circle-opacity": 0.9,
              "circle-stroke-width": 1,
            },
          });
          applyThemeColors(map);
          updateInView();
        });
        timer = window.setTimeout(() => {
          if (!map.getSource(SOURCE)) setFailed(true);
        }, LOAD_TIMEOUT_MS);
        map.on("moveend", updateInView);
        // A group under the pointer can vanish while the map moves, and its
        // card would stay behind.
        map.on("movestart", () => hover.remove());

        map.on("mouseenter", CIRCLES, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", CIRCLES, () => {
          map.getCanvas().style.cursor = "";
          hover.remove();
        });
        map.on("mousemove", CIRCLES, (event: MapLayerMouseEvent) => {
          const props = event.features?.[0]?.properties as PartnerProperties | undefined;
          if (!props) return;
          const { t, labels } = textRef.current;
          const type = element("p", "jb-map-type");
          type.append(swatch(props.org_type), labels.orgType(props.org_type));
          const node = element("div", "space-y-0.5");
          node.append(
            element("p", "font-semibold leading-snug", props.name),
            type,
            element(
              "p",
              "tabular-nums text-[var(--muted-foreground)]",
              t("map.point", { works: props.works }),
            ),
          );
          hover.setLngLat(event.lngLat).setDOMContent(node).addTo(map);
        });
        map.on("click", CIRCLES, (event: MapLayerMouseEvent) => {
          const ror: unknown = event.features?.[0]?.properties?.ror;
          if (typeof ror === "string") onSelectRef.current(ror);
        });

        /** The partners of one group in a popup, most shared works first. */
        const openList = (leaves: PartnerProperties[], at: [number, number]) => {
          const { t, labels } = textRef.current;
          leaves.sort((a, b) => b.works - a.works || a.name.localeCompare(b.name));
          const node = element("div", "jb-map-list");
          node.append(
            element("p", "jb-map-list-title", t("map.listTitle", { count: leaves.length })),
          );
          const items = element("ul", "jb-map-list-items");
          for (const leaf of leaves) {
            const item = element("li", "");
            const button = element("button", "jb-map-list-item");
            button.type = "button";
            button.title = labels.orgType(leaf.org_type);
            button.append(
              swatch(leaf.org_type),
              element("span", "jb-map-list-name", leaf.name),
              element("span", "jb-map-list-works", t("map.works", { works: leaf.works })),
            );
            button.addEventListener("click", () => onSelectRef.current(leaf.ror));
            item.append(button);
            items.append(item);
          }
          node.append(items);
          hover.remove();
          list?.remove();
          // The group moves to the upper part of the map, so the list below
          // it has room.
          map.easeTo({ center: at, offset: [0, -map.getContainer().clientHeight / 4] });
          list = new Popup({ offset: 22, maxWidth: "20rem", anchor: "top" })
            .setLngLat(at)
            .setDOMContent(node)
            .addTo(map);
        };

        /** Zoom to the extent of a group's partners, or list them when they
         * share one place or the map cannot zoom further. */
        const openGroup = async (id: number, count: number, at: [number, number]) => {
          try {
            const zoom = await source().getClusterExpansionZoom(id);
            const leaves = await source().getClusterLeaves(id, count, 0);
            const coords = leaves.flatMap((leaf) =>
              leaf.geometry.type === "Point" ? [leaf.geometry.coordinates] : [],
            );
            const places = new Set(coords.map((c) => c.join(",")));
            if (zoom > MAX_ZOOM || map.getZoom() >= MAX_ZOOM || places.size === 1) {
              openList(
                leaves.map((leaf) => leaf.properties as PartnerProperties),
                at,
              );
              return;
            }
            const lngs = coords.map((c) => c[0]);
            const lats = coords.map((c) => c[1]);
            map.fitBounds(
              [
                [Math.min(...lngs), Math.min(...lats)],
                [Math.max(...lngs), Math.max(...lats)],
              ],
              { padding: 48, maxZoom: MAX_ZOOM },
            );
          } catch (error) {
            console.error("Partner group failed to open", error);
          }
        };

        /** The breakdown of a group by type, for its hover card. */
        const groupCard = (count: number, counts: [OrgType, number][]) => {
          const { t, labels } = textRef.current;
          const node = element("div", "space-y-1");
          node.append(element("p", "font-semibold tabular-nums", t("map.group", { count })));
          const rows = element("ul", "space-y-0.5");
          for (const [type, n] of counts) {
            const row = element("li", "jb-map-type");
            row.append(
              swatch(type),
              element("span", "flex-1", labels.orgType(type)),
              element("span", "tabular-nums text-[var(--muted-foreground)]", String(n)),
            );
            rows.append(row);
          }
          node.append(rows, element("p", "text-[var(--muted-foreground)]", t("map.groupHint")));
          return node;
        };

        /** One DOM marker per group on screen; groups change with the zoom. */
        let shown = new Set<number>();
        const syncGroups = () => {
          if (!map.getSource(SOURCE) || !map.isSourceLoaded(SOURCE)) return;
          const next = new Set<number>();
          for (const feature of map.querySourceFeatures(SOURCE)) {
            const props = feature.properties;
            if (!props?.cluster || feature.geometry.type !== "Point") continue;
            const id = Number(props.cluster_id);
            if (next.has(id)) continue;
            next.add(id);
            let marker = markers.get(id);
            if (!marker) {
              const count = Number(props.point_count);
              const counts = groupCounts(props);
              const at = feature.geometry.coordinates as [number, number];
              const node = groupMarker(count, textRef.current.t("map.group", { count }), counts);
              node.addEventListener("mouseenter", () => {
                hover.setLngLat(at).setDOMContent(groupCard(count, counts)).addTo(map);
              });
              node.addEventListener("mouseleave", () => hover.remove());
              node.addEventListener("click", (event) => {
                event.stopPropagation();
                void openGroup(id, count, at);
              });
              marker = new Marker({ element: node }).setLngLat(at);
              markers.set(id, marker);
            }
            // A new data set or style removes every marker; put it back.
            if (!marker.getElement().isConnected) marker.addTo(map);
          }
          for (const id of shown) if (!next.has(id)) markers.get(id)?.remove();
          shown = next;
        };
        map.on("render", syncGroups);
        // The last render can come before the source has its groups ready;
        // idle follows once everything has loaded.
        map.on("idle", syncGroups);

        // The column can change width without a window resize.
        const observer = new ResizeObserver(() => map.resize());
        observer.observe(container);
        cleanup = () => {
          observer.disconnect();
          hover.remove();
          list?.remove();
          for (const marker of markers.values()) marker.remove();
          markers.clear();
          map.remove();
          mapRef.current = null;
        };
      } catch (error) {
        console.error("Partner map failed to start", error);
        setFailed(true);
      }
    })();

    return () => {
      disposed = true;
      window.clearTimeout(timer);
      cleanup?.();
    };
  }, [failed, attempt, updateInView]);

  return (
    <>
      <p className="sr-only">{description}</p>
      {failed ? (
        <div className="flex h-[22rem] flex-col items-center justify-center gap-3 px-6 text-center text-sm sm:h-[26rem]">
          <p role="status">{failedText}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setFailed(false);
              setAttempt((n) => n + 1);
            }}
          >
            {retryText}
          </Button>
        </div>
      ) : (
        <>
          <div ref={containerRef} className="jb-map h-[22rem] w-full sm:h-[26rem]" />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs">
            <p className="font-semibold tabular-nums" aria-live="polite">
              {t("map.inView", { count: inView.total })}
            </p>
            <ul
              className="flex flex-wrap items-center gap-x-3 gap-y-1"
              aria-label={t("map.legend")}
            >
              {TYPES.filter((type) => (inView.byType[type] ?? 0) > 0).map((type) => (
                <li key={type} className="flex items-center gap-1.5 text-[var(--muted-foreground)]">
                  <span
                    aria-hidden
                    className="inline-block size-2.5 rounded-full"
                    style={{ backgroundColor: `var(--org-${type})` }}
                  />
                  <span className="text-[var(--foreground)]">{labels.orgType(type)}</span>
                  <span className="tabular-nums">{format.number(inView.byType[type] ?? 0)}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
