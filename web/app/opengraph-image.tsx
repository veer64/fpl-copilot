import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";

/** Prompt W7b (F5): the link-preview image (1200 x 630) -- the logo, the wordmark and the pitch-grid style on the site's dark
 *  background; no photo of a real person. Built with next/og at request time; Next adds the og:image / twitter:image tags. */
export const alt = "FPL Copilot — AI assistant for Fantasy Premier League managers";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OpenGraphImage() {
  const svg = await readFile(path.join(process.cwd(), "public", "logo.svg"), "utf8");
  const logo = `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: "#04070C",
          color: "#E8F6FF",
          fontFamily: "sans-serif",
          position: "relative",
        }}
      >
        <div style={{ position: "absolute", left: 0, right: 0, top: 0, bottom: 0, display: "flex", backgroundImage: "radial-gradient(circle at 50% 20%, rgba(59,232,255,0.16), rgba(4,7,12,0) 55%)" }} />
        <div style={{ position: "absolute", left: -80, right: -80, bottom: 0, height: 290, display: "flex", backgroundImage: "linear-gradient(rgba(59,232,255,0.14) 2px, transparent 2px), linear-gradient(90deg, rgba(59,232,255,0.14) 2px, transparent 2px)", backgroundSize: "72px 72px", opacity: 0.9 }} />
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 290, display: "flex", backgroundImage: "linear-gradient(to top, rgba(4,7,12,0.1), #04070C)" }} />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", flexGrow: 1, gap: 26, padding: "0 80px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- the logo inside the generated image */}
            <img src={logo} width={112} height={112} alt="" />
            <div style={{ fontSize: 88, fontWeight: 700, letterSpacing: -3, color: "#F2FBFF", display: "flex" }}>FPL Copilot</div>
          </div>
          <div style={{ fontSize: 30, color: "#C9D6E3", textAlign: "center", lineHeight: 1.35, display: "flex", maxWidth: 980 }}>
            AI assistant for FPL managers: injury flags, points predictions, fixtures and cited club news.
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: 22, letterSpacing: 6, color: "#7FE9FF", marginTop: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: 10, background: "#3BE8FF", display: "flex" }} />
            EVERY DECISION, SCOUTED
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
