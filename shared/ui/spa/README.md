# Spine Hub SPA

**Scope:** Wave 3 part 2 Squad SPA1 — scaffold + 2 example panels + login UI.
SPA2 and SPA3 build the remaining 8 panels against this skeleton.

---

## Framework choice — SvelteKit 2 + Svelte 4

Per [Part 4.1 of `docs/V3_BUILD_SEQUENCE.md`](../../../docs/V3_BUILD_SEQUENCE.md),
the v3 frontend framework decision was deferred to start of Wave 3, with
Svelte as the recommended option (T1 + T6: vanilla won't scale to 10 panels).

**Squad SPA1 picks SvelteKit 2 on top of Svelte 4 (not Svelte 5 / runes), and
not bare Svelte.** Rationale:

1. **File-based routing** — 9 Hub surfaces become 9 directories under
   `src/routes/panels/`. SPA2 + SPA3 just add directories; zero router config.
2. **`+layout.svelte` / `+layout.ts` pattern** — the auth-guarded shell + the
   redirect-on-401 load function are exactly what SvelteKit primitives express
   natively. Hand-rolling them on bare Svelte costs ~200 lines.
3. **`adapter-static`** — builds to a pure static `dist/` directory the Hub
   container serves via FastAPI `StaticFiles`. No Node runtime in production.
4. **Svelte 4 (not 5)** — stable LTS as of 2026-05; the runes API is still
   land-grabbing across the ecosystem (testing-library, Vite plugin, IDE
   extensions). Squad SPA1 prioritises a stable substrate over the newest API.
5. **MIT-licensed end-to-end** — Svelte, SvelteKit, Vite, Tailwind, Vitest,
   adapter-static, testing-library. Satisfies design decision #18 (closed-source
   v1.0 — no GPL/AGPL JS in the bundle).

Trade-off accepted: SvelteKit pulls more dev-tooling weight than bare
Svelte. The production bundle is unchanged (~30 kB gzipped for the scaffold).

---

## Build + run

Squad SPA1 ships **declared dependencies only** — no `node_modules/`, no
`package-lock.json`. CI / Hub Docker build runs:

```bash
cd shared/ui/spa
npm ci                  # or `npm install` for the first generation of lockfile
npm run build           # → shared/ui/spa/dist/
npm test                # → vitest unit + component tests
```

Local dev:

```bash
cd shared/ui/spa
npm install
HUB_API_URL=http://localhost:8088 npm run dev    # SPA on :5173, proxies /api/* → :8088
```

The Hub `Dockerfile` runs the SvelteKit build in a dedicated
`spa-builder` stage and copies the output to `/app/static/spa/` in the
runtime image; see `hub/Dockerfile`.

---

## Hub integration

`shared/api/app.py:_mount_spa(app)` (added by Squad SPA1) wires two FastAPI
mounts:

