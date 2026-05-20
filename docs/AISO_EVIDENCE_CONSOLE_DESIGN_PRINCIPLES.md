# AISO Evidence Console Design Principles

## Purpose

AISO is a data-intensive AI visibility platform. The product helps a business understand where AI models mention it, where they do not, what sources those models trust, which competitors are winning, and what actions should be taken before the next scan.

The new UI should not feel like a marketing dashboard or a playful SaaS homepage. It should feel like a precise evidence console: calm, dense, trustworthy, and built for repeated analysis.

## North Star

An evidence console for understanding what AI models say, why they say it, and what to fix next.

The product's signature experience should be the movement from scan evidence to action:

1. Build or confirm the business context.
2. Generate buyer-intent questions.
3. Run those questions across AI providers.
4. Compare visibility by provider, intent group, source, and competitor.
5. Classify cited evidence.
6. Turn gaps into prioritized actions and content drafts.
7. Rerun scans and track movement over time.

## Design References

Use these references as product logic inspiration, not as visual templates to copy.

- Linear: app shell discipline, compact navigation, side panels, issue/action queue behavior.
- Supabase: data-heavy tables, logs, technical artifacts, source rows, developer-grade clarity.
- Stripe: metric polish, comparison surfaces, trust and billing/export clarity.
- Cohere: calm enterprise AI tone, model/provider seriousness, restrained command-center feel.
- Clay: only the workflow idea that different object types can carry distinct color identities.

Do not clone exact colors, type systems, gradients, layouts, copy, icons, or component shapes from any of these products.

## Product Surface Inventory

The UI must support these AISO surfaces:

- Overview dashboard: latest scan summary, AI Visibility Score, provider status, intent gaps, competitor pressure, source opportunities, and priority actions.
- Responses and proof: AI answers, missed questions, citations, source roles, raw evidence, filters, and drilldowns.
- Scan detail: scan status, timing, selected providers, intent groups, custom questions, skipped providers, artifacts, exports, and scan-scoped metrics.
- Action plan: prioritized remediation queue with evidence, impact, effort, status, target providers, and target questions.
- Competitors: mention share, score comparison, provider split, rank movement, and proof blockers.
- Progress: score movement, gaps closed, recommendation completion, scan timeline, and before/after comparisons.
- Assistant: scan-grounded conversations, tool progress, action/content context, generated content, and saved drafts.
- Content library: generated drafts, review states, approval flow, export actions, and source action linkage.
- Onboarding: business setup, website discovery, context review, provider keys, scan objectives, custom questions, and launch.
- Settings: BYOK state, provider key status, plan/export access, and security reassurance.

## Current Implementation Risks To Design Against

The existing product already has the right data model for an evidence console, but the redesign must avoid carrying forward these source-level clutter risks:

- Overview and Scan Detail reuse many card-based summary patterns; the new system should convert repeated metrics into a matrix, compact rows, and focused drilldowns.
- Responses currently separates proof into many tabs and card panels; the new default should be a strong evidence table with filters and drawers.
- Actions are rendered as action cards; the new default should be an issue-queue table so priority, evidence, effort, and status are comparable at a glance.
- Scan Detail nests overview-style data, metadata, custom questions, exports, and warnings; the new layout must separate run metadata from evidence analysis.
- Compare and Progress should avoid hero-style explanatory blocks inside the authenticated app; users need selectors, deltas, and proof rows first.
- Onboarding has many important setup concepts: discovered profile, buyer context, objectives, provider keys, custom questions, and scan launch. It needs a stepper/workbench pattern with clear state, not a long form that treats every section equally.
- Assistant and drafts should behave like a workbench attached to scan evidence, not an isolated chat surface.

## Core Principles

### 1. Evidence Before Decoration

Every screen must make evidence easier to read. Scores, answers, citations, source roles, missed questions, competitors, and recommended actions are the visual priority. Decorative effects are allowed only when they help orient the user or create hierarchy.

### 2. Dense, Not Cluttered

AISO needs to display a lot of information. Density is acceptable; clutter is not. Use hierarchy, grouping, tables, drawers, sticky controls, and progressive disclosure instead of spreading everything across equal-weight cards.

