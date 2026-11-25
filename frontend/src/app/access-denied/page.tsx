import Link from "next/link";
import { ShieldOff } from "lucide-react";

export default function AccessDenied() {
  return <main className="security-content">
    <div className="panel security-card">
      <ShieldOff aria-hidden="true" />
      <h1>Access restricted</h1>
      <p>Your role does not have access to this workspace.</p>
      <Link href="/" className="asset-inline-link">Return to the dashboard</Link>
    </div>
  </main>;
}
