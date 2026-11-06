import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async redirects() {
    // the root is the login page (Prompt W1; a signed-in visitor is sent on to /home by the page itself); /teams was the
    // W1 placeholder and now lives on /home (Prompt W3)
    return [
      { source: "/", destination: "/login", permanent: false },
      { source: "/teams", destination: "/home", permanent: false },
    ];
  },
};

export default nextConfig;
