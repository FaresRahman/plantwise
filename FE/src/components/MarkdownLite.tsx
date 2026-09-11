import React from "react";

/**
 * Minimal markdown renderer for chat messages — the LLM's replies commonly
 * use **bold**, bullet/numbered lists, and `### headings`, and showing that
 * literally (asterisks/hashes as plain text) reads as broken chat UX. Rather
 * than pull in react-markdown + remark/unified (~100 transitive packages,
 * see FE/package.json's deliberately small dependency list), this covers
 * just the subset LLM answers actually use.
 */

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const parts = text.split(/(\*\*.+?\*\*|`.+?`|\*.+?\*)/g);
  return parts
    .filter((part) => part.length > 0)
    .map((part, i) => {
      const key = `${keyPrefix}-${i}`;
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={key}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={key}
            style={{
              background: "var(--color-neutral-100)",
              padding: "1px 5px",
              borderRadius: 4,
              fontSize: "0.9em",
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith("*") && part.endsWith("*")) {
        return <em key={key}>{part.slice(1, -1)}</em>;
      }
      return <React.Fragment key={key}>{part}</React.Fragment>;
    });
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; text: string };

function parseBlocks(content: string): Block[] {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i++;
      continue;
    }

    const headingMatch = /^(#{1,6})\s+(.*)$/.exec(line);
    if (headingMatch) {
      blocks.push({ kind: "heading", level: headingMatch[1].length, text: headingMatch[2] });
      i++;
      continue;
    }

    const bulletMatch = /^\s*[-*]\s+(.*)$/.exec(line);
    const numberedMatch = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bulletMatch || numberedMatch) {
      const ordered = !!numberedMatch;
      const items: string[] = [];
      while (i < lines.length) {
        const m = ordered ? /^\s*\d+[.)]\s+(.*)$/.exec(lines[i]) : /^\s*[-*]\s+(.*)$/.exec(lines[i]);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    // Paragraph: consecutive non-blank, non-list, non-heading lines joined with a space.
    const isBlockStart = (l: string) =>
      l.trim() === "" || /^(#{1,6})\s+/.test(l) || /^\s*[-*]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l);
    const paraLines: string[] = [line];
    i++;
    while (i < lines.length && !isBlockStart(lines[i])) {
      paraLines.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "paragraph", text: paraLines.join(" ") });
  }

  return blocks;
}

export function MarkdownLite({ content }: { content: string }) {
  const blocks = parseBlocks(content);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {blocks.map((block, i) => {
        const key = `block-${i}`;
        if (block.kind === "heading") {
          return (
            <div key={key} style={{ fontWeight: 800, fontSize: block.level <= 2 ? 15 : 14, marginTop: i > 0 ? 4 : 0 }}>
              {renderInline(block.text, key)}
            </div>
          );
        }
        if (block.kind === "list") {
          const Tag = block.ordered ? "ol" : "ul";
          return (
            <Tag key={key} style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 3 }}>
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item, `${key}-${j}`)}</li>
              ))}
            </Tag>
          );
        }
        return (
          <div key={key} style={{ margin: 0 }}>
            {renderInline(block.text, key)}
          </div>
        );
      })}
    </div>
  );
}
