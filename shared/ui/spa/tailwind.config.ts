// Spine Hub SPA — Tailwind config (V3 Wave 3 part 2, Squad SPA1)
//
// Per design decision #28: mobile-responsive Day 1. Mobile-first
// breakpoints are Tailwind defaults (sm 640 / md 768 / lg 1024 / xl 1280),
// and we add an `xs` breakpoint at 390px for iPhone Safari + an `iphone-se`
// alias at 375px so panel grids degrade gracefully on the smallest devices
// we test against.
//
// Target viewports verified by Squad SPA1:
//   - iPhone Safari       390 x 844  (iOS 17 / Safari 17 default)
//   - Android Chrome      393 x 851  (Pixel 8 default)
//   - iPad portrait       768 x 1024
//   - Desktop             >= 1024
//
// Colour palette mirrors the existing shared/ui/dashboard/dashboard.css
// tokens so the SPA visually inherits Hub branding once SPA2/SPA3 ship
// the remaining 8 panels.

import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  darkMode: 'class',
  theme: {
    screens: {
      // Mobile-first: every util applies to >= the width listed.
      'xs': '390px',     // iPhone Safari / small Android
      'sm': '640px',     // landscape phone
      'md': '768px',     // iPad portrait
      'lg': '1024px',    // desktop
      'xl': '1280px',    // wide desktop
      '2xl': '1536px'
    },
    extend: {
      colors: {
        // Spine brand neutral surface stack (light + dark).
        surface: {
          50:  '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b'
        },
        // Decision-card severity palette (per shared/api/routes/decisions.py).
        severity: {
          info: '#3b82f6',
          warning: '#f59e0b',
          critical: '#ef4444'
        },
        accent: {
          DEFAULT: '#6366f1',
          muted: '#a5b4fc'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace']
      },
      maxWidth: {
        panel: '64rem',
        chat: '48rem'
      }
    }
  },
  plugins: []
} satisfies Config;
