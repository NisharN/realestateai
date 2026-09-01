"use client";

/**
 * Market page — the comps map plus a price-positioning checker.
 *
 * This is the screen an agent opens mid-argument with a landlord who insists
 * their unit is worth more than the market says. The map shows what actually
 * transacted nearby; the checker turns an asking price into a number
 * ("18% above comparable price-per-sqft") instead of an opinion.
 */

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { Info, MapPin, TrendingDown, TrendingUp, Minus } from "lucide-react";
import {
  marketApi,
  type Community,
  type CompsResult,
  type DldTransaction,
} from "@/lib/api";

// Leaflet touches `window` on import, so the map can't be server-rendered.
const CompsMap = dynamic(
  () => import("./_comps-map").then((m) => m.CompsMap),
  { ssr: false, loading: () => <div className="h-full w-full bg-gray-100 animate-pulse rounded-2xl" /> }
);

export default function MarketPage() {
  const [transactions, setTransactions] = useState<DldTransaction[]>([]);
  const [communities, setCommunities] = useState<Community[]>([]);
  const [selectedArea, setSelectedArea] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ mode: string; source: string; isDemo: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    Promise.all([marketApi.transactions({ limit: 800 }), marketApi.communities()]).then(
      ([txResult, commResult]) => {
        if (!active) return;
        setLoading(false);
        if (txResult.data) {
          setTransactions(txResult.data.transactions);
          setMeta({
            mode: txResult.data.mode,
            source: txResult.data.source,
            isDemo: txResult.data.is_demo_data,
          });
        } else {
          setError(txResult.error ?? "Unable to load market data");
        }
        if (commResult.data) setCommunities(commResult.data.communities);
      }
    );
    return () => {
      active = false;
    };
  }, []);

  const visible = useMemo(
    () => (selectedArea ? transactions.filter((t) => t.area === selectedArea) : transactions),
    [transactions, selectedArea]
  );

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        <header className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Market comps</h1>
          <p className="text-sm text-gray-500 mt-1">
            Recent comparable transactions across Dubai communities.
          </p>
        </header>

        {meta?.isDemo && (
          <div className="mb-4 flex items-start gap-2 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200">
            <Info className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-amber-800">
              <span className="font-medium">Demo data.</span> {meta.source}. Set{" "}
              <code className="px-1 py-0.5 bg-amber-100 rounded text-xs">DATA_MODE_DLD=live</code>{" "}
              to pull real Dubai Land Department transactions from Dubai Pulse.
            </p>
          </div>
        )}

        {error && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
              <div className="p-4 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-2 text-sm text-gray-600">
                  <MapPin className="w-4 h-4 text-gray-400" />
                  {loading ? "Loading…" : `${visible.length.toLocaleString()} transactions`}
                </div>
                <select
                  value={selectedArea ?? ""}
                  onChange={(e) => setSelectedArea(e.target.value || null)}
                  className="px-3 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none"
                >
                  <option value="">All communities</option>
                  {communities.map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="h-[520px] p-4">
                <CompsMap
                  transactions={visible}
                  communities={communities}
                  selectedArea={selectedArea}
                />
              </div>
              <div className="px-4 pb-4 flex items-center gap-3 text-xs text-gray-500">
                <span>Lower AED/sqft</span>
                <div className="h-2 flex-1 rounded-full bg-gradient-to-r from-teal-500 via-amber-500 to-rose-500" />
                <span>Higher AED/sqft</span>
              </div>
            </div>
          </div>

          <div className="space-y-6">
            <PriceChecker communities={communities} />
            <CommunityTable communities={communities} onSelect={setSelectedArea} />
          </div>
        </div>
      </div>
    </div>
  );
}

