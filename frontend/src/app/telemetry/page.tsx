import type { Metadata } from "next";
import { TelemetryWorkspace } from "@/components/telemetry-workspace";

export const metadata: Metadata = { title: "Telemetry Command Center | FleetMind" };

export default function TelemetryPage() {
  return <TelemetryWorkspace />;
}
