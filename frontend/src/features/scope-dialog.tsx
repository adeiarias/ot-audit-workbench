import { History, Loader2, Pencil, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Alert } from "@/components/ui/misc";
import { api, type ScopeChange, type ScopeParse } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

import { useCampaign } from "./campaign-context";
import { ScopeEditor, useScopeParse } from "./scope-editor";

const values = (p: ScopeParse | null) => new Set(p?.rules.map((r) => r.value) ?? []);

export function ScopeDialog({ trigger }: { trigger?: ReactNode }) {
  const { campaign, refresh } = useCampaign();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(campaign.scope);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<ScopeChange[]>([]);
  const parseNew = useScopeParse(text);
  const parseOld = useScopeParse(campaign.scope);

  useEffect(() => {
    if (!open) return;
    setText(campaign.scope);
    setError("");
    api.scopeHistory(campaign.id).then(setHistory).catch(() => setHistory([]));
  }, [open, campaign.id, campaign.scope]);

  const { added, removed } = useMemo(() => {
    const a = values(parseNew), b = values(parseOld);
    return { added: [...a].filter((x) => !b.has(x)), removed: [...b].filter((x) => !a.has(x)) };
  }, [parseNew, parseOld]);
  const changed = text !== campaign.scope;
  const invalid = !parseNew || parseNew.errors.length > 0;

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await api.update(campaign.id, { scope: text });
      await refresh();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger ?? <Button variant="outline" size="sm"><Pencil /> Editar alcance</Button>}</DialogTrigger>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><ShieldCheck className="size-5" /> Alcance de la campaña</DialogTitle>
          <DialogDescription>Es el límite de lo autorizado: ninguna herramienta, ni manual ni del asistente, puede apuntar fuera de él. Cada cambio queda registrado.</DialogDescription>
        </DialogHeader>
        <ScopeEditor value={text} onChange={setText} parse={parseNew} rows={9} autoFocus />
        {changed && !invalid && (
          <div className="grid gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
            <p className="font-medium">Cambios respecto al alcance guardado</p>
            <div className="flex flex-wrap gap-1.5">
              {added.map((v) => <Badge key={`+${v}`} variant="success" className="font-mono">+ {v}</Badge>)}
              {removed.map((v) => <Badge key={`-${v}`} variant="destructive" className="font-mono">− {v}</Badge>)}
              {added.length + removed.length === 0 && <span className="text-muted-foreground">Solo cambian comentarios o el orden.</span>}
            </div>
            {removed.length > 0 && (
              <Alert tone="warning">
                Los activos ya descubiertos se conservan pero se marcan «fuera de alcance». Las acciones del asistente pendientes de aprobar cuyo objetivo quede fuera se rechazarán automáticamente.
              </Alert>
            )}
          </div>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancelar</Button>
          <Button onClick={save} disabled={!changed || invalid || saving}>{saving && <Loader2 className="animate-spin" />} Guardar alcance</Button>
        </DialogFooter>
        {history.length > 0 && (
          <details className="rounded-lg border p-3 text-sm">
            <summary className="flex cursor-pointer items-center gap-2 font-medium"><History className="size-4" /> Historial ({history.length})</summary>
            <ul className="mt-3 space-y-3">
              {history.map((h) => (
                <li key={h.id} className="grid gap-1">
                  <span className="text-xs text-muted-foreground">{fmtDate(h.changed_at, true)} · {h.initial ? "alcance inicial" : "modificado"}</span>
                  <div className="flex flex-wrap gap-1">
                    {h.added.map((v) => <Badge key={`+${v}`} variant="success" className="font-mono">+ {v}</Badge>)}
                    {h.removed.map((v) => <Badge key={`-${v}`} variant="destructive" className="font-mono">− {v}</Badge>)}
                  </div>
                </li>
              ))}
            </ul>
          </details>
        )}
      </DialogContent>
    </Dialog>
  );
}
