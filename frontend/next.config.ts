import type { NextConfig } from "next";

// All three apps call the FastAPI backend through this origin, so phones on the LAN
// (or a single tunnel URL) only ever need to reach the Next.js server.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Keeps the dev badge out of demo recordings.
  devIndicators: false,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_URL}/:path*` },
      { source: "/photos/:path*", destination: `${API_URL}/photos/:path*` },
    ];
  },
};

export default nextConfig;
