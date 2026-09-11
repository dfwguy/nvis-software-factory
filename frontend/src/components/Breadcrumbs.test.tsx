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
// Breadcrumbs.test.tsx — the trail, and the way back out.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { type BreadcrumbDetail, useBreadcrumb } from "../context/BreadcrumbContext";
import { BreadcrumbProvider } from "../context/BreadcrumbProvider";
import { renderWithProviders } from "../test/render";
import { Breadcrumbs } from "./Breadcrumbs";

/** Stands in for a detail view reporting what it loaded. */
function Reporting(detail: BreadcrumbDetail) {
  useBreadcrumb(detail);
  return null;
}

function show(route: string, reporting?: ReactNode) {
  return renderWithProviders(
    <BreadcrumbProvider>
      {reporting}
      <Breadcrumbs />
    </BreadcrumbProvider>,
    { route },
  );
}

describe("the trail", () => {
  it("says nothing on a top-level page, which is not inside anything", () => {
    show("/repositories");

    expect(screen.queryByLabelText("Breadcrumb")).toBeNull();
  });

  it("leads back to the list a detail page was reached from", () => {
    show("/assessments/f3c1d0a2-0000-4000-8000-000000000000");

    expect(screen.getByRole("link", { name: "Assessments" })).toHaveAttribute(
      "href",
      "/assessments",
    );
  });

  it("names the page from what the view loaded, not from the UUID in the URL", () => {
    show(
      "/assessments/f3c1d0a2-0000-4000-8000-000000000000",
      <Reporting label="3eb4fac5" />,
    );

    expect(screen.getByText("3eb4fac5")).toBeInTheDocument();
  });

  it("puts the repository between the list and the run, so its other runs are one click away", () => {
    // The reason this component exists: comparing two runs of one repository used to mean
    // starting again from the sidebar.
    show(
      "/assessments/f3c1d0a2-0000-4000-8000-000000000000",
      <Reporting
        label="3eb4fac5"
        parentLabel="nvis/some-tool"
        parentPath="/repositories/9f2b"
      />,
    );

    expect(screen.getByRole("link", { name: "nvis/some-tool" })).toHaveAttribute(
      "href",
      "/repositories/9f2b",
    );
  });
});

describe("the way back", () => {
  it("goes up to the nearest ancestor and says where that is", () => {
    show(
      "/assessments/f3c1d0a2-0000-4000-8000-000000000000",
      <Reporting
        label="3eb4fac5"
        parentLabel="nvis/some-tool"
        parentPath="/repositories/9f2b"
      />,
    );

    expect(screen.getByRole("link", { name: "Back to nvis/some-tool" })).toHaveAttribute(
      "href",
      "/repositories/9f2b",
    );
  });

  it("falls back to the list when the view reported no parent", () => {
    show("/assessments/f3c1d0a2-0000-4000-8000-000000000000");

    expect(screen.getByRole("link", { name: "Back to Assessments" })).toHaveAttribute(
      "href",
      "/assessments",
    );
  });
});
