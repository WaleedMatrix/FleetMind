import type { Metadata } from "next";
import { ModelIntelligence } from "@/components/model-intelligence";

export const metadata: Metadata = { title: "Model Intelligence | FleetMind" };

export default function ModelIntelligencePage() {
  return <ModelIntelligence />;
}
