import Link from "next/link";
import { Activity, LayoutDashboard } from "lucide-react";
import type { ReactNode } from "react";

export default function AssetsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="topbar asset-topbar">
        <Link className="brand" href="/" aria-label="FleetMind dashboard">
          <span className="brand-symbol"><Activity size={21} aria-hidden="true" /></span>
          <strong>FleetMind<span className="brand-dot">.</span></strong>
        </Link>
        <nav aria-label="FleetMind sections">
          <Link className="asset-home-link" href="/"><LayoutDashboard size={16} aria-hidden="true" /> Command center</Link>
          <Link className="asset-home-link asset-home-active" href="/assets">Assets</Link>
        </nav>
      </header>
      <main className="content-container asset-content">{children}</main>
    </>
  );
}
