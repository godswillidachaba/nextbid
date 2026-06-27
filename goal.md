# Goal: Material Tailwind Quality Upgrade

## Reference
Use `/sample/material-tailwind` (Material Tailwind component library) as the design system foundation — specifically the `@material-tailwind/html` package at `packages/material-tailwind-html/` — to bring the same component quality, visual polish, and interactive richness to the NextBid admin SPA (`/site/templates/admin.html`).

- React is NOT used. Everything stays as plain HTML + CSS + JS with Alpine.js for state management.
- `@material-tailwind/html` provides the CSS theme tokens (colors, typography, shadows, breakpoints), interactive JS (ripple, tooltip, popover, dialog, tabs, collapse, dismissible), and the design language.
- Alpine.js continues to handle business logic (auth, navigation, API calls, polling, toasts).
- The two layers coexist cleanly: MT uses `data-*` attributes for interactivity; Alpine manages reactive state.

## Target State
The existing 10 pages (Dashboard, Opportunities, Intelligence Feed, Organizations, Analysts, Reports, Monitoring, Administration, Settings, Documentation) are upgraded to match the quality, polish, and component richness of the Creative Tim Material Tailwind Dashboard. Pictures, avatars, and images from the sample assets are used throughout.

---

## Phase 1: Foundation — Integrate @material-tailwind/html

### 1.1 Theme Tokens
Replace ad-hoc CSS variables with the full Material Design palette from `@material-tailwind/html/theme/base/colors.js`:
- Blue-gray (50–900): `#eceff1` → `#263238`
- Gray (50–900): `#fafafa` → `#212121`
- All Material color groups: blue, green, red, amber, purple, indigo, teal, cyan, pink, orange, etc.
- Shadow scale from `shadows.js` (sm, DEFAULT, md, lg, xl, 2xl, inner, none)
- Breakpoints from `breakpoints.js`: sm=540px, md=720px, lg=960px, xl=1140px, 2xl=1320px

### 1.2 Typography
- Switch primary font from Inter → **Roboto** (300,400,500,700,900)
- Add **Roboto Slab** as serif option (100–900)
- Keep JetBrains Mono for monospace
- Match MT's `fontFamily` config: `sans: Roboto, serif: Roboto Slab, body: Roboto, mono: SFMono + fallbacks`

### 1.3 Interactive JS Layer
- Copy `material-tailwind-html-v2.js` from `/sample/material-tailwind/public/` to `/site/static/js/` or inline it
- Call `initHtmlScripts()` on page load to enable:
  - **Ripple effects** (`data-ripple-light` / `data-ripple-dark`)
  - **Tooltips** (`data-tooltip-target` + `data-tooltip`)
  - **Popovers** (`data-popover-target` + `data-popover`)
  - **Dialogs** (`data-dialog-target` + `data-dialog`)
  - **Collapse/Accordion** (`data-collapse-target`)
  - **Tabs** (`data-tabs` + `data-tab-target` + `data-tab-content`)
  - **Dismissible alerts** (`data-dismissible`)

### 1.4 Asset Directory
Create `/site/static/` with:
```
static/
  js/material-tailwind-html-v2.js
  img/
    avatars/         (from sample/public/img/avatars/avatar-1..6.jpg)
    logos/           (from sample/public/img/logos/ and logos-grey/)
    faces/           (from sample/public/img/face-1..5.jpg, bruce-mars.jpg, etc.)
    team/            (from sample/public/img/team-1..6.jpg)
    backgrounds/     (bg-header.jpg, bg-gradient.jpg, header-bg.png, etc.)
    blog/            (blog.jpg, blog-2.jpg, subscribe.jpg)
```

---

## Phase 2: Layout & Navigation Improvements

### 2.1 Sidebar
- Add user profile section below logo: circular avatar, name, role/title
- Add gradient overlay at sidebar bottom
- Add `data-ripple-light` to all sidebar links
- Add tooltips on collapsed sidebar icons

### 2.2 Navbar
- **User dropdown menu** (right side): avatar thumbnail with popover menu (Profile, Settings, Logout)
- **Notification bell** with red badge count and popover panel
- **Search** styled with MT input patterns

### 2.3 Breadcrumbs
- Keep existing breadcrumb, style with MT tokens
- Add home icon before breadcrumb path

### 2.4 Footer
- Simple footer: copyright, product name, version

---

## Phase 3: Page-by-Page Upgrades

### 3.1 Dashboard (HIGH)
- Stat cards: MT Card pattern with gradient icon badges, MT shadow scale, hover lift
- Expand to 4 charts: Source bar chart, Pipeline chart, Opportunity trend line, Source donut
- Feed items: avatars instead of colored dots
- Recommendations: better visual hierarchy, icon illustrations

### 3.2 Opportunities (HIGH)
- Filter tabs: All / Pursued / Monitored / Declined (MT Tabs component)
- Pagination (MT Pagination)
- Sortable columns (click header)
- Row selection checkboxes + bulk actions bar
- Collapsible filters panel (MT Collapse)
- Tooltips on truncated cells

### 3.3 Intelligence Feed (MEDIUM)
- Filter tabs: All / Completed / Running / Failed
- Run duration as MT progress bar
- Mini sparkline charts per run
- Timeline with icons/avatars

