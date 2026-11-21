import { ArrowRight, Bot, CheckCircle2, FileWarning, Loader2, Network, Server, ShieldAlert, Waypoints, XCircle, Zap } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty } from "@/components/ui/misc";
import { useCampaign } from "@/features/campaign-context";
import { ScopeDialog } from "@/features/scope-dialog";
import { api, type Summary } from "@/lib/api";
import { useTheme } from "@/lib/theme";
import { fmtDate } from "@/lib/utils";

const RATINGS = [
  { key: "Critical", label: "Crítico", color: "#7B1020" }, { key: "High", label: "Alto", color: "#C2410C" }, { key: "Medium", label: "Medio", color: "#A16207" },
  { key: "Low", label: "Bajo", color: "#2F7D32" }, { key: "None", label: "Info", color: "#6B7280" }, { key: "", label: "Sin CVSS", color: "#9CA3AF" },
];

/** Color de un token del tema (p. ej. --chart-1) listo para SVG; se recalcula al cambiar de tema. */
function useThemeColor(token: string): string {
  const { preset, isDark } = useTheme();
  const [color, setColor] = useState("#888");
  useEffect(() => {
    const t = setTimeout(() => setColor(`oklch(${getComputedStyle(document.documentElement).getPropertyValue(token).trim()})`), 0);
    return () => clearTimeout(t);
  }, [token, preset, isDark]);
  return color;
}

