import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Type errors fail the build. A deploy that ships a type error is a deploy that ships
  // a bug someone already told us about. (Next 16 no longer takes an `eslint` key here;
  // linting runs as its own step — see `npm run lint` and the CI commands in CLAUDE.md.)
  typescript: { ignoreBuildErrors: false },
  poweredByHeader: false,
  // Development only. Next 16 blocks cross-origin requests to dev resources, which
  // silently breaks hydration when the app is opened on a different host spelling than
  // the one the dev server advertises — `127.0.0.1` rather than `localhost`. Playwright
  // and container port-forwards both do exactly that, and the only symptom is a page
  // whose buttons do nothing, so both spellings are allowed here.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
