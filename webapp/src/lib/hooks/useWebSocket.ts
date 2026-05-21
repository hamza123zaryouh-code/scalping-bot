"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "../api";

export type WebSocketMessage = {
  type: string;
  channel?: string;
  payload?: unknown;
  error?: string;
  ts?: string;
};

interface UseWebSocketOptions {
  onMessage?: (msg: WebSocketMessage) => void;
  reconnectDelay?: number;
  enabled?: boolean;
  channels?: string[];
}

export function useWebSocket({
  onMessage,
  reconnectDelay = 3000,
  enabled = true,
  channels = [],
}: UseWebSocketOptions = {}) {
  const [connected, setConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<"idle" | "connecting" | "connected" | "reconnecting" | "closed">("idle");
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const [reconnectCount, setReconnectCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const onMessageRef = useRef(onMessage);
  const channelsRef = useRef(channels);
  const enabledRef = useRef(enabled);
  const reconnectDelayRef = useRef(reconnectDelay);

  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    channelsRef.current = channels;
  }, [channels]);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    reconnectDelayRef.current = reconnectDelay;
  }, [reconnectDelay]);

  const handleMessage = useCallback((msg: WebSocketMessage) => {
    setLastMessage(msg);
    onMessageRef.current?.(msg);
  }, []);

  const connect = useCallback(() => {
    if (!enabledRef.current || !mountedRef.current) return;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const token = getToken();
    if (!token) return;
    setConnectionState((current) => (current === "idle" ? "connecting" : "reconnecting"));

    const wsBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000")
      .replace(/^http/, "ws");
    const ws = new WebSocket(`${wsBase}/ws/live?token=${token}`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      setConnectionState("connected");
      ws.send(JSON.stringify({ type: "ping" }));
      if (channelsRef.current.length > 0) {
        ws.send(JSON.stringify({ type: "subscribe", channels: channelsRef.current }));
      }
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(ev.data) as WebSocketMessage;
        handleMessage(msg);
      } catch {}
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      wsRef.current = null;
      setConnected(false);
      setConnectionState("closed");
      setReconnectCount((count) => count + 1);
      if (!enabledRef.current) return;
      timerRef.current = setTimeout(() => {
        connect();
      }, reconnectDelayRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [handleMessage]);

  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setConnected(false);
      setConnectionState("idle");
      return () => {
        mountedRef.current = false;
      };
    }
    connect();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [connect, enabled]);

  const send = useCallback((msg: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { connected, connectionState, lastMessage, reconnectCount, send };
}
