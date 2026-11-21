import { KeyRound, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Alert } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, type LLMProfile, type Provider, type ProviderPreset } from "@/lib/api";

const PROVIDERS: Provider[] = ["anthropic", "deepseek", "litellm", "openai"];

export function ProfileDialog({ open, onOpenChange, profile, presets, onSaved }: {
  open: boolean; onOpenChange: (o: boolean) => void; profile: LLMProfile | null; presets: Record<Provider, ProviderPreset> | null; onSaved: () => void;
}) {
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [effort, setEffort] = useState("high");
  const [maxTokens, setMaxTokens] = useState("8192");
  const [tools, setTools] = useState(true);
  const [reasoning, setReasoning] = useState("auto");
  const [extra, setExtra] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    const p = profile;
    const preset = presets?.[p?.provider ?? "anthropic"];
    setProvider(p?.provider ?? "anthropic");
    setName(p?.name ?? preset?.label ?? "");
    setModel(p?.model ?? preset?.model ?? "");
    setBaseUrl(p?.base_url ?? preset?.base_url ?? "");
    setApiKey(""); setClearKey(false);
    setEffort(p?.effort ?? "high");
    setMaxTokens(String(p?.max_tokens ?? 8192));
    setTools(p?.tools ?? true);
    setReasoning(p?.pass_reasoning == null ? "auto" : p.pass_reasoning ? "yes" : "no");
    setExtra(p && Object.keys(p.extra_body).length ? JSON.stringify(p.extra_body, null, 2) : "");
    setIsDefault(p?.is_default ?? false);
    setError("");
  }, [open, profile, presets]);

  const preset = presets?.[provider];
  const onProvider = (v: string) => {
    const next = v as Provider;
    setProvider(next);
    if (!profile && presets) {  // al crear, rellena los valores típicos del proveedor
      setBaseUrl(presets[next].base_url); setModel(presets[next].model);
      if (!name || Object.values(presets).some((x) => x.label === name)) setName(presets[next].label);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    let extra_body: Record<string, unknown> = {};
    if (extra.trim()) {
      try {
        const v = JSON.parse(extra);
        if (typeof v !== "object" || v === null || Array.isArray(v)) throw new Error();
        extra_body = v;
      } catch { setError("«Cuerpo extra» debe ser un objeto JSON válido, p. ej. {\"thinking\":{\"type\":\"disabled\"}}"); return; }
    }
    setBusy(true);
    setError("");
    const body = {
      name: name.trim(), provider, model: model.trim(), base_url: provider === "anthropic" ? "" : baseUrl.trim(), effort, max_tokens: Number(maxTokens) || 8192, tools,
      pass_reasoning: reasoning === "auto" ? null : reasoning === "yes", extra_body, is_default: isDefault,
      ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}), ...(clearKey ? { clear_api_key: true } : {}),
    };
    try {
      if (profile) await api.updateProfile(profile.id, body); else await api.createProfile(body);
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>{profile ? `Editar «${profile.name}»` : "Nuevo perfil de LLM"}</DialogTitle>
            <DialogDescription>Un perfil es una conexión a un proveedor. Cada campaña elige cuál usa en su pestaña Asistente.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Proveedor"><SimpleSelect value={provider} onChange={onProvider} options={PROVIDERS.map((p) => ({ value: p, label: presets?.[p].label ?? p }))} /></Field>
            <Field label="Nombre del perfil"><Input required value={name} maxLength={100} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Modelo" hint={provider === "litellm" ? "El model_name de tu config.yaml de LiteLLM" : undefined}><Input value={model} placeholder={preset?.model || "nombre del modelo"} onChange={(e) => setModel(e.target.value)} /></Field>
            {provider !== "anthropic" && <Field label="URL base" hint={preset?.hint}><Input value={baseUrl} placeholder="https://…  o  http://localhost:…" onChange={(e) => setBaseUrl(e.target.value)} /></Field>}
            <Field label="Clave de API" className="sm:col-span-2"
              hint={profile?.has_key && !clearKey ? `Hay una clave guardada (${profile.key_hint}). Escribe otra para reemplazarla.` : preset?.needs_key ? "Obligatoria para este proveedor." : "Opcional si tu servidor no la exige."}>
              <div className="flex gap-2">
                <Input type="password" autoComplete="off" value={apiKey} placeholder={profile?.has_key && !clearKey ? "•••••••• (sin cambios)" : "sk-…"} onChange={(e) => setApiKey(e.target.value)} />
                {profile?.has_key && <Button type="button" variant={clearKey ? "secondary" : "outline"} onClick={() => setClearKey(!clearKey)}>{clearKey ? "Se quitará" : "Quitar clave"}</Button>}
              </div>
            </Field>
          </div>
          <Alert tone="info"><KeyRound className="mr-1 inline size-3.5" />La clave se guarda en texto plano en la base de datos local (<code>audit.db</code>, permisos 600) y la interfaz nunca la vuelve a mostrar. Las copias de seguridad de la base de datos también la contienen.</Alert>
          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer text-sm font-medium">Opciones avanzadas</summary>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {(provider === "anthropic" || provider === "deepseek") && (
                <Field label="Esfuerzo de razonamiento"><SimpleSelect value={effort} onChange={setEffort} options={["low", "medium", "high", "xhigh", "max"].map((v) => ({ value: v, label: v }))} /></Field>
              )}
              {provider !== "anthropic" && <Field label="Salida máxima (tokens)"><Input type="number" min={256} value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} /></Field>}
              {provider !== "anthropic" && (
                <Field label="Reenviar razonamiento" hint="DeepSeek lo exige con herramientas. Actívalo si LiteLLM apunta a DeepSeek.">
                  <SimpleSelect value={reasoning} onChange={setReasoning} options={[{ value: "auto", label: "Automático (según proveedor)" }, { value: "yes", label: "Sí" }, { value: "no", label: "No" }]} />
                </Field>
              )}
              <label className="flex items-center gap-3 text-sm sm:col-span-2"><Switch checked={tools} onCheckedChange={setTools} /> Permitir herramientas (desactívalo si el modelo no las soporta: el asistente solo verá la instantánea inicial)</label>
              {provider !== "anthropic" && <Field label="Cuerpo extra (JSON)" hint="Se fusiona en cada petición." className="sm:col-span-2"><Textarea rows={3} className="font-mono text-xs" value={extra} placeholder='{"thinking": {"type": "disabled"}}' onChange={(e) => setExtra(e.target.value)} /></Field>}
            </div>
          </details>
          <label className="flex items-center gap-3 text-sm"><Switch checked={isDefault} onCheckedChange={setIsDefault} /> Usar como predeterminado (campañas que no eligen perfil)</label>
          {error && <Alert tone="error">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
            <Button type="submit" disabled={busy || !name.trim()}>{busy && <Loader2 className="animate-spin" />} {profile ? "Guardar cambios" : "Crear perfil"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
