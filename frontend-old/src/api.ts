export type AuditType = "OT" | "IoT" | "Web" | "Mobile" | "Red" | "Mixta";
export type CampaignStatus = "planned" | "active" | "closed";

export interface Campaign {
  id: number;
  name: string;
  audit_type: AuditType;
  start_date: string;
  end_date: string | null;
  scope: string;
  status: CampaignStatus;
  llm_enabled: boolean;
  llm_redaction: boolean;
  created_at: string;
  updated_at: string;
}

export type CampaignInput = Pick<
  Campaign,
  "name" | "audit_type" | "start_date" | "end_date" | "scope" | "llm_enabled"
>;

export interface Tool {
  server: string;
  tool: string;
  description: string;
  input_schema: {
    properties: Record<string, { type?: string; enum?: string[]; default?: unknown; description?: string }>;
    required?: string[];
  };
  target_arg: string;
  active: boolean;
}

export interface Run {
  id: number;
  campaign_id: number;
  server: string;
  tool: string;
  arguments: Record<string, unknown>;
  origin: string;
  status: "running" | "succeeded" | "failed";
  output: string;
  error: string;
  created_at: string;
  finished_at: string | null;
}

export interface Asset {
  id: number;
  ip: string;
  hostname: string;
  mac: string;
  vendor: string;
  ports: { port: number; proto: string; service: string; product: string; version: string }[];
  sources: string[];
  last_seen: string;
}

export interface Capture {
  id: number;
  filename: string;
  sha256: string;
  size: number;
  status: "analyzing" | "analyzed" | "failed";
  error: string;
  packets: number;
  non_ip_packets: number;
  created_at: string;
}

export interface GraphNode {
  ip: string;
  kind: "host" | "multicast";
  in_scope: boolean;
  is_asset: boolean;
  hostname: string;
  mac: string;
  vendor: string;
}

