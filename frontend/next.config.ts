import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

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