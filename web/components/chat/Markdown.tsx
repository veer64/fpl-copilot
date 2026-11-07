"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/** The assistant's answer as markdown (react-markdown + remark-gfm; raw HTML is never rendered). Tables: mono uppercase
 *  headers, numeric columns right-aligned and tabular, the BEST ROW (every cell bold -- the agent's own emphasis; its
 *  prompt is not changed) tinted cyan with its numeric bold cells as the key values. The hit rate of that rule is counted
 *  on window.__fplTableStats for the report. */

type HastNode = { type?: string; tagName?: string; children?: HastNode[]; value?: string; position?: { start: { offset?: number } } };
type TableInfo = { numeric: Set<number>; bestRows: Set<number>; cellCol: Map<number, number>; cellBold: Set<number> };
const TableCtx = createContext<TableInfo | null>(null);

declare global {
  interface Window {
    __fplTableStats?: { tables: number; bestRows: number };
  }
}

function text(n: HastNode): string {
  if (n.type === "text") return n.value ?? "";
  return (n.children ?? []).map(text).join("");
}

function isBoldCell(cell: HastNode): boolean {
  const kids = (cell.children ?? []).filter((k) => !(k.type === "text" && !(k.value ?? "").trim()));
  return kids.length > 0 && kids.every((k) => k.type === "element" && k.tagName === "strong");
}

const NUM = /^[+−–-]?\s*[£$€]?\s*\d[\d,]*(\.\d+)?\s*(%|m|pts|k)?$/i;
function isNumeric(s: string): boolean {
  const t = s.trim();
  return t !== "" && NUM.test(t);
}

function analyse(table: HastNode): TableInfo {
  const info: TableInfo = { numeric: new Set(), bestRows: new Set(), cellCol: new Map(), cellBold: new Set() };
  const rows: HastNode[] = [];
  for (const sec of table.children ?? []) {
    if (sec.type !== "element") continue;
    if (sec.tagName === "tr") rows.push(sec);
    for (const r of sec.children ?? []) if (r.type === "element" && r.tagName === "tr") rows.push(r);
  }
  const body = rows.filter((r) => (r.children ?? []).some((c) => c.type === "element" && c.tagName === "td"));
  const cols = new Map<number, { total: number; numeric: number }>();
  for (const r of rows) {
    const cells = (r.children ?? []).filter((c) => c.type === "element" && (c.tagName === "td" || c.tagName === "th"));
    cells.forEach((c, i) => {
      const off = c.position?.start.offset ?? -1;
      info.cellCol.set(off, i);
      if (c.tagName === "td") {
        const v = text(c);
        const col = cols.get(i) ?? { total: 0, numeric: 0 };
        col.total += 1;
        if (isNumeric(v)) col.numeric += 1;
        cols.set(i, col);
        if (isBoldCell(c)) info.cellBold.add(off);
      }
    });
  }
  for (const [i, c] of cols) if (c.total > 0 && c.numeric === c.total) info.numeric.add(i);
  for (const r of body) {
    const cells = (r.children ?? []).filter((c) => c.type === "element" && c.tagName === "td");
    if (cells.length > 0 && cells.every(isBoldCell)) info.bestRows.add(r.position?.start.offset ?? -1);
  }
  if (typeof window !== "undefined") {
    const s = (window.__fplTableStats ??= { tables: 0, bestRows: 0 });
    s.tables += 1;
    if (info.bestRows.size) s.bestRows += 1;
  }
  return info;
}

function Table({ node, children }: { node?: HastNode; children?: ReactNode }) {
  const info = useMemo(() => (node ? analyse(node) : null), [node]);
  return (
    <TableCtx.Provider value={info}>
      <div className="ch-tbl-wrap">
        <table className="ch-tbl">{children}</table>
      </div>
    </TableCtx.Provider>
  );
}

function Tr({ node, children }: { node?: HastNode; children?: ReactNode }) {
  const info = useContext(TableCtx);
  const best = info?.bestRows.has(node?.position?.start.offset ?? -2) ?? false;
  return <tr className={best ? "best" : undefined}>{children}</tr>;
}

function cellClass(node: HastNode | undefined, info: TableInfo | null, inBest: boolean): string | undefined {
  const off = node?.position?.start.offset ?? -2;
  const col = info?.cellCol.get(off);
  const cls: string[] = [];
  if (col !== undefined && info?.numeric.has(col)) cls.push("num");
  if (inBest && info?.cellBold.has(off) && col !== undefined && info.numeric.has(col)) cls.push("hi");
  return cls.length ? cls.join(" ") : undefined;
}

function Td({ node, children }: { node?: HastNode; children?: ReactNode }) {
  const info = useContext(TableCtx);
  // the row's offset is not on the cell: a best row is one whose every cell is bold, so a bold cell whose row is best is
  // one where every sibling is bold too -- the context's bestRows set answers through the parent <tr>; here we only need
  // whether this cell is bold and numeric, and the row class tints the background
  const bold = info?.cellBold.has(node?.position?.start.offset ?? -2) ?? false;
  return <td className={cellClass(node, info, bold)}>{children}</td>;
}

function Th({ node, children }: { node?: HastNode; children?: ReactNode }) {
  const info = useContext(TableCtx);
  return <th className={cellClass(node, info, false)}>{children}</th>;
}

const components: Components = {
  table: Table as Components["table"],
  tr: Tr as Components["tr"],
  td: Td as Components["td"],
  th: Th as Components["th"],
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
};

export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
      {text}
    </ReactMarkdown>
  );
}