function Stat({ icon, label, value, sub, to }: { icon: ReactNode; label: string; value: ReactNode; sub?: ReactNode; to?: string }) {
  const body = (
    <Card className="h-full transition-shadow hover:shadow-md">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0 space-y-1">
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-3xl font-semibold tabular-nums leading-none tracking-tight">{value}</p>
          {sub && <div className="pt-1 text-xs text-muted-foreground">{sub}</div>}
        </div>
        <div className="rounded-lg bg-muted p-2 text-muted-foreground [&_svg]:size-5">{icon}</div>
      </CardContent>
    </Card>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

function targetOf(args: Record<string, unknown>): string {
  if (typeof args.path === "string") return args.path.split("/").pop() ?? "";  // de una ruta solo interesa el fichero; un objetivo (10.0.0.0/24) va entero
  return String(args.target ?? args.host ?? "");
}

export default function OverviewPage() {
  const { campaign, runs, assets, captures, findings, evidence, graph, chat } = useCampaign();
  const base = `/campaigns/${campaign.id}`;
  const [s, setS] = useState<Summary | null>(null);
  const chart1 = useThemeColor("--chart-1");
  const key = `${campaign.scope}|${runs.length}|${runs[0]?.status}|${assets.length}|${captures.length}|${graph.edges.length}|${evidence.length}|${findings.map((f) => `${f.id}${f.status}${f.cvss_score}`).join()}`;
  useEffect(() => { api.summary(campaign.id).then(setS).catch(() => undefined); }, [campaign.id, key]);

  const ratingData = useMemo(() => RATINGS.map((r) => ({ ...r, value: s?.findings_by_rating[r.key] ?? 0 })), [s]);
  const totalFindings = ratingData.reduce((a, r) => a + r.value, 0);
  const urgent = (s?.findings_by_rating.Critical ?? 0) + (s?.findings_by_rating.High ?? 0);

  if (!s) return <p className="text-sm text-muted-foreground"><Loader2 className="mr-2 inline size-4 animate-spin" />Cargando resumen…</p>;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat to={`${base}/assets`} icon={<Server />} label="Activos" value={s.counts.assets} sub={s.counts.assets_out_of_scope > 0 ? <span className="text-amber-600">{s.counts.assets_out_of_scope} fuera de alcance</span> : "todos en alcance"} />
        <Stat to={`${base}/findings`} icon={<ShieldAlert />} label="Hallazgos" value={totalFindings} sub={urgent > 0 ? <span className="font-medium text-severity-high">{urgent} crítico/alto</span> : "ninguno crítico ni alto"} />
        <Stat to={`${base}/captures`} icon={<Waypoints />} label="Flujos observados" value={s.counts.flows} sub={`${s.counts.captures} captura(s) · ${s.counts.evidence} evidencia(s)`} />
        <Stat to={`${base}/tools`} icon={<Zap />} label="Ejecuciones" value={s.counts.runs} sub={`${s.runs_by_status.succeeded ?? 0} ok · ${s.runs_by_status.failed ?? 0} con error`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Hallazgos por criticidad</CardTitle><CardDescription>Los falsos positivos no cuentan.</CardDescription></CardHeader>
          <CardContent>
            {totalFindings === 0 ? <Empty icon={<ShieldAlert />} title="Sin hallazgos">Cuando registres hallazgos con su CVSS, verás aquí la distribución.</Empty> : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={ratingData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid vertical={false} strokeOpacity={0.15} />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                    <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} />
                    <Tooltip cursor={{ fill: "currentColor", opacity: 0.06 }} contentStyle={{ borderRadius: 8, fontSize: 12 }} formatter={(v) => [v, "hallazgos"]} />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>{ratingData.map((r) => <Cell key={r.key} fill={r.color} />)}</Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Protocolos observados</CardTitle><CardDescription>Por paquetes, en las capturas analizadas.</CardDescription></CardHeader>
          <CardContent>
            {s.protocols.length === 0 ? <Empty icon={<Network />} title="Sin tráfico analizado">Sube una captura (.pcap) para ver qué protocolos hablan tus activos.</Empty> : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={s.protocols} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="protocol" width={96} tickLine={false} axisLine={false} fontSize={12} />
                    <Tooltip cursor={{ fill: "currentColor", opacity: 0.06 }} contentStyle={{ borderRadius: 8, fontSize: 12 }} formatter={(v, _n, p) => [`${v} paquetes · ${(p.payload as { flows: number }).flows} flujo(s)`, ""]} />
                    <Bar dataKey="packets" fill={chart1} radius={[0, 6, 6, 0]} barSize={16} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div className="space-y-1.5"><CardTitle>Alcance</CardTitle><CardDescription>{s.scope.rules.length} entrada(s){s.scope.changes > 1 && ` · ${s.scope.changes - 1} cambio(s)`}</CardDescription></div>
            <ScopeDialog trigger={<Button variant="outline" size="sm">Editar</Button>} />
          </CardHeader>
          <CardContent className="flex flex-wrap gap-1.5">
            {s.scope.rules.length === 0 && <p className="text-sm text-amber-600">Alcance vacío: no se puede ejecutar ninguna herramienta.</p>}
            {s.scope.rules.map((r) => <Badge key={r.value} variant={r.warning ? "warning" : "secondary"} className="font-mono" title={r.warning || r.kind}>{r.value}</Badge>)}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Actividad reciente</CardTitle></CardHeader>
          <CardContent>
            {s.recent_runs.length === 0 ? <p className="text-sm text-muted-foreground">Nada ejecutado todavía.</p> : (
              <ul className="space-y-3">
                {s.recent_runs.map((r) => (
                  <li key={r.id} className="flex items-start gap-2.5 text-sm">
                    {r.status === "succeeded" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : r.status === "running" ? <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-amber-600" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />}
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{r.tool}{targetOf(r.arguments) && <span className="font-mono font-normal text-muted-foreground"> {targetOf(r.arguments)}</span>}</p>
                      <p className="text-xs text-muted-foreground">{fmtDate(r.created_at, true)}{r.origin === "agent" && " · asistente"}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Estado</CardTitle></CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div className="flex items-start gap-3">
              <Bot className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">Asistente</p>
                {campaign.llm_enabled && chat ? (
                  <p className="text-muted-foreground">{chat.profile_name || "Entorno"} · {chat.model || chat.provider} <Badge variant={chat.external ? "warning" : "success"} className="ml-1">{chat.external ? "externo" : "local"}</Badge></p>
                ) : <p className="text-muted-foreground">Desactivado: no se envía nada a ningún modelo.</p>}
              </div>
              <Button asChild variant="ghost" size="sm"><Link to={`${base}/assistant`}><ArrowRight /></Link></Button>
            </div>
            <div className="flex items-start gap-3">
              <FileWarning className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">Informe</p>
                <p className="text-muted-foreground">{s.report_warnings === 0 ? "Nada pendiente antes de entregar." : `${s.report_warnings} aviso(s) antes de entregar.`}</p>
              </div>
              <Button asChild variant="ghost" size="sm"><Link to={`${base}/report`}><ArrowRight /></Link></Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
