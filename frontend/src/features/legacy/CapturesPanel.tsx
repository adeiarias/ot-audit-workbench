import { useRef, useState } from "react";
import { api, Capture } from "@/lib/api";

const mb = (n: number) => (n / 1024 / 1024).toFixed(n < 1024 * 1024 ? 2 : 1) + " MB";

export default function CapturesPanel({ campaignId, captures, onChange }: { campaignId: number; captures: Capture[]; onChange: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    for (const f of Array.from(files)) {
      try {
        await api.uploadCapture(campaignId, f);
      } catch (e) {
        setError(`${f.name}: ${e}`);
      }
    }
    setBusy(false);
    if (input.current) input.current.value = "";
    onChange();
  };

  return (
    <div>
      <div className="card">
        <h2>Subir captura (.pcap / .pcapng)</h2>
        <input ref={input} type="file" accept=".pcap,.pcapng,.cap" multiple disabled={busy} onChange={(e) => upload(e.target.files)} />
        <p className="muted">El análisis es offline (tshark) y no genera tráfico. Los hosts fuera del alcance aparecen en el mapa pero no se crean como activos.</p>
        {error && <p className="error">{error}</p>}
      </div>
      <table className="card">
        <thead><tr><th title="Es el capture_id que piden las herramientas de análisis de capturas">ID</th><th>Fichero</th><th>Tamaño</th><th>Paquetes</th><th>No IP</th><th>Estado</th><th /></tr></thead>
        <tbody>
          {captures.map((c) => (
            <tr key={c.id}>
              <td className="tabular-nums">{c.id}</td>
              <td title={`sha256 ${c.sha256}`}>{c.filename}</td>
              <td>{mb(c.size)}</td>
              <td>{c.status === "analyzed" ? c.packets : "–"}</td>
              <td title="Paquetes sin capa IP (ARP, LLDP, PROFINET…): no aparecen en el mapa lógico">{c.status === "analyzed" ? c.non_ip_packets : "–"}</td>
              <td>{c.status === "analyzing" ? "⏳ analizando" : c.status === "analyzed" ? "✅ ok" : <span className="error" title={c.error}>❌ error</span>}</td>
              <td>
                <button onClick={() => api.reanalyze(c.id).then(onChange)}>Reanalizar</button>{" "}
                <button onClick={() => confirm(`¿Borrar "${c.filename}"? Se elimina el fichero y sus flujos.`) && api.deleteCapture(c.id).then(onChange)}>Borrar</button>
              </td>
            </tr>
          ))}
          {captures.length === 0 && <tr><td colSpan={7}>Sin capturas todavía.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
