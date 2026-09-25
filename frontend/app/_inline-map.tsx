"use client";

import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker, Popup, CircleMarker } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

L.Marker.prototype.options.icon = L.icon({
  iconUrl: (markerIcon as { src?: string }).src || (markerIcon as unknown as string),
  iconRetinaUrl: (markerIcon2x as { src?: string }).src || (markerIcon2x as unknown as string),
  shadowUrl: (markerShadow as { src?: string }).src || (markerShadow as unknown as string),
});

export interface MapPin {
  id: string;
  lat: number;
  lng: number;
  label: string;
  sublabel?: string;
}

export interface TravelLine {
  to_id: string;
  to_lat: number;
  to_lng: number;
  label: string;
  minutes: number;
  approx: boolean;
}

/**
 * Small embedded map for chat cards. Only draws coordinates that came from
 * stored inventory / the offline gazetteer — callers pass nothing when a
 * listing has no lat/lng and the map is simply not rendered.
 */
export function InlineMap({
  pins,
  travel = [],
  height = 160,
  interactive = false,
}: {
  pins: MapPin[];
  travel?: TravelLine[];
  height?: number;
  interactive?: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted || pins.length === 0) return null;

  const points: [number, number][] = [
    ...pins.map((p) => [p.lat, p.lng] as [number, number]),
    ...travel.map((t) => [t.to_lat, t.to_lng] as [number, number]),
  ];
  const bounds = L.latLngBounds(points).pad(0.25);

  return (
    <div className="rounded-xl overflow-hidden border border-gray-100" style={{ height }}>
      <MapContainer
        bounds={bounds}
        scrollWheelZoom={interactive}
        dragging={interactive}
        zoomControl={interactive}
        doubleClickZoom={interactive}
        touchZoom={interactive}
        attributionControl={false}
        style={{ width: "100%", height: "100%" }}
      >
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {pins.map((p) => (
          <Marker key={p.id} position={[p.lat, p.lng]}>
            <Popup>
              <div className="text-sm">
                <div className="font-semibold">{p.label}</div>
                {p.sublabel && <div className="text-gray-500">{p.sublabel}</div>}
              </div>
            </Popup>
          </Marker>
        ))}
        {travel.map((t) => (
          <CircleMarker key={`lm-${t.to_id}`} center={[t.to_lat, t.to_lng]} radius={6} pathOptions={{ color: "#7c3aed", fillOpacity: 0.9 }}>
            <Popup>
              <div className="text-sm">
                <div className="font-semibold">{t.label}</div>
                <div className="text-gray-500">
                  {t.approx ? "≈ " : ""}
                  {t.minutes} min drive
                </div>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