| URL prefix              | Behaviour                                              |
|-------------------------|--------------------------------------------------------|
| `/static/spa/*`         | StaticFiles serving of hashed JS/CSS bundles.          |
| `/spa/` and `/spa/{path:path}` | SPA catch-all: returns `dist/index.html` so SvelteKit's history-mode handles deep links. Files under `dist/` (e.g. `favicon.svg`) are served directly. |
| `/api/v2/*`             | Existing REST + SSE routes (unchanged).                |
| `/api/v2/auth/{login,callback,logout}` | OIDC SPA flow (Keycloak per #25).         |
| `/healthz`, `/readyz`   | Health probes (unchanged).                             |

The SPA never hits `/api/v2/auth/*` directly with fetch — it issues a
hard navigation to `/api/v2/auth/login` so the browser follows the
Keycloak redirect chain naturally and the eventual `Set-Cookie` header
is honoured.

### Deployment-shape matrix

| Shape (per `docs/DEPLOYMENT_SHAPES.md`) | Who serves the SPA?               | SPA URL                  |
|-----------------------------------------|------------------------------------|--------------------------|
| Laptop                                  | Hub container (FastAPI StaticFiles)| `http://localhost:8088/spa/` |
| BYOC (founder)                          | Same — Hub container               | `https://<tenant>.spine.app/spa/` |
| Customer cloud                          | Same — Hub container               | `https://hub.<customer>/spa/` |
| On-prem                                 | Same — Hub container               | `https://spine-hub.<corp>/spa/` |
| Hub-on-CDN (deferred)                   | CloudFront / Fastly + `dist/` upload | `https://app.spine.dev/`     |

Across the first four shapes the SPA lives *inside* the Hub container —
no extra infrastructure needed. The CDN shape is deferred to v1.1 per
the deployment-shape doc and only becomes relevant once we want to
offload SPA traffic from per-customer Hub instances.

---

## Directory layout (the pattern SPA2 + SPA3 follow)

```
shared/ui/spa/
├── package.json
├── svelte.config.js
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── README.md                            ← you are here
└── src/
    ├── app.html                         ← base shell (viewport meta etc.)
    ├── app.css                          ← Tailwind layers + component classes
    ├── app.d.ts                         ← SvelteKit ambient types
    ├── lib/
    │   ├── responsive.css               ← minimal non-Tailwind overrides
    │   ├── test-setup.ts                ← vitest setup (jest-dom matchers)
    │   ├── api/
    │   │   ├── client.ts                ← apiFetch + subscribeSse + redirectToLogin
    │   │   ├── types.ts                 ← TS types mirroring shared/api Pydantic
    │   │   └── __tests__/client.test.ts ← vitest unit test
    │   ├── components/
    │   │   ├── Topbar.svelte
    │   │   ├── Sidebar.svelte
    │   │   ├── PanelHeader.svelte
    │   │   ├── LoadingSpinner.svelte
    │   │   ├── EmptyState.svelte
    │   │   ├── ErrorBanner.svelte
    │   │   └── CitationChip.svelte       ← Cite-or-Refuse chip per #12
    │   └── stores/
    │       ├── user.ts
    │       ├── decisions.ts             ← SSE-backed decision queue
    │       └── toasts.ts
    └── routes/
        ├── +layout.svelte               ← auth-guarded shell
        ├── +layout.ts                   ← auth load fn (401 → /auth/login)
        ├── +page.svelte                 ← dashboard tile grid (9 surfaces)
        ├── auth/
        │   ├── login/+page.svelte
        │   ├── logout/+page.svelte
        │   └── callback/+page.svelte
        └── panels/
            ├── decision-queue/
            │   ├── +page.svelte              ← Squad SPA1
            │   └── __tests__/page.test.ts
            └── role-chat/
                └── +page.svelte              ← Squad SPA1
```

### Pattern contract for SPA2 + SPA3 panels

Every new panel page MUST:

1. Live under `src/routes/panels/<panel-slug>/+page.svelte`.
2. Import + render `<PanelHeader title=... subtitle=... />` at the top.
3. Use `apiFetch` / `subscribeSse` from `$lib/api/client` — **never** call
   `fetch` directly; the wrapper handles the 401 → Keycloak redirect.
4. Render `<LoadingSpinner />` for in-flight state, `<EmptyState />` for
   zero-data, `<ErrorBanner />` for failures.
5. Surface any verify-class response citations through `<CitationChip />`
   (per design decision #12 Cite-or-Refuse). If the backend tagged the
   tool `requires_citation=True`, the SPA MUST render at least one chip.
6. Use Tailwind utilities — no per-panel CSS files unless a custom rule
   truly cannot be expressed in Tailwind (responsive.css is the escape
   hatch).
7. Co-locate a `__tests__/page.test.ts` next to the page; mock
   `$lib/api/client` rather than network.

---

## Type generation (OpenAPI → TypeScript) — Squad SPA3

Hand-maintaining `src/lib/api/types.ts` against `shared/api/routes/*.py`
is a drift hazard (Wave 3 part 2 drift audit Finding-3). Squad SPA3 wires
`openapi-typescript` so the SPA types are generated from the FastAPI
OpenAPI document at `/api/v2/spec`.

### Dev workflow

1. Start a Hub locally (`uvicorn shared.api.app:create_app --factory --port 8090`).
2. Run the codegen script:

   ```bash
   cd shared/ui/spa
   npm run codegen:types
   # equivalent to:
   bash scripts/codegen-types.sh
   ```

3. The script writes `src/lib/api/types.generated.ts`. The public
   `src/lib/api/types.ts` façade re-exports named shapes (`Citation`,
   `DecisionCard`, …) so panel imports never change.

Environment overrides:

| Variable                  | Effect                                                       |
|---------------------------|--------------------------------------------------------------|
| `SPINE_OPENAPI_URL`       | Source URL (default `http://localhost:8090/api/v2/spec`).    |
| `SPINE_OPENAPI_SNAPSHOT=1`| Force using `scripts/openapi-sample.json` instead of live URL.|

If the live URL is unreachable the script auto-falls back to the
snapshot — so `npm run codegen:types` always succeeds, even offline.

### CI / production strategy

CI / Hub Docker build MUST source from the checked-in snapshot
(`scripts/openapi-sample.json`) — production builds NEVER reach out to
a live Hub. Wave 4 will add a `make refresh-openapi-snapshot` target
that diffs the live spec against the snapshot and fails CI if they have
drifted (forcing the dev who changed a route to commit the regenerated
snapshot in the same PR).

The snapshot is a JSON document, version-controlled, ~5 KB today.
Refresh it whenever you add/change a backend response shape:

```bash
# from a running Hub:
curl -s http://localhost:8090/api/v2/spec > shared/ui/spa/scripts/openapi-sample.json
git add shared/ui/spa/scripts/openapi-sample.json
```

### Why the façade keeps the hand-rolled fallback

Squad SPA3 ships under a strict no-`npm install` constraint, so the
generated file does not exist on this branch. The façade keeps the
hand-rolled types so the SPA still builds; once codegen runs (Wave 4
build pipeline), the commented re-export block in `types.ts` becomes the
canonical surface and the fallback is deleted.

---

## Responsive testing (per design decision #28)

Squad SPA1 verifies all panels at:

| Device                | Viewport (px) | Tested layout                       |
|-----------------------|---------------|--------------------------------------|
| iPhone Safari (iOS 17)| 390 × 844     | Single-column cards; stacked actions |
| Android Chrome (Pixel 8)| 393 × 851   | Identical single-column behaviour    |
| iPad portrait         | 768 × 1024    | 2-column grid; sidebar still drawer  |
| Desktop               | ≥ 1024        | 3-column grid; sidebar pinned        |

Tailwind breakpoints (`tailwind.config.ts`) reflect those targets, with
an added `xs: 390px` to absorb the iPhone width as a first-class
breakpoint rather than relying on default `sm: 640px`.

The handful of mobile concerns Tailwind doesn't cover sit in
`src/lib/responsive.css`:

- `env(safe-area-inset-*)` honoured for iOS notch
- Touch targets ≥ 44 px square on `pointer: coarse` devices (WCAG 2.5.5)
- `font-size: 16px` floor on form inputs to defeat iOS auto-zoom
- `prefers-reduced-motion` strips animations
- Compact scrollbar styling on `pointer: fine` + `min-width: 1024px`

---

## What ships in this PR vs. what stays for SPA2 / SPA3

**Squad SPA1 ships:**

- The complete scaffold (config, layout, stores, components, responsive)
- 2 example panels: `decision-queue/` + `role-chat/`
- The full auth flow (login / callback / logout pages)
- Sidebar / dashboard advertise all 9 surfaces with `soon` placeholders
- 1 client unit test + 1 panel component test
- Hub Dockerfile + `shared/api/app.py` mount integration

**Squad SPA2 owns (5 panels):** `master-roles`, `registry`, `audit`,
`vault-config`, `integrations`. Backends already exist under
`shared/api/routes/`. Each panel:
- Reuses `PanelHeader`, `LoadingSpinner`, `EmptyState`, `ErrorBanner`,
  `CitationChip`.
- Adds at least one component test.
- Documents any new responsive edge cases in `responsive.css`.

**Squad SPA3 owns (3 panels + 1 cross-cutting):** `federation`,
`license`, `kg-search` *plus* the OpenAPI → TypeScript codegen pipeline
that replaces the hand-maintained `$lib/api/types.ts`. Federation panel
needs the hub-switcher UX (per design decision #4 / #10).

---

## Troubleshooting

### Project workspace tab freezes (“Loading actions” / Page Unresponsive)

See **[`docs/SPA_PROJECT_WORKSPACE_HANG.md`](../../../docs/SPA_PROJECT_WORKSPACE_HANG.md)** — root cause, staged boot fix, and Playwright regression tests.

```bash
bash tools/hub-up.sh --rebuild
cd shared/ui/spa && npx playwright test e2e/project-workspace-hang.spec.ts e2e/booger-workspace.spec.ts
```

---

## Open items left for future waves

- **`/api/v2/auth/whoami`** doesn't exist yet — `+layout.ts` probes
  `/api/v2/registry/me` as a fallback. Wave 4 adds the dedicated whoami
  endpoint; the SPA needs no change beyond swapping the probe URL.
- **SSE reconnect/backoff** — current `subscribeSse` aborts on error.
  Wave 4 adds exponential reconnect once the persistence layer (Wave 4
  Squad D) backs the decision queue.
- **Streaming role-chat reply** — backend returns synchronously. The
  panel is structured so swapping `apiFetch` for an SSE consumer is a
  ~30-line change.
- **Federation hub switcher** — SPA3 panel; depends on Wave 4 Squad A.
- **Storybook / Playwright E2E** — deferred to Squad SPA4 per the Wave 3
  part 2 scope split.
