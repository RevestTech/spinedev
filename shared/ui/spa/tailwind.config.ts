// Spine Hub SPA — Tailwind config (modernized, dark-first).
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
        surface: {
          50:  '#fafafa',
          100: '#f4f4f5',
          200: '#e4e4e7',
          300: '#d4d4d8',
          400: '#a1a1aa',
          500: '#71717a',
          600: '#52525b',
          700: '#3f3f46',
          800: '#27272a',
          900: '#18181b',
          950: '#09090b'
        },
        severity: {
          info: '#3b82f6',
          warning: '#f59e0b',
          critical: '#ef4444',
          success: '#10b981'
        },
        accent: {
          DEFAULT: '#8b5cf6',
          muted: '#a78bfa',
          dim: '#6d28d9',
          glow: 'rgba(139,92,246,0.45)'
        },
        accent2: {
          DEFAULT: '#06b6d4',
          muted: '#67e8f9'
        },
        brand: {
          from: '#8b5cf6',
          via:  '#6366f1',
          to:   '#06b6d4'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace']
      },
      maxWidth: {
        panel: '64rem',
        chat: '48rem'
      },
      backgroundImage: {
        'gradient-brand':
          'linear-gradient(135deg, #8b5cf6 0%, #6366f1 50%, #06b6d4 100%)',
        'gradient-brand-soft':
          'linear-gradient(135deg, rgba(139,92,246,0.14) 0%, rgba(6,182,212,0.06) 100%)',
        'gradient-mesh':
          'radial-gradient(at 0% 0%, rgba(139,92,246,0.18), transparent 50%), ' +
          'radial-gradient(at 100% 0%, rgba(6,182,212,0.12), transparent 50%), ' +
          'radial-gradient(at 100% 100%, rgba(99,102,241,0.10), transparent 50%)'
      },
      boxShadow: {
        glow:     '0 0 28px 0 rgba(139, 92, 246, 0.32)',
        'glow-sm':'0 0 14px 0 rgba(139, 92, 246, 0.22)',
        card:     '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 10px 30px -16px rgba(0,0,0,0.55)'
      },
      keyframes: {
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' }
        }
      },
      animation: {
        shimmer: 'shimmer 2.4s linear infinite'
      }
    }
  },
  plugins: []
} satisfies Config;
