"use client";

import Link from "next/link";
import { useState } from "react";
import { portfolio } from "@/lib/portfolio";

export function PortfolioCopilot() {
  const [active, setActive] = useState(0);
  const item = portfolio.copilot[active];
  return <main className="content-container portfolio-content">
    <Link className="asset-inline-link" href="/">← Command center</Link>
    <header className="model-hero">
      <div><h1>Maintenance <span>Copilot.</span></h1>
        <p>Recorded examples from the deterministic regression suite. The scripted provider selected evidence and FleetMind assembled the cited response.</p></div>
    </header>
    <div className="portfolio-copilot-grid">
      <section className="panel model-panel" aria-labelledby="example-questions">
        <h2 id="example-questions">Example questions</h2>
        <div className="portfolio-questions">
          {portfolio.copilot.map((entry, index) =>
            <button key={entry.id} className="security-secondary" aria-pressed={active === index}
              onClick={() => setActive(index)}>{entry.question}</button>,
          )}
        </div>
      </section>
      <article className="panel model-panel" aria-live="polite">
        <span className="section-overline">Recorded response</span>
        <h2>{item.question}</h2>
        <p className="portfolio-answer">{item.answer}</p>
        {!!item.citations.length && <><h3>Evidence</h3><ul>
          {item.citations.map(citation => <li key={citation.id}>
            <strong>{citation.title}</strong>{citation.section && <> · {citation.section}</>}
            {citation.source_ref && <small className="portfolio-source">{citation.source_ref}</small>}
          </li>)}
        </ul></>}
      </article>
    </div>
  </main>;
}
