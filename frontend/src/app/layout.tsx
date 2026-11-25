import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import "./assets.css";
import "./model-intelligence.css";
import "./copilot.css";
import "./telemetry.css";
import "./security.css";
import "../components/alert-intelligence.css";
import { AuthShell } from "@/components/auth-shell";

export const metadata: Metadata = {
  title: "FleetMind — Operations Intelligence",
  description: "Local machine assessment and maintenance monitoring dashboard.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Suspense fallback={<main className="security-pending"><p role="status">Checking access…</p></main>}>
          <AuthShell>{children}</AuthShell>
        </Suspense>
      </body>
    </html>
  );
}
