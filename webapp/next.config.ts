import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseImageUrl = supabaseUrl ? new URL(supabaseUrl) : null;
const configDirectory = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  turbopack: {
    root: configDirectory,
  },
  images: {
    remotePatterns: supabaseImageUrl
      ? [
          {
            protocol: supabaseImageUrl.protocol === "http:" ? "http" : "https",
            hostname: supabaseImageUrl.hostname,
            port: supabaseImageUrl.port,
            pathname: "/storage/v1/object/public/**",
          },
        ]
      : [],
  },
};

export default nextConfig;