### 3. One Primary Job Per Screen

Each page should answer one main question:

- Overview: What changed, what matters, and what should I do next?
- Responses: What did AI say, and what proof supports it?
- Actions: What should I fix next?
- Scan detail: What happened in this run?
- Competitors: Who is winning across AI providers, and why?
- Progress: Are we improving over time?
- Assistant: What can I ask or generate from the current evidence?
- Settings: Is my account and provider setup ready to run scans safely?

### 4. Matrix-First Product Identity

AISO should have its own signature UI object: the Provider x Intent Evidence Matrix.

Rows represent AI providers. Columns represent intent groups. Cells show score, mentions, misses, or status. This matrix should become the fastest way to understand scan performance and should appear in the Overview, Scan Detail, and Compare experiences.

### 5. Progressive Disclosure

The first view should show signal. Details should open in side drawers, expanded rows, tabs, or drilldown panels.

Do not dump raw answer excerpts, citation URLs, source classifications, and artifact links into the same first-level view unless the page's job is explicit audit review.

### 6. Tables For Repeated Data

Use tables or compact rows for repeated entities:

- Responses
- Missed questions
- Sources
- Actions
- Scans
- Artifacts
- Competitors
- Content drafts

Cards are for summaries, highlights, or small sets of heterogeneous content. Avoid card grids for large repeated lists.

### 7. Every Recommendation Must Show Its Proof

An action is not credible unless it links back to evidence. Every recommendation surface should expose:

- Why this action exists.
- Which questions triggered it.
- Which providers missed the client.
- Which sources were cited instead.
- What impact or priority score caused its rank.
- What the user should do next.

### 8. Security Is Quiet But Visible

BYOK and proxy security are core product trust features. Show key status, skipped providers, and export access clearly, but avoid alarmist banners unless the user must act.

Never design a flow that implies API keys are stored on AISO servers.

### 9. Responsive Density Must Be Designed

Dense desktop tables cannot simply shrink on mobile. Responsive behavior must be defined per component:

- Large matrices become horizontally scrollable with sticky row labels.
- Tables become grouped rows with primary columns visible and details collapsed.
- Side drawers become bottom sheets or full-page detail routes.
- Toolbar filters wrap into compact segmented controls.
- Long source URLs truncate with accessible full-text copy behavior.

### 10. No Marketing Layouts Inside The App

Do not use oversized hero sections, decorative section bands, or landing-page storytelling inside authenticated product pages. The app should start with useful state, not persuasion.

## Information Architecture

### App Shell

Use a compact left navigation and a persistent top context bar.

The top context bar should carry:

- Active client.
- Latest scan status.
- Last completed scan date.
- Provider readiness.
- Primary action: run scan or continue setup.

The left navigation should group pages by workflow:

- Command: Overview, Responses, Actions.
- Analysis: Scans, Compare, Progress, Competitors.
- Workbench: Assistant, Content Library.
- Setup: Onboarding, Settings.

### Overview Page

The Overview page should be the command center. Recommended desktop structure:

1. Header context row: client, latest scan, provider status, run-scan action.
2. Executive readout strip: visibility score, delta, appearance rate, missed answers, open high-priority actions.
3. Provider x Intent Evidence Matrix.
4. Priority action queue: top 3-5 items, rendered as compact rows.
5. Evidence columns:
   - Source opportunities.
   - Competitor pressure.
   - Scan health and warnings.

Avoid a page dominated by three or four large cards. The Overview should be scannable in 10 seconds and drillable in 2 clicks.

### Responses Page

Responses should be the product's strongest audit surface.

Default view: evidence table.

Primary columns:

- Question
- Intent group
- Provider
- Mention state
- Answer excerpt
- Sources cited
- Source role
- Priority
- Action

Clicking a row opens an evidence drawer with:

- Full question.
- Provider answer excerpt.
- Client mentioned or missed.
- Competitors mentioned.
- Cited source list.
- Source classifications.
- Recommended next action.
- Link to create or open related action.

Tabs can still exist, but they should not fragment the user's understanding. Prefer one strong table with filters, plus detail drawers.

### Actions Page

Actions should behave like an issue queue, not a card gallery.

Primary columns:

