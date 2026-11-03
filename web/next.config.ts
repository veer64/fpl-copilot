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
    // the site has no home page yet (Prompt W1): the root is the login page
    return [{ source: "/", destination: "/login", permanent: false }];
  },
};

export default nextConfig;
