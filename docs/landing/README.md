# Spine — Landing Page

Public-facing landing page for Spine v2. Implements `STORY-5.1.4` in [`docs/BACKLOG.md`](../BACKLOG.md).

Static. No framework. No build step. No CDN. No analytics. No tracking.

## Files

| File | Purpose | Approx LOC |
|---|---|---|
| `index.html` | Page structure (hero, six-corner moat, demo, architecture, personas, why-local, install, footer) | ~310 |
| `landing.css` | Theme tokens, dark/light, responsive grid, hex tiles, terminal demo styling | ~250 |
| `landing.js` | Theme toggle, smooth scroll, animated 5-move dialogue player | ~180 |
| `demo-script.json` | Scripted product-role dialogue (vibecoder building a family media tracker) | ~150 |

## How to host

The directory is fully static — any HTTP server will do.

```bash
# Local preview
cd docs/landing
python3 -m http.server 8080
# → http://localhost:8080

# GitHub Pages
# Point Pages at /docs and add an index redirect, or copy this directory to /
```

Production hosts: nginx, Caddy, GitHub Pages, Cloudflare Pages, Vercel static, Netlify. No server-side code; no environment variables.

## Customization

- **Branding** — edit `index.html` (`<title>`, header brand, hero copy) and the `--accent` / `--accent-strong` CSS custom properties at the top of `landing.css`.
- **Demo dialogue** — edit `demo-script.json`. Each turn needs `move` (1–5), `label`, `actor` (`user` or `product`), `text`. `landing.js` reads the file on page load and animates one turn at a time.
- **Architecture diagram** — inline SVG in `index.html` `#architecture`. Edit the `<rect>` and `<text>` elements directly; no asset pipeline.
- **Six-corner moat tiles** — duplicate or remove `<article class="hex-tile">` blocks in `#moat`.

## Accessibility

- Semantic landmarks (`header`/`main`/`section`/`nav`/`footer`).
- Skip link to `#main`.
- ARIA labels on the demo terminal (`role="log"`, `aria-live="polite"`) and the move indicator.
- Theme toggle button reports state via `aria-pressed`.
- Focus rings preserved (no `outline: none`).
- WCAG AA contrast on both themes (dark default, light via toggle / system pref).
- `prefers-reduced-motion` disables typewriter pacing and the blinking cursor.

## Demo player controls

| Control | Behavior |
|---|---|
| Play | Start (or resume) auto-playback from the current turn. Types each turn, pauses ~700ms between turns. |
| Pause | Cancel the in-flight typewriter and animation queue. State preserved. |
| Step | Advance exactly one turn. Useful for screen-recording walkthroughs. |
| Reset | Wipe the terminal, return to turn 0. |

The move indicator (`Move 0 / 5` → `Move 5 / 5`) tracks the active turn for sighted users; the same info is announced via `aria-live`.

## Cross-references

- `docs/positioning.md` — one-page positioning narrative (source of hero + moat copy).
- `docs/comparison.md` — capability matrix.
- `docs/naming-decision.md` — `STORY-5.1.3` decision doc; landing page uses "Spine" pending the recorded decision there.
- `docs/research/COMPETITIVE_LANDSCAPE.md` — full competitive analysis the moat copy draws from.
- `docs/PRD.md` REQ-INIT-1 FR-2 — the 5-move protocol the demo dramatizes.
- `shared/charters/product.md` — charter implementing the 5-move intake protocol.
- `plan/templates/intake/web-app.yaml` — intake template the demo references in move 4.

## Out of scope (for this page; do not add without a story)

- Marketing analytics / pixels.
- Newsletter / lead capture forms.
- External font CDNs (system font stack only).
- A JS framework.
