import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/components/ui";

import "@/styles/globals.css";

/*
 * Fonts are self-hosted through `next/font`, which inlines the CSS and preloads the files
 * from our own origin. That removes a third-party request on first paint and eliminates
 * the layout shift a late-arriving webfont causes.
 */
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
  // Only the weights the design system actually uses.
  weight: ["400", "500", "600"],
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono-stack",
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: {
    default: "IOMETE COMPASS — Understand. Experience. Resolve. Improve.",
    template: "%s · IOMETE COMPASS",
  },
  description:
    "Understand IOMETE's sovereign data lakehouse, assess whether it fits your " +
    "infrastructure, and resolve technical issues with guided, verified playbooks.",
  applicationName: "IOMETE COMPASS",
  authors: [{ name: "IOMETE COMPASS" }],
  // No indexing: this is a demonstration deployment, and the synthetic support history
  // should not appear in search results as though it were real.
  robots: { index: false, follow: false },
  openGraph: {
    title: "IOMETE COMPASS",
    description:
      "Customer enablement and Forward Deployed Engineer productivity for IOMETE.",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Pinch-zoom left enabled deliberately: disabling it is a WCAG 1.4.4 failure and makes
  // dense tables unusable for anyone who needs to magnify.
  maximumScale: 5,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fdfcfa" },
    { media: "(prefers-color-scheme: dark)", color: "#1b1d22" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB" className={`${inter.variable} ${mono.variable}`}>
      <body className="antialiased">
        <AuthProvider>
          <ToastProvider>{children}</ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
