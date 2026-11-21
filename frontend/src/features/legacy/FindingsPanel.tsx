import { useEffect, useRef, useState } from "react";
import { api, Asset, Evidence, evidenceUrl, Finding, FindingInput, FindingPhase, FindingStatus } from "@/lib/api";
import { RatingBadge as Badge } from "@/components/ui/badge";
import { findingLabel } from "./EvidencePanel";

const PHASES: [FindingPhase, string][] = [["discovery", "Descubrimiento"], ["exploitation", "Explotación"], ["post_exploitation", "Post-Explotación"]];
const STATUSES: [FindingStatus, string][] = [["draft", "borrador"], ["confirmed", "confirmado"], ["false_positive", "falso positivo"]];

export const ratingOf = (score: number | null) =>
  score === null || Number.isNaN(score) ? "" : score === 0 ? "None" : score < 4 ? "Low" : score < 7 ? "Medium" : score < 9 ? "High" : "Critical";

export function RatingBadge({ rating, score }: { rating: string; score: number | null }) {
  return <Badge rating={rating} score={score} />;
}

const EMPTY: FindingInput = {
  identifier: "", name: "", phase: "discovery", status: "draft", cvss_vector: "", cvss_score: null,
  description: "", poc: "", impact: "", recommendations: "", affected_other: "", depends_on_id: null, asset_ids: [],
};