- Priority
- Action
- Impact
- Effort
- Category
- Evidence count
- Providers
- Status

Clicking an action opens a detail drawer:

- Problem statement.
- Evidence summary.
- Target questions.
- Target providers.
- Cited sources.
- Remediation type.
- Suggested content or optimization next step.
- Status controls.

### Scan Detail

Scan Detail should answer what happened in one run.

Required sections:

- Run metadata: status, started/completed, duration, providers, groups, skipped providers.
- Scan-scoped Provider x Intent Matrix.
- Custom Questions panel, explicitly separate from benchmark metrics.
- Artifacts and exports.
- Errors and warnings.
- Link to compare this scan against another scan.

### Competitors

Competitor views should focus on pressure and proof, not podium decoration.

Use:

- Compact leaderboard.
- Provider split table.
- Intent-group comparison.
- Competitor proof sources.
- Questions where competitors were mentioned and the client was not.

### Progress And Compare

Progress should show movement over time without hiding the underlying scan runs.

Use:

- Score timeline.
- Gaps closed.
- Action completion rate.
- Scan table beneath the charts.
- Compare entry point for before/after evidence.

Compare should use side-by-side scan selectors and delta rows. Avoid visually heavy mirrored card stacks.

### Assistant

The assistant should feel like an evidence-aware workbench.

Required context surfaces:

- Active client.
- Latest scan.
- Open actions.
- Available tools.
- Draft notices.
- Citations or scan evidence used in the answer.

The assistant should not visually compete with the main evidence pages. It should support interpretation and content generation.

## Visual Direction

### Tone

Calm, precise, enterprise-grade, technical, and trustworthy.

Avoid playful mascots, consumer softness, neon overload, glass clutter, and decorative gradients as a primary identity.

### Color

Use an AISO-owned palette based on graphite surfaces and Linear-inspired indigo/lavender signal colors.

- Canvas: deep carbon, not blue-black.
- Surface 1: raised graphite.
- Surface 2: command-panel charcoal.
- Hairline: cool gray with enough contrast on dark.
- Text primary: near-white.
- Text secondary: muted gray.
- Primary accent: muted indigo.
- Evidence accent: clear blue.
- Competitor accent: restrained violet.
- Warning accent: amber.
- Critical accent: rose.
- Success accent: controlled green.

Rules:

- Accent colors carry semantic meaning, not decoration.
- Provider colors may appear as small chips or cell indicators, never as giant blocks.
- Avoid one-note purple, blue-slate, beige, or neon themes.
- Heatmaps should use controlled intensity and labels, not color alone.

### Typography

Use a highly legible UI sans for product text and a mono face only for technical identifiers.

Use monospace for:

- Scan IDs
- Provider IDs
- Source URLs
- Artifacts
- Code-like export names
- Numeric counters only where alignment matters

Do not use mono for body copy or marketing effect.

### Shape And Elevation

- Default radius: 8px.
- Major panels: 10-12px.
- Pills only for badges, filters, and status chips.
- Elevation should come from surface contrast and hairline borders.
- Shadows should be subtle and rare.
- Avoid nested cards.

### Motion

Motion should be functional:

- Row hover.
- Drawer open/close.
- Scan progress pulse.
- Filter transitions.
- Matrix cell focus.

Avoid decorative animations, parallax, excessive glow, or constant movement.

## Component Principles

### Provider x Intent Evidence Matrix

The signature AISO component.

Desktop:

- Rows: providers.
- Columns: intent groups.
- Sticky provider labels.
- Cell states: score, mentions/misses, unavailable, skipped, no data.
- Click cell opens filtered Responses view or drawer.

Mobile:

- Provider sections stack vertically.
- Intent cells scroll horizontally or collapse into ranked rows.

### Evidence Table

Used for responses, sources, actions, scans, and artifacts.

Rules:

- Sticky header where useful.
- First column carries the main object.
- Secondary data is compact and aligned.
- Long text uses two-line clamp with drawer for full details.
- Every row has one obvious click target.

### Evidence Drawer

The standard drilldown pattern.

Rules:

- Right side on desktop.
- Full-screen or bottom-sheet style on mobile.
- Header states the object and status.
- Body groups evidence, source, and action.
- Footer carries primary next action.

