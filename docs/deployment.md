# Free-tier portfolio deployment

The deployable candidate is a Next.js portfolio build on Vercel Hobby. A Render Free service can supply one stateless inference endpoint. All screenshots, investigation history, model reports, explanations, playback and Copilot examples are independent of the service. The portfolio build bundles fictional assets and deterministic records from the repository. Start with the recorded-only deployment. The CPU service matched frozen scores and fit in memory but showed slow first starts under the local CPU quota. Enable it only after verifying provider startup and fallback. [Measured results](release-validation.md#optional-stateless-inference) The full workspace runs locally with authenticated PostgreSQL, private Copilot conversations, and optional infrastructure.

## Provider terms verified for the release candidate

- Vercel Hobby is intended for personal, noncommercial use. When included limits are reached, access to the affected feature can be restricted until its usage resets. The documentation lists 100 GB of Fast Data Transfer and the first 1 million Function Invocations under Hobby usage. Check current bandwidth and compute allowances before publishing. [Vercel Hobby](https://vercel.com/docs/plans/hobby) · [Vercel limits](https://vercel.com/docs/limits)
- Render Free web services provide 512 MB and 0.1 CPU, share 750 free instance hours per workspace per calendar month, and spin down after 15 minutes without inbound traffic. Waking can take about a minute. The filesystem is ephemeral and Render limits free service usage. [Render Free](https://render.com/docs/free) · [Render pricing](https://render.com/pricing)
- This deployment requires no Neon project or hosted database. Keep the existing local PostgreSQL, broker, model tracking and monitoring private. Use neither scheduled warmups nor paid add-ons.

## Prepare a clean source repository

The existing repository history contains a database dump. The release tree removes it, but earlier commits still contain that object. See [release security](security-release.md). Use a clean source repository unless the owner separately approves and validates remediation of the existing history. Work through the following steps after reviewing the release tree and the permitted redistribution of the included artifacts.

~~~powershell
git status --short
git diff --check
python -m scripts.verify_frozen_artifacts
git add -A
git diff --cached --stat
git diff --cached --name-only
git commit -m "Prepare FleetMind v1.0.0 candidate"
$archive = Join-Path $env:TEMP 'FleetMind-v1.0.0-clean.zip'
git archive --format=zip --output="$archive" HEAD
$releaseSource = Join-Path (Split-Path (Get-Location).Path -Parent) 'FleetMind_Public'
Expand-Archive -LiteralPath $archive -DestinationPath $releaseSource
Set-Location -LiteralPath $releaseSource
git init -b main
git add -A
git commit -m "Import reviewed FleetMind v1.0.0 candidate"
git ls-files
~~~

After you create and approve a new source repository, add it as the remote in the **clean** repository and push the reviewed tree.

~~~powershell
git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-CLEAN-REPOSITORY.git
git push -u origin main
~~~

## Vercel frontend

1. In Vercel under your personal Hobby account, import the clean repository as a new project. Select **Next.js**, set **Root Directory** to `frontend`, and select Node.js 22. The checked-in [configuration](../frontend/vercel.json) runs `npm ci` and `npm run build`.
2. Set `NEXT_PUBLIC_FLEETMIND_MODE=portfolio` in Production and any public Preview environment. It determines the profile at build time. Do not set `FLEETMIND_API_URL` on this project. Deploy the recorded experience first.
3. Test dashboard, asset detail, SHAP, Model Intelligence and Model Health, Copilot examples, and telemetry replay in a private browser window and a phone-sized viewport. Check that a POST to `/api/fleetmind/predict` and a GET to `/api/fleetmind/auth/me` return 404.
4. Optionally connect the Render service by setting server-only `FLEETMIND_PORTFOLIO_API_URL` to its exact HTTPS origin, with no path or query, and redeploy. In Architecture, try **Score this reading**. During a cold start or outage the bridge returns a bounded unavailable response and the example keeps its recorded score. Retry after the free service wakes.

[Repository root configuration](https://vercel.com/docs/monorepos) · [Environment variables](https://vercel.com/docs/environment-variables)

## Render inference service

1. Review [render.yaml](../render.yaml), [Dockerfile.portfolio](../Dockerfile.portfolio) and the [dependency audit](security-release.md). In your Free workspace create a **Blueprint** from the clean repository, or create a Docker **Web Service** with the same settings. Select the **Free** instance, repository root build context, Dockerfile `./Dockerfile.portfolio`, health check `/health`, and turn off automatic redeploys. The container reads Render's `PORT`.
2. Add no database, persistent disk, model credentials, environment secrets or worker. Test `GET /health` and a known simulator input at `POST /infer` before configuring Vercel. Direct calls share the same 30-attempt-per-minute process budget, with one inference slot and a 2 KiB upload limit. A low ceiling is intentional.
3. Verify after an idle sleep. A wake longer than the bridge deadline is normal. The portfolio remains usable without live inference. If the service renews beyond your free allowances, remove its URL from Vercel and redeploy the recorded profile.

[Render Docker support](https://render.com/docs/docker) · [Blueprint configuration](https://render.com/docs/blueprint-spec)

## Local reproduction

~~~powershell
$env:NEXT_PUBLIC_FLEETMIND_MODE = 'portfolio'
Set-Location frontend
npm.cmd ci
npm.cmd run build
npm.cmd run start -- --hostname 127.0.0.1 --port 3000
~~~

For optional loopback inference, use the Git root in a separate terminal. The limit reproduces the advertised quota locally. It does not measure Render startup, scheduling, network latency or capacity.

~~~powershell
docker build -f Dockerfile.portfolio -t fleetmind-portfolio .
docker run --rm --name fleetmind-portfolio-dev --cpus=0.1 --memory=512m --memory-swap=512m --read-only --tmpfs /tmp:size=16m -p 127.0.0.1:19983:8000 fleetmind-portfolio
~~~

Set `FLEETMIND_PORTFOLIO_API_URL=http://127.0.0.1:19983` before the portfolio build and start. The proxy accepts an exact Render HTTPS origin or this loopback form. The hosted configuration ships precomputed SHAP and does not install the local SHAP stack for live requests.

## Release approval

After host verification and owner approval, add the real demo URL to the reviewed clean repository's README and verify that deployment. Tag that exact commit in the clean repository and copy [the release notes](../CHANGELOG.md) into the release entry.

~~~powershell
git log -1 --oneline
git tag -a v1.0.0 -m "FleetMind v1.0.0"
git push origin v1.0.0
~~~
