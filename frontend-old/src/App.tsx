import { useEffect, useState } from "react";
import { api, AuditType, Campaign, CampaignStatus } from "./api";
import CampaignDetail from "./CampaignDetail";

const TYPES: AuditType[] = ["OT", "IoT", "Web", "Mobile", "Red", "Mixta"];
const STATUSES: CampaignStatus[] = ["planned", "active", "closed"];
const today = () => new Date().toISOString().slice(0, 10);

export default function App() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState({
    name: "",
    audit_type: "OT" as AuditType,
    start_date: today(),
    scope: "",
    llm_enabled: false,
  });

  const run = async (fn: () => Promise<unknown>) => {
    try {
      setError("");
      await fn();
      setCampaigns(await api.list());
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    run(async () => {});
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.create({ ...form, end_date: null });
      setForm({ ...form, name: "", scope: "" });
    });
  };

  const selected = campaigns.find((c) => c.id === selectedId);
  if (selected) return <CampaignDetail campaign={selected} onBack={() => setSelectedId(null)} onCampaignChange={() => run(async () => {})} />;

  return (
    <main>
      <h1>Campañas de auditoría</h1>
      {error && <p className="error">{error}</p>}

      <form onSubmit={submit} className="card">
        <h2>Nueva campaña</h2>
        <label>
          Nombre
          <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label>
          Tipo
          <select value={form.audit_type} onChange={(e) => setForm({ ...form, audit_type: e.target.value as AuditType })}>
            {TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <label>
          Fecha de inicio
          <input type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </label>
        <label>
          Alcance (un rango/host por línea)
          <textarea rows={3} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} />
        </label>
        <label className="inline">
          <input type="checkbox" checked={form.llm_enabled} onChange={(e) => setForm({ ...form, llm_enabled: e.target.checked })} />
          Permitir LLM en esta campaña (los datos que lea el agente se envían a la API)
        </label>
        <button type="submit">Crear</button>
      </form>

      <table className="card">
        <thead>
          <tr><th>Nombre</th><th>Tipo</th><th>Inicio</th><th>Estado</th><th>LLM</th><th /></tr>
        </thead>
        <tbody>
          {campaigns.map((c) => (
            <tr key={c.id}>
              <td><a href="#" onClick={(e) => { e.preventDefault(); setSelectedId(c.id); }}>{c.name}</a></td>
              <td>{c.audit_type}</td>
              <td>{c.start_date}</td>
              <td>
                <select value={c.status} onChange={(e) => run(() => api.update(c.id, { status: e.target.value as CampaignStatus }))}>
                  {STATUSES.map((s) => <option key={s}>{s}</option>)}
                </select>
              </td>
              <td>{c.llm_enabled ? "sí" : "no"}</td>
              <td>
                <button onClick={() => confirm(`¿Borrar "${c.name}"?`) && run(() => api.remove(c.id))}>Borrar</button>
              </td>
            </tr>
          ))}
          {campaigns.length === 0 && <tr><td colSpan={6}>Sin campañas todavía.</td></tr>}
        </tbody>
      </table>
    </main>
  );
}