### Status Pills

Use short, semantic labels:

- Running
- Complete
- Failed
- Skipped
- Missing key
- Mentioned
- Not mentioned
- Source target
- Monitor
- Done

Avoid long explanatory labels inside pills.

### Action Rows

Actions are work items. They need the same discipline as issue rows:

- Priority marker.
- Short title.
- Evidence count.
- Impact.
- Effort.
- Status.
- Owner or next step when available.

## Clutter Prevention Rules

These are non-negotiable for implementation.

1. No page should open with more than one hero-scale headline.
2. Do not put UI cards inside other cards.
3. Do not show more than 5 summary cards in one row/cluster.
4. Repeated data must use a table, matrix, or compact list.
5. Every large panel needs a clear title, one sentence of context, and one primary action at most.
6. Do not give every metric the same visual weight.
7. Long answer excerpts must be clamped and opened in a drawer.
8. Source URLs must truncate intelligently.
9. Filter bars must wrap cleanly or collapse.
10. Drawer content must not duplicate the entire page; it should add detail.
11. Empty states should be compact and action-oriented.
12. Banners are only for active warnings or required setup.
13. Use whitespace between groups, not inside every row.
14. Tables must have stable column widths.
15. Mobile layouts must be designed separately, not squeezed.

## Visual QA Workflow

No major UI redesign should be considered complete until it passes browser verification.

### Browser Readiness Notes

The frontend can be run locally against the Railway backend for authenticated UI review:

- Frontend command shape: set `AISO_API_URL` and `NEXT_PUBLIC_API_URL` to the Railway backend URL, then run the Next.js dev server.
- Use `127.0.0.1` explicitly when browser tooling has trouble reaching `localhost`.
- Verify the login page first, then inspect protected product pages with a test account.
- If automation cannot safely continue after credential entry, pause and use a user-authenticated session rather than judging dashboard pages from unauthenticated redirects.

### Before Coding

1. Start the local backend and frontend.
2. Open the app in the browser.
3. Inspect the current target page.
4. Capture the clutter risks before editing:
   - Too many cards.
   - Repeated information.
   - Overlapping text.
   - Cramped rows.
   - Weak hierarchy.
   - Hidden or unclear primary action.
   - Broken responsive behavior.

For protected dashboard pages, use an authenticated local browser session or a test account before judging layout quality.

### During Implementation

Check each redesigned surface at:

- 1440 x 900 desktop.
- 1280 x 720 compact desktop.
- 1024 x 768 tablet landscape.
- 768 x 1024 tablet portrait.
- 390 x 844 mobile.

### Required Page Checks

- Overview: matrix readable, action queue compact, no competing hero/card clutter.
- Responses: table columns fit, filters usable, drawer readable, excerpts do not overflow.
- Actions: rows scan quickly, evidence drawer explains why, status controls do not crowd content.
- Scan Detail: metadata, custom questions, exports, and errors are separated cleanly.
- Assistant: chat, context, drafts, and secondary actions do not crowd one another.
- Settings: BYOK state is clear without making the page feel alarming.

### Completion Criteria

A page passes visual QA only when:

- No text overlaps or escapes its container.
- No button label wraps awkwardly.
- No table becomes unreadable at supported breakpoints.
- Primary action is obvious.
- Secondary actions are available but quiet.
- Empty/loading/error states fit the same layout.
- Console has no UI-breaking errors.
- The design supports real data, not only ideal demo data.

## Redesign Sequence

Implement the redesign in this order:

1. Design tokens and app shell.
2. Core primitives: table, drawer, status pills, metric tiles, matrix cells.
3. Overview page.
4. Responses page.
5. Actions page.
6. Scan Detail page.
7. Scans, Compare, Progress, Competitors.
8. Assistant and Content Library.
9. Onboarding and Settings polish.

Do not redesign all pages independently. The system should be built from reusable product primitives so density and hierarchy stay consistent.

## Final Design Standard

AISO should feel like the place a serious operator goes to inspect AI visibility evidence and decide what to do next.

If a design choice does not improve scan comprehension, evidence trust, or action prioritization, it probably does not belong in the authenticated app.
