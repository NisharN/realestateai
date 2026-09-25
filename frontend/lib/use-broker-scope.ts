"use client";

import { useEffect, useState } from "react";
import { authApi, type SessionContext } from "./api";

const STORAGE_KEY = "broker_scope_id";

/**
 * Agents are always scoped to their own broker profile by the backend.
 * Owners/admins can act on behalf of a broker; that choice is remembered locally.
 */
export function useBrokerScope() {
  const [session, setSession] = useState<SessionContext | null>(null);
  const [override, setOverride] = useState<string>("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    authApi.me().then(({ data }) => {
      if (data) setSession(data);
      setReady(true);
    });
    setOverride(window.localStorage.getItem(STORAGE_KEY) ?? "");
  }, []);

  const isAgent = session?.role === "agent";
  const brokerId = isAgent ? session?.broker_id ?? null : override || null;

  const setBrokerId = (value: string) => {
    setOverride(value);
    if (value) window.localStorage.setItem(STORAGE_KEY, value);
    else window.localStorage.removeItem(STORAGE_KEY);
  };

  return { session, isAgent, brokerId, setBrokerId, ready };
}
