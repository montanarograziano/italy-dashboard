# Security Policy

Italy Dashboard is a **read-only statistics viewer**: it has no user accounts,
no login, no write endpoints, and collects no personal data. It reads public
datasets (ISTAT, INPS, MUR/USTAT, Open-Meteo/Copernicus) into local Parquet
snapshots and serves them back through two frontends (a Reflex app and a
static DuckDB-WASM app). There is no database to inject into and nothing to
exfiltrate beyond what the site already displays publicly.

That said, real risk surfaces exist and reports are welcome:

- Dependency vulnerabilities (Python, npm, or the Docker base image)
- XSS or injection in the Reflex/React frontends
- Anything that lets a client read files or paths it should not
  (path traversal in the static asset / parquet serving)
- CI or supply-chain issues (e.g. a workflow that could leak `GITHUB_TOKEN`
  or run untrusted code from a fork with elevated permissions)

## Reporting a vulnerability

Please **do not open a public GitHub issue** for a security report. Use
GitHub's private reporting instead: on this repository, go to
**Security → Advisories → Report a vulnerability** (or the direct
[`/security/advisories/new`](https://github.com/montanarograziano/italy-dashboard/security/advisories/new)
link). This opens a private channel with the maintainer before anything is
public.

Include what you tried, what you expected, and what happened. A minimal
reproduction (a URL, a request, a diff) is more useful than a description.

## Response

This is a solo-maintained, seed-stage project — there is no SLA, but reports
are read and triaged as they come in. Fixes ship as a normal commit + release;
there is no separate embargo process for a project with no user data at
stake.

## Scope notes

- **Not in scope:** the accuracy of upstream data (ISTAT/INPS/USTAT/
  Open-Meteo publish what they publish; see
  [`docs/07-methodology.md`](docs/07-methodology.md) for known caveats) and
  the free-tier availability of the Render/Netlify deployments.
- **Dependencies:** `just check` runs lint, types, and tests in CI on every
  PR; there is no separate scheduled dependency-audit job yet — a PR bumping
  a vulnerable pin is also a welcome report.
