import { Bot, Calendar, ShieldCheck } from "lucide-react";
import { Outlet } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { SimpleSelect } from "@/components/ui/select";
import { useCampaign } from "@/features/campaign-context";
import { ScopeDialog } from "@/features/scope-dialog";
import { api, type CampaignStatus } from "@/lib/api";
import { fmtDate } from "@/lib/utils";

import { STATUS_LABEL } from "./campaigns-page";

export default function CampaignLayout() {
  const { campaign, refresh, error } = useCampaign();
  const rules = campaign.scope.split("\n").filter((l) => l.split("#")[0].trim()).length;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{campaign.name}</h1>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <Badge variant="outline">{campaign.audit_type}</Badge>
            <span className="flex items-center gap-1.5"><Calendar className="size-4" /> {fmtDate(campaign.start_date)}{campaign.end_date && ` → ${fmtDate(campaign.end_date)}`}</span>
            <span className="flex items-center gap-1.5"><ShieldCheck className="size-4" /> {rules} entrada(s) de alcance</span>
            {campaign.llm_enabled && <Badge variant="secondary"><Bot className="size-3" /> IA activada</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <SimpleSelect className="w-36" value={campaign.status} onChange={(v) => api.update(campaign.id, { status: v as CampaignStatus }).then(refresh)} options={(Object.keys(STATUS_LABEL) as CampaignStatus[]).map((s) => ({ value: s, label: STATUS_LABEL[s] }))} />
          <ScopeDialog />
        </div>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Outlet />
    </div>
  );
}
