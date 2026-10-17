import { Fragment, type ReactNode } from "react";

/**
 * Minimal, safe markdown renderer for assistant answers.
 * Supports paragraphs, "-"/"*" bullets, "1." numbered lists, **bold**, _italic_/*italic*, `code`.
 * It builds React elements only (no innerHTML), so model output can never inject markup.
 */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const pattern = ordered ? numbered : bullet;
      const items: string[] = [];
      while (i < lines.length && pattern.test(lines[i])) {
        items.push(lines[i].replace(pattern, ""));
        i++;
      }
      const List = ordered ? "ol" : "ul";
      blocks.push(
        <List key={key++} className={ordered ? "my-3 list-decimal space-y-1.5 pl-5 marker:font-medium marker:text-brand-600" : "my-3 list-disc space-y-1.5 pl-5 marker:text-brand-500"}>
          {items.map((item, j) => <li key={j}>{inline(item)}</li>)}
        </List>,
      );
      continue;
    }
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(<p key={key++} className="mt-3 mb-1 font-semibold text-ink">{inline(heading[1])}</p>);
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !/^#{1,4}\s/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={key++} className="my-3 first:mt-0 last:mb-0">{inline(para.join(" "))}</p>);
  }
  return <>{blocks}</>;
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_|\*[^*\s][^*]*\*)/g;

function inline(text: string): ReactNode {
  const parts = text.split(TOKEN);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) {
      return <strong key={i} className="font-semibold text-ink">{p.slice(2, -2)}</strong>;
    }
    if (p.startsWith("`") && p.endsWith("`") && p.length > 2) {
      return <code key={i} className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.85em]">{p.slice(1, -1)}</code>;
    }
    if (((p.startsWith("_") && p.endsWith("_")) || (p.startsWith("*") && p.endsWith("*"))) && p.length > 2) {
      return <em key={i} className="text-muted">{p.slice(1, -1)}</em>;
    }
    return <Fragment key={i}>{p}</Fragment>;
  });
}