function PriceChecker({ communities }: { communities: Community[] }) {
  const [area, setArea] = useState("");
  const [price, setPrice] = useState("");
  const [size, setSize] = useState("");
  const [result, setResult] = useState<CompsResult | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    if (!area && communities.length) setArea(communities[0].name);
  }, [communities, area]);

  async function check() {
    const priceValue = Number(price);
    if (!area || !priceValue) return;
    setChecking(true);
    const response = await marketApi.comps({
      area,
      price: priceValue,
      size_sqft: size ? Number(size) : undefined,
    });
    setChecking(false);
    if (response.data) setResult(response.data);
  }

  const verdictStyle: Record<string, { label: string; cls: string; Icon: typeof TrendingUp }> = {
    below_market: { label: "Below market", cls: "text-teal-700 bg-teal-50 border-teal-200", Icon: TrendingDown },
    in_line: { label: "In line with market", cls: "text-gray-700 bg-gray-50 border-gray-200", Icon: Minus },
    above_market: { label: "Above market", cls: "text-rose-700 bg-rose-50 border-rose-200", Icon: TrendingUp },
    no_comparable_data: { label: "No comparable data", cls: "text-gray-600 bg-gray-50 border-gray-200", Icon: Info },
  };

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-1">Price positioning</h2>
      <p className="text-xs text-gray-500 mb-4">
        Compare an asking price against recent comparable sales.
      </p>

      <div className="space-y-3">
        <select
          value={area}
          onChange={(e) => setArea(e.target.value)}
          className="w-full px-3 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none"
        >
          {communities.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          type="number"
          inputMode="numeric"
          placeholder="Asking price (AED)"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          className="w-full px-3 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none"
        />
        <input
          type="number"
          inputMode="numeric"
          placeholder="Size (sqft) — for like-for-like"
          value={size}
          onChange={(e) => setSize(e.target.value)}
          className="w-full px-3 py-2 bg-gray-100 rounded-xl text-sm focus:outline-none"
        />
        <button
          onClick={check}
          disabled={checking || !price}
          className="w-full px-4 py-2.5 bg-gray-900 text-white rounded-xl text-sm font-medium hover:bg-gray-800 transition disabled:opacity-40"
        >
          {checking ? "Checking…" : "Check price"}
        </button>
      </div>

      {result && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 pt-5 border-t border-gray-100"
        >
          {(() => {
            const style = verdictStyle[result.verdict] ?? verdictStyle.no_comparable_data;
            const Icon = style.Icon;
            return (
              <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border ${style.cls} mb-3`}>
                <Icon className="w-4 h-4" />
                <span className="text-sm font-medium">{style.label}</span>
                {result.verdict !== "no_comparable_data" && (
                  <span className="text-sm ml-auto">
                    {result.delta_pct > 0 ? "+" : ""}
                    {result.delta_pct}%
                  </span>
                )}
              </div>
            );
          })()}

          <dl className="space-y-1.5 text-sm">
            <Row label="Sample size" value={`${result.sample_size} sales`} />
            <Row
              label="Median AED/sqft"
              value={result.median_price_per_sqft?.toLocaleString() ?? "—"}
            />
            {result.asking_price_per_sqft && (
              <Row
                label="This asking AED/sqft"
                value={result.asking_price_per_sqft.toLocaleString()}
              />
            )}
            <Row
              label="Compared on"
              value={result.basis === "price_per_sqft" ? "Price per sqft" : "Total price"}
            />
          </dl>

          {result.caveat && (
            <p className="mt-3 text-xs text-gray-500">{result.caveat}</p>
          )}
        </motion.div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-900 font-medium">{value}</dd>
    </div>
  );
}

function CommunityTable({
  communities,
  onSelect,
}: {
  communities: Community[];
  onSelect: (area: string) => void;
}) {
  const sorted = [...communities].sort(
    (a, b) => (b.median_price_per_sqft ?? 0) - (a.median_price_per_sqft ?? 0)
  );

  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="p-4 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">Median AED/sqft</h2>
      </div>
      <div className="divide-y divide-gray-50 max-h-80 overflow-y-auto">
        {sorted.map((c) => (
          <button
            key={c.name}
            onClick={() => onSelect(c.name)}
            className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 transition text-left"
          >
            <span className="text-sm text-gray-700">{c.name}</span>
            <span className="text-sm font-medium text-gray-900">
              {c.median_price_per_sqft
                ? Math.round(c.median_price_per_sqft).toLocaleString()
                : "—"}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
