import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import { Graph, GraphEdge, GraphNode } from "./api";

const INDUSTRIAL = /modbus|s7|enip|cip|dnp3|bacnet|opc|profinet|iec|mms|goose|fins|melsec/i;

function pairLabel(edges: GraphEdge[]): string {
  const uniq = Array.from(new Set(edges.map((e) => `${e.protocol}${e.port ? ":" + e.port : ""}`)));
  return uniq.length > 3 ? `${uniq.slice(0, 3).join(", ")} +${uniq.length - 3}` : uniq.join(", ");
}

export default function GraphPanel({ graph }: { graph: Graph }) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<cytoscape.Core | null>(null);
  const lastShape = useRef("");
  const [selected, setSelected] = useState<{ node?: GraphNode; edges?: GraphEdge[]; title: string } | null>(null);

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
        { selector: "node", style: { label: "data(label)", "font-size": 11, color: "#888", "text-valign": "bottom", "text-margin-y": 5, "text-wrap": "wrap", "text-max-width": "140px", "background-color": "#2b7de9", width: 28, height: 28 } },
        { selector: "node.external", style: { "background-color": "#999" } },
        { selector: "node.multicast", style: { shape: "diamond", "background-color": "#e69f00" } },
        { selector: "edge", style: { width: "data(w)", "line-color": "#8aa", "target-arrow-color": "#8aa", "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", "font-size": 9, color: "#888", "text-rotation": "autorotate", "text-margin-y": -7, "text-wrap": "wrap", "text-max-width": "160px" } },
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
    layout.one("layoutstop", () => { c.maxZoom(3); });
    layout.run();
  }, [graph, pairs]);

  return (
    <div>
      <div className="legend muted">
        <span style={{ color: "#2b7de9" }}>●</span> activo en alcance · <span style={{ color: "#999" }}>●</span> fuera de alcance ·{" "}
        <span style={{ color: "#e69f00" }}>◆</span> multicast/broadcast · <span style={{ color: "#d9480f" }}>―</span> protocolo industrial
      </div>
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
            <ul>{selected.edges.map((e, i) => <li key={i}>{e.protocol} {e.transport}/{e.port} · {e.packets} pkts · {e.bytes} B</li>)}</ul>
          )}
        </div>
      )}
      <table className="card">
        <thead><tr><th>Origen (cliente)</th><th>Destino (servidor)</th><th>Protocolo</th><th>Puerto</th><th>Paquetes</th><th>Bytes</th></tr></thead>
        <tbody>
          {graph.edges.map((e, i) => (
            <tr key={i}><td>{e.src}</td><td>{e.dst}</td><td>{e.protocol}</td><td>{e.transport}/{e.port}</td><td>{e.packets}</td><td>{e.bytes}</td></tr>
          ))}
          {graph.edges.length === 0 && <tr><td colSpan={6}>Sin flujos todavía.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
