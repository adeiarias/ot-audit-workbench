import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api, ApiError, type Asset, type Campaign, type Capture, type ChatView, type Evidence, type Finding, type Graph, type Run, type Tool } from "@/lib/api";
import { useCampaignEvents } from "@/lib/events";

export interface CampaignData {
  campaign: Campaign;
  runs: Run[];
  assets: Asset[];
  captures: Capture[];
  graph: Graph;
  findings: Finding[];
  evidence: Evidence[];
  chat: ChatView | null;
  tools: Tool[];
  error: string;
  refresh: () => Promise<void>;
}

const Ctx = createContext<CampaignData | null>(null);

export const useCampaign = (): CampaignData => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCampaign fuera de una campaña");
  return v;
};
export const useOptionalCampaign = () => useContext(Ctx);

/** Carga TODO lo de una campaña y se mantiene al día: el backend avisa por WebSocket de cada cambio. */
export function CampaignProvider({ id, children }: { id: number; children: ReactNode }) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [chat, setChat] = useState<ChatView | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [c, r, a, cp, g, f, e, ch] = await Promise.all([
        api.get(id), api.runs(id), api.assets(id), api.captures(id), api.graph(id), api.findings(id), api.evidence(id), api.chat(id),
      ]);
      setCampaign(c); setRuns(r); setAssets(a); setCaptures(cp); setGraph(g); setFindings(f); setEvidence(e); setChat(ch);
      setError(""); setMissing(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setMissing(true);
      else setError(String(err instanceof Error ? err.message : err));
    }
  }, [id]);

  useEffect(() => {
    setCampaign(null);
    setMissing(false);
    setChat(null);
  }, [id]);
  useEffect(() => { api.tools().then(setTools).catch(() => undefined); }, []);
  useCampaignEvents(id, refresh);

  // Respaldo por si el WebSocket no llega: sondeo mientras haya algo en curso
  const busy = runs.some((r) => r.status === "running") || captures.some((c) => c.status === "analyzing") || !!chat?.busy;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  if (missing) return <div className="p-10 text-center text-muted-foreground">Esta campaña no existe (¿se ha borrado?).</div>;
  if (!campaign) return <div className="p-10 text-center text-muted-foreground">{error || "Cargando campaña…"}</div>;
  return <Ctx.Provider value={{ campaign, runs, assets, captures, graph, findings, evidence, chat, tools, error, refresh }}>{children}</Ctx.Provider>;
}
