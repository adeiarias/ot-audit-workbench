import { Cloud, Home, Loader2, Pencil, Plus, Star, Trash2, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Alert, Empty } from "@/components/ui/misc";
import { ProfileDialog } from "@/features/profile-dialog";
import { api, type EnvProfile, type LLMProfile, type Provider, type ProviderPreset, type TestResult } from "@/lib/api";
import { PRESETS, useTheme, type Mode } from "@/lib/theme";
import { cn } from "@/lib/utils";

function Where({ external }: { external: boolean }) {
  return external ? <Badge variant="warning"><Cloud className="size-3" /> servidor externo</Badge> : <Badge variant="success"><Home className="size-3" /> local / red interna</Badge>;
}

function TestLine({ r }: { r?: TestResult }) {
  if (!r) return null;
  return r.ok
    ? <p className="text-xs text-emerald-600">✓ Conexión correcta · {r.ms} ms · responde «{r.reply}»</p>
    : <p className="break-words text-xs text-destructive">✗ {r.error}</p>;
}

export default function SettingsPage() {
  const { mode, preset, setMode, setPreset } = useTheme();
  const [profiles, setProfiles] = useState<LLMProfile[]>([]);
  const [env, setEnv] = useState<EnvProfile | null>(null);
  const [presets, setPresets] = useState<Record<Provider, ProviderPreset> | null>(null);
  const [editing, setEditing] = useState<LLMProfile | null | "new">(null);
  const [deleting, setDeleting] = useState<LLMProfile | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.llmProfiles();
      setProfiles(r.profiles); setEnv(r.env);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { load(); api.llmPresets().then(setPresets).catch(() => undefined); }, [load]);

  const test = async (id: number | null) => {
    const k = String(id);
    setTesting(k);
    try { const r = await api.testProfile(id); setTests((t) => ({ ...t, [k]: r })); }
    catch (e) { setTests((t) => ({ ...t, [k]: { ok: false, error: e instanceof Error ? e.message : String(e), label: "", model: "" } })); }
    setTesting(null);
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ajustes</h1>
        <p className="text-sm text-muted-foreground">Proveedores de IA y apariencia de la aplicación.</p>
      </div>
      {error && <Alert tone="error">{error}</Alert>}

      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div className="space-y-1.5">
            <CardTitle>Proveedores de IA</CardTitle>
            <CardDescription>Anthropic, DeepSeek, LiteLLM (que puede apuntar a un modelo local) o cualquier API compatible con OpenAI. Cada campaña elige uno en su pestaña Asistente.</CardDescription>
          </div>
          <Button onClick={() => setEditing("new")}><Plus /> Añadir perfil</Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {profiles.length === 0 && <Empty title="Sin perfiles">Mientras no crees ninguno se usa la configuración por entorno (AUDIT_LLM_*), que se muestra abajo.</Empty>}
          {profiles.map((p) => (
            <div key={p.id} className="flex flex-wrap items-start justify-between gap-3 rounded-lg border p-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">{p.name}</span>
                  {p.is_default && <Badge variant="brand"><Star className="size-3" /> predeterminado</Badge>}
                  <Where external={p.external} />
                  {p.campaigns_using > 0 && <Badge variant="outline">{p.campaigns_using} campaña(s)</Badge>}
                </div>
                <p className="text-sm text-muted-foreground">{p.label} · modelo <code className="rounded bg-muted px-1">{p.model || "(por defecto)"}</code> · {p.has_key ? `clave ${p.key_hint}` : "sin clave"}</p>
                {p.problem && <p className="text-xs text-amber-600">⚠ {p.problem}</p>}
                <TestLine r={tests[String(p.id)]} />
              </div>
              <div className="flex shrink-0 gap-1.5">
                <Button variant="outline" size="sm" onClick={() => test(p.id)} disabled={testing !== null}>{testing === String(p.id) ? <Loader2 className="animate-spin" /> : <Zap />} Probar</Button>
                {!p.is_default && <Button variant="ghost" size="sm" onClick={() => api.updateProfile(p.id, { is_default: true }).then(load)}><Star /> Predeterminado</Button>}
                <Button variant="ghost" size="icon" onClick={() => setEditing(p)} aria-label="Editar"><Pencil /></Button>
                <Button variant="ghost" size="icon" className="text-destructive hover:text-destructive" onClick={() => setDeleting(p)} aria-label="Borrar"><Trash2 /></Button>
              </div>
            </div>
          ))}
          {env && (
            <div className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-dashed p-4">
              <div className="min-w-0 flex-1 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">Entorno del backend</span>
                  {env.in_use_by_default && <Badge variant="brand">en uso por defecto</Badge>}
                  <Where external={env.external} />
                </div>
                <p className="text-sm text-muted-foreground">{env.label} · modelo <code className="rounded bg-muted px-1">{env.model || "(sin definir)"}</code> · variables <code className="rounded bg-muted px-1">AUDIT_LLM_*</code> / <code className="rounded bg-muted px-1">ANTHROPIC_API_KEY</code>…</p>
                {env.problem && <p className="text-xs text-amber-600">⚠ {env.problem}</p>}
                <TestLine r={tests["null"]} />
              </div>
              <Button variant="outline" size="sm" onClick={() => test(null)} disabled={testing !== null}>{testing === "null" ? <Loader2 className="animate-spin" /> : <Zap />} Probar</Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Apariencia</CardTitle><CardDescription>Se guarda en este navegador.</CardDescription></CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap gap-2">
            {([["light", "Claro"], ["dark", "Oscuro"], ["system", "Sistema"]] as [Mode, string][]).map(([m, l]) => <Button key={m} variant={mode === m ? "default" : "outline"} size="sm" onClick={() => setMode(m)}>{l}</Button>)}
          </div>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {PRESETS.map((p) => (
              <button key={p.value} onClick={() => setPreset(p.value)} className={cn("rounded-lg border p-3 text-left transition-colors hover:bg-accent", preset === p.value && "border-primary ring-1 ring-primary")}>
                <div className="mb-2 flex gap-1">{p.swatch.map((c) => <span key={c} className="size-6 rounded-full border" style={{ background: c }} />)}</div>
                <span className="text-sm font-medium">{p.label}</span>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      <ProfileDialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} profile={editing === "new" ? null : editing} presets={presets} onSaved={load} />
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} destructive title={`¿Borrar el perfil «${deleting?.name}»?`} confirmLabel="Borrar perfil"
        description={deleting?.campaigns_using ? `${deleting.campaigns_using} campaña(s) lo usan: pasarán al predeterminado. Sus conversaciones no se pueden continuar con otro proveedor: habrá que iniciar una nueva.` : "Se elimina el perfil y su clave guardada."}
        onConfirm={async () => { if (deleting) { await api.deleteProfile(deleting.id); await load(); } }} />
    </div>
  );
}
