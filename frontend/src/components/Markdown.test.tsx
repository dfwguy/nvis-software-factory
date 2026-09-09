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
// Markdown.test.tsx — the renderer that handles untrusted model output.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// The security tests here are the reason this component is hand-written rather than a library
// plus a sanitizer. They are the tests that must never be relaxed.
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "../test/render";
import { Markdown } from "./Markdown";

describe("untrusted content", () => {
  it("renders a script tag as text, never as an element", () => {
    // A finding's detail quotes a third-party repository. If that repository contains this, it
    // must appear on the page as characters.
    const { container } = renderWithProviders(
      <Markdown source={'Found this: <script>alert("xss")</script>'} />,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain('<script>alert("xss")</script>');
  });

  it("renders an image with an onerror handler as text", () => {
    const { container } = renderWithProviders(
      <Markdown source={'<img src=x onerror="alert(1)">'} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("onerror");
  });

  it("refuses to make a javascript: link clickable", () => {
    // A model can be talked into emitting a link. An anchor is the one element where a URL
    // becomes executable, so the scheme is checked rather than the markup.
    const { container } = renderWithProviders(
      <Markdown source="[click me](javascript:alert(1))" />,
    );

    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("[click me](javascript:alert(1))");
  });

  it("refuses a data: URL as well", () => {
    const { container } = renderWithProviders(
      <Markdown source="[report](data:text/html;base64,PHNjcmlwdD4=)" />,
    );

    expect(container.querySelector("a")).toBeNull();
  });

  it("does allow the link schemes the standards files actually use", () => {
    const { container } = renderWithProviders(
      <Markdown source="See [the pillar](/golden-path/durability) and [upstream](https://diataxis.fr/)." />,
    );

    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "/golden-path/durability",
      "https://diataxis.fr/",
    ]);
    // An external link opening in a new tab must not hand the opener over with it.
    expect(links[1].getAttribute("rel")).toBe("noreferrer");
    expect(links[0].getAttribute("target")).toBeNull();
  });
});

describe("the supported subset", () => {
  it("starts headings at h2 so they do not compete with the page title", () => {
    const { container } = renderWithProviders(<Markdown source={"# Durability\n\n## Criteria"} />);

    expect(container.querySelector("h1")).toBeNull();
    expect(container.querySelector("h2")?.textContent).toBe("Durability");
    expect(container.querySelector("h3")?.textContent).toBe("Criteria");
  });

  it("renders fenced code without interpreting what is inside it", () => {
    const { container } = renderWithProviders(
      <Markdown source={"```\nDATA_DIR = os.environ['X']\n**not bold**\n```"} />,
    );

    const code = container.querySelector("pre code");
    expect(code?.textContent).toBe("DATA_DIR = os.environ['X']\n**not bold**");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("renders lists, inline code, bold and italic", () => {
    const { container } = renderWithProviders(
      <Markdown source={"- run `pytest`\n- and **stop** on *any* failure"} />,
    );

    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("code")?.textContent).toBe("pytest");
    expect(container.querySelector("strong")?.textContent).toBe("stop");
    expect(container.querySelector("em")?.textContent).toBe("any");
  });

  it("shows unsupported syntax as its literal text rather than dropping it", () => {
    // The correct failure mode: a reader still sees the content, just unformatted. Silently
    // discarding part of a remediation plan would be worse than rendering it plainly.
    renderWithProviders(<Markdown source={"| a | b |\n| - | - |"} />);

    expect(screen.getByText(/\| a \| b \|/)).toBeInTheDocument();
  });

  it("renders an empty source without throwing", () => {
    const { container } = renderWithProviders(<Markdown source="" />);
    expect(container.textContent).toBe("");
  });

  it("closes an unterminated code fence at the end of input", () => {
    // A truncated model response ends mid-fence. That must render, not hang or throw.
    const { container } = renderWithProviders(<Markdown source={"```\nhalf a snippet"} />);
    expect(container.querySelector("pre code")?.textContent).toBe("half a snippet");
  });
});
