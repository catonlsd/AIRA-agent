import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle for small production / Docker images.
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination:
          "https://ai-research-assistant-backend-eoew.onrender.com/:path*",
      },
    ];
  },
};

export default nextConfig;