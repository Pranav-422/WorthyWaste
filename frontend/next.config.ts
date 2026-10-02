import type { NextConfig } from "next";

// On Vercel the API is a sibling service on the same domain (root vercel.json routes /api/* to it), so
// no rewrite is needed. Locally, or anywhere API_URL is set, /api/* is proxied to the FastAPI server
// with the path unchanged (the API serves its routes under /api).
const API_URL =
  process.env.API_URL ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : undefined);

const nextConfig: NextConfig = {
  // Keeps the dev badge out of demo recordings.
  devIndicators: false,
  async rewrites() {
    return API_URL ? [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }] : [];
  },
};

export default nextConfig;
