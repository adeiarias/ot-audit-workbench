import { useEffect, useRef, useState } from "react";
import { api, Campaign, ChatCall, ChatView } from "./api";

const STATUS: Record<ChatCall["status"], string> = {
  pending: "⏸ pendiente de tu aprobación", running: "⏳ ejecutando", done: "✅ ejecutada", failed: "❌ no ejecutada / error", denied: "🚫 denegada",
};

function CallCard({ call, onChange }: { call: ChatCall; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const act = async (fn: () => Promise<unknown>) => {
    try { setError(""); await fn(); } catch (e) { setError(String(e)); }
    onChange();
  };
  return (
    <div className={`card call ${call.status}`}>
      <div><strong>{call.name}</strong> <code>{JSON.stringify(call.input)}</code></div>
      <div className="muted">{STATUS[call.status]}{call.requires_approval ? " · herramienta ACTIVA" : " · consulta local"}</div>
      {call.status === "pending" && (
        <div className="row">
          <p className="grow">El asistente quiere ejecutar <strong>{call.name}</strong> con los argumentos de arriba. Se enviará tráfico al objetivo.</p>
          <button onClick={() => act(() => api.approveCall(call.id))}>Aprobar y ejecutar</button>
          <button className="danger" onClick={() => act(() => api.denyCall(call.id))}>Denegar</button>
        </div>
      )}
      {call.result_preview && call.status !== "pending" && (
        <>
          <button className="linkish" onClick={() => setOpen(!open)}>{open ? "Ocultar resultado" : "Ver resultado"}</button>
          {open && <pre>{call.result_preview}</pre>}
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

export default function ChatPanel({ campaign, chat, onChange, onCampaignChange }: {
  campaign: Campaign; chat: ChatView | null; onChange: () => void; onCampaignChange: () => void;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [chat?.messages.length, chat?.busy]);

  if (!chat) return <p className="muted">Cargando…</p>;
  const pending = chat.messages.some((m) => m.calls.some((c) => c.status === "pending" || c.status === "running"));
  const canSend = chat.enabled && chat.configured && !chat.busy && !pending && text.trim() !== "";

  const toggle = async (patch: Partial<Campaign>) => {
    setError("");
    try { await api.update(campaign.id, patch); onCampaignChange(); onChange(); } catch (e) { setError(String(e)); }
  };
  const send = async () => {
    if (!canSend) return;
    const msg = text.trim();
    setError("");
    try { await api.sendChat(campaign.id, msg); setText(""); } catch (e) { setError(String(e)); }
    onChange();
  };

  return (
    <div>
      <div className="card">
        <div className="row">
          <label className="inline">
            <input type="checkbox" checked={chat.enabled} onChange={(e) => {
              const dest = `${chat.provider_label} — ${chat.external ? "servidor EXTERNO a tu red" : "servidor local / red interna"}`;
              if (!e.target.checked || confirm(`Al habilitar el asistente, los datos que lea (salidas de herramientas, activos, hallazgos) se enviarán a: ${dest}` + (chat.redaction ? ", con IPs, MAC y hostnames seudonimizados y secretos eliminados." : " SIN seudonimizar.") + (chat.external ? "\n\n¿Tienes permiso del cliente para ello?" : ""))) toggle({ llm_enabled: e.target.checked });
            }} />
            Permitir LLM en esta campaña
          </label>
          <label className="inline">
            <input type="checkbox" checked={chat.redaction} onChange={(e) => {
              if (e.target.checked || confirm("Sin seudonimizar, las IPs, MAC y hostnames reales se enviarán a la API. ¿Continuar?")) toggle({ llm_redaction: e.target.checked });
            }} />
            Anonimizar IPs / MAC / hostnames al enviar
          </label>
          <span className="muted grow">Modelo: {chat.model} · {chat.provider_label} · {chat.external ? "☁ servidor externo" : "🏠 local"}</span>
          <button onClick={() => confirm("¿Borrar la conversación? Los hallazgos y ejecuciones no se tocan.") && api.resetChat(campaign.id).then(onChange).catch((e) => setError(String(e)))} disabled={chat.busy || pending}>
            Nueva conversación
          </button>
        </div>
        {!chat.enabled && <p className="muted">El asistente está desactivado: no se envía nada al modelo. Actívalo para consultar sobre esta auditoría.</p>}
        {chat.enabled && !chat.configured && <p className="error">LLM sin configurar: {chat.problem}</p>}
        {chat.enabled && chat.configured && !chat.tools && <p className="muted">Herramientas desactivadas (AUDIT_LLM_TOOLS=0): el asistente solo conoce la instantánea inicial de la campaña y no puede proponer ejecuciones.</p>}
        {error && <p className="error">{error}</p>}
      </div>

      <div className="chat">
        {chat.messages.length === 0 && <p className="muted">Pregunta lo que quieras sobre esta auditoría: «resume la superficie de ataque», «¿qué hallazgos faltan por confirmar?», «¿qué prueba pasiva haría ahora sobre el PLC?»…</p>}
        {chat.messages.map((m) => (
          <div key={m.id} className={`bubble ${m.role}`}>
            {m.text && <div className="btext">{m.text}</div>}
            {m.calls.map((c) => <CallCard key={c.id} call={c} onChange={onChange} />)}
          </div>
        ))}
        {chat.busy && <div className="bubble assistant muted">⏳ pensando…</div>}
        <div ref={end} />
      </div>

      <div className="card chatinput">
        <textarea rows={3} value={text} disabled={!chat.enabled || !chat.configured} placeholder={pending ? "Resuelve primero las acciones pendientes de arriba" : "Escribe tu pregunta (Ctrl+Enter para enviar)"}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && send()} />
        <button disabled={!canSend} onClick={send}>Enviar</button>
      </div>
    </div>
  );
}
