import Link from "next/link";
import { notFound } from "next/navigation";
import { PortfolioInference } from "@/components/portfolio-inference";
import { portfolio } from "@/lib/portfolio";
import { PORTFOLIO } from "@/lib/profile";

export default function Showcase() {
  if (!PORTFOLIO) notFound();
  const { workers, longTasks, heapMiB } = portfolio.performance;
  return <main className="content-container portfolio-content">
    <Link className="asset-inline-link" href="/">← Command center</Link>
    <header className="model-hero">
      <div><h1>Engineering <span>overview.</span></h1>
        <p>From synthetic sensor readings to model scores, committed telemetry events, and cited maintenance evidence.</p></div>
    </header>
    <div className="model-dashboard-grid">
      <section className="panel model-panel">
        <h2>Deployment architecture</h2>
        <ol className="portfolio-flow">
          <li><strong>Portfolio frontend</strong><span>Bundled simulation fixtures, recorded SHAP, playback and Copilot examples.</span></li>
          <li><strong>Optional inference service</strong><span>A bounded CPU-only request through the same-origin bridge. No database or worker.</span></li>
          <li><strong>Full local workspace</strong><span>Authenticated API, PostgreSQL and pgvector, Redpanda workers, committed SSE, and optional Grafana.</span></li>
        </ol>
      </section>
      <section className="panel model-panel">
        <h2>Measured local performance</h2>
        <p>Milestone 11B used disposable infrastructure on a Windows development machine. These are recorded results.</p>
        <dl className="model-health-summary">
          {workers.map(row => <div key={row.workers}><dt>{row.workers} worker{row.workers === 1 ? "" : "s"} · {row.events} readings</dt>
            <dd>{row.commits_per_s.toFixed(1)} commits/s</dd><dd>{row.p95_s.toFixed(2)} s observation-to-commit p95</dd></div>)}
          <div><dt>Desktop telemetry long tasks</dt><dd>{longTasks[0]} → {longTasks[1]}</dd></div>
          <div><dt>Desktop heap sample</dt><dd>{heapMiB[0].toFixed(2)} → {heapMiB[1].toFixed(2)} MiB</dd></div>
        </dl>
      </section>
      <PortfolioInference available={Boolean(process.env.FLEETMIND_PORTFOLIO_API_URL)} />
    </div>
  </main>;
}
