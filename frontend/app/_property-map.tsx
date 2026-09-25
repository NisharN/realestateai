"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { X } from "lucide-react";

interface Property {
  id: string;
  title: string;
  area: string;
  price: number;
  map_lat: number | null;
  map_lng: number | null;
  match_score?: number;
}

L.Marker.prototype.options.icon = L.icon({
  iconUrl: (markerIcon as { src?: string }).src || (markerIcon as unknown as string),
  iconRetinaUrl: (markerIcon2x as { src?: string }).src || (markerIcon2x as unknown as string),
  shadowUrl: (markerShadow as { src?: string }).src || (markerShadow as unknown as string),
});

export function PropertyMap({
  properties,
  selectedProperty,
  onClose,
}: {
  properties: Property[];
  selectedProperty: Property | null;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  const placed = properties.filter((p): p is Property & { map_lat: number; map_lng: number } => p.map_lat != null && p.map_lng != null);
  const focus = selectedProperty && selectedProperty.map_lat != null && selectedProperty.map_lng != null ? selectedProperty : null;
  const center: [number, number] = focus ? [focus.map_lat as number, focus.map_lng as number] : [25.2048, 55.2708];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
    >
      <motion.div
        initial={{ scale: 0.9 }}
        animate={{ scale: 1 }}
        exit={{ scale: 0.9 }}
        className="bg-white rounded-2xl overflow-hidden w-full max-w-4xl h-[80vh] relative"
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-[1000] p-2 bg-white/90 backdrop-blur rounded-full shadow-lg hover:bg-white transition"
        >
          <X className="w-5 h-5 text-gray-700" />
        </button>
        <MapContainer
          center={center}
          zoom={focus ? 14 : 11}
          scrollWheelZoom
          style={{ width: "100%", height: "100%" }}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {placed.map((p) => (
            <Marker key={p.id} position={[p.map_lat, p.map_lng]}>
              <Popup>
                <div className="text-sm">
                  <div className="font-semibold">{p.title}</div>
                  <div className="text-gray-500">{p.area}</div>
                  <div className="mt-1 font-bold">AED {p.price.toLocaleString()}</div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </motion.div>
    </motion.div>
  );
}
