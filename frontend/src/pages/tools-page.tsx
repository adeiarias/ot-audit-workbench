import { CheckCircle2, ChevronDown, ChevronRight, Loader2, Play, XCircle, Zap } from "lucide-react";
import { Fragment, useState } from "react";

import { Alert, Empty, Table, TBody, TD, TH, THead, TR } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { useCampaign } from "@/features/campaign-context";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

function ToolForm() {
  const { campaign, tools, captures, refresh } = useCampaign();
  const [idx, setIdx] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const tool = tools[idx];
  if (!tool) return <Card><CardContent className="pt-5 text-sm text-muted-foreground">Cargando herramientas…</CardContent></Card>;
  const props = Object.entries(tool.input_schema.properties);
  const required = new Set(tool.input_schema.required ?? []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const args: Record<string, unknown> = {};
    for (const [name, spec] of props) {
      const v = values[name] ?? (name === "capture_id" && captures[0] ? String(captures[0].id) : spec.default !== undefined ? String(spec.default) : "");
      if (v === "") continue;
      args[name] = spec.type === "integer" ? Number(v) : v;
    }
    setBusy(true);
    try {
      setError("");
      await api.createRun(campaign.id, { server: tool.server, tool: tool.tool, arguments: args });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
    setBusy(false);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ejecutar herramienta</CardTitle>
        <CardDescription>Los objetivos deben estar dentro del alcance de la campaña: se comprueba en el servidor.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
          <Field label="Herramienta" hint={tool.description} className="md:col-span-2">
            <SimpleSelect value={String(idx)} onChange={(v) => { setIdx(Number(v)); setValues({}); setError(""); }} options={tools.map((t, i) => ({ value: String(i), label: `${t.server} / ${t.tool}` }))} />
          </Field>
          {props.map(([name, spec]) => (
            <Field key={name} label={`${name}${required.has(name) ? " *" : ""}`} hint={name === tool.target_arg ? "Debe estar en el alcance" : spec.description}>
              {name === "capture_id" ? (
                captures.length === 0
                  ? <p className="text-sm text-muted-foreground">No hay capturas: súbela primero en la pestaña Capturas.</p>
                  : <SimpleSelect value={values[name] ?? String(captures[0].id)} onChange={(v) => setValues({ ...values, [name]: v })} options={captures.map((c) => ({ value: String(c.id), label: `#${c.id} · ${c.filename}` }))} />
              ) : spec.enum ? (
                <SimpleSelect value={values[name] ?? String(spec.default ?? spec.enum[0])} onChange={(v) => setValues({ ...values, [name]: v })} options={spec.enum.map((o) => ({ value: o, label: o }))} />
              ) : (
                <Input type={spec.type === "integer" ? "number" : "text"} required={required.has(name)} placeholder={spec.default !== undefined ? String(spec.default) : ""} value={values[name] ?? ""} onChange={(e) => setValues({ ...values, [name]: e.target.value })} />
              )}
            </Field>
          ))}
          <div className="grid gap-3 md:col-span-2">
            {tool.external && <Alert tone="info" title="Servidor de terceros">{tool.capture_arg ? "Analiza una captura ya subida (offline, sin tráfico): indica su ID de la pestaña Capturas. " : ""}Solo se admiten los argumentos declarados en el manifiesto.</Alert>}
            {tool.active && <Alert tone="warning" title="Herramienta activa">Genera tráfico hacia el objetivo. Al pulsar Ejecutar confirmas que tienes autorización.</Alert>}
            {error && <Alert tone="error">{error}</Alert>}
            <div><Button type="submit" disabled={busy}>{busy ? <Loader2 className="animate-spin" /> : <Play />} Ejecutar</Button></div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function RunStatus({ status }: { status: string }) {
  if (status === "running") return <Badge variant="warning"><Loader2 className="size-3 animate-spin" /> en curso</Badge>;
  if (status === "succeeded") return <Badge variant="success"><CheckCircle2 className="size-3" /> ok</Badge>;
  return <Badge variant="destructive"><XCircle className="size-3" /> error</Badge>;
}

export default function ToolsPage() {
  const { runs } = useCampaign();
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="space-y-6">
      <ToolForm />
      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">Ejecuciones</h2>
        {runs.length === 0 ? <Empty icon={<Zap />} title="Sin ejecuciones todavía">Lanza una herramienta arriba, o pídele al asistente que proponga una.</Empty> : (
          <Table>
            <THead><TR><TH className="w-12">#</TH><TH>Herramienta</TH><TH>Argumentos</TH><TH>Origen</TH><TH>Estado</TH><TH>Cuándo</TH><TH className="w-10" /></TR></THead>
            <TBody>
              {runs.map((r) => (
                <Fragment key={r.id}>
                  <TR className="cursor-pointer" onClick={() => setOpen(open === r.id ? null : r.id)}>
                    <TD className="tabular-nums text-muted-foreground">{r.id}</TD>
                    <TD className="font-medium">{r.server}/{r.tool}</TD>
                    <TD><code className="rounded bg-muted px-1.5 py-0.5 text-xs">{JSON.stringify(r.arguments)}</code></TD>
                    <TD>{r.origin === "agent" ? <Badge variant="secondary">asistente</Badge> : <span className="text-muted-foreground">manual</span>}</TD>
                    <TD><RunStatus status={r.status} /></TD>
                    <TD className="text-muted-foreground">{fmtDate(r.created_at, true)}</TD>
                    <TD>{open === r.id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}</TD>
                  </TR>
                  {open === r.id && <tr><td colSpan={7} className="bg-muted/30 p-3"><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-md bg-background p-3 text-xs">{r.error || r.output || "(sin salida)"}</pre></td></tr>}
                </Fragment>
              ))}
            </TBody>
          </Table>
        )}
      </section>
    </div>
  );
}