### 3.4 Organizations (MEDIUM)
- MT Progress component for source bars
- Source cards with brand logos (from sample assets)
- Distribution donut chart
- Source health indicators

### 3.5 Analysts (LOW)
- Replace placeholder with user list table: avatars, names, roles, last active
- Add/remove user form (UI-only for future release)
- MT Avatar Group component

### 3.6 Reports (MEDIUM)
- Scan frequency bar chart + notices trend
- Report type tabs: Scan / Scheduled / Custom
- MT button variants for export buttons
- Date range picker for filtering

### 3.7 Monitoring (MEDIUM)
- Mini status charts per source (sparklines)
- System health donut chart
- MT Chip/Badge for source status
- Tooltips on last-check timestamps

### 3.8 Administration (HIGH)
- Tabbed layout: Recipients / SMTP / AI Engine
- MT table patterns for recipient list
- Initials avatars for recipients
- Inline editing for recipient name
- MT floating label inputs on forms
- Success/error animations for save operations

### 3.9 Settings (MEDIUM)
- Tabbed layout: General / Email / AI Engine
- API key visibility toggle with MT icon button
- Connection test status indicator
- Save confirmation alert (MT Alert)

### 3.10 Documentation (LOW)
- Right-side table of contents (sticky, MT page-map pattern)
- Code samples with syntax highlighting
- Illustrations from sample assets
- Expandable sections (MT Collapse)

---

## Phase 4: System-Wide Enhancements

### 4.1 Ripple Effects
- `data-ripple-light` on all buttons, links, clickable cards, table rows (light backgrounds)
- `data-ripple-dark` on elements over dark backgrounds (login screen, gradient panels)

### 4.2 Tooltips (data-tooltip-target)
- Icon-only buttons (search, cmd palette, hamburger)
- Truncated table cells (show full content on hover)
- Stat card labels (detailed description)
- Status dots and badges

### 4.3 Animations & Transitions
- Standardize to 300ms ease (MT convention)
- Page transition animations (subtle slide/fade)
- Staggered entry for stat cards
- Counter animation on stat numbers

### 4.4 Responsive Refinement
- Breakpoints: sm=540px, md=720px, lg=960px, xl=1140px, 2xl=1320px
- Collapsible sidebar on tablet
- Mobile nav with hamburger
- Horizontally scrollable tables on mobile

### 4.5 Loading & Empty States
- MT Skeleton patterns for all loading states
- Illustrated empty states (sample images as backgrounds)
- Error states with retry buttons

---

## Phase 5: Visual Polish

### 5.1 Shadow System
- Cards: `shadow-md`
- Modals: `shadow-2xl`
- Dropdowns: `shadow-lg`
- Navbar: `shadow-sm`
- Buttons (hover): `shadow-lg`

### 5.2 Gradients
- Header/banner overlays
- Gradient buttons for primary CTAs (Scan Now, Save, Add)
- Gradient text on key metrics
- Gradient icon badge backgrounds

### 5.3 Images & Illustrations
- Team photos on Analysts page
- Brand logos on Organizations source cards
- Background images on dashboard hero area
- Avatars throughout (user menu, recipients, run history)
- Blog/stock images on documentation page

### 5.4 Color Consistency
- Body text: blue-gray 700/800
- Headings: blue-gray 900
- Secondary: blue-gray 400/500
- Page background: gray/blue-gray 50
- Card background: white
- Borders: blue-gray 200/300
- Success/Warning/Danger/Info: MT color palette

---

## Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `site/templates/admin.html` | Modify | Apply all design system changes, component upgrades, pictures |
| `site/static/js/material-tailwind-html-v2.js` | Create | Compiled MT interactive JS (ripple, tooltip, popover, dialog, tabs, collapse) |
| `site/static/img/avatars/` | Create | Copy 6 avatar JPGs from sample |
| `site/static/img/logos/` | Create | Copy brand logo SVGs from sample |
| `site/static/img/faces/` | Create | Copy face photos from sample |
| `site/static/img/team/` | Create | Copy team photos from sample |
| `site/static/img/backgrounds/` | Create | Copy background images from sample |
| `site/static/img/blog/` | Create | Copy blog images from sample |

---

## Effort Estimate

| Phase | Tasks | Estimated Effort |
|-------|-------|------------------|
| 1 | Foundation (theme, JS layer, assets) | 2–3 hours |
| 2 | Layout & Navigation (sidebar, navbar, footer) | 2–3 hours |
| 3 | Page upgrades (all 10 pages) | 5–8 hours |
| 4 | System-wide (ripple, tooltips, animations, responsive) | 3–4 hours |
| 5 | Visual polish (shadows, gradients, images, colors) | 2–3 hours |
| **Total** | | **14–21 hours** |

## Key Design Decisions

1. **Hybrid approach**: Alpine.js handles state/routing/API; MT handles visuals/interactivity via `data-*` attributes — they coexist without conflict.
2. **No build step**: Single HTML file + CDN-loaded scripts + static assets in `site/static/`.
3. **MT compiled JS** (`material-tailwind-html-v2.js`, 682 lines): self-contained, includes ripple, tooltip, popover, dialog, collapse, tabs, dismissible.
4. **Pictures**: 88+ files from the sample's `public/img/` — avatars, team photos, brand logos, faces, backgrounds.
5. **Tailwind CDN** (not PostCSS): theme customization via CSS variables + custom utility classes in the `<style>` block.
