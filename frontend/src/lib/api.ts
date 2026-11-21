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
  llm_profile_id: number | null;
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
  target_arg: string | null; // objetivo de red (se valida contra el alcance); null en herramientas sobre capturas
  capture_arg?: string | null; // la herramienta analiza una captura: se indica capture_id
  active: boolean;
  external?: boolean; // servidor de terceros (mcp_servers.yaml)
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
  in_scope: boolean;
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
  events: number; // eventos de protocolo (HTTP, MQTT, Modbus, S7, FTP) observados en el flujo
  secrets: number; // de ellos, con credenciales en claro
}

export interface FlowEvent {
  id: number;
  protocol: "http" | "mqtt" | "modbus" | "s7" | "ftp";
  direction: "c2s" | "s2c";
  kind: "request" | "response" | "write" | "control" | "auth";
  summary: string;
  detail: Record<string, unknown>;
  count: number;
  first_seen: string;
  last_seen: string;
  secret: boolean;
  secret_kind: string;
  finding_id: number | null; // hallazgo ya creado desde este evento (si lo hay)
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
  profile_id: number | null;
  profile_name: string;
  source: "env" | "profile";
  conversation_provider: string | null;
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

export type Provider = "anthropic" | "deepseek" | "litellm" | "openai";

export interface LLMProfile {
  id: number;
  name: string;
  provider: Provider;
  model: string;
  base_url: string;
  has_key: boolean;
  key_hint: string;
  effort: string;
  max_tokens: number;
  tools: boolean;
  pass_reasoning: boolean | null;
  extra_body: Record<string, unknown>;
  is_default: boolean;
  label: string;
  external: boolean;
  problem: string | null;
  campaigns_using: number;
}

export interface EnvProfile {
  provider: string;
  model: string;
  label: string;
  external: boolean;
  problem: string | null;
  has_key: boolean;
  in_use_by_default: boolean;
}

export interface ProfileInput {
  name: string;
  provider: Provider;
  model: string;
  base_url: string;
  api_key?: string | null;
  clear_api_key?: boolean;
  effort: string;
  max_tokens: number;
  tools: boolean;
  pass_reasoning: boolean | null;
  extra_body: Record<string, unknown>;
  is_default: boolean;
}

export interface ProviderPreset {
  label: string;
  base_url: string;
  model: string;
  needs_key: boolean;
  hint: string;
}

export interface TestResult {
  ok: boolean;
  error?: string;
  ms?: number;
  reply?: string;
  label: string;
  model: string;
}

export interface ScopeParse {
  rules: { line: number; kind: "ip" | "cidr" | "hostname"; value: string; warning: string }[];
  errors: { line: number; text: string; error: string }[];
  counts: { ip: number; cidr: number; hostname: number };
  warnings: number;
}

export interface ScopeChange {
  id: number;
  changed_at: string;
  initial: boolean;
  added: string[];
  removed: string[];
}

export interface Summary {
  counts: { assets: number; assets_out_of_scope: number; flows: number; captures: number; evidence: number; runs: number; findings: number };
  runs_by_status: Record<string, number>;
  findings_by_rating: Record<string, number>;
  findings_by_phase: Record<string, number>;
  findings_by_status: Record<string, number>;
  protocols: { protocol: string; packets: number; flows: number }[];
  recent_runs: { id: number; server: string; tool: string; arguments: Record<string, unknown>; status: string; origin: string; created_at: string }[];
  scope: { rules: { kind: string; value: string; warning: string }[]; changes: number };
  report_warnings: number;
}

/** Texto legible de un error de FastAPI: `detail` puede ser un string o una lista de errores de validación. */
function humanize(d: unknown): string {
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => String((x as { msg?: string }).msg ?? JSON.stringify(x)).replace(/^Value error, /, "")).join("; ");
  return JSON.stringify(d);
}

async function detail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    return humanize(JSON.parse(text).detail);
  } catch {
    return text;
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new ApiError(res.status, await detail(res));
  return res.status === 204 ? (undefined as T) : res.json();
}

export const api = {
  list: () => req<Campaign[]>("/api/campaigns"),
  get: (id: number) => req<Campaign>(`/api/campaigns/${id}`),
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
    if (!res.ok) throw new ApiError(res.status, await detail(res));
    return (await res.json()) as Capture;
  },
  reanalyze: (captureId: number) => req<Capture>(`/api/captures/${captureId}/reanalyze`, { method: "POST" }),
  deleteCapture: (captureId: number) => req<void>(`/api/captures/${captureId}`, { method: "DELETE" }),
  graph: (id: number) => req<Graph>(`/api/campaigns/${id}/graph`),
  flowEvents: (id: number, e: { src: string; dst: string; transport: string; port: number }) =>
    req<FlowEvent[]>(`/api/campaigns/${id}/events?${new URLSearchParams({ src: e.src, dst: e.dst, transport: e.transport, port: String(e.port) })}`),
  findingFromEvent: (eventId: number) => req<Finding>(`/api/events/${eventId}/finding`, { method: "POST" }),
  cvssScore: (vector: string) => req<{ score: number; rating: string }>(`/api/cvss/score?${new URLSearchParams({ vector })}`),
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
    if (!res.ok) throw new ApiError(res.status, await detail(res));
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
    if (!res.ok) throw new ApiError(res.status, await detail(res));
    const cd = res.headers.get("content-disposition") ?? "";
    const name = decodeURIComponent(/filename\*=utf-8''([^;]+)/i.exec(cd)?.[1] ?? /filename="?([^";]+)"?/i.exec(cd)?.[1] ?? `informe.${format}`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
    return name;
  },
  summary: (id: number) => req<Summary>(`/api/campaigns/${id}/summary`),
  parseScope: (scope: string) => req<ScopeParse>("/api/scope/parse", { method: "POST", body: JSON.stringify({ scope }) }),
  scopeHistory: (id: number) => req<ScopeChange[]>(`/api/campaigns/${id}/scope-history`),
  llmProfiles: () => req<{ profiles: LLMProfile[]; env: EnvProfile }>("/api/llm/profiles"),
  llmPresets: () => req<Record<Provider, ProviderPreset>>("/api/llm/presets"),
  createProfile: (p: ProfileInput) => req<LLMProfile>("/api/llm/profiles", { method: "POST", body: JSON.stringify(p) }),
  updateProfile: (id: number, p: Partial<ProfileInput>) => req<LLMProfile>(`/api/llm/profiles/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteProfile: (id: number) => req<void>(`/api/llm/profiles/${id}`, { method: "DELETE" }),
  testProfile: (profile_id: number | null) => req<TestResult>("/api/llm/test", { method: "POST", body: JSON.stringify({ profile_id }) }),
  remove: (id: number) => req<void>(`/api/campaigns/${id}`, { method: "DELETE" }),
};
