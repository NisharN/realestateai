/**
 * Ambient shims for Leaflet.
 *
 * These `declare module` blocks take precedence over the packages' own bundled
 * types, so anything used from `react-leaflet` must be listed here or it will
 * fail to typecheck with "has no exported member" — even though the real
 * package does export it.
 */

declare module "leaflet" {
  const L: any;
  export default L;
}

declare module "react-leaflet" {
  import type { ComponentType } from "react";
  export const MapContainer: ComponentType<any>;
  export const TileLayer: ComponentType<any>;
  export const Marker: ComponentType<any>;
  export const Popup: ComponentType<any>;
  export const CircleMarker: ComponentType<any>;
  export const Tooltip: ComponentType<any>;
  export const useMap: () => any;
}
