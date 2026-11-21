import { useCampaign } from "@/features/campaign-context";
import GraphPanel from "@/features/legacy/GraphPanel";

// Fichero propio: así cytoscape solo se descarga al abrir el mapa.
export default function MapPage() {
  const { graph, campaign } = useCampaign();
  return <div className="legacy"><GraphPanel graph={graph} campaignId={campaign.id} /></div>;
}