export function Editor({ campaignId, finding, findings, assets, evidence, onDone, onSaved }: {
  campaignId: number; finding: Finding | null; findings: Finding[]; assets: Asset[]; evidence: Evidence[];
  onDone: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState<FindingInput>(finding ? { ...EMPTY, ...finding } : EMPTY);
  const [score, setScore] = useState(finding?.cvss_score?.toString() ?? "");
  const [error, setError] = useState("");
  const [computed, setComputed] = useState(false); // la puntuación sale del vector (CVSS 3.x); si no, es manual
  const poc = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const v = f.cvss_vector;
    if (!v) return setComputed(false);
    let alive = true;
    const t = setTimeout(() => {
      api.cvssScore(v).then((r) => { if (alive) { setScore(String(r.score)); setComputed(true); } }).catch(() => alive && setComputed(false));
    }, 300);
    return () => { alive = false; clearTimeout(t); };
  }, [f.cvss_vector]);
  const set = <K extends keyof FindingInput>(k: K, v: FindingInput[K]) => setF((p) => ({ ...p, [k]: v }));
  const scoreNum = score.trim() === "" ? null : Number(score);
  const mine = finding ? evidence.filter((e) => e.finding_id === finding.id).sort((a, b) => a.position - b.position) : [];

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (scoreNum !== null && (Number.isNaN(scoreNum) || scoreNum < 0 || scoreNum > 10)) return setError("La puntuación CVSS debe estar entre 0 y 10");
    const body = { ...f, cvss_score: scoreNum };
    try {
      setError("");
      if (finding) await api.updateFinding(finding.id, body);
      else await api.createFinding(campaignId, body);
      onSaved();
      onDone();
    } catch (err) {
      setError(String(err));
    }
  };

  const insertMarker = (n: number, caption: string) => {
    const marker = `[Evidencia ${n}: ${caption || "descripción"}]`;
    const el = poc.current;
    const pos = el ? el.selectionStart : f.poc.length;
    const end = el ? el.selectionEnd : pos;
    set("poc", `${f.poc.slice(0, pos)}${marker}${f.poc.slice(end)}`);
    el?.focus();
  };

  return (
    <form className="card editor" onSubmit={save}>
      <h2>{finding ? "Editar hallazgo" : "Nuevo hallazgo"}</h2>
      <div className="row">
        <label>Identifier (lo asignas tú)<input value={f.identifier} maxLength={50} placeholder="[ID]" onChange={(e) => set("identifier", e.target.value)} /></label>
        <label className="grow">Name *<input required value={f.name} maxLength={300} onChange={(e) => set("name", e.target.value)} /></label>
      </div>
      <div className="row">
        <label>Fase
          <select value={f.phase} onChange={(e) => set("phase", e.target.value as FindingPhase)}>{PHASES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label>Estado
          <select value={f.status} onChange={(e) => set("status", e.target.value as FindingStatus)}>{STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        <label>Depende de
          <select value={f.depends_on_id ?? ""} onChange={(e) => set("depends_on_id", e.target.value ? Number(e.target.value) : null)}>
            <option value="">— ninguno —</option>
            {findings.filter((x) => x.id !== finding?.id).map((x) => <option key={x.id} value={x.id}>{findingLabel(x)}</option>)}
          </select>
        </label>
      </div>
      <div className="row">
        <label className="grow">Vector CVSS (3.0/3.1: la puntuación se calcula sola)
          <input value={f.cvss_vector} placeholder="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" onChange={(e) => set("cvss_vector", e.target.value.trim())} />
        </label>
        <label>Puntuación
          <input value={score} inputMode="decimal" placeholder="0–10" size={6} readOnly={computed} title={computed ? "Calculada desde el vector" : "Manual (CVSS 4.0 o sin vector)"} onChange={(e) => setScore(e.target.value)} />
        </label>
        <div className="ratingbox"><span className="muted">Criticality</span><RatingBadge rating={ratingOf(scoreNum)} score={scoreNum} /></div>
      </div>

      <fieldset>
        <legend>Affected assets</legend>
        {assets.length === 0 && <span className="muted">No hay activos descubiertos todavía. </span>}
        {assets.map((a) => (
          <label key={a.id} className="inline">
            <input type="checkbox" checked={f.asset_ids.includes(a.id)}
              onChange={(e) => set("asset_ids", e.target.checked ? [...f.asset_ids, a.id] : f.asset_ids.filter((x) => x !== a.id))} />
            {a.ip}{a.hostname && ` (${a.hostname})`}
          </label>
        ))}
        <label>Otros activos (sin IP, p. ej. "Vending Machine")
          <input value={f.affected_other} maxLength={500} onChange={(e) => set("affected_other", e.target.value)} />
        </label>
      </fieldset>

      <label>Description<textarea rows={5} value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
      <label>Proof of Concept
        <textarea ref={poc} rows={8} value={f.poc} onChange={(e) => set("poc", e.target.value)} />
      </label>
      {finding && (
        <div className="muted">
          Evidencias de este hallazgo — inserta el marcador en el PoC (en la posición del cursor):
          {mine.length === 0 && " ninguna todavía (vincúlalas desde la pestaña Evidencias)."}
          <div className="evmini">
            {mine.map((e, i) => (
              <button type="button" key={e.id} onClick={() => insertMarker(i + 1, e.caption)} title={e.caption}>
                <img src={evidenceUrl(e)} alt="" /> Insertar «Evidencia {i + 1}»
              </button>
            ))}
          </div>
        </div>
      )}
      <label>Impact<textarea rows={4} value={f.impact} onChange={(e) => set("impact", e.target.value)} /></label>
      <label>Recommendations<textarea rows={4} value={f.recommendations} onChange={(e) => set("recommendations", e.target.value)} /></label>

      {error && <p className="error">{error}</p>}
      <div className="row">
        <button type="submit">Guardar</button>
        <button type="button" onClick={onDone}>Cancelar</button>
        {finding && (
          <button type="button" className="danger" onClick={() => confirm(`¿Borrar "${finding.name}"? Sus evidencias se conservan sin hallazgo.`) && api.deleteFinding(finding.id).then(() => { onSaved(); onDone(); })}>
            Borrar
          </button>
        )}
      </div>
    </form>
  );
}

export default function FindingsPanel({ campaignId, findings, assets, evidence, onChange }: {
  campaignId: number; findings: Finding[]; assets: Asset[]; evidence: Evidence[]; onChange: () => void;
}) {
  const [editing, setEditing] = useState<Finding | "new" | null>(null);

  if (editing) {
    return (
      <Editor key={editing === "new" ? "new" : editing.id} campaignId={campaignId} finding={editing === "new" ? null : editing}
        findings={findings} assets={assets} evidence={evidence} onDone={() => setEditing(null)} onSaved={onChange} />
    );
  }
  return (
    <div>
      <p className="mb-4"><button onClick={() => setEditing("new")}>+ Nuevo hallazgo</button></p>
      {PHASES.map(([phase, label]) => {
        const list = findings.filter((f) => f.phase === phase);
        if (!list.length) return null;
        return (
          <div key={phase}>
            <h2>{label}</h2>
            <table className="card findings">
              <thead><tr><th>ID</th><th>Nombre</th><th>Criticality</th><th>Activos</th><th>Evid.</th><th>Estado</th></tr></thead>
              <tbody>
                {list.map((f) => (
                  <tr key={f.id} className="click" onClick={() => setEditing(f)}>
                    <td>{f.identifier || <span className="muted">[ID]</span>}</td>
                    <td>{f.name}</td>
                    <td><RatingBadge rating={f.rating} score={f.cvss_score} /></td>
                    <td>{[...f.asset_ids.map((id) => assets.find((a) => a.id === id)?.ip ?? "?"), ...(f.affected_other ? [f.affected_other] : [])].join(", ")}</td>
                    <td>{evidence.filter((e) => e.finding_id === f.id).length}</td>
                    <td>{STATUSES.find(([v]) => v === f.status)?.[1]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
      {findings.length === 0 && <p className="muted">Sin hallazgos todavía.</p>}
    </div>
  );
}
