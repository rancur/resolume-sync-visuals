import { useEffect, useRef, useCallback } from 'react';

export function useJobUpdates(onUpdate: (data: any) => void) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/jobs`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onUpdateRef.current(data);
      } catch {
        // ignore malformed messages
      }
    };

    ws.onclose = () => {
      if (mountedRef.current) {
        reconnectTimer.current = setTimeout(connect, 3000);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);
}

export function useLogStream(runId: string | null, onEntry: (entry: any) => void) {
  const onEntryRef = useRef(onEntry);
  onEntryRef.current = onEntry;

  useEffect(() => {
    if (!runId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/logs/${runId}`);

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        onEntryRef.current(data);
      } catch {
        // ignore
      }
    };

    return () => ws.close();
  }, [runId]);
}
