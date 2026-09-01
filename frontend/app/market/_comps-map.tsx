"use client";

/**
 * Dubai comparable-transactions map.
 *
 * Leaflet + OpenStreetMap tiles (free, no access token — the Mapbox token this
 * project used to reference was never actually used) plotting Dubai Land
 * Department transaction data. DLD publishes this as free open data via Dubai
 * Pulse, which makes it the one genuinely unrestricted market-data source
 * available here — unlike portal listing data, which is contractually fenced.
 *
 * Split into its own client component and loaded with ssr:false because
 * Leaflet touches `window` at import time.
 */

import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import type { Community, DldTransaction } from "@/lib/api";

const DUBAI_CENTER: [number, number] = [25.12, 55.2];

/** Colour a transaction by price-per-sqft relative to the citywide spread. */
function ppsfColor(ppsf: number | null | undefined, low: number, high: number): string {
  if (!ppsf) return "#9ca3af";
  const t = Math.min(Math.max((ppsf - low) / Math.max(high - low, 1), 0), 1);
  // teal (cheap) -> amber (mid) -> rose (expensive)
  if (t < 0.5) {
    const k = t / 0.5;
    return `rgb(${Math.round(20 + k * 225)}, ${Math.round(184 - k * 26)}, ${Math.round(166 - k * 155)})`;
  }
  const k = (t - 0.5) / 0.5;
  return `rgb(${Math.round(245 - k * 20)}, ${Math.round(158 - k * 95)}, ${Math.round(11 + k * 118)})`;
}

export function CompsMap({
  transactions,
  communities,
  selectedArea,
}: {
  transactions: DldTransaction[];
  communities: Community[];
  selectedArea: string | null;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const { low, high } = useMemo(() => {
    const values = transactions
      .map((t) => t.price_per_sqft)
      .filter((v): v is number => typeof v === "number")
      .sort((a, b) => a - b);
    if (values.length === 0) return { low: 0, high: 1 };
    // Trim the tails so a single outlier doesn't flatten the whole scale.
    return {
      low: values[Math.floor(values.length * 0.05)],
      high: values[Math.floor(values.length * 0.95)],
    };
  }, [transactions]);

  const center = useMemo<[number, number]>(() => {
    if (selectedArea) {
      const match = communities.find((c) => c.name === selectedArea);
      if (match) return [match.lat, match.lng];
    }
    return DUBAI_CENTER;
  }, [selectedArea, communities]);

  if (!mounted) {
    return (
      <div className="h-full w-full bg-gray-100 animate-pulse rounded-2xl" />
    );
  }

  return (
    <MapContainer
      key={selectedArea ?? "all"}
      center={center}
      zoom={selectedArea ? 13 : 11}
      scrollWheelZoom
      className="h-full w-full rounded-2xl"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {transactions.map((t) =>
        t.lat && t.lng ? (
          <CircleMarker
            key={t.transaction_id}
            center={[t.lat, t.lng]}
            radius={5}
            pathOptions={{
              color: ppsfColor(t.price_per_sqft, low, high),
              fillColor: ppsfColor(t.price_per_sqft, low, high),
              fillOpacity: 0.72,
              weight: 1,
            }}
          >
            <Popup>
              <div className="text-sm">
                <p className="font-semibold text-gray-900">{t.area}</p>
                <p className="capitalize text-gray-600">
                  {t.property_type}
                  {t.rooms ? ` · ${t.rooms} bed` : ""}
                  {t.size_sqft ? ` · ${t.size_sqft.toLocaleString()} sqft` : ""}
                </p>
                <p className="mt-1 font-medium">
                  AED {t.amount_aed.toLocaleString()}
                </p>
                {t.price_per_sqft && (
                  <p className="text-gray-500">
                    AED {t.price_per_sqft.toLocaleString()}/sqft
                  </p>
                )}
                <p className="text-xs text-gray-400 mt-1">{t.transaction_date}</p>
              </div>
            </Popup>
          </CircleMarker>
        ) : null
      )}

      {communities.map((c) => (
        <CircleMarker
          key={c.name}
          center={[c.lat, c.lng]}
          radius={3}
          pathOptions={{ color: "#111827", fillColor: "#111827", fillOpacity: 1, weight: 0 }}
        >
          <Tooltip permanent direction="top" offset={[0, -4]} className="comps-label">
            <span className="text-[11px] font-medium">
              {c.name}
              {c.median_price_per_sqft
                ? ` · ${Math.round(c.median_price_per_sqft).toLocaleString()}/sqft`
                : ""}
            </span>
          </Tooltip>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
