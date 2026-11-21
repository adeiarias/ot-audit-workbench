import { useEffect, useRef, useState } from "react";
import { api, Evidence, evidenceUrl, Finding } from "@/lib/api";

export const findingLabel = (f: Finding) => (f.identifier ? `${f.identifier} · ` : "") + f.name;

export default function EvidencePanel({ campaignId, evidence, findings, onChange }: {
  campaignId: number; evidence: Evidence[]; findings: Finding[]; onChange: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);

  const upload = async (files: (File | Blob)[]) => {
    if (!files.length) return;
    setBusy(true);
    setError("");
    for (const f of files) {
      try {
        await api.uploadEvidence(campaignId, f);
      } catch (e) {
        setError(String(e));
      }
    }
    setBusy(false);
    if (input.current) input.current.value = "";
    onChange();
  };

  // Pegar capturas desde el portapapeles (Ctrl+V) mientras esta pestaña está abierta
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []).filter((f) => f.type.startsWith("image/"));
      if (files.length) {
        e.preventDefault();
        upload(files);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });

  return (
    <div>
      <div
        className={`card dropzone${over ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(Array.from(e.dataTransfer.files)); }}
      >
        <strong>Arrastra imágenes aquí, pega una captura (Ctrl+V) o </strong>
        <input ref={input} type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple disabled={busy}
          onChange={(e) => upload(Array.from(e.target.files ?? []))} />
        <p className="muted">PNG, JPEG, GIF o WebP (máx. 20 MB). Se guarda el hash SHA-256 de cada imagen; las repetidas se rechazan.</p>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="evgrid">
        {evidence.map((e) => {
          const linked = findings.find((f) => f.id === e.finding_id);
          const n = linked ? evidence.filter((x) => x.finding_id === linked.id).sort((a, b) => a.position - b.position).findIndex((x) => x.id === e.id) + 1 : 0;
          return (
            <div key={e.id} className="card evcard">
              <a href={evidenceUrl(e)} target="_blank" rel="noreferrer">
                <img src={evidenceUrl(e)} alt={e.caption || e.filename} loading="lazy" />
              </a>
              <input
                key={`${e.id}-${e.caption}`}
                defaultValue={e.caption}
                placeholder="Descripción (qué muestra)"
                maxLength={500}
                onBlur={(ev) => ev.target.value !== e.caption && api.updateEvidence(e.id, { caption: ev.target.value }).then(onChange)}
              />
              <select value={e.finding_id ?? ""} onChange={(ev) => api.updateEvidence(e.id, { finding_id: ev.target.value ? Number(ev.target.value) : null }).then(onChange)}>
                <option value="">— sin hallazgo —</option>
                {findings.map((f) => <option key={f.id} value={f.id}>{findingLabel(f)}</option>)}
              </select>
              <div className="muted evmeta">
                <span title={`${e.filename} · sha256 ${e.sha256}`}>{n ? `Evidencia ${n}` : e.filename}</span>
                <button onClick={() => confirm("¿Borrar esta evidencia? Se elimina el fichero.") && api.deleteEvidence(e.id).then(onChange)}>Borrar</button>
              </div>
            </div>
          );
        })}
      </div>
      {evidence.length === 0 && <p className="muted">Sin evidencias todavía.</p>}
    </div>
  );
}
