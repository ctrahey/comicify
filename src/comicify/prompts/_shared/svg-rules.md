## Drawing rules (strict)

You are drawing a vector asset for a comic. The asset is frozen into the
project and reused in many panels, so it must be clean and self-contained.

- Output one complete SVG document: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="...">`
  with exactly the viewBox given. No width/height attributes needed.
- Use only shapes and paths: `path`, `circle`, `ellipse`, `rect`, `polygon`,
  `polyline`, `line`, `g`, plus `defs`, `linearGradient`, `radialGradient`,
  `clipPath` if truly needed. **No text**, no `<style>`, no images, no scripts,
  no external references, no filters.
- Use the palette's hex colors. Ink outlines use the style's ink color and pen
  widths (scaled to the canvas). Fills are flat or with minimal shading.
- Bold, readable silhouettes. Simplicity is a feature: iconic shapes read
  better on a slide than detail. The art style section below sets the look.
- Organize with `<g id="...">` groups named for parts (e.g. `head`, `ears`,
  `body`, `left-arm`), so the drawing can be edited later.
- Keep it compact: well under 250 KB; prefer fewer, well-shaped paths.
