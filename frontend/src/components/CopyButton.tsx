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
// CopyButton.tsx — copy text to the clipboard, with a confirmation the user can see.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// Used a lot here: the whole deliverable is text meant to be pasted into an agent session, so
// "copy" is a primary action in this application rather than a convenience.
import { Button } from "@nvidia/foundations-react-core";
import { Check, Copy } from "lucide-react";
import { useCallback, useRef, useState } from "react";

interface Props {
  text: string;
  label?: string;
  kind?: "primary" | "secondary" | "tertiary";
  size?: "tiny" | "small" | "medium";
}

export function CopyButton({ text, label = "Copy", kind = "secondary", size = "small" }: Props) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      // The clipboard API needs a secure context. Over a plain-http tunnel it is simply absent,
      // which is a normal way to reach this deployment -- so say "select and copy" rather than
      // failing silently and leaving the user unsure whether it worked.
      setState("failed");
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2500);
  }, [text]);

  return (
    <Button kind={kind} size={size} onClick={copy}>
      {state === "copied" ? <Check size={14} /> : <Copy size={14} />}
      {state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : label}
    </Button>
  );
}
