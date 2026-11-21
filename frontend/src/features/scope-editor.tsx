import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Alert } from "@/components/ui/misc";
import { Textarea } from "@/components/ui/input";
import { api, type ScopeParse } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Analiza el alcance en el servidor (misma lógica que valida y aplica) con un pequeño retardo al teclear. */
export function useScopeParse(value: string): ScopeParse | null {
  const [parse, setParse] = useState<ScopeParse | null>(null);
  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => { api.parseScope(value).then((p) => alive && setParse(p)).catch(() => alive && setParse(null)); }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [value]);
  return parse;
}

const KIND: Record<string, string> = { ip: "IP", cidr: "CIDR", hostname: "hostname" };

export function ScopeEditor({ value, onChange, rows = 8, parse, autoFocus }: { value: string; onChange: (v: string) => void; rows?: number; parse: ScopeParse | null; autoFocus?: boolean }) {
  const invalid = !!parse && parse.errors.length > 0;
  const warnings = parse?.rules.filter((r) => r.warning) ?? [];
  return (
    <div className="grid gap-2">
      <Textarea
        autoFocus={autoFocus}
        rows={rows}
        value={value}
        spellCheck={false}
        aria-invalid={invalid}
        placeholder={"10.0.0.0/24\n192.168.1.50\nplc.planta.local\n# comentario"}
        className={cn("resize-y font-mono text-[13px]", invalid && "border-destructive focus-visible:ring-destructive")}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {parse && parse.rules.length > 0 ? (
          <>
            <span>{parse.rules.length} reconocidas:</span>
            {(Object.keys(KIND) as (keyof typeof parse.counts)[]).map((k) => parse.counts[k] > 0 && <Badge key={k} variant="secondary" className="font-mono">{KIND[k]} {parse.counts[k]}</Badge>)}
          </>
        ) : <span>Una entrada por línea: IP, CIDR u hostname exacto. Lo que sigue a # es un comentario. Vacío = no se puede ejecutar nada.</span>}
      </div>
      {invalid && (
        <Alert tone="error" title={`${parse!.errors.length} línea(s) no válida(s)`}>
          <ul className="space-y-0.5">{parse!.errors.slice(0, 6).map((e) => <li key={e.line}>Línea {e.line}: <code className="rounded bg-muted px-1">{e.text}</code> — {e.error}</li>)}</ul>
          {parse!.errors.length > 6 && <p>… y {parse!.errors.length - 6} más</p>}
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert tone="warning" title="Comprueba estos rangos">
          <ul className="space-y-0.5">{warnings.map((r) => <li key={r.line}>Línea {r.line}: <code className="rounded bg-muted px-1">{r.value}</code> — {r.warning}</li>)}</ul>
        </Alert>
      )}
    </div>
  );
}
