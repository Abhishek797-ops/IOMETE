---
name: frontend-design
description: Premium B2B SaaS frontend work in this repo — design tokens, layout, component architecture, motion, accessibility and responsive behaviour. Use when building or reviewing any page or component under frontend/src.
---

# Frontend design — IOMETE COMPASS

## The look we are aiming for

A funded enterprise data-infrastructure product. Reference points: Linear, Vercel dashboard,
Stripe docs, Temporal Cloud. Confident typography, generous but disciplined spacing, dense
information presented calmly.

## Tokens — use them, never raw hex

Defined on `:root` in `src/styles/globals.css`, consumed via Tailwind v4 `@theme`.

| Surface role | Token | Notes |
| --- | --- | --- |
| Public pages background | `--surface` (warm white `oklch(99% 0.004 85)`) | Slight warmth, never pure `#fff` |
| Elevated card | `--surface-raised` | |
| Dashboard chrome | `--graphite-*` scale | Deep charcoal, used for `/app`, `/fde`, `/admin` shells |
| Accent | `--accent` (emerald) | Restraint: one accent action per view |
| Borders | `--border`, `--border-strong` | Hairlines, `0.5px`-feel at 1px |

Dark mode is driven by `@media (prefers-color-scheme: dark)` plus a `data-theme` override.

## Banned

Purple/violet AI gradients. Glassmorphism beyond one deliberate instance. Glowing borders.
Cards nested more than two deep. Decorative charts with no data behind them. Full-viewport
hero sections with three words in them. Spinner-only loading states.

## Required on every page

1. **Loading** — skeletons that match the final layout's geometry, not a centred spinner.
2. **Error** — what failed, why, and one recovery action. Never a bare "Something went wrong".
3. **Empty** — explain what would appear here and give the action that creates the first one.
   Empty states are a design opportunity, not a fallback.
4. **Validation** — client-side with Zod + React Hook Form, mirrored by server validation.
   Errors attach to fields with `aria-describedby`.
5. **Responsive** — works at 375px with a 16px gutter and no horizontal scroll. Tables either
   scroll in a labelled region or collapse to a definition-list card layout under `md`.
6. **Keyboard** — every interactive element reachable and operable, visible `:focus-visible`
   ring, logical tab order, `Escape` closes overlays, focus trapped in modals and returned on close.
7. **Feedback** — every mutation produces a visible result: optimistic update, toast, or inline
   state change. No silent success.

## Component architecture

- `components/ui/` — primitives (Button, Card, Badge, Input, Select, Dialog, Tabs, Table,
  Toast, Skeleton, Tooltip, StatusDot). No business logic, no data fetching.
- `components/layout/` — shells: `PublicShell`, `AppShell`, `FdeShell`, `AdminShell`, nav.
- `components/diagrams/` — `@xyflow/react` architecture canvases, SVG pipeline diagrams.
- `components/charts/` — Recharts wrappers that already carry our axis/tooltip/legend defaults.
- `components/features/<domain>/` — composed, domain-aware components.

Server Components by default. `"use client"` only for interactivity. Fetch on the server where
the data is not user-interactive; use the typed client in `src/lib/api.ts` otherwise.

## Motion

`motion` (Framer Motion v14). Motion must explain something: a step advancing, a node
connecting, a panel's origin. Durations 150–300ms, `ease-out` for entrances. Respect
`prefers-reduced-motion` — gate every non-trivial animation on the `useReducedMotion` hook.
No infinite ambient animation.

## Accessibility is a product requirement

Target WCAG 2.1 AA. Text contrast ≥ 4.5:1 (≥ 3:1 for ≥ 24px). Never encode meaning in colour
alone — status gets a shape or label too (`StatusDot` pairs a hue with a glyph). Icon-only
buttons get `aria-label`. Live regions for async results. Charts carry a text summary or an
accessible data table.
