import type { Metadata } from "next";
import "./globals.css";
import "./assets.css";
import "../components/alert-intelligence.css";

export const metadata: Metadata = {
  title: "FleetMind — Operations Intelligence",
  description: "Local machine assessment and maintenance monitoring dashboard.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
