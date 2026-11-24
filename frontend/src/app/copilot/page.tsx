import { Suspense } from "react";
import type { Metadata } from "next";
import { CopilotWorkspace } from "@/components/copilot-workspace";

export const metadata: Metadata = { title: "Maintenance Copilot | FleetMind" };

export default function CopilotPage() {
  return (
    <Suspense fallback={<p className="copilot-loading" role="status">Opening Maintenance Copilot…</p>}>
      <CopilotWorkspace />
    </Suspense>
  );
}
