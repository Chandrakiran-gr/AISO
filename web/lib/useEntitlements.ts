"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchEntitlements, type Entitlements } from "@/lib/entitlements";

/**
 * Live per-user entitlements hook. Fetches from /api/proxy/v1/auth/me on mount
 * and re-fetches on window focus, so a tier change (admin/billing) is reflected
 * without forcing a re-login — unlike reading tier from the signed NextAuth JWT.
 */
export function useEntitlements() {
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const refetch = useCallback(async () => {
    try {
      const data = await fetchEntitlements();
      setEntitlements(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const data = await fetchEntitlements();
        if (active) {
          setEntitlements(data);
          setError(null);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err : new Error(String(err)));
      } finally {
        if (active) setLoading(false);
      }
    })();

    const onFocus = () => {
      void refetch();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      active = false;
      window.removeEventListener("focus", onFocus);
    };
  }, [refetch]);

  return { entitlements, loading, error, refetch };
}
