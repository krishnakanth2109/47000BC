import { useEffect, useRef, useState, useCallback } from "react";
import { wsUrl } from "../api.js";

/**
 * useWebSocket — connects to the backend WebSocket at /api/live
 * (using VITE_API_URL / VITE_RENDER_URL when set) and calls onMessage()
 * whenever a text message arrives. Auto-reconnects on disconnect.
 */
export function useWebSocket(onMessage, enabled = true) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    if (!enabled) return;

    const url = wsUrl("live");
    const ws = new WebSocket(url);

    ws.onopen = () => setConnected(true);
    ws.onmessage = (e) => onMessage(e.data);
    ws.onclose = () => {
      setConnected(false);
      // Reconnect after 3 seconds
      setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();

    wsRef.current = ws;
  }, [enabled, onMessage]);

  useEffect(() => {
    if (!enabled) return;
    connect();
    return () => {
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on unmount
        wsRef.current.close();
      }
    };
  }, [connect, enabled]);

  return { connected };
}
