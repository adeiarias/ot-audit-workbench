import { useCampaign } from "@/features/campaign-context";
import CapturesPanel from "@/features/legacy/CapturesPanel";
import EvidencePanel from "@/features/legacy/EvidencePanel";
import FindingsPanel from "@/features/legacy/FindingsPanel";
import ReportPanel from "@/features/legacy/ReportPanel";

/** Paneles aún no migrados a los componentes nuevos: se envuelven en `.legacy` para heredar el aspecto del nuevo sistema. */
export function CapturesPage() {
  const { campaign, captures, refresh } = useCampaign();
  return <div className="legacy"><CapturesPanel campaignId={campaign.id} captures={captures} onChange={refresh} /></div>;
}
export function FindingsPage() {
  const { campaign, findings, assets, evidence, refresh } = useCampaign();
  return <div className="legacy"><FindingsPanel campaignId={campaign.id} findings={findings} assets={assets} evidence={evidence} onChange={refresh} /></div>;
}
export function EvidencePage() {
  const { campaign, evidence, findings, refresh } = useCampaign();
  return <div className="legacy"><EvidencePanel campaignId={campaign.id} evidence={evidence} findings={findings} onChange={refresh} /></div>;
}
export function ReportPage() {
  const { campaign, findings, evidence } = useCampaign();
  const key = `${findings.map((f) => `${f.id}:${f.status}:${f.cvss_score}`).join(",")}|${evidence.length}`;
  return <div className="legacy"><ReportPanel campaign={campaign} refreshKey={key} /></div>;
}
