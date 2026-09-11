/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */
// App.tsx — providers, router, shell.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// HashRouter, like the reference application. The Flask catch-all does serve the SPA for any
// path, so BrowserRouter would work -- but a hash route survives being opened through an SSH
// tunnel with a path prefix, and it cannot 404 against a reverse proxy that was configured
// without knowing this app's client-side routes.
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import { Sidebar } from "./components/Sidebar";
import { SignInGate } from "./components/SignInGate";
import { Toolbar } from "./components/Toolbar";
import { BreadcrumbProvider } from "./context/BreadcrumbProvider";
import { SessionProvider } from "./context/SessionProvider";
import { ThemeProvider } from "./context/ThemeProvider";
import { useApi } from "./hooks/useApi";
import { getIndex } from "./services/contracts";
import { getStandards } from "./services/platform";
import {
  activeViewFor,
  ASSESSMENTS_PATH,
  CONTRACT_PATH,
  DEFAULT_PATH,
  GOLDEN_PATH,
  REPOSITORIES_PATH,
  routeFor,
} from "./routes";

// Eager: the landing view and the one it leads to. Everything else is split, because the
// contract explorer and the golden path are large read-only documents that most sessions never
// open, and paying for them on first paint would slow down the path that matters.
import { RepositoriesView } from "./views/RepositoriesView";

const RepositoryDetailView = lazy(() =>
  import("./views/RepositoryDetailView").then((m) => ({ default: m.RepositoryDetailView })),
);
const AssessmentsView = lazy(() =>
  import("./views/AssessmentsView").then((m) => ({ default: m.AssessmentsView })),
);
const AssessmentDetailView = lazy(() =>
  import("./views/AssessmentDetailView").then((m) => ({ default: m.AssessmentDetailView })),
);
const GoldenPathView = lazy(() =>
  import("./views/GoldenPathView").then((m) => ({ default: m.GoldenPathView })),
);
const PillarView = lazy(() => import("./views/PillarView").then((m) => ({ default: m.PillarView })));
const ContractExplorerView = lazy(() =>
  import("./views/ContractExplorerView").then((m) => ({ default: m.ContractExplorerView })),
);
const EntityView = lazy(() => import("./views/EntityView").then((m) => ({ default: m.EntityView })));
const CrosswalksView = lazy(() =>
  import("./views/CrosswalksView").then((m) => ({ default: m.CrosswalksView })),
);
const CrosswalkView = lazy(() =>
  import("./views/CrosswalkView").then((m) => ({ default: m.CrosswalkView })),
);
const ValidateView = lazy(() =>
  import("./views/ValidateView").then((m) => ({ default: m.ValidateView })),
);
const MappingAssistantView = lazy(() =>
  import("./views/MappingAssistantView").then((m) => ({ default: m.MappingAssistantView })),
);
const PlatformView = lazy(() =>
  import("./views/PlatformView").then((m) => ({ default: m.PlatformView })),
);

const SIDEBAR_KEY = "nvsf-sidebar-open";

function ViewFallback() {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
      <CircularProgress size={24} />
    </Box>
  );
}

function Shell() {
  const location = useLocation();
  const route = routeFor(location.pathname);

  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) !== "false";
    } catch {
      return true;
    }
  });

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((open) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, String(!open));
      } catch {
        // Preference not persisted. The toggle still works for this session.
      }
      return !open;
    });
  }, []);

  // Both versions are fetched once, here, and shown in the footer on every page. They are the
  // context every conclusion in this app depends on: a finding means nothing without the
  // baseline version that produced it, and a schema means nothing without the contract version.
  const standards = useApi(getStandards);
  const contract = useApi(getIndex);

  useEffect(() => {
    document.title = route ? `${route.label} — NVIS Software Factory` : "NVIS Software Factory";
  }, [route]);

  return (
    <AppLayout
      sidebar={
        <Sidebar
          open={sidebarOpen}
          onToggle={toggleSidebar}
          activeView={activeViewFor(location.pathname)}
        />
      }
      toolbar={
        <Toolbar
          title={route?.label ?? "NVIS Software Factory"}
          blurb={route?.blurb}
          sidebarOpen={sidebarOpen}
          onOpenSidebar={toggleSidebar}
        />
      }
      standardsVersion={standards.data?.version}
      contractVersion={contract.data?.nrm_version}
    >
      <Suspense fallback={<ViewFallback />}>
        <Routes>
          <Route path="/" element={<Navigate to={DEFAULT_PATH} replace />} />
          <Route path={REPOSITORIES_PATH} element={<RepositoriesView />} />
          <Route path={`${REPOSITORIES_PATH}/:repositoryId`} element={<RepositoryDetailView />} />
          <Route path={ASSESSMENTS_PATH} element={<AssessmentsView />} />
          <Route path={`${ASSESSMENTS_PATH}/:assessmentId`} element={<AssessmentDetailView />} />
          <Route path={GOLDEN_PATH} element={<GoldenPathView />} />
          <Route path={`${GOLDEN_PATH}/:pillarId`} element={<PillarView />} />
          <Route path={CONTRACT_PATH} element={<ContractExplorerView />} />
          <Route path={`${CONTRACT_PATH}/entity/:entity`} element={<EntityView />} />
          <Route path={`${CONTRACT_PATH}/crosswalk`} element={<CrosswalksView />} />
          <Route path={`${CONTRACT_PATH}/crosswalk/:system`} element={<CrosswalkView />} />
          <Route path={`${CONTRACT_PATH}/validate`} element={<ValidateView />} />
          <Route path={`${CONTRACT_PATH}/map`} element={<MappingAssistantView />} />
          <Route path="/platform" element={<PlatformView />} />
          {/* No 404 page. Every path in this app is reachable from the nav, so an unknown one is
              a stale bookmark, and the useful response to a stale bookmark is the landing view
              rather than a dead end. */}
          <Route path="*" element={<Navigate to={DEFAULT_PATH} replace />} />
        </Routes>
      </Suspense>
    </AppLayout>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <HashRouter>
        <SessionProvider>
          <SignInGate>
            {/* Outside the router's Routes but inside the router: the toolbar reads the trail and
                the view being rendered writes to it, so the provider has to wrap both. */}
            <BreadcrumbProvider>
              <Shell />
            </BreadcrumbProvider>
          </SignInGate>
        </SessionProvider>
      </HashRouter>
    </ThemeProvider>
  );
}
