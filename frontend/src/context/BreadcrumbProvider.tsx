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
// BreadcrumbProvider.tsx — holds the name the current view reported for itself.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
import { type ReactNode, useCallback, useMemo, useState } from "react";

import { type BreadcrumbDetail, BreadcrumbContext } from "./BreadcrumbContext";

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [detail, setDetail] = useState<BreadcrumbDetail>({});

  // Stable identity: `useBreadcrumb` lists the setter among its effect dependencies, and a new
  // function on every render would re-run that effect on every render, which sets state, which
  // renders again.
  const set = useCallback((next: BreadcrumbDetail) => setDetail(next), []);

  const value = useMemo(() => ({ detail, set }), [detail, set]);
  return <BreadcrumbContext.Provider value={value}>{children}</BreadcrumbContext.Provider>;
}
