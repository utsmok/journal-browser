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
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { CollaborationMapPoint } from "@/lib/api";

const SOURCE = "partners";
const HALO = "partner-halo";
const CIRCLES = "partner-circles";
const STYLE = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
} as const;
const WORKER_URL = "/maplibre-gl-worker.mjs";
const WORLD: [[number, number], [number, number]] = [
  [-168, -57],
  [178, 71],
];
const EUROPE: [[number, number], [number, number]] = [
  [-11, 35],
  [32, 62],
];
const NETHERLANDS: [[number, number], [number, number]] = [
  [3.2, 50.7],
  [7.3, 53.6],
];
const MAX_ZOOM = 12;
const CLUSTER_RADIUS = 46;
const LOAD_TIMEOUT_MS = 20_000;
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

type PartnerProperties = {
  ror: string;
  name: string;
  city: string;
  country_code: string;
  works: number;
  corresponding_works: number;
  home_corresponding_works: number;
  oa_pct: number;
  org_type: OrgType;
};

function partnerFeatures(points: CollaborationMapPoint[]) {
  return {
    type: "FeatureCollection" as const,
    features: points.map((p) => ({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [p.lng, p.lat] },
      properties: {
        ror: p.ror,
        name: p.name,
        city: p.city ?? "",
        country_code: p.country_code ?? "",
        works: p.works,
        corresponding_works: p.corresponding_works,
        home_corresponding_works: p.home_corresponding_works ?? 0,
        oa_pct: p.oa_share != null ? Math.round(p.oa_share * 100) : -1,
        org_type: orgType(p.org_type),
      } satisfies PartnerProperties,
    })),
  };
}

const CLUSTER_PROPERTIES = Object.fromEntries(
  TYPES.map((type) => [`n_${type}`, ["+", ["case", ["==", ["get", "org_type"], type], 1, 0]]]),
) as Record<string, [unknown, unknown]>;

function radiusExpression(
  points: CollaborationMapPoint[],
  min: number,
  max: number,
): ExpressionSpecification {
  const top = Math.log(points.reduce((most, p) => Math.max(most, p.works), 2));
  return ["interpolate", ["linear"], ["ln", ["get", "works"]], 0, min, top, max];
}

function tokenColor(name: string): string {
  const ctx = document.createElement("canvas").getContext("2d");
  if (!ctx) return "#000000";
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return ctx.fillStyle;
}

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

function boundsForPoints(
  points: CollaborationMapPoint[],
): [[number, number], [number, number]] | null {
  if (points.length === 0) return null;
  let minLng = Infinity;
  let maxLng = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const p of points) {
    if (p.lng < minLng) minLng = p.lng;
    if (p.lng > maxLng) maxLng = p.lng;
    if (p.lat < minLat) minLat = p.lat;
    if (p.lat > maxLat) maxLat = p.lat;
  }
  if (!Number.isFinite(minLng)) return null;
  // Pad single-point or single-city selections so fitBounds zooms cleanly.
  const padLng = maxLng - minLng < 0.05 ? 0.5 : 0;
  const padLat = maxLat - minLat < 0.05 ? 0.5 : 0;
  return [
    [minLng - padLng, minLat - padLat],
    [maxLng + padLng, maxLat + padLat],
  ];
}

