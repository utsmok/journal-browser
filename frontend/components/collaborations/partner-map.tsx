"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import * as React from "react";
import type {
  ExpressionSpecification,
  GeoJSONSource,
  Map as MapLibreMap,
  MapLayerMouseEvent,
  StyleSpecification,
} from "maplibre-gl";

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
/** Give up waiting for the tiles after this long; the retry starts a new
 * attempt, so a slow tile host costs a click and nothing else. */
const LOAD_TIMEOUT_MS = 20_000;

type PartnerFeatures = {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: { ror: string; name: string; works: number };
  }[];
};

function partnerFeatures(points: CollaborationMapPoint[]): PartnerFeatures {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      properties: { ror: p.ror, name: p.name, works: p.works },
    })),
  };
}

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

/**
 * World map with one circle per partner. The map library loads in the browser
 * only; the partner table carries the same links for keyboard and screen
 * reader users, so a map that fails to load shows a sentence and nothing else
 * is lost.
 */
export function PartnerMap({
  points,
  description,
  pointLabel,
  failedText,
  retryText,
  onSelect,
}: {
  points: CollaborationMapPoint[];
  /** Screen reader description of what the map shows. */
  description: string;
  /** Text of the hover card for one partner: its number of shared works. */
  pointLabel: (works: number) => string;
  failedText: string;
  retryText: string;
  onSelect: (ror: string) => void;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<MapLibreMap | null>(null);
  const pointsRef = React.useRef(points);
  const onSelectRef = React.useRef(onSelect);
  const pointLabelRef = React.useRef(pointLabel);
  // The base style in use, set before the map starts and on every switch.
  const styleRef = React.useRef<string>(STYLE.light);
  // The site theme, once known.
  const [dark, setDark] = React.useState<boolean | null>(null);
  const [failed, setFailed] = React.useState(false);
  // Counts the retries of a map that did not load.
  const [attempt, setAttempt] = React.useState(0);

  /** The current partners into the loaded source. A style switch leaves a
   * moment without one, which the next style.load event covers. */
  const applyPoints = React.useCallback(() => {
    const map = mapRef.current;
    const source = map?.getSource(SOURCE) as GeoJSONSource | undefined;
    if (!map || !source) return;
    const current = pointsRef.current;
    source.setData(partnerFeatures(current));
    map.setPaintProperty(CIRCLES, "circle-radius", radiusExpression(current, 5, 22));
    map.setPaintProperty(HALO, "circle-radius", radiusExpression(current, 7, 25));
  }, []);

  React.useEffect(() => {
    pointsRef.current = points;
    applyPoints();
  }, [points, applyPoints]);

  React.useEffect(() => {
    onSelectRef.current = onSelect;
    pointLabelRef.current = pointLabel;
  }, [onSelect, pointLabel]);

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
      // The circle colours follow the theme tokens of the new theme.
      if (map.getLayer(CIRCLES)) {
        const surface = tokenColor("--card");
        map.setPaintProperty(HALO, "circle-color", surface);
        map.setPaintProperty(CIRCLES, "circle-color", tokenColor("--primary"));
        map.setPaintProperty(CIRCLES, "circle-stroke-color", surface);
      }
      applyPoints();
    });
  }, [dark, applyPoints]);

  React.useEffect(() => {
    if (failed) return;
    const container = containerRef.current;
    if (!container) return;
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
        const { Map, NavigationControl, Popup, setWorkerUrl } = await import("maplibre-gl");
        if (disposed) return;
        setWorkerUrl(WORKER_URL);
        const accent = tokenColor("--primary");
        const surface = tokenColor("--card");
        const map = new Map({
          container,
          style: styleRef.current,
          bounds: WORLD,
          fitBoundsOptions: { padding: 16 },
          attributionControl: { compact: false },
          dragRotate: false,
          pitchWithRotate: false,
        });
        mapRef.current = map;
        map.addControl(new NavigationControl({ showCompass: false }), "top-right");

        const popup = new Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 14,
          maxWidth: "18rem",
        });
        map.on("load", () => {
          window.clearTimeout(timer);
          if (map.getSource(SOURCE)) return;
          map.addSource(SOURCE, {
            type: "geojson",
            data: partnerFeatures(pointsRef.current),
          });
          // A surface-colored ring separates touching circles from each other.
          map.addLayer({
            id: HALO,
            type: "circle",
            source: SOURCE,
            paint: {
              "circle-radius": radiusExpression(pointsRef.current, 7, 25),
              "circle-color": surface,
              "circle-opacity": 0.9,
            },
          });
          map.addLayer({
            id: CIRCLES,
            type: "circle",
            source: SOURCE,
            paint: {
              "circle-radius": radiusExpression(pointsRef.current, 5, 22),
              "circle-color": accent,
              "circle-opacity": 0.85,
              "circle-stroke-color": surface,
              "circle-stroke-width": 1,
            },
          });
        });
        timer = window.setTimeout(() => {
          if (!map.getSource(SOURCE)) setFailed(true);
        }, LOAD_TIMEOUT_MS);

        map.on("mouseenter", CIRCLES, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", CIRCLES, () => {
          map.getCanvas().style.cursor = "";
          popup.remove();
        });
        map.on("mousemove", CIRCLES, (event: MapLayerMouseEvent) => {
          const ror: unknown = event.features?.[0]?.properties?.ror;
          const point = pointsRef.current.find((p) => p.ror === ror);
          if (!point) return;
          const node = document.createElement("div");
          const name = document.createElement("p");
          name.className = "font-semibold leading-snug";
          name.textContent = point.name;
          const works = document.createElement("p");
          works.className = "tabular-nums text-[var(--muted-foreground)]";
          works.textContent = pointLabelRef.current(point.works);
          node.append(name, works);
          popup.setLngLat(event.lngLat).setDOMContent(node).addTo(map);
        });
        map.on("click", CIRCLES, (event: MapLayerMouseEvent) => {
          const ror: unknown = event.features?.[0]?.properties?.ror;
          if (typeof ror === "string") onSelectRef.current(ror);
        });

        // The column can change width without a window resize.
        const observer = new ResizeObserver(() => map.resize());
        observer.observe(container);
        cleanup = () => {
          observer.disconnect();
          popup.remove();
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
  }, [failed, attempt]);

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
        <div ref={containerRef} className="jb-map h-[22rem] w-full sm:h-[26rem]" />
      )}
    </>
  );
}
