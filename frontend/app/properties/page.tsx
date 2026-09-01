"use client";

import { useEffect, useState } from "react";
import { propertiesApi } from "@/lib/api";

interface PropertySummary { id: string; title: string; area: string; price: number; bedrooms?: number; property_type?: string }

export default function PropertiesPage() {
  const [properties, setProperties] = useState<PropertySummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { propertiesApi.search({ limit: 50 }).then((result) => result.data ? setProperties(result.data as PropertySummary[]) : setError(result.error ?? "Unable to load inventory")); }, []);
  return <main className="min-h-screen bg-slate-50 px-5 py-10"><div className="mx-auto max-w-6xl"><h1 className="text-3xl font-semibold">Property inventory</h1><p className="mt-2 text-slate-600">Workspace-scoped listings available for AI matching.</p>{error && <p role="alert" className="mt-6 rounded-xl bg-red-50 p-4 text-red-700">{error}</p>}<div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">{properties.map((property) => <article key={property.id} className="rounded-2xl border bg-white p-5 shadow-sm"><p className="text-xs font-semibold uppercase tracking-wide text-amber-700">{property.area}</p><h2 className="mt-2 font-semibold">{property.title}</h2><p className="mt-4 text-lg font-bold">AED {property.price.toLocaleString()}</p><p className="mt-1 text-sm text-slate-500">{property.bedrooms ?? "—"} bedrooms · {property.property_type ?? "Property"}</p></article>)}</div>{!error && properties.length === 0 && <p className="mt-8 rounded-2xl border border-dashed p-10 text-center text-slate-500">No inventory has been imported for this workspace.</p>}</div></main>;
}
