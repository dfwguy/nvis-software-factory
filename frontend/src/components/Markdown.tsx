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

/**
 * Turns a document-relative link target into somewhere this application can actually go, or
 * returns null to leave it alone.
 *
 * Only trusted callers pass one. The standards files link to each other by repository path --
 * `pillars/durability.md` -- which is correct on disk and meaningless in a browser, so without a
 * resolver those render as literal `[label](path)` text. That is the right default for the
 * model's prose, where a link is precisely what a model can be talked into fabricating, and the
 * wrong one for our own files.
 */
export type LinkResolver = (href: string) => string | null;

/** Inline spans: `code`, **bold**, *italic*, [text](url). */
function inline(text: string, keyPrefix: string, resolveLink?: LinkResolver): ReactNode[] {
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
      const raw = token.slice(split + 2, -1);
      // A resolver gets first refusal, and whatever it returns is still put through the same
      // scheme test below -- a trusted caller is trusted to know its own document layout, not to
      // hand back a `javascript:` URL.
      const href = resolveLink?.(raw) ?? raw;
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

/**
 * Collect list items, folding each one's indented continuation lines back into it.
 *
 * A list item's text may wrap onto the following lines, indented under the marker, and every
 * hand-written file in `standards/` does this because they are wrapped at 100 columns. Consuming
 * only the marker line leaves the continuation to be parsed as a fresh paragraph: the item ends
 * mid-sentence and the rest of it reappears below the list as its own block. That looks like a
 * broken renderer, and the source looks fine, so it is worth the explicit handling.
 *
 * A nested list is flattened into a sibling, which is the same behaviour as before and consistent
 * with the rest of the supported subset.
 */
function collectItems(lines: string[], start: number, marker: RegExp): [string[], number] {
  const items: string[] = [];
  let index = start;

  while (index < lines.length && marker.test(lines[index])) {
    items.push(lines[index].replace(marker, ""));
    index += 1;

    while (
      index < lines.length &&
      lines[index].trim() &&
      /^\s{2,}\S/.test(lines[index]) &&
      !marker.test(lines[index]) &&
      !lines[index].startsWith("```")
    ) {
      items[items.length - 1] += ` ${lines[index].trim()}`;
      index += 1;
    }
  }

  return [items, index];
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
      const [items, next] = collectItems(lines, index, /^\s*[-*+]\s+/);
      index = next;
      blocks.push({ kind: "ul", lines: items });
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const [items, next] = collectItems(lines, index, /^\s*\d+[.)]\s+/);
      index = next;
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

function render(block: Block, key: string, resolveLink?: LinkResolver): ReactNode {
  switch (block.kind) {
    case "heading": {
      // h1 in a document body would compete with the page title, so headings start at h2 and the
      // Markdown's own levels shift down with them.
      const level = Math.min((block.level ?? 1) + 1, 6);
      const Tag = `h${level}` as "h2";
      return <Tag key={key}>{inline(block.lines[0], key, resolveLink)}</Tag>;
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
            <li key={i}>{inline(item, `${key}-${i}`, resolveLink)}</li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key}>
          {block.lines.map((item, i) => (
            <li key={i}>{inline(item, `${key}-${i}`, resolveLink)}</li>
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
          {inline(block.lines.join(" "), key, resolveLink)}
        </Box>
      );
    case "rule":
      return <Box key={key} component="hr" sx={{ border: 0, borderTop: 1, borderColor: "divider", my: 2 }} />;
    default:
      return <p key={key}>{inline(block.lines.join(" "), key, resolveLink)}</p>;
  }
}

export function Markdown({ source, resolveLink }: { source: string; resolveLink?: LinkResolver }) {
  return (
    <Box className="nvsf-prose">
      {parse(source).map((block, i) => render(block, `b${i}`, resolveLink))}
    </Box>
  );
}
