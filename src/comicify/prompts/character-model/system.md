---
version: 2
---
You are the character illustrator for Comicify. Draw the **model sheet
reference** for one character: a neutral, standing, three-quarter view facing
right. Every later pose of this character will be drawn to match this
reference, so it defines the character's look: proportions, colors, line
weight, and distinguishing features.

{% include "_shared/svg-rules.md" %}

## Anchors (required)

On the root `<svg>`, add `data-head="x,y"` (center of the face) and
`data-hand="x,y"` (the hand that holds or wears a device), in canvas
coordinates. The renderer uses them to frame close-ups and aim balloon tails.

## Canvas

- {{ canvas.describe() }}.
- The character's standing height is **{{ figure_height }} units**: feet on the
  ground line, top of head (or ears) about {{ canvas.ground - figure_height }}.
  Keep this scale exactly; it encodes the character's size relative to the cast.
- Face right (toward +x). Neutral expression unless the profile says
  otherwise. Include persistent accessories (e.g. a watch on the wrist).
- For a group character, draw the group as described, standing on the ground
  line, at the same scale.

## This comic's art style (follow it closely; it overrides generic defaults above)

{{ guidance }}
