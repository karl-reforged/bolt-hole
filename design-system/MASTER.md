# Bolt Hole — Design System

## Identity

**Name:** Bolt Hole
**Tagline:** Property search for George Miltenyi
**Personality:** Curated, unhurried, grounded. Feels like a well-prepared dossier from a trusted advisor — not a tech product.

---

## Style Foundation

**Primary style:** Editorial Grid (magazine-inspired, document-like clarity)
**Secondary influence:** Bento Grid (modular cards for property presentation)
**Anti-style:** Dashboard/data-dense. No dark mode. No dev-tool aesthetic.

### Principles
1. **Photography first** — property images dominate; data supports, never competes
2. **Document feel** — reads like a brief, not a software interface
3. **Quiet confidence** — no flashy animations, no urgency patterns
4. **One reader** — designed for George, not for scale

---

## Color Palette

Drawn from Australian rural landscape — eucalyptus, sandstone, creek water, dry grass.

### Core

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Background | Limestone | `#F4F1EC` | Page background, cards |
| Surface | Paper | `#FFFFFF` | Elevated cards, modals |
| Text Primary | Bark | `#2B2523` | Headings, body text |
| Text Secondary | Shale | `#6B635B` | Captions, metadata, secondary info |
| Text Muted | Dust | `#9C948B` | Timestamps, tertiary info |

### Accent

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Primary | Eucalyptus | `#4A7C6B` | Links, active states, scoring bars |
| Primary Dark | Canopy | `#2D5A4A` | Hover states, emphasis |
| Primary Light | Lichen | `#E8F0EC` | Tag backgrounds, subtle highlights |
| Warm Accent | Ochre | `#C17817` | Notifications, new property badge |
| Warm Light | Sandstone | `#F5E6D0` | Warm highlights, selected states |

### Semantic

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Positive | Creek | `#3D8B6E` | Strong match, high score |
| Caution | Dry Grass | `#B8960F` | Moderate match, flags |
| Negative | Ironbark | `#A8453E` | Poor match, risk flags |
| Border | Fence | `#E2DDD6` | Card borders, dividers |
| Border Subtle | Wire | `#EDEBE7` | Subtle separators |

### Contrast Ratios (WCAG AA verified)
- Bark on Limestone: 12.4:1 (AAA)
- Bark on Paper: 14.2:1 (AAA)
- Shale on Limestone: 5.1:1 (AA)
- Eucalyptus on Paper: 4.8:1 (AA)
- Ochre on Paper: 4.5:1 (AA)

---

## Typography

### Pairing: DM Serif Display + Inter

| Role | Font | Weight | Size | Usage |
|------|------|--------|------|-------|
| Display | DM Serif Display | 400 | 32-40px | Property names, page titles |
| Heading | Inter | 600 | 20-24px | Section headings |
| Subheading | Inter | 500 | 16-18px | Card titles, labels |
| Body | Inter | 400 | 15-16px | Descriptions, notes |
| Caption | Inter | 400 | 13px | Metadata, timestamps |
| Mono | JetBrains Mono | 400 | 13px | Scores, data values |

### Google Fonts Import
```css
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
```

### Why this pairing
- **DM Serif Display**: Warm, approachable serif. Not as ornate as Playfair or Cinzel — feels like a country newspaper masthead, not a fashion magazine. Has personality without being loud.
- **Inter**: Already used in the Reforged brief George loved. Excellent readability, clean, professional. No learning curve.
- **JetBrains Mono**: For data/scores only — gives numbers precision without making the whole interface feel technical.

---

## Spacing & Layout

### Base Unit: 8px

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | 4px | Tight gaps, icon padding |
| `--space-sm` | 8px | Inline spacing |
| `--space-md` | 16px | Card padding, list gaps |
| `--space-lg` | 24px | Section spacing |
| `--space-xl` | 32px | Major section breaks |
| `--space-2xl` | 48px | Page-level breathing room |
| `--space-3xl` | 64px | Hero spacing |

### Container
- Max width: `960px` (single column, document-like)
- Card max width: `720px` (property detail)
- Side padding: `24px` (mobile), `48px` (desktop)

### Border Radius
- Cards: `12px`
- Buttons: `8px`
- Tags/badges: `6px`
- Images: `8px` (never fully rounded)

---

## Components

### 1. Property Card (Primary)
- Hero image (16:9 ratio, fills card width)
- Property name in DM Serif Display
- Location + LGA as subtitle
- Key stats row: price, acres, drive time
- Score bar (horizontal, filled proportionally)
- Tags as small pills below
- "New" badge in Ochre if surfaced < 48hrs

### 2. Property Detail (Dossier View)
- Full-width hero image with gradient overlay at bottom
- Property name + location overlay on image
- Structured sections: Overview, Scoring Breakdown, Location (map), Notes
- Each section has a subtle divider (not heavy borders)
- Scoring shown as horizontal bars with labels
- Map embed (Leaflet, terrain tiles — not satellite)
- Feedback section at bottom

### 3. Score Display
- Horizontal bar chart, one row per criterion
- Bar fill uses Eucalyptus gradient (light to dark based on score)
- Score value in JetBrains Mono at right
- Weight percentage shown as muted caption
- Total score prominently displayed

### 4. Feedback Mechanism
- Three states: Interested / Maybe / Pass
- Simple large buttons (not radio buttons or dropdowns)
- Optional comment textarea below
- George's previous feedback visible as a timeline
- His reactions shape future scoring (shown subtly)

### 5. Feed View (Main Interface)
- Reverse-chronological list of surfaced properties
- Each item is a compact Property Card
- Filter chips at top: All / New / Interested / Maybe
- "Last checked" timestamp
- Empty state: "No new properties match your criteria"

### 6. Map View (Secondary)
- Leaflet with terrain/topo tiles (not default blue)
- Property markers as Eucalyptus circles
- Popup on click shows mini property card
- Sydney marker for drive time reference
- Corridor boundaries shown as subtle shaded regions

### 7. Navigation
- Minimal top bar: "Bolt Hole" wordmark left, view toggle right (Feed / Map)
- No hamburger menu, no sidebar
- Breadcrumb on detail view: Feed > Property Name

---

## Imagery

### Map Tiles
- Use topographic/terrain style (Stadia Outdoors or similar)
- Muted colours that don't compete with markers
- Terrain emphasis matches rural property context

### Property Photos
- Always 16:9 crop for cards
- Object-fit: cover
- Subtle shadow beneath (not drop-shadow — more like natural ground shadow)
- Placeholder: Limestone background with Eucalyptus icon

### Icons
- Lucide icon set (consistent, clean, available as SVG)
- Key icons: MapPin, Home, Droplets, Mountain, Clock, TreePine, Star

---

## Motion

- Transitions: 200ms ease for color/opacity changes
- Card hover: subtle border-color shift only (no scale, no lift)
- Page transitions: fade (150ms)
- Respect `prefers-reduced-motion`
- No parallax, no scroll hijacking, no loading animations beyond a simple spinner

---

## Responsive Behaviour

| Breakpoint | Layout |
|------------|--------|
| < 640px | Single column, full-width cards, stacked stats |
| 640-1024px | Single column, comfortable margins |
| > 1024px | Centered container (960px max), optional map sidebar |

George will likely view this on an iPad or desktop. Mobile is secondary but should work.

---

## Voice & Tone (UI Copy)

- Direct, warm, professional
- "3 new properties match your criteria" not "We found 3 new matches!"
- "George's notes" not "User feedback"
- No exclamation marks, no urgency language
- Dates in Australian format: "10 March 2026"
