"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { getToken } from "../api";

type WSMessage = { type: string; payload?: unknown; error?: string };

interface UseWebSocketOptions {
  onMessage?: (msg: WSMessage) => void;
  reconnectDelay?: number;
  enabled?: boolean;
}

export function useWebSocket({ onMessage, reconnectDelay = 3000, enabled = true }: UseWebSocketOptions = {}) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!enabled || !mountedRef.current) return;
    const token = getToken();
    if (!token) return;

    const wsBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
      .replace(/^http/, "ws");
    const ws = new WebSocket(`${wsBase}/ws/live?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      ws.send(JSON.stringify({ type: "ping" }));
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(ev.data) as WSMessage;
        onMessage?.(msg);
      } catch {}
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      timerRef.current = setTimeout(connect, reconnectDelay);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [enabled, reconnectDelay, onMessage]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((msg: WSMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { connected, send };
}
