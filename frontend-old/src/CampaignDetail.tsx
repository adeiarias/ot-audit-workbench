import { Fragment, useCallback, useEffect, useState } from "react";
import { api, Asset, Campaign, Capture, ChatView, Evidence, Finding, Graph, Run, Tool } from "./api";
import ChatPanel from "./ChatPanel";
import ReportPanel from "./ReportPanel";
import EvidencePanel from "./EvidencePanel";
import FindingsPanel from "./FindingsPanel";
import CapturesPanel from "./CapturesPanel";
import GraphPanel from "./GraphPanel";
import { useCampaignEvents } from "./useEvents";

function ToolForm({ campaign, tools, onRun }: { campaign: Campaign; tools: Tool[]; onRun: () => void }) {
  const [idx, setIdx] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const tool = tools[idx];
  if (!tool) return <p>Cargando herramientas…</p>;
  const props = Object.entries(tool.input_schema.properties);
  const required = new Set(tool.input_schema.required ?? []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const args: Record<string, unknown> = {};
    for (const [name, spec] of props) {
      const v = values[name] ?? (spec.default !== undefined ? String(spec.default) : "");
      if (v === "") continue;
      args[name] = spec.type === "integer" ? Number(v) : v;
    }
    try {
      setError("");
      await api.createRun(campaign.id, { server: tool.server, tool: tool.tool, arguments: args });
      onRun();
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <form onSubmit={submit} className="card">
      <h2>Ejecutar herramienta</h2>
      <label>
        Herramienta
        <select value={idx} onChange={(e) => { setIdx(Number(e.target.value)); setValues({}); }}>
          {tools.map((t, i) => <option key={i} value={i}>{t.server} / {t.tool}</option>)}
        </select>
      </label>
      <p className="muted">{tool.description}</p>
      {props.map(([name, spec]) => (
        <label key={name}>
          {name}{required.has(name) ? " *" : ""}{name === tool.target_arg ? " (debe estar en el alcance)" : ""}
          {spec.enum ? (
            <select value={values[name] ?? String(spec.default ?? spec.enum[0])} onChange={(e) => setValues({ ...values, [name]: e.target.value })}>
              {spec.enum.map((o) => <option key={o}>{o}</option>)}
            </select>
          ) : (
            <input
              type={spec.type === "integer" ? "number" : "text"}
              required={required.has(name)}
              placeholder={spec.default !== undefined ? String(spec.default) : ""}
              value={values[name] ?? ""}
              onChange={(e) => setValues({ ...values, [name]: e.target.value })}
            />
          )}
        </label>
      ))}
      {tool.active && <p className="muted">⚠ Herramienta activa: genera tráfico hacia el objetivo. Al pulsar Ejecutar confirmas que tienes autorización.</p>}
      {error && <p className="error">{error}</p>}
      <button type="submit">Ejecutar</button>
    </form>
  );
}

type Tab = "tools" | "assets" | "captures" | "map" | "findings" | "evidence" | "chat" | "report";
const TABS: [Tab, string][] = [["tools", "Herramientas"], ["assets", "Activos"], ["captures", "Capturas"], ["map", "Mapa"], ["findings", "Hallazgos"], ["evidence", "Evidencias"], ["chat", "Asistente"], ["report", "Informe"]];

export default function CampaignDetail({ campaign, onBack, onCampaignChange }: { campaign: Campaign; onBack: () => void; onCampaignChange: () => void }) {
  const [tab, setTab] = useState<Tab>("tools");
  const [tools, setTools] = useState<Tool[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [graph, setGraph] = useState<Graph>({ nodes: [], edges: [] });
  const [findings, setFindings] = useState<Finding[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [chat, setChat] = useState<ChatView | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [r, a, c, g, fi, ev, ch] = await Promise.all([
        api.runs(campaign.id), api.assets(campaign.id), api.captures(campaign.id), api.graph(campaign.id),
        api.findings(campaign.id), api.evidence(campaign.id), api.chat(campaign.id),
      ]);
      setRuns(r);
      setAssets(a);
      setCaptures(c);
      setGraph(g);
      setFindings(fi);
      setEvidence(ev);
      setChat(ch);
    } catch (e) {
      setError(String(e));
    }
  }, [campaign.id]);

  useEffect(() => {
    api.tools().then(setTools).catch((e) => setError(String(e)));
  }, []);

  // Tiempo real: el backend avisa por WebSocket cuando cambia algo
  useCampaignEvents(campaign.id, refresh);

  // Respaldo por si el WebSocket no está disponible: sondeo mientras haya algo en curso
  const busy = runs.some((r) => r.status === "running") || captures.some((c) => c.status === "analyzing") || !!chat?.busy;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  return (
    <main>
      <p><a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>← Campañas</a></p>
      <h1>{campaign.name}</h1>
      <p className="muted">{campaign.audit_type} · inicio {campaign.start_date} · {campaign.status}</p>
      <div className="card">
        <strong>Alcance</strong>
        <pre>{campaign.scope || "(vacío: no se puede ejecutar ninguna herramienta)"}</pre>
      </div>
      {error && <p className="error">{error}</p>}

      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}{id === "assets" ? ` (${assets.length})` : id === "captures" ? ` (${captures.length})` : id === "findings" ? ` (${findings.length})` : id === "evidence" ? ` (${evidence.length})` : id === "chat" && chat?.messages.some((m) => m.calls.some((c) => c.status === "pending")) ? " ⏸" : ""}
          </button>
        ))}
      </nav>

      {tab === "tools" && (
        <>
          <ToolForm campaign={campaign} tools={tools} onRun={refresh} />
          <h2>Ejecuciones</h2>
          <table className="card">
            <thead><tr><th>#</th><th>Herramienta</th><th>Argumentos</th><th>Estado</th><th /></tr></thead>
            <tbody>
              {runs.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td>{r.id}</td>
                    <td>{r.server}/{r.tool}</td>
                    <td><code>{JSON.stringify(r.arguments)}</code></td>
                    <td>{r.status === "running" ? "⏳ en curso" : r.status === "succeeded" ? "✅ ok" : "❌ error"}</td>
                    <td><button onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "Ocultar" : "Ver salida"}</button></td>
                  </tr>
                  {open === r.id && (
                    <tr><td colSpan={5}><pre>{r.error || r.output || "(sin salida)"}</pre></td></tr>
                  )}
                </Fragment>
              ))}
              {runs.length === 0 && <tr><td colSpan={5}>Sin ejecuciones todavía.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "assets" && (
        <table className="card">
          <thead><tr><th>IP</th><th>Hostname</th><th>MAC / fabricante</th><th>Puertos abiertos</th><th>Fuentes</th></tr></thead>
          <tbody>
            {assets.map((a) => (
              <tr key={a.id}>
                <td>{a.ip}</td>
                <td>{a.hostname}</td>
                <td>{a.mac} {a.vendor && `(${a.vendor})`}</td>
                <td>{a.ports.map((p) => `${p.port}/${p.proto} ${p.service}`.trim()).join(", ")}</td>
                <td>{a.sources.join(", ")}</td>
              </tr>
            ))}
            {assets.length === 0 && <tr><td colSpan={5}>Sin activos todavía.</td></tr>}
          </tbody>
        </table>
      )}

      {tab === "captures" && <CapturesPanel campaignId={campaign.id} captures={captures} onChange={refresh} />}
      {tab === "map" && <GraphPanel graph={graph} />}
      {tab === "findings" && <FindingsPanel campaignId={campaign.id} findings={findings} assets={assets} evidence={evidence} onChange={refresh} />}
      {tab === "report" && <ReportPanel campaign={campaign} refreshKey={`${findings.map((f) => `${f.id}:${f.status}:${f.cvss_score}`).join(",")}|${evidence.length}`} />}
      {tab === "chat" && <ChatPanel campaign={campaign} chat={chat} onChange={refresh} onCampaignChange={onCampaignChange} />}
      {tab === "evidence" && <EvidencePanel campaignId={campaign.id} evidence={evidence} findings={findings} onChange={refresh} />}
    </main>
  );
}
