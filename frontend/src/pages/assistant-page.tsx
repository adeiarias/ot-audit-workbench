import { Bot, Check, Cloud, Home, Loader2, PauseCircle, RotateCcw, Send, Settings, Wrench, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Textarea } from "@/components/ui/input";
import { Alert } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useCampaign } from "@/features/campaign-context";
import { api, type ChatCall, type LLMProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

const CALL_STATUS: Record<ChatCall["status"], { label: string; cls: string }> = {
  pending: { label: "Pendiente de tu aprobación", cls: "text-amber-600" }, running: { label: "Ejecutando…", cls: "text-sky-600" },
  done: { label: "Ejecutada", cls: "text-emerald-600" }, failed: { label: "No ejecutada / error", cls: "text-destructive" }, denied: { label: "Denegada", cls: "text-muted-foreground" },
};

function CallCard({ call, onChange }: { call: ChatCall; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setBusy(false); onChange();
  };
  const st = CALL_STATUS[call.status];
  return (
    <div className={cn("mt-3 grid gap-2 rounded-lg border bg-background p-3 text-sm", call.status === "pending" && "border-amber-500/60 bg-amber-500/5")}>
      <div className="flex flex-wrap items-center gap-2">
        <Wrench className="size-4 text-muted-foreground" />
        <span className="font-semibold">{call.name}</span>
        <code className="min-w-0 break-all rounded bg-muted px-1.5 py-0.5 text-xs">{JSON.stringify(call.input)}</code>
        <Badge variant={call.requires_approval ? "warning" : "secondary"} className="ml-auto">{call.requires_approval ? "herramienta ACTIVA" : "consulta local"}</Badge>
      </div>
      <p className={cn("flex items-center gap-1.5 text-xs font-medium", st.cls)}>{call.status === "running" && <Loader2 className="size-3 animate-spin" />}{call.status === "pending" && <PauseCircle className="size-3.5" />}{st.label}</p>
      {call.status === "pending" && (
        <div className="flex flex-wrap items-center gap-3 border-t pt-3">
          <p className="min-w-[14rem] flex-1 text-muted-foreground">El asistente quiere ejecutar <strong className="text-foreground">{call.name}</strong> con estos argumentos. Se enviará tráfico al objetivo.</p>
          <Button size="sm" disabled={busy} onClick={() => act(() => api.approveCall(call.id))}><Check /> Aprobar y ejecutar</Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => api.denyCall(call.id))}><X /> Denegar</Button>
        </div>
      )}
      {call.result_preview && call.status !== "pending" && (
        <div>
          <button className="text-xs text-primary underline-offset-4 hover:underline" onClick={() => setOpen(!open)}>{open ? "Ocultar resultado" : "Ver resultado"}</button>
          {open && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">{call.result_preview}</pre>}
        </div>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

type Confirm = { title: string; description: string; label: string; action: () => Promise<unknown> };

export default function AssistantPage() {
  const { campaign, chat, refresh } = useCampaign();
  const [profiles, setProfiles] = useState<LLMProfile[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [resetting, setResetting] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { api.llmProfiles().then((r) => setProfiles(r.profiles)).catch(() => undefined); }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [chat?.messages.length, chat?.busy]);

  if (!chat) return <p className="text-sm text-muted-foreground">Cargando…</p>;
  const pending = chat.messages.some((m) => m.calls.some((c) => c.status === "pending" || c.status === "running"));
  const canSend = chat.enabled && chat.configured && !chat.busy && !pending && text.trim() !== "";
  const mismatch = chat.conversation_provider !== null && chat.conversation_provider !== chat.provider;
  const defaultName = profiles.find((p) => p.is_default)?.name ?? "Entorno del backend";
  const dest = `${chat.provider_label} (${chat.external ? "servidor EXTERNO a tu red" : "servidor local / red interna"})`;

  const patch = async (body: Parameters<typeof api.update>[1]) => { setError(""); try { await api.update(campaign.id, body); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } };
  const send = async () => {
    if (!canSend) return;
    const msg = text.trim();
    setError("");
    try { await api.sendChat(campaign.id, msg); setText(""); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    refresh();
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid gap-4 p-5 lg:grid-cols-[1fr_auto]">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <label className="text-sm font-medium">Proveedor de IA para esta campaña</label>
              <SimpleSelect
                value={campaign.llm_profile_id ? String(campaign.llm_profile_id) : "default"}
                onChange={(v) => patch({ llm_profile_id: v === "default" ? null : Number(v) })}
                options={[{ value: "default", label: `Predeterminado (${defaultName})` }, ...profiles.map((p) => ({ value: String(p.id), label: `${p.name} · ${p.provider}` }))]}
              />
              <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                {chat.model || "—"} · {chat.provider_label}
                <Badge variant={chat.external ? "warning" : "success"}>{chat.external ? <><Cloud className="size-3" /> externo</> : <><Home className="size-3" /> local</>}</Badge>
              </p>
            </div>
            <div className="grid content-start gap-3">
              <label className="flex items-center gap-3 text-sm">
                <Switch checked={chat.enabled} onCheckedChange={(on) => on
                  ? setConfirm({ title: "¿Habilitar el asistente de IA?", label: "Habilitar", description: `Los datos que lea (salidas de herramientas, activos, hallazgos) se enviarán a: ${dest}${chat.redaction ? ", con IPs, MAC y hostnames seudonimizados y secretos eliminados" : " SIN seudonimizar"}.${chat.external ? " ¿Tienes permiso del cliente para ello?" : ""}`, action: () => patch({ llm_enabled: true }) })
                  : patch({ llm_enabled: false })} />
                Permitir IA en esta campaña
              </label>
              <label className="flex items-center gap-3 text-sm">
                <Switch checked={chat.redaction} onCheckedChange={(on) => on ? patch({ llm_redaction: true })
                  : setConfirm({ title: "¿Enviar los datos sin anonimizar?", label: "Enviar sin anonimizar", description: `Sin seudonimizar, las IPs, MAC y hostnames reales se enviarán a ${dest}.`, action: () => patch({ llm_redaction: false }) })} />
                Anonimizar IPs, MAC y hostnames al enviar
              </label>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <Button asChild variant="ghost" size="sm"><Link to="/settings"><Settings /> Gestionar perfiles</Link></Button>
            <Button variant="outline" size="sm" disabled={chat.busy || pending || chat.messages.length === 0} onClick={() => setResetting(true)}><RotateCcw /> Nueva conversación</Button>
          </div>
        </CardContent>
      </Card>

      {!chat.enabled && <Alert tone="info" title="Asistente desactivado">No se envía nada a ningún modelo. Actívalo con el interruptor para consultar sobre esta auditoría.</Alert>}
      {chat.enabled && !chat.configured && <Alert tone="error" title="Proveedor sin configurar">{chat.problem} <Link to="/settings" className="underline">Ir a Ajustes</Link></Alert>}
      {chat.enabled && chat.configured && !chat.tools && <Alert tone="info">Herramientas desactivadas en este perfil: el asistente solo conoce la instantánea inicial y no puede proponer ejecuciones.</Alert>}
      {mismatch && chat.messages.length > 0 && <Alert tone="warning" title="Cambio de proveedor">Esta conversación se inició con «{chat.conversation_provider}» y ahora la campaña usa «{chat.provider}». Pulsa «Nueva conversación» para continuar con el nuevo.</Alert>}
      {error && <Alert tone="error">{error}</Alert>}

      <div className="space-y-4 py-2">
        {chat.messages.length === 0 && (
          <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
            <Bot className="size-8" />
            <p>Pregunta lo que quieras sobre esta auditoría: «resume la superficie de ataque», «¿qué hallazgos faltan por confirmar?», «¿qué prueba pasiva haría ahora sobre el PLC?»…</p>
          </div>
        )}
        {chat.messages.map((m) => (
          <div key={m.id} className={cn("flex", m.role === "user" && "justify-end")}>
            <div className={cn("max-w-[92%] rounded-2xl px-4 py-3 text-sm md:max-w-[80%]",
              m.role === "user" && "bg-primary text-primary-foreground", m.role === "assistant" && "bg-muted", m.role === "error" && "bg-destructive/10 text-destructive")}>
              {m.text && <div className="whitespace-pre-wrap break-words leading-relaxed">{m.text}</div>}
              {m.calls.map((c) => <CallCard key={c.id} call={c} onChange={refresh} />)}
            </div>
          </div>
        ))}
        {chat.busy && <div className="flex"><div className="flex items-center gap-2 rounded-2xl bg-muted px-4 py-3 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> pensando…</div></div>}
        <div ref={end} />
      </div>

      <Card>
        <CardContent className="flex items-end gap-3 p-4">
          <Textarea rows={3} value={text} disabled={!chat.enabled || !chat.configured} className="min-h-[5rem] flex-1 resize-none"
            placeholder={pending ? "Resuelve primero las acciones pendientes de arriba" : "Escribe tu pregunta (Ctrl+Enter para enviar)"}
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.ctrlKey || e.metaKey) && send()} />
          <Button disabled={!canSend} onClick={send}><Send /> Enviar</Button>
        </CardContent>
      </Card>

      {confirm && <ConfirmDialog open onOpenChange={(o) => !o && setConfirm(null)} title={confirm.title} description={confirm.description} confirmLabel={confirm.label} onConfirm={async () => { await confirm.action(); }} />}
      <ConfirmDialog open={resetting} onOpenChange={setResetting} destructive title="¿Borrar la conversación?" confirmLabel="Borrar conversación" description="Los hallazgos, evidencias y ejecuciones no se tocan. La próxima pregunta empezará con una instantánea nueva de la campaña." onConfirm={async () => { try { await api.resetChat(campaign.id); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } }} />
    </div>
  );
}

