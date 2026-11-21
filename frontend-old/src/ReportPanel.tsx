import { useCallback, useEffect, useRef, useState } from "react";
import { api, Campaign, ReportData, ReportView } from "./api";

type TextKey = "introduction" | "methodology" | "dut_description" | "exploitation_summary" | "remediation_summary" | "conclusions";

const TEXTS: { key: TextKey; label: string; rows: number; hint: string; ai?: boolean }[] = [
  { key: "introduction", label: "1. Introducción", rows: 3, hint: "Vacío = texto estándar." },
  { key: "methodology", label: "2. Metodología", rows: 3, hint: "Vacío = texto estándar." },
  { key: "dut_description", label: "4. Descripción del DUT", rows: 4, hint: "Qué es el sistema auditado y su contexto." },
  { key: "exploitation_summary", label: "6. Resumen de Explotación", rows: 7, hint: "Prosa: la cadena de ataque de principio a fin (sin viñetas).", ai: true },
  { key: "remediation_summary", label: "7. Resumen de Remediaciones", rows: 6, hint: "4–8 viñetas por tema: • **Tema**: explicación.", ai: true },
  { key: "conclusions", label: "9. Conclusiones", rows: 6, hint: "Dos párrafos: valoración de riesgo y línea de acción.", ai: true },
];

export default function ReportPanel({ campaign, refreshKey }: { campaign: Campaign; refreshKey: string }) {
  const [view, setView] = useState<ReportView | null>(null);
  const [form, setForm] = useState<ReportData | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [showWarn, setShowWarn] = useState(true);

  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;

  const load = useCallback(async () => {
    try {
      const v = await api.report(campaign.id);
      setView(v);
      setForm((f) => (f && dirtyRef.current ? f : v.data)); // no pisar lo que se está editando
    } catch (e) {
      setError(String(e));
    }
  }, [campaign.id]);
  useEffect(() => { load(); }, [load, refreshKey]); // refreshKey: cambian hallazgos/evidencias → recalcula avisos

  if (!view || !form) return <p className="muted">{error || "Cargando…"}</p>;
  const set = <K extends keyof ReportData>(k: K, v: ReportData[K]) => { setForm({ ...form, [k]: v }); setDirty(true); setMsg(""); };

  const save = async (): Promise<boolean> => {
    try {
      setError("");
      const v = await api.saveReport(campaign.id, form);
      setView(v); setForm(v.data); setDirty(false); setMsg("Guardado.");
      return true;
    } catch (e) { setError(String(e)); return false; }
  };

  const draft = async (key: TextKey) => {
    if (form[key].trim() && !confirm("Esto reemplazará el texto actual de la sección por un borrador de la IA. ¿Continuar?")) return;
    setBusy(key); setError(""); setMsg("");
    try {
      const r = await api.draftSection(campaign.id, key);
      set(key, r.text);
      setMsg("Borrador generado: revísalo, corrígelo y guarda. No se ha guardado nada todavía.");
    } catch (e) { setError(String(e)); }
    setBusy("");
  };

  const download = async (fmt: "docx" | "pdf" | "md") => {
    setBusy(fmt); setError(""); setMsg("");
    if (dirty && !(await save())) { setBusy(""); return; }
    try { setMsg(`Descargado: ${await api.exportReport(campaign.id, fmt)}`); } catch (e) { setError(String(e)); }
    setBusy("");
  };

  const aiOff = !view.llm.enabled ? "Habilita el LLM en la pestaña Asistente" : !view.llm.configured ? "El proveedor LLM no está configurado (mira el aviso en la pestaña Asistente)" : "";

  return (
    <div className="editor">
      <div className="card">
        <h2>Datos del informe</h2>
        <div className="row">
          <label className="grow">Cliente<input value={form.client} onChange={(e) => set("client", e.target.value)} /></label>
          <label className="grow">Sistema auditado (DUT)<input value={form.dut_name} onChange={(e) => set("dut_name", e.target.value)} /></label>
        </div>
        <div className="row">
          <label>Tipo de prueba
            <select value={form.test_type} onChange={(e) => set("test_type", e.target.value as ReportData["test_type"])}>
              <option value="">— sin indicar —</option><option value="white">White box</option><option value="grey">Grey box</option><option value="black">Black box</option>
            </select>
          </label>
          <label>Idioma del informe
            <select value={form.language} onChange={(e) => set("language", e.target.value as "es" | "en")}><option value="es">Español</option><option value="en">English</option></select>
          </label>
          <label>Versión<input size={6} value={form.version} onChange={(e) => set("version", e.target.value)} /></label>
          <label>Fecha<input type="date" value={form.report_date ?? ""} onChange={(e) => set("report_date", e.target.value || null)} /></label>
          <label className="grow">Autor<input value={form.author} onChange={(e) => set("author", e.target.value)} /></label>
          <label>Clasificación<input value={form.classification} onChange={(e) => set("classification", e.target.value)} /></label>
        </div>
        <p className="muted">El idioma cambia los títulos y las etiquetas fijas; el texto que escribes se respeta tal cual. Fecha vacía = fecha de generación.</p>
      </div>

      {TEXTS.map((t) => (
        <div key={t.key} className="card">
          <div className="row">
            <strong className="grow">{t.label}</strong>
            {t.ai && <button type="button" disabled={!!aiOff || busy !== ""} title={aiOff || `Redacta un borrador a partir de los hallazgos. Se envía a ${view.llm.provider_label} (${view.llm.external ? "servidor externo" : "local"}) con IPs/MAC/hostnames anonimizados si la campaña lo tiene activado.`} onClick={() => draft(t.key)}>
              {busy === t.key ? "⏳ redactando…" : "✨ Borrador con IA"}
            </button>}
          </div>
          <textarea rows={t.rows} value={form[t.key]} onChange={(e) => set(t.key, e.target.value)} />
          <span className="muted">{t.hint}</span>
        </div>
      ))}

      <div className="card">
        <div className="row">
          <button disabled={!dirty || busy !== ""} onClick={save}>Guardar{dirty ? " *" : ""}</button>
          <button disabled={busy !== ""} onClick={() => download("docx")}>{busy === "docx" ? "⏳ generando…" : "Descargar Word (.docx)"}</button>
          <button disabled={busy !== "" || !view.pdf_available} title={view.pdf_available ? "" : "LibreOffice no está disponible"} onClick={() => download("pdf")}>{busy === "pdf" ? "⏳ generando (puede tardar)…" : "Descargar PDF"}</button>
          <button disabled={busy !== ""} onClick={() => download("md")}>Descargar Markdown</button>
          {msg && <span className="muted">{msg}</span>}
        </div>
        {error && <p className="error">{error}</p>}
        <p className="muted">Descargar guarda antes los cambios. Los hallazgos en estado «falso positivo» no se incluyen; las evidencias se incrustan donde el PoC cita «[Evidencia N: …]».</p>
      </div>

      <div className="card">
        <button className="linkish" onClick={() => setShowWarn(!showWarn)}>{showWarn ? "▾" : "▸"} Antes de entregar ({view.warnings.length} aviso{view.warnings.length === 1 ? "" : "s"})</button>
        {showWarn && (view.warnings.length === 0 ? <p>✅ Nada pendiente.</p> : <ul>{view.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>)}
      </div>
    </div>
  );
}