export function PartnerMap({
  points,
  description,
  failedText,
  retryText,
  onSelect,
  activeTypes = [],
  onToggleType,
  autoFitKey,
}: {
  points: CollaborationMapPoint[];
  description: string;
  failedText: string;
  retryText: string;
  onSelect: (ror: string) => void;
  activeTypes?: string[];
  onToggleType?: (type: string) => void;
  /** Changes whenever narrow geographic/search filters change so the map
   * automatically fits the matching partners. */
  autoFitKey?: string;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const site = useSiteMeta();
  const format = useFormatter();
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<MapLibreMap | null>(null);
  const pointsRef = React.useRef(points);
  const onSelectRef = React.useRef(onSelect);
  const textRef = React.useRef({ t, labels, instShort: site.short });
  const markersRef = React.useRef(new Map<number, MapLibreMarker>());
  const styleRef = React.useRef<string>(STYLE.light);
  const lastFitKeyRef = React.useRef<string | undefined>(autoFitKey);
  const [dark, setDark] = React.useState<boolean | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [attempt, setAttempt] = React.useState(0);
  const [inView, setInView] = React.useState<InView>(() => countInView(points, null));

  const updateInView = React.useCallback(() => {
    setInView(countInView(pointsRef.current, mapRef.current?.getBounds() ?? null));
  }, []);

  const fitTo = React.useCallback((bounds: [[number, number], [number, number]], maxZoom = 10) => {
    mapRef.current?.fitBounds(bounds, { padding: 40, maxZoom, duration: 500 });
  }, []);

  const fitResults = React.useCallback(() => {
    const b = boundsForPoints(pointsRef.current);
    if (b) fitTo(b, 10);
    else fitTo(WORLD, 3);
  }, [fitTo]);

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
    if (autoFitKey && autoFitKey !== lastFitKeyRef.current) {
      lastFitKeyRef.current = autoFitKey;
      const b = boundsForPoints(points);
      if (b) fitTo(b, 10);
    } else if (!autoFitKey && lastFitKeyRef.current) {
      lastFitKeyRef.current = undefined;
      fitTo(WORLD, 3);
    }
  }, [points, applyPoints, autoFitKey, fitTo]);

  React.useEffect(() => {
    onSelectRef.current = onSelect;
    textRef.current = { t, labels, instShort: site.short };
  }, [onSelect, t, labels, site.short]);

  React.useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains("dark"));
    read();
    const observer = new MutationObserver(read);
    observer.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

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
    styleRef.current = document.documentElement.classList.contains("dark")
      ? STYLE.dark
      : STYLE.light;

    (async () => {
      try {
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
          maxWidth: "20rem",
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
          const { t, labels, instShort } = textRef.current;
          const place = [props.city, props.country_code ? labels.region(props.country_code) : ""]
            .filter(Boolean)
            .join(", ");
          const type = element("p", "jb-map-type");
          type.append(swatch(props.org_type), labels.orgType(props.org_type));
          const statsParts = [t("map.point", { works: props.works })];
          if (props.oa_pct >= 0) statsParts.push(t("map.oaPct", { pct: props.oa_pct }));
          const node = element("div", "space-y-0.5 text-xs");
          node.append(element("p", "font-semibold leading-snug text-sm", props.name));
          if (place) node.append(element("p", "text-[var(--muted-foreground)]", place));
          node.append(
            type,
            element("p", "tabular-nums font-medium", statsParts.join(" · ")),
            element(
              "p",
              "tabular-nums text-[var(--muted-foreground)]",
              t("map.corrMeta", {
                home: props.home_corresponding_works ?? 0,
                inst: instShort,
                partner: props.corresponding_works ?? 0,
              }),
            ),
          );
          hover.setLngLat(event.lngLat).setDOMContent(node).addTo(map);
        });
        map.on("click", CIRCLES, (event: MapLayerMouseEvent) => {
          const ror: unknown = event.features?.[0]?.properties?.ror;
          if (typeof ror === "string") onSelectRef.current(ror);
        });

        /** City-stack popup with inline search when >8 partners share a place. */
        const openList = (leaves: PartnerProperties[], at: [number, number]) => {
          const { t, labels } = textRef.current;
          leaves.sort((a, b) => b.works - a.works || a.name.localeCompare(b.name));
          const node = element("div", "jb-map-list");
          node.append(
            element("p", "jb-map-list-title", t("map.listTitle", { count: leaves.length })),
          );
          const items = element("ul", "jb-map-list-items");
          const renderRows = (query: string) => {
            items.replaceChildren();
            const q = query.trim().toLowerCase();
            const matches = q ? leaves.filter((l) => l.name.toLowerCase().includes(q)) : leaves;
            for (const leaf of matches) {
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
          };
          if (leaves.length > 8) {
            const input = element(
              "input",
              "mb-1.5 w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)]",
            );
            input.type = "search";
            input.placeholder = t("map.listFilterPlaceholder");
            input.addEventListener("input", () => renderRows(input.value));
            node.append(input);
          }
          renderRows("");
          node.append(items);
          hover.remove();
          list?.remove();
          map.easeTo({ center: at, offset: [0, -map.getContainer().clientHeight / 4] });
          list = new Popup({ offset: 22, maxWidth: "20rem", anchor: "top" })
            .setLngLat(at)
            .setDOMContent(node)
            .addTo(map);
        };

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
            if (!marker.getElement().isConnected) marker.addTo(map);
          }
          for (const id of shown) if (!next.has(id)) markers.get(id)?.remove();
          shown = next;
        };
        map.on("render", syncGroups);
        map.on("idle", syncGroups);

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

  const presetBtn =
    "min-h-11 rounded border border-[var(--border)] bg-[var(--card)]/95 px-2 py-1 text-xs font-medium text-[var(--foreground)] shadow-sm backdrop-blur-sm hover:border-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[1024px]:min-h-0";

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
          <div className="relative">
            <div ref={containerRef} className="jb-map h-[22rem] w-full sm:h-[26rem]" />
            <div className="pointer-events-auto absolute left-2.5 top-2.5 z-10 flex flex-wrap gap-1">
              <button type="button" onClick={() => fitTo(WORLD, 3)} className={presetBtn}>
                {t("map.presetWorld")}
              </button>
              <button type="button" onClick={() => fitTo(EUROPE, 5)} className={presetBtn}>
                {t("map.presetEurope")}
              </button>
              <button type="button" onClick={() => fitTo(NETHERLANDS, 8)} className={presetBtn}>
                {t("map.presetNl")}
              </button>
              {points.length > 0 && (
                <button type="button" onClick={fitResults} className={presetBtn}>
                  {t("map.presetFit")}
                </button>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-[var(--border)] bg-[var(--card)] px-3 py-2 text-xs">
            <p className="font-semibold tabular-nums" aria-live="polite">
              {t("map.inView", { count: inView.total })}
            </p>
            <ul className="flex flex-wrap items-center gap-1.5" aria-label={t("map.legend")}>
              {TYPES.filter(
                (type) => (inView.byType[type] ?? 0) > 0 || activeTypes.includes(type),
              ).map((type) => {
                const active = activeTypes.includes(type);
                return (
                  <li key={type}>
                    <button
                      type="button"
                      disabled={!onToggleType}
                      aria-pressed={active}
                      title={t("map.legendHint")}
                      onClick={() => onToggleType?.(type)}
                      className={`inline-flex min-h-11 items-center gap-1.5 rounded-full border px-2 py-0.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[1024px]:min-h-0 ${
                        active
                          ? "border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] font-medium text-[var(--primary-text)]"
                          : "border-transparent text-[var(--muted-foreground)] hover:border-[var(--border)] hover:text-[var(--foreground)]"
                      }`}
                    >
                      <span
                        aria-hidden
                        className="inline-block size-2.5 rounded-full"
                        style={{ backgroundColor: `var(--org-${type})` }}
                      />
                      <span className={active ? "" : "text-[var(--foreground)]"}>
                        {labels.orgType(type)}
                      </span>
                      <span className="tabular-nums">
                        {format.number(inView.byType[type] ?? 0)}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
