import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, FlowEvent, Graph, GraphEdge, GraphNode } from "@/lib/api";

const INDUSTRIAL = /modbus|s7|enip|cip|dnp3|bacnet|opc|profinet|iec|mms|goose|fins|melsec/i;

function pairLabel(edges: GraphEdge[]): string {
  const uniq = Array.from(new Set(edges.map((e) => `${e.protocol}${e.port ? ":" + e.port : ""}`)));
  return uniq.length > 3 ? `${uniq.slice(0, 3).join(", ")} +${uniq.length - 3}` : uniq.join(", ");
}

const KIND_STYLE: Record<FlowEvent["kind"], { label: string; cls: string }> = {
  auth: { label: "credencial", cls: "bg-destructive/15 text-destructive" },
  control: { label: "control", cls: "bg-destructive/15 text-destructive" },
  write: { label: "escritura", cls: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  request: { label: "petición", cls: "bg-muted text-muted-foreground" },
  response: { label: "respuesta", cls: "bg-muted text-muted-foreground" },
};

function detailText(e: FlowEvent): string {
  const d = e.detail as Record<string, unknown>;
  const parts: string[] = [];
  if (e.secret) {
    for (const k of ["user", "password", "client_id", "authorization"]) if (d[k]) parts.push(`${k}: ${d[k]}`);
  }
  if (typeof d.host === "string") parts.push(`host: ${d.host}`);
  if (typeof d.user_agent === "string") parts.push(`UA: ${d.user_agent}`);
  if (typeof d.sample === "string") parts.push(`payload: ${d.sample}`);
  if (Array.isArray(d.values) && d.values.length) parts.push(`valores: ${d.values.join(", ")}`);
  return parts.join(" · ");
}

/** Contenido de protocolo de un flujo: qué se envió (URLs, topics, funciones, comandos) y credenciales en claro. */
function EventsCard({ campaignId, edge }: { campaignId: number; edge: GraphEdge }) {
  const [events, setEvents] = useState<FlowEvent[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    setEvents(null);
    api.flowEvents(campaignId, edge).then((r) => live && setEvents(r)).catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [campaignId, edge.src, edge.dst, edge.transport, edge.port, edge.events]);
  return (
    <div className="card">
      <strong>Contenido · {edge.src} → {edge.dst} · {edge.protocol} {edge.transport}/{edge.port}</strong>
      {error && <p className="error">{error}</p>}
      {events === null && !error && <p className="muted">Cargando…</p>}
      {events && events.length === 0 && <p className="muted">No hay contenido de protocolo decodificado para este flujo (se interpretan HTTP, MQTT, Modbus, S7 y FTP en sus puertos estándar).</p>}
      {events && events.length > 0 && (
        <table>
          <thead><tr><th>Tipo</th><th>Dir.</th><th>Operación</th><th>Detalle</th><th>Veces</th></tr></thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${KIND_STYLE[e.kind].cls}`}>{KIND_STYLE[e.kind].label}</span>
                  {e.secret && <span className="ml-1 text-[11px] font-semibold text-destructive" title="Credencial en claro: posible hallazgo">⚠ {e.secret_kind}</span>}
                </td>
                <td title={e.direction === "c2s" ? "cliente → servidor" : "servidor → cliente"}>{e.direction === "c2s" ? "→" : "←"}</td>
                <td><code>{e.summary}</code></td>
                <td className="break-all text-xs text-muted-foreground">{detailText(e)}</td>
                <td className="tabular-nums">{e.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function GraphPanel({ graph, campaignId }: { graph: Graph; campaignId: number }) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  const lastShape = useRef("");
  const [selected, setSelected] = useState<{ node?: GraphNode; edges?: GraphEdge[]; title: string } | null>(null);
  const [flow, setFlow] = useState<GraphEdge | null>(null); // flujo cuyo contenido se muestra
  const flowKey = (e: GraphEdge) => `${e.src}>${e.dst}>${e.transport}>${e.port}`;
  const current = flow && graph.edges.find((e) => flowKey(e) === flowKey(flow)); // se refresca con el WebSocket
  const secrets = graph.edges.reduce((n, e) => n + e.secrets, 0);

  const pairs = useMemo(() => {
    const m = new Map<string, GraphEdge[]>();
    for (const e of graph.edges) m.set(`${e.src}>${e.dst}`, [...(m.get(`${e.src}>${e.dst}`) ?? []), e]);
    return m;
  }, [graph]);

  useEffect(() => {
    if (!box.current) return;
    const c = cytoscape({
      container: box.current,
      minZoom: 0.2,
      maxZoom: 1.3, // durante el layout: evita ampliar grafos pequeños; se libera al terminar
      style: [
        { selector: "node", style: { label: "data(label)", "font-size": 12, color: "#888", "text-valign": "bottom", "text-margin-y": 5, "text-wrap": "wrap", "text-max-width": "140px", "background-color": "#2b7de9", width: 28, height: 28 } },
        { selector: "node.external", style: { "background-color": "#999" } },
        { selector: "node.multicast", style: { shape: "diamond", "background-color": "#e69f00" } },
        { selector: "edge", style: { width: "data(w)", "line-color": "#8aa", "target-arrow-color": "#8aa", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": 10, color: "#888", "text-rotation": "autorotate", "text-margin-y": -7, "text-wrap": "wrap", "text-max-width": "160px" } },
        { selector: "edge.industrial", style: { "line-color": "#d9480f", "target-arrow-color": "#d9480f" } },
        { selector: ":selected", style: { "border-width": 3, "border-color": "#f5c518", "line-color": "#f5c518", "target-arrow-color": "#f5c518" } },
      ],
    });
    c.on("tap", "node", (ev) => {
      const n = graph.nodes.find((x) => x.ip === ev.target.id());
      if (n) setSelected({ node: n, title: n.ip });
    });
    c.on("tap", "edge", (ev) => {
      const list = pairs.get(ev.target.id()) ?? [];
      setSelected({ edges: list, title: `${ev.target.data("source")} → ${ev.target.data("target")}` });
    });
    c.on("tap", (ev) => ev.target === c && setSelected(null));
    cy.current = c;
    lastShape.current = "";
    return () => { c.destroy(); cy.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    const shape = JSON.stringify([graph.nodes.map((n) => n.ip), [...pairs.keys()]]);
    const elements: cytoscape.ElementDefinition[] = [
      ...graph.nodes.map((n) => ({
        data: { id: n.ip, label: n.hostname ? `${n.ip}\n${n.hostname}` : n.ip },
        classes: n.kind === "multicast" ? "multicast" : n.in_scope ? "" : "external",
      })),
      ...[...pairs.entries()].map(([id, es]) => ({
        data: { id, source: es[0].src, target: es[0].dst, label: pairLabel(es), w: 1 + Math.log10(1 + es.reduce((a, e) => a + e.packets, 0)) * 1.5 },
        classes: es.some((e) => INDUSTRIAL.test(e.protocol)) ? "industrial" : "",
      })),
    ];
    if (shape === lastShape.current) {
      // misma topología: solo actualiza datos, sin recolocar (no marea en vivo)
      for (const el of elements) c.getElementById(el.data.id!).data(el.data);
      return;
    }
    lastShape.current = shape;
    c.elements().remove();
    c.add(elements);
    const layout = c.layout({
      name: "cose", animate: false, fit: true, padding: 50, randomize: true,
      nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 60000, nodeOverlap: 30,
      idealEdgeLength: () => 130, edgeElasticity: () => 100, gravity: 0.6, numIter: 1000,
    });
    layout.one("layoutstop", () => {
      // Con un lienzo ancho, un grafo en cadena queda como una columna diminuta: se estira en horizontal hasta igualar la proporción del lienzo.
      const bb = c.elements().boundingBox();
      const sx = Math.min(2.5, Math.max(1, c.width() / c.height() / ((bb.w || 1) / (bb.h || 1))));
      if (sx > 1.05) c.nodes().positions((n) => ({ x: n.position("x") * sx, y: n.position("y") }));
      c.fit(undefined, 60);
      c.maxZoom(3);
    });
    layout.run();
  }, [graph, pairs]);

  return (
    <div>
      <div className="legend muted">
        <span style={{ color: "#2b7de9" }}>●</span> activo en alcance · <span style={{ color: "#999" }}>●</span> fuera de alcance ·{" "}
        <span style={{ color: "#e69f00" }}>◆</span> multicast/broadcast · <span style={{ color: "#d9480f" }}>―</span> protocolo industrial
      </div>
      {secrets > 0 && (
        <p className="card border-destructive/40 text-sm text-destructive">
          ⚠ Se han visto {secrets} credencial{secrets === 1 ? "" : "es"} en claro en las capturas. Pulsa en el flujo marcado para ver cuáles.
        </p>
      )}
      <div className="graph card" ref={box} />
      {graph.nodes.length === 0 && <p className="muted">Sin datos: sube una captura para ver cómo se comunican los activos.</p>}
      {selected && (
        <div className="card">
          <strong>{selected.title}</strong>
          {selected.node && (
            <p className="muted">
              {selected.node.is_asset ? "Activo" : selected.node.kind === "multicast" ? "Multicast/broadcast" : "Host observado (no es activo)"}
              {selected.node.hostname && ` · ${selected.node.hostname}`}{selected.node.mac && ` · ${selected.node.mac}`}{selected.node.vendor && ` (${selected.node.vendor})`}
              {!selected.node.in_scope && " · fuera de alcance"}
            </p>
          )}
          {selected.node && (
            <ul>
              {graph.edges.filter((e) => e.src === selected.node!.ip || e.dst === selected.node!.ip).map((e, i) => (
                <li key={i}>{e.src} → {e.dst} · {e.protocol} {e.transport}/{e.port} · {e.packets} pkts</li>
              ))}
            </ul>
          )}
          {selected.edges && (
            <ul>{selected.edges.map((e, i) => (
              <li key={i}>
                {e.protocol} {e.transport}/{e.port} · {e.packets} pkts · {e.bytes} B
                {e.events > 0 && <> · <button className="linkish" onClick={() => setFlow(e)}>ver contenido ({e.events})</button></>}
              </li>
            ))}</ul>
          )}
        </div>
      )}
      {current && <EventsCard campaignId={campaignId} edge={current} />}
      <table className="card">
        <thead><tr><th>Origen (cliente)</th><th>Destino (servidor)</th><th>Protocolo</th><th>Puerto</th><th>Paquetes</th><th>Bytes</th><th>Contenido</th></tr></thead>
        <tbody>
          {graph.edges.map((e, i) => (
            <tr key={i} className={e.events > 0 ? "cursor-pointer hover:bg-muted/40" : ""} onClick={() => e.events > 0 && setFlow(e)}>
              <td>{e.src}</td><td>{e.dst}</td><td>{e.protocol}</td><td>{e.transport}/{e.port}</td><td>{e.packets}</td><td>{e.bytes}</td>
              <td>
                {e.events > 0 ? <button className="linkish">{e.events} op.</button> : "–"}
                {e.secrets > 0 && <span className="ml-1 font-semibold text-destructive" title="Credenciales en claro">⚠ {e.secrets}</span>}
              </td>
            </tr>
          ))}
          {graph.edges.length === 0 && <tr><td colSpan={7}>Sin flujos todavía.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
