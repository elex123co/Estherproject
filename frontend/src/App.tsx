import { BrowserRouter, Route, Routes } from "react-router-dom";
import { HealthProvider } from "./context/HealthContext";
import { ScanProvider } from "./context/ScanContext";
import { AppLayout } from "./layouts/AppLayout";
import { AlertsPage } from "./pages/AlertsPage";
import { LivePage } from "./pages/LivePage";
import { ModelPage } from "./pages/ModelPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReportsPage } from "./pages/ReportsPage";
import { RiskRulesPage } from "./pages/RiskRulesPage";
import { TrafficPage } from "./pages/TrafficPage";
import { UploadPage } from "./pages/UploadPage";
import { Empty } from "./components/ui";

export default function App() {
  return (
    <BrowserRouter>
      <HealthProvider>
        <ScanProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route index element={<OverviewPage />} />
              <Route path="live" element={<LivePage />} />
              <Route path="traffic" element={<TrafficPage />} />
              <Route path="alerts" element={<AlertsPage />} />
              <Route path="upload" element={<UploadPage />} />
              <Route path="model" element={<ModelPage />} />
              <Route path="reports" element={<ReportsPage />} />
              <Route path="risk-rules" element={<RiskRulesPage />} />
              <Route path="*" element={<Empty title="Page not found" />} />
            </Route>
          </Routes>
        </ScanProvider>
      </HealthProvider>
    </BrowserRouter>
  );
}