export interface GraphEdge {
  src: string;
  dst: string;
  transport: string;
  port: number;
  protocol: string;
  packets: number;
  bytes: number;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type FindingPhase = "discovery" | "exploitation" | "post_exploitation";
export type FindingStatus = "draft" | "confirmed" | "false_positive";

export interface Finding {
  id: number;
  campaign_id: number;
  identifier: string;
  name: string;
  phase: FindingPhase;
  status: FindingStatus;
  cvss_vector: string;
  cvss_score: number | null;
  rating: string;
  description: string;
  poc: string;
  impact: string;
  recommendations: string;
  affected_other: string;
  depends_on_id: number | null;
  asset_ids: number[];
}

export type FindingInput = Omit<Finding, "id" | "campaign_id" | "rating">;

export interface Evidence {
  id: number;
  campaign_id: number;
  finding_id: number | null;
  position: number;
  filename: string;
  mime: string;
  sha256: string;
  size: number;
  caption: string;
}

export const evidenceUrl = (e: Evidence) => `/api/evidence/${e.id}/file?h=${e.sha256.slice(0, 12)}`; // el hash evita cachés obsoletas si se reutiliza un id

export interface ChatCall {
  id: number;
  name: string;
  input: Record<string, unknown>;
  status: "pending" | "running" | "done" | "failed" | "denied";
  requires_approval: boolean;
  run_id: number | null;
  result_preview: string;
}

export interface ChatItem {
  id: number;
  role: "user" | "assistant" | "error";
  text: string;
  stop_reason?: string;
  calls: ChatCall[];
}

export interface ChatView {
  enabled: boolean;
  redaction: boolean;
  configured: boolean;
  problem: string | null;
  provider: string;
  provider_label: string;
  external: boolean;
  tools: boolean;
  model: string;
  busy: boolean;
  messages: ChatItem[];
}

export interface ReportData {
  client: string;
  dut_name: string;
  test_type: "" | "white" | "grey" | "black";
  language: "es" | "en";
  version: string;
  author: string;
  classification: string;
  report_date: string | null;
  introduction: string;
  methodology: string;
  dut_description: string;
  exploitation_summary: string;
  remediation_summary: string;
  conclusions: string;
}

export interface ReportView {
  data: ReportData;
  warnings: string[];
  pdf_available: boolean;
  llm: { enabled: boolean; configured: boolean; provider_label: string; external: boolean };
}

async function detail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const d = JSON.parse(text).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  } catch {
    return text;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try {
      const d = JSON.parse(text).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d);
    } catch { /* texto plano */ }
    throw new Error(`${res.status}: ${msg}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  list: () => req<Campaign[]>("/api/campaigns"),
  create: (c: CampaignInput) =>
    req<Campaign>("/api/campaigns", { method: "POST", body: JSON.stringify(c) }),
  update: (id: number, c: Partial<Campaign>) =>
    req<Campaign>(`/api/campaigns/${id}`, { method: "PATCH", body: JSON.stringify(c) }),
  tools: () => req<Tool[]>("/api/tools"),
  runs: (id: number) => req<Run[]>(`/api/campaigns/${id}/runs`),
  createRun: (id: number, body: { server: string; tool: string; arguments: Record<string, unknown> }) =>
    req<Run>(`/api/campaigns/${id}/runs`, { method: "POST", body: JSON.stringify(body) }),
  assets: (id: number) => req<Asset[]>(`/api/campaigns/${id}/assets`),
  captures: (id: number) => req<Capture[]>(`/api/campaigns/${id}/captures`),
  uploadCapture: async (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`/api/campaigns/${id}/captures`, { method: "POST", body: form });
    if (!res.ok) {
      let msg = await res.text();
      try { msg = JSON.parse(msg).detail ?? msg; } catch { /* texto plano */ }
      throw new Error(`${res.status}: ${msg}`);
    }
    return (await res.json()) as Capture;
  },
  reanalyze: (captureId: number) => req<Capture>(`/api/captures/${captureId}/reanalyze`, { method: "POST" }),
  deleteCapture: (captureId: number) => req<void>(`/api/captures/${captureId}`, { method: "DELETE" }),
  graph: (id: number) => req<Graph>(`/api/campaigns/${id}/graph`),
  findings: (id: number) => req<Finding[]>(`/api/campaigns/${id}/findings`),
  createFinding: (id: number, f: Partial<FindingInput>) =>
    req<Finding>(`/api/campaigns/${id}/findings`, { method: "POST", body: JSON.stringify(f) }),
  updateFinding: (id: number, f: Partial<FindingInput>) =>
    req<Finding>(`/api/findings/${id}`, { method: "PATCH", body: JSON.stringify(f) }),
  deleteFinding: (id: number) => req<void>(`/api/findings/${id}`, { method: "DELETE" }),
  evidence: (id: number) => req<Evidence[]>(`/api/campaigns/${id}/evidence`),
  uploadEvidence: async (id: number, file: File | Blob, name?: string) => {
    const form = new FormData();
    form.append("file", file, name ?? (file instanceof File ? file.name : "captura.png"));
    const res = await fetch(`/api/campaigns/${id}/evidence`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`${res.status}: ${await detail(res)}`);
    return (await res.json()) as Evidence;
  },
  updateEvidence: (id: number, body: { caption?: string; finding_id?: number | null }) =>
    req<Evidence>(`/api/evidence/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteEvidence: (id: number) => req<void>(`/api/evidence/${id}`, { method: "DELETE" }),
  chat: (id: number) => req<ChatView>(`/api/campaigns/${id}/chat`),
  sendChat: (id: number, message: string) =>
    req<{ status: string }>(`/api/campaigns/${id}/chat`, { method: "POST", body: JSON.stringify({ message }) }),
  resetChat: (id: number) => req<void>(`/api/campaigns/${id}/chat`, { method: "DELETE" }),
  approveCall: (id: number) => req<{ status: string }>(`/api/agent-calls/${id}/approve`, { method: "POST" }),
  denyCall: (id: number) => req<{ status: string }>(`/api/agent-calls/${id}/deny`, { method: "POST" }),
  report: (id: number) => req<ReportView>(`/api/campaigns/${id}/report`),
  saveReport: (id: number, data: ReportData) =>
    req<ReportView>(`/api/campaigns/${id}/report`, { method: "PUT", body: JSON.stringify(data) }),
  draftSection: (id: number, section: string) =>
    req<{ section: string; text: string }>(`/api/campaigns/${id}/report/draft`, { method: "POST", body: JSON.stringify({ section }) }),
  exportReport: async (id: number, format: "docx" | "pdf" | "md") => {
    const res = await fetch(`/api/campaigns/${id}/report/export?format=${format}`);
    if (!res.ok) throw new Error(`${res.status}: ${await detail(res)}`);
    const cd = res.headers.get("content-disposition") ?? "";
    const name = decodeURIComponent(/filename\*=utf-8''([^;]+)/i.exec(cd)?.[1] ?? /filename="?([^";]+)"?/i.exec(cd)?.[1] ?? `informe.${format}`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
    return name;
  },
  remove: (id: number) => req<void>(`/api/campaigns/${id}`, { method: "DELETE" }),
};
