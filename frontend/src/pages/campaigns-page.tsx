import { Bot, Calendar, FolderOpen, Loader2, MoreHorizontal, Plus, Server, ShieldAlert, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Alert, Empty } from "@/components/ui/misc";
import { SimpleSelect } from "@/components/ui/select";
import { ScopeEditor, useScopeParse } from "@/features/scope-editor";
import { api, type AuditType, type Campaign, type CampaignStatus, type Summary } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

const TYPES: AuditType[] = ["OT", "IoT", "Web", "Mobile", "Red", "Mixta"];
export const STATUS_LABEL: Record<CampaignStatus, string> = { planned: "Planificada", active: "Activa", closed: "Cerrada" };
export const STATUS_VARIANT: Record<CampaignStatus, "secondary" | "brand" | "outline"> = { planned: "secondary", active: "brand", closed: "outline" };
const today = () => new Date().toISOString().slice(0, 10);

function NewCampaignDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [type, setType] = useState<AuditType>("OT");
  const [start, setStart] = useState(today());
  const [scope, setScope] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const parse = useScopeParse(scope);
  const invalid = !!parse && parse.errors.length > 0;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const c = await api.create({ name: name.trim(), audit_type: type, start_date: start, end_date: null, scope, llm_enabled: false });
      onOpenChange(false);
      setName(""); setScope("");
      nav(`/campaigns/${c.id}`);
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
            <DialogTitle>Nueva campaña</DialogTitle>
            <DialogDescription>El alcance se puede modificar después, y cada cambio queda registrado. El asistente de IA empieza desactivado.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Nombre" className="sm:col-span-3"><Input required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Planta de embotellado — auditoría OT" /></Field>
            <Field label="Tipo"><SimpleSelect value={type} onChange={(v) => setType(v as AuditType)} options={TYPES.map((t) => ({ value: t, label: t }))} /></Field>
            <Field label="Inicio"><Input type="date" required value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          </div>
          <Field label="Alcance autorizado"><ScopeEditor value={scope} onChange={setScope} parse={parse} rows={5} /></Field>
          {error && <Alert tone="error">{error}</Alert>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancelar</Button>
            <Button type="submit" disabled={busy || invalid || !name.trim()}>{busy && <Loader2 className="animate-spin" />} Crear campaña</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function CampaignCard({ c, s, onChanged }: { c: Campaign; s?: Summary; onChanged: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const crit = (s?.findings_by_rating.Critical ?? 0), high = (s?.findings_by_rating.High ?? 0);
  return (
    <Card className="group relative flex flex-col transition-shadow hover:shadow-md">
      <Link to={`/campaigns/${c.id}`} className="absolute inset-0 z-0 rounded-xl" aria-label={`Abrir ${c.name}`} />
      <div className="relative z-10 flex items-start justify-between gap-2 p-5 pb-2 pointer-events-none">
        <div className="min-w-0 space-y-1.5">
          <h3 className="truncate text-base font-semibold leading-tight">{c.name}</h3>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">{c.audit_type}</Badge>
            <Badge variant={STATUS_VARIANT[c.status]}>{STATUS_LABEL[c.status]}</Badge>
            {c.llm_enabled && <Badge variant="secondary"><Bot className="size-3" /> IA</Badge>}
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="pointer-events-auto -mr-2 size-8 shrink-0"><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Estado</DropdownMenuLabel>
            {(Object.keys(STATUS_LABEL) as CampaignStatus[]).map((st) => (
              <DropdownMenuItem key={st} disabled={st === c.status} onSelect={() => api.update(c.id, { status: st }).then(onChanged)}>{STATUS_LABEL[st]}</DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-destructive focus:text-destructive" onSelect={() => setConfirm(true)}><Trash2 /> Borrar…</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="pointer-events-none relative z-10 mt-auto grid gap-3 p-5 pt-3 text-sm">
        <div className="flex items-center gap-4 text-muted-foreground">
          <span className="flex items-center gap-1.5"><Server className="size-4" /> {s?.counts.assets ?? "–"} activos</span>
          <span className="flex items-center gap-1.5"><ShieldAlert className="size-4" /> {s?.counts.findings ?? "–"} hallazgos</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><Calendar className="size-3.5" /> {fmtDate(c.start_date)}</span>
          <div className="flex gap-1">{crit > 0 && <Badge variant="critical">{crit} crítico</Badge>}{high > 0 && <Badge variant="high">{high} alto</Badge>}</div>
        </div>
      </div>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} destructive title={`¿Borrar «${c.name}»?`} confirmLabel="Borrar campaña"
        description="Se eliminan sus activos, capturas, evidencias, hallazgos, informes y la conversación con el asistente. No se puede deshacer." onConfirm={() => api.remove(c.id).then(onChanged)} />
    </Card>
  );
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [summaries, setSummaries] = useState<Record<number, Summary>>({});
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const list = await api.list();
      setCampaigns(list);
      const entries = await Promise.all(list.map((c) => api.summary(c.id).then((s) => [c.id, s] as const).catch(() => null)));
      setSummaries(Object.fromEntries(entries.filter((e): e is readonly [number, Summary] => e !== null)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Campañas</h1>
          <p className="text-sm text-muted-foreground">Cada campaña tiene su propio alcance, evidencias, hallazgos e informe.</p>
        </div>
        <Button onClick={() => setOpen(true)}><Plus /> Nueva campaña</Button>
      </div>
      {error && <Alert tone="error" title="No se pudo cargar">{error}</Alert>}
      {campaigns === null && !error && <p className="text-sm text-muted-foreground">Cargando…</p>}
      {campaigns?.length === 0 && <Empty icon={<FolderOpen />} title="Aún no hay campañas">Crea la primera: define el nombre, el tipo de auditoría y el alcance autorizado.</Empty>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {campaigns?.map((c) => <CampaignCard key={c.id} c={c} s={summaries[c.id]} onChanged={load} />)}
      </div>
      <NewCampaignDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
