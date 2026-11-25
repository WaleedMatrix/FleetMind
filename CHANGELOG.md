# Changelog

## v1.0.0 release candidate

- Added a read-only portfolio profile with simulator assessments, version-checked precomputed SHAP, playback, cited scripted Copilot examples, and measured benchmark context.
- Added a separate bounded CPU inference container and Vercel and Render deployment configuration.
- Added clean-room fixture generation, frozen artifact integrity verification, CI, and release validation instructions.
- Consolidated architecture, API, operations, MLOps, security, setup, and attribution guidance. Added the case study, browser captures, and portfolio materials.
- Removed the previously tracked database dump from the release tree. The history remains intact and needs a clean source export or separately approved remediation before publication.

The full local workspace keeps its existing authentication, assets, inference, knowledge retrieval, private Copilot, telemetry and observability. The portfolio requires no database migration. Local Model Health uses the existing optional revision `0008_model_health_lookup`.
