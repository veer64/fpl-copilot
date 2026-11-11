import type { MetadataRoute } from "next";

/** Prompt W7b (F9): the web app manifest -- Add to Home Screen gets the name, the icons (192 / 512 from the logo, in
 *  public/), the site's dark colours and /home as the start page. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "FPL Copilot",
    short_name: "FPL Copilot",
    description: "AI assistant for FPL managers: injury flags, points predictions, fixtures and cited club news.",
    start_url: "/home",
    display: "standalone",
    background_color: "#04070C",
    theme_color: "#04070C",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
