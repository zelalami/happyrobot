# Carrier Sales — Ops Dashboard (HappyRobot Apps overlay)

The inbound carrier-sales operations dashboard, delivered as an **overlay** onto the
HappyRobot **Next.js Full-Stack** custom-app template (Next 16 / React 19, `src/` layout).
It rides the template's existing auth and Twin wiring — so there are **no env vars to set**.

Source of truth lives here in the `happyrobot` monorepo under `apps-dashboard/`.

- **Auth:** every page calls `requireAppUser()` (the template's `hr_token`-cookie login). No
  separate password gate.
- **Twin reads:** server-side only, via the template's `getTwinRows()` (gateway + `hr_token`
  + `x-org-id`). The dashboard never reads Twin from the browser.
- **Data:** reads the `call_outcomes` table (one row per completed carrier call).

## Pages
- **Overview** (`/`) — KPI tiles (authority pass rate, OTP-verified rate, ceiling-respected,
  booking rate, avg negotiation rounds, agreed-vs-posted spread, handle time) + outcome bars.
- **Recent Calls** (`/calls`) — filterable table; row → detail.
- **Call Detail** (`/calls/[runId]`) — full row, lane, negotiation/booking, transcript/recording.
- **Compliance** (`/compliance`) — audit view; every section should be empty.

## Data secrecy
The dashboard never shows `max_buy`, a raw ceiling, or an agreed-vs-ceiling margin — that signal
isn't in the data layer at all. It shows `ceiling_respected` (a boolean compliance proof) and the
**agreed-vs-POSTED** spread (both numbers non-secret), bucketed/percentage.

## Apply it to your App (in the sandbox)
From the template project root (the folder that contains `src/` and `package.json`):

```bash
git clone https://github.com/zelalami/happyrobot /tmp/hr
cp -rf /tmp/hr/apps-dashboard/src/* src/   # adds the dashboard pages; replaces the template home page only
npm run build                              # verify it compiles
```

Then **Deploy** from the sandbox. This overlay only adds `app/calls`, `app/compliance`,
`app/dash.css`, `components/ui.tsx`, `lib/{types,kpis,calls}.ts`, and replaces `app/page.tsx`.
It does not touch the template's `auth.ts`, `twin.ts`, `env.ts`, `layout.tsx`, `globals.css`,
or the `login`/`logout`/`callback`/`api` routes.
