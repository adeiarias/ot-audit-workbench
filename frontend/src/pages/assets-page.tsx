import { Server } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Empty, Table, TBody, TD, TH, THead, TR } from "@/components/ui/misc";
import { useCampaign } from "@/features/campaign-context";

export default function AssetsPage() {
  const { assets } = useCampaign();
  if (assets.length === 0) return <Empty icon={<Server />} title="Sin activos todavía">Aparecen al ejecutar un escaneo o al analizar una captura. Solo se crean para direcciones dentro del alcance.</Empty>;
  const out = assets.filter((a) => !a.in_scope).length;
  return (
    <div className="space-y-3">
      {out > 0 && <p className="text-sm text-muted-foreground">{out} activo(s) quedaron fuera del alcance actual: se conservan, pero ya no se pueden escanear.</p>}
      <Table>
        <THead><TR><TH>IP</TH><TH>Hostname</TH><TH>MAC / fabricante</TH><TH>Puertos abiertos</TH><TH>Fuentes</TH></TR></THead>
        <TBody>
          {assets.map((a) => (
            <TR key={a.id}>
              <TD><div className="flex items-center gap-2"><span className="font-mono">{a.ip}</span>{!a.in_scope && <Badge variant="warning">fuera de alcance</Badge>}</div></TD>
              <TD>{a.hostname || <span className="text-muted-foreground">–</span>}</TD>
              <TD className="text-muted-foreground">{a.mac}{a.vendor && ` (${a.vendor})`}{!a.mac && !a.vendor && "–"}</TD>
              <TD><div className="flex flex-wrap gap-1">{a.ports.map((p) => <Badge key={`${p.port}/${p.proto}`} variant="outline" className="font-mono">{p.port}/{p.proto}{p.service && ` ${p.service}`}</Badge>)}{a.ports.length === 0 && <span className="text-muted-foreground">–</span>}</div></TD>
              <TD><div className="flex flex-wrap gap-1">{a.sources.map((s) => <Badge key={s} variant="secondary">{s}</Badge>)}</div></TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
