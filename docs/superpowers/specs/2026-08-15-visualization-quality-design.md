# Visualization quality — design

**Date** 2026-08-15
**Scope** Raise the dashboard's charts from functional to well-designed: correct
encodings, a validated multi-role palette, visual polish, two richer chart forms,
and dark mode.

## Problem

The charts work and mislead nobody, but they under-use their own idioms and the
chart library. Reflex exposes 103 Recharts symbols; the dashboard uses about
eight. The clearest symptom: **warming stripes render as uniform orange bars.**
The entire visual grammar of that form is a diverging scale where colour carries
the value. Rendering it in one categorical hue is not merely plain, it is the
wrong encoding.

A related gap sits underneath it. The project has polarity data (temperature
anomalies, above or below a baseline) and no diverging palette. Anomalies are the
textbook case for diverging colour, and they are currently drawn with a
categorical hue.

This is not a library limitation. One real Recharts gap remains: no heatmap mark,
which is why the month-by-year view was dropped and stays dropped.

## Palette

Every value below was derived by search against
`dataviz/scripts/validate_palette.js` and verified independently. Nothing here
was chosen by eye. The full validator reports live in
`.superpowers/sdd/palette.md`.

Four roles, two modes:

| Role | Light | Dark |
|---|---|---|
| Categorical | `#2a78d6` `#eb6834` `#1baf7a` | `#2072d0` `#de5c27` `#00995f` |
| Diverging cool (deep→pale) | `#1f5fa8` `#2a78d6` `#8ab8ea` | `#005acb` `#2072d0` `#4986d4` |
| Diverging neutral | `#b2b2b2` | `#4c4d4c` |
| Diverging warm (pale→deep) | `#ff7d44` `#eb6834` `#cc5e34` | `#ef7344` `#de5c27` `#c34f1e` |
| Sequential (pale→deep) | `#71b2ff` `#5090e2` `#2e6ebd` `#054e9a` `#002d77` | `#8ed1ff` `#6eafff` `#4e8ee0` `#2e6ebd` `#074f9b` |

Constraints these satisfy, all machine-checked: OKLCH lightness inside each
mode's band, chroma floor, colourblind separation on adjacent pairs above the
target rather than the floor, normal-vision separation, and contrast against the
mode's surface. Both diverging midpoints are true neutrals (OKLCH chroma 0) and
still read as marks at 2.07:1 and 2.05:1.

Blue is the cool pole and orange the warm pole, reusing the categorical hues so
the palette reads as one system rather than two unrelated schemes.

One documented residual: light aqua `#1baf7a` sits at 2.74:1 against the light
surface, inside the validator's relief band rather than a failure. Relief is
already present, since every chart using it carries a table view. It is the
existing anchor and is deliberately unchanged.

Dark steps are **selected and validated against the dark surface**, never a
mechanical inversion of the light values. An inversion would fail the lightness
band outright, which is exactly what the first candidate set did.

## Encodings

- **Warming stripes** get the diverging ramp, one `cell` per year, coloured by
  anomaly. Colour becomes the data.
- **Anomaly charts** get a `reference_line` at zero and a `reference_area`
  shading the CLINO baseline band, so "above or below normal" is visible without
  reading the axis.
- **Distribution** becomes two overlapping `area`s with a surface ring, instead
  of two thin lines that are hard to compare.
- **Long daily series** get a `brush` for zoom and pan across 76 years.
- **Threshold days** keep line form and gain direct labels on the final point, so
  identity is never carried by colour alone.

## Polish

Gradient fills under areas, tooltips styled with the surface and ink tokens,
entry and hover transitions, 2px lines, markers at 8px or larger, and a 2px
surface gap between adjacent fills. Text keeps ink tokens and never takes a
series colour; a coloured mark beside the text carries identity instead.

## Richer forms

- **Composed chart**: threshold-day bars with a trend line over them, on one
  axis. Never a second y-scale.
- **Small multiples**: a compact grid of warming stripes across cities, the only
  view that makes many cities legible at once.

## Dark mode

Reflex has native colour-mode support, so this uses `rx.color_mode_cond` and
`rx.color_mode.button` rather than bespoke state. Data-driven colours that also
have to respond to mode (the per-cell stripe colours) resolve through CSS custom
properties defined for both modes, because a per-datum colour cannot be a
build-time constant.

## Testing

Palette validation becomes a test rather than a one-off, so a future colour edit
that breaks colourblind separation fails the suite instead of shipping. Chart
helpers get render tests, and a structural test asserts every multi-series chart
carries a legend.

## Out of scope

The month-by-year heatmap stays out: Recharts has no heatmap mark, and faking one
with stacked bars would be worse than its absence. `climate_month_heatmap`
remains in the query layer for a future choropleth or notebook use.
