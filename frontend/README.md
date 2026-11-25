# FleetMind frontend

This Next.js application has two build profiles. The default connects to the secured local FastAPI API through the same-origin bridge. The portfolio profile bundles simulated model assessments, SHAP, playback and scripted Copilot examples.

Copy [the frontend environment template](.env.example) to `.env.local`, then run `npm ci` and `npm run dev`. See [local setup](../docs/local-setup.md) and the [deployment guide](../docs/deployment.md) for configuration. Run `npm run lint`, `npm run test:proxy`, `npm run build` and `npx tsc --noEmit` to validate changes.
