// Prompt W5b: the computed-colour contrast sweep of every button and button-styled link on a rendered page. The static table
// (contrast_public.mjs) checks the DESIGN's pairs; this reads what the browser actually painted -- text colour vs the
// backgrounds composited up the tree -- so a cascade accident (W5b: `.pp a` outranking `.pp-btn-p`, cyan text on a cyan fill)
// fails here. Shared by `node scripts/contrast_public.mjs --live <url>` (signed out) and e2e/w5b-music.spec.ts (signed in).

/** Runs inside the page. Returns one row per visible text-bearing control: {label, fg, bg, ratio, large, note}. */
export function sweepInPage() {
  const SEL = 'button, [role="button"], a[class*="btn"], a.pp-signin, a.pp-home, a.pp-chip, a.pp-lk, a.pp-card, a.ch-home, a.ch-drawer-home, .hm-chip, .pp-chip, .hm-idchip';
  const toRgba = (s) => {
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(",").map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({ r, g, b }) => {
    const c = [r, g, b].map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const hex = (c) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === "none" || cs.visibility === "hidden" || parseFloat(cs.opacity) === 0) return false;
      if (e.getAttribute("aria-hidden") === "true") return false;
    }
    return true;
  };
  // the backgrounds from the element up to the root, composited bottom-up; a gradient on the way is reported, not guessed
  const background = (el) => {
    const layers = [];
    let gradient = false;
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage && cs.backgroundImage !== "none" && /gradient/.test(cs.backgroundImage)) gradient = true;
      const c = toRgba(cs.backgroundColor);
      if (c && c.a > 0) {
        layers.push(c);
        if (c.a >= 1) break;
      }
    }
    let out = { r: 4, g: 7, b: 12, a: 1 }; // the page's #04070C
    for (let i = layers.length - 1; i >= 0; i--) out = over(layers[i], out);
    return { color: out, gradient };
  };
  const rows = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(SEL)) {
    if (!(el instanceof HTMLElement) || seen.has(el) || !visible(el)) continue;
    seen.add(el);
    if (el.matches("[disabled], [aria-disabled='true']")) continue;
    // the text nodes inside: each checked against its own parent's colour and the composited background
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    let any = false;
    while ((node = walker.nextNode())) {
      const text = (node.textContent || "").trim();
      if (!text) continue;
      const parent = node.parentElement;
      if (!parent || !visible(parent)) continue;
      const cs = getComputedStyle(parent);
      const fg = toRgba(cs.color);
      if (!fg || fg.a === 0) continue;
      const { color: bg, gradient } = background(parent);
      const fgc = over({ ...fg }, bg);
      const l1 = lum(fgc);
      const l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const size = parseFloat(cs.fontSize);
      const bold = parseInt(cs.fontWeight, 10) >= 700;
      const large = size >= 24 || (size >= 18.66 && bold);
      any = true;
      rows.push({ label: `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(/\s+/).slice(0, 2).join(".") : ""} "${text.slice(0, 40)}"`, fg: hex(fgc), bg: hex(bg), ratio: Math.round(ratio * 100) / 100, large, note: gradient ? "gradient behind (background approximated by the flat colours)" : "" });
    }
    if (!any) rows.push({ label: `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.split(/\s+/).slice(0, 2).join(".") : ""} (${el.getAttribute("aria-label") || "icon only"})`, fg: "", bg: "", ratio: null, large: false, note: "no text (icon only): not a text-contrast case" });
  }
  return rows;
}

/** The sweep of one rendered page: every row, the failures (< 4.5:1, or < 3:1 for large text) and the lowest ratio. */
export async function sweepPage(page) {
  const rows = await page.evaluate(sweepInPage);
  const text = rows.filter((r) => r.ratio !== null);
  const fails = text.filter((r) => r.ratio < (r.large ? 3 : 4.5));
  const lowest = text.reduce((m, r) => (m === null || r.ratio < m.ratio ? r : m), null);
  return { rows, text, fails, lowest };
}
