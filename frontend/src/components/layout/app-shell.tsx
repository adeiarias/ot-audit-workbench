import { Bot, ChevronsLeft, ChevronsRight, FileText, Image as ImageIcon, LayoutDashboard, LayoutGrid, Menu, Network, Server, Settings, ShieldAlert, ShieldCheck, Waypoints, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tip, TooltipProvider } from "@/components/ui/tooltip";
import { CampaignProvider, useOptionalCampaign } from "@/features/campaign-context";
import { cn } from "@/lib/utils";

import { ThemeMenu } from "./theme-menu";

const COLLAPSE_KEY = "audit-sidebar-collapsed";

interface Item { to: string; label: string; icon: typeof Bot; end?: boolean; badge?: number | string; alert?: boolean }

function NavItem({ item, collapsed, onNavigate }: { item: Item; collapsed: boolean; onNavigate: () => void }) {
  const link = (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) => cn(
        "group relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        isActive && "bg-sidebar-accent text-sidebar-accent-foreground before:absolute before:-left-2 before:top-1.5 before:h-6 before:w-1 before:rounded-full before:bg-sidebar-primary",
        collapsed && "justify-center px-0",
      )}
    >
      <item.icon className="size-[18px] shrink-0" />
      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}
      {!collapsed && item.badge !== undefined && item.badge !== 0 && <span className="rounded-full bg-sidebar-foreground/10 px-1.5 text-[11px] tabular-nums">{item.badge}</span>}
      {item.alert && <span className={cn("size-2 rounded-full bg-sidebar-primary", collapsed ? "absolute right-2 top-2" : "")} title="Requiere tu atención" />}
    </NavLink>
  );
  return collapsed ? <Tip content={item.label}>{link}</Tip> : link;
}

function SidebarBody({ collapsed, onNavigate }: { collapsed: boolean; onNavigate: () => void }) {
  const camp = useOptionalCampaign();
  const base = camp ? `/campaigns/${camp.campaign.id}` : "";
  const pendingApproval = !!camp?.chat?.messages.some((m) => m.calls.some((c) => c.status === "pending"));
  const critical = camp ? camp.findings.filter((f) => f.status !== "false_positive" && (f.rating === "Critical" || f.rating === "High")).length : 0;

  const general: Item[] = [
    { to: "/", label: "Campañas", icon: LayoutGrid, end: true },
    { to: "/settings", label: "Ajustes", icon: Settings },
  ];
  const campaignItems: Item[] = camp ? [
    { to: base, label: "Resumen", icon: LayoutDashboard, end: true },
    { to: `${base}/tools`, label: "Herramientas", icon: Wrench, badge: camp.runs.length },
    { to: `${base}/assets`, label: "Activos", icon: Server, badge: camp.assets.length },
    { to: `${base}/captures`, label: "Capturas", icon: Waypoints, badge: camp.captures.length },
    { to: `${base}/map`, label: "Mapa", icon: Network },
    { to: `${base}/findings`, label: "Hallazgos", icon: ShieldAlert, badge: camp.findings.length },
    { to: `${base}/evidence`, label: "Evidencias", icon: ImageIcon, badge: camp.evidence.length },
    { to: `${base}/assistant`, label: "Asistente", icon: Bot, alert: pendingApproval },
    { to: `${base}/report`, label: "Informe", icon: FileText },
  ] : [];

  return (
    <>
      <div className={cn("flex h-14 shrink-0 items-center border-b border-sidebar-border px-4", collapsed && "justify-center px-0")}>
        <Link to="/" onClick={onNavigate} className="flex items-center gap-2" aria-label="Audit Platform">
          {collapsed
            ? <ShieldCheck className="size-6 text-sidebar-primary" />
            : <><ShieldCheck className="size-6 text-sidebar-primary" /><span className="text-base font-semibold tracking-tight text-sidebar-foreground">Audit Platform</span></>}
        </Link>
      </div>
      <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4">
        <div className="space-y-1">{general.map((i) => <NavItem key={i.to} item={i} collapsed={collapsed} onNavigate={onNavigate} />)}</div>
        {camp && (
          <div className="space-y-1">
            {!collapsed && (
              <div className="mb-2 px-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">Campaña</p>
                <p className="truncate text-sm font-semibold text-sidebar-foreground" title={camp.campaign.name}>{camp.campaign.name}</p>
                {critical > 0 && <Badge variant="critical" className="mt-1">{critical} crítico/alto</Badge>}
              </div>
            )}
            {campaignItems.map((i) => <NavItem key={i.to} item={i} collapsed={collapsed} onNavigate={onNavigate} />)}
          </div>
        )}
      </nav>
    </>
  );
}

const SECTION_NAMES: Record<string, string> = { tools: "Herramientas", assets: "Activos", captures: "Capturas", map: "Mapa", findings: "Hallazgos", evidence: "Evidencias", assistant: "Asistente", report: "Informe" };

function Crumbs() {
  const camp = useOptionalCampaign();
  const { pathname } = useLocation();
  const section = pathname.split("/")[3];
  if (pathname.startsWith("/settings")) return <span className="font-medium">Ajustes</span>;
  if (!camp) return <span className="font-medium">Campañas</span>;
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-sm">
      <Link to="/" className="text-muted-foreground hover:text-foreground">Campañas</Link>
      <span className="text-muted-foreground">/</span>
      <Link to={`/campaigns/${camp.campaign.id}`} className={cn("truncate", section ? "text-muted-foreground hover:text-foreground" : "font-medium")}>{camp.campaign.name}</Link>
      {section && <><span className="text-muted-foreground">/</span><span className="font-medium">{SECTION_NAMES[section] ?? section}</span></>}
    </div>
  );
}

function Frame() {
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; } });
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => { setMobileOpen(false); }, [pathname]);
  useEffect(() => { try { localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0"); } catch { /* sin almacenamiento */ } }, [collapsed]);

  return (
    <TooltipProvider>
      <div className="flex h-screen overflow-hidden bg-background">
        {mobileOpen && <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setMobileOpen(false)} />}
        <aside className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-all duration-200 md:static md:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          collapsed && "md:w-[4.25rem]",
        )}>
          <SidebarBody collapsed={collapsed && !mobileOpen} onNavigate={() => setMobileOpen(false)} />
          <div className="hidden border-t border-sidebar-border p-3 md:block">
            <Button variant="ghost" size="sm" className={cn("w-full justify-start text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground", collapsed && "justify-center px-0")} onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? <ChevronsRight /> : <><ChevronsLeft /> Contraer</>}
            </Button>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
            <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)} aria-label="Abrir menú"><Menu /></Button>
            <div className="min-w-0 flex-1"><Crumbs /></div>
            <ThemeMenu />
          </header>
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-7xl p-4 md:p-6"><Outlet /></div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}

/** Estructura general. Si la ruta es /campaigns/:id/… envuelve todo en el proveedor de datos de esa campaña (la barra lateral también lo usa). */
export function AppShell() {
  const match = useMatch("/campaigns/:id/*");
  const id = match ? Number(match.params.id) : NaN;
  return Number.isFinite(id) ? <CampaignProvider id={id}><Frame /></CampaignProvider> : <Frame />;
}
