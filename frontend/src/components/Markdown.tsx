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
// Markdown.tsx — a small Markdown renderer that emits React nodes, never HTML.
// Author: Rafael M. Koike & Cursor Agent ("Ada")
//
// WHY THIS EXISTS RATHER THAN A LIBRARY
// -------------------------------------
// Two of the three things rendered here are not trusted input. The standards bodies are ours, but
// the model's prose quotes an arbitrary third-party repository, and a finding's `detail` can
// contain a fragment of someone else's source. A Markdown library plus
// `dangerouslySetInnerHTML` puts that content one sanitizer misconfiguration away from stored
// XSS -- and the sanitizer would be a fourth dependency to keep current.
//
// Emitting React elements removes the class of bug entirely: React escapes text nodes, so there
// is no HTML string at any point and no sanitizer to get wrong.
//
// WHAT IT SUPPORTS
// ----------------
// ATX headings, paragraphs, fenced code blocks, unordered and ordered lists, blockquotes,
// horizontal rules, and inline code / bold / italic / links. That is the subset the standards
// files and the prompts actually produce -- both are ours, so the subset is a constraint we
// control rather than a guess. Anything else renders as its literal text, which is the correct
// failure mode: the reader still sees the content, just without the formatting.
import Box from "@mui/material/Box";
import { Fragment, type ReactNode } from "react";

/** Inline spans: `code`, **bold**, *italic*, [text](url). */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let index = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;

    if (token.startsWith("`")) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      const split = token.indexOf("](");
      const label = token.slice(1, split);
      const href = token.slice(split + 2, -1);
      // Only http(s), mailto and site-relative links are turned into anchors. `javascript:` and
      // `data:` are rendered as text: this content can come from a model, and a link is exactly
      // the thing a model can be talked into producing.
      const safe = /^(https?:\/\/|mailto:|\/|#)/i.test(href);
      nodes.push(
        safe ? (
          <a key={key} href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noreferrer">
            {label}
          </a>
        ) : (
          <Fragment key={key}>{token}</Fragment>
        ),
      );
    }
    cursor = match.index + token.length;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

interface Block {
  kind: "heading" | "paragraph" | "code" | "ul" | "ol" | "quote" | "rule";
  level?: number;
  lines: string[];
}

function parse(source: string): Block[] {
  const blocks: Block[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1; // closing fence, or end of input
      blocks.push({ kind: "code", lines: body });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, lines: [heading[2]] });
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      blocks.push({ kind: "rule", lines: [] });
      index += 1;
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ""));
        index += 1;
      }
      blocks.push({ kind: "ul", lines: items });
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+[.)]\s+/, ""));
        index += 1;
      }
      blocks.push({ kind: "ol", lines: items });
      continue;
    }

    if (line.startsWith(">")) {
      const quoted: string[] = [];
      while (index < lines.length && lines[index].startsWith(">")) {
        quoted.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push({ kind: "quote", lines: quoted });
      continue;
    }

    // Paragraph: consecutive non-blank lines that do not start another block.
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].startsWith("```") &&
      !/^#{1,6}\s/.test(lines[index]) &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+[.)]\s+/.test(lines[index]) &&
      !lines[index].startsWith(">")
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", lines: paragraph });
  }

  return blocks;
}

function render(block: Block, key: string): ReactNode {
  switch (block.kind) {
    case "heading": {
      // h1 in a document body would compete with the page title, so headings start at h2 and the
      // Markdown's own levels shift down with them.
      const level = Math.min((block.level ?? 1) + 1, 6);
      const Tag = `h${level}` as "h2";
      return <Tag key={key}>{inline(block.lines[0], key)}</Tag>;
    }
    case "code":
      return (
        <pre key={key}>
          <code className="nvsf-code">{block.lines.join("\n")}</code>
        </pre>
      );
    case "ul":
      return (
        <ul key={key}>
          {block.lines.map((item, i) => (
            <li key={i}>{inline(item, `${key}-${i}`)}</li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key}>
          {block.lines.map((item, i) => (
            <li key={i}>{inline(item, `${key}-${i}`)}</li>
          ))}
        </ol>
      );
    case "quote":
      return (
        <Box
          key={key}
          component="blockquote"
          sx={{
            m: 0,
            pl: 2,
            borderLeft: 3,
            borderColor: "divider",
            color: "text.secondary",
          }}
        >
          {inline(block.lines.join(" "), key)}
        </Box>
      );
    case "rule":
      return <Box key={key} component="hr" sx={{ border: 0, borderTop: 1, borderColor: "divider", my: 2 }} />;
    default:
      return <p key={key}>{inline(block.lines.join(" "), key)}</p>;
  }
}

export function Markdown({ source }: { source: string }) {
  return <Box className="nvsf-prose">{parse(source).map((block, i) => render(block, `b${i}`))}</Box>;
}
