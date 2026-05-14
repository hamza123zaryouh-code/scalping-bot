"use client";
import { useEffect, useRef, useState, useCallback } from "react";

export function useAutoRefresh<T>(
  fetcher: () => Promise<T>,
  interval = 5000,
  enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  const fetch_ = useCallback(async () => {
    try {
      const result = await fetcher();
      if (mountedRef.current) {
        setData(result);
        setError(null);
        setLoading(false);
      }
    } catch (e) {
      if (mountedRef.current) {
        setError(e instanceof Error ? e.message : "Error");
        setLoading(false);
      }
    }
  }, [fetcher]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return;
    fetch_();
    timerRef.current = setInterval(fetch_, interval);
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetch_, interval, enabled]);

  return { data, loading, error, refetch: fetch_ };
}
