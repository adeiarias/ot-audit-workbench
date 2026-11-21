import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/layout/app-shell";
import AssetsPage from "@/pages/assets-page";
import AssistantPage from "@/pages/assistant-page";
import CampaignLayout from "@/pages/campaign-layout";
import CampaignsPage from "@/pages/campaigns-page";
import { CapturesPage, EvidencePage, FindingsPage, ReportPage } from "@/pages/legacy-pages";
import SettingsPage from "@/pages/settings-page";
import ToolsPage from "@/pages/tools-page";

// Los gráficos (recharts) y el mapa (cytoscape) pesan mucho: se descargan solo al entrar en su pantalla
const OverviewPage = lazy(() => import("@/pages/overview-page"));
const MapPage = lazy(() => import("@/pages/map-page"));

export default function App() {
  return (
    <Suspense fallback={<div className="p-10 text-center text-sm text-muted-foreground">Cargando…</div>}>
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<CampaignsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="campaigns/:id" element={<CampaignLayout />}>
          <Route index element={<OverviewPage />} />
          <Route path="tools" element={<ToolsPage />} />
          <Route path="assets" element={<AssetsPage />} />
          <Route path="captures" element={<CapturesPage />} />
          <Route path="map" element={<MapPage />} />
          <Route path="findings" element={<FindingsPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="report" element={<ReportPage />} />
        </Route>
        <Route path="*" element={<div className="p-10 text-center text-muted-foreground">Página no encontrada.</div>} />
      </Route>
    </Routes>
    </Suspense>
  );
}
