import { useEffect, useRef } from "react";

/** Se suscribe al WebSocket de la campaña y llama a onChange en cada evento. Reconecta solo. */
export function useCampaignEvents(campaignId: number, onChange: () => void) {
  const cb = useRef(onChange);
  cb.current = onChange;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/api/campaigns/${campaignId}/ws`);
      ws.onmessage = () => cb.current();
      ws.onopen = () => cb.current(); // resincroniza tras (re)conectar
      ws.onclose = () => {
        if (!closed) timer = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [campaignId]);
}
