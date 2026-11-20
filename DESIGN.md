# Comicify — Design

Status: draft, iterating. See `README.md` for the thesis and `prompts/` for the
human-authored prompts that drive development of this tool.

## Vocabulary

Three "products" are in play, so we name them carefully:

| Term | Meaning |
|---|---|
| **Comicify** | This tool (the CLI). |
| **Author** | Our user: a product developer who writes a comic prompt. |
| **Comic project** | One directory containing an author's `prompt.md` and everything derived from it. |
| **Subject product** | The product the comic depicts (e.g. the *Keeper-Asleeper Racer-Pacer 5000*). |
| **Intermediates** | The structured, VCS-tracked artifacts under `structured/`. **The source of truth.** |
| **Assets** | Frozen visual artifacts (SVG sheets, raster sprites, fonts) under `assets/`. |

## Guiding principles

1. **Intermediates are the source of truth.** `prompt.md` is the seed and history,
   not the spec. Renderers read only `structured/` + `assets/`.
2. **LLMs edit intermediates; renderers don't improvise.** Every generative step
   produces a file that gets committed. Re-rendering an unchanged project is
   byte-identical (for a given renderer version).
3. **Freeze generative art.** When an image model or LLM produces art, it lands in
   `assets/` with provenance and is reused forever until explicitly regenerated.
4. **Narrow context per inference.** Each stage declares exactly which inputs it
   reads. Smaller context → better repeatability, fewer tokens, cleaner caching.
5. **Abstraction is a feature** (Cheng, *See What I Mean*): simple, symbolic
   characters; detailed-enough settings; interfaces shown only as much as the story
   needs, drawn in the comic's style — never screenshots.
6. **Provider-agnostic.** Model access goes through Pydantic AI; provider/model
   per stage is configuration.

## Comic project layout

```
example-A-tortoise-hare/
  prompt.md                    # author-owned; never modified by the tool
  revisions/                   # author-written revision prompts (applied in order)
    001-hare-sunglasses.md
  sessions/                    # tool-written notes: clarification Q&A, chat edit sessions, reviews
    2026-11-19-01-clarify.md
  structured/                  # THE SOURCE OF TRUTH
    brief.yaml
    product.yaml               # the subject product: features, states, screens
    story.yaml                 # beats
    cast.yaml                  # who's in it (index)
    characters/{hare,tortoise}.yaml
    sets/meadow.yaml
    props.yaml                 # all props, incl. subject-product devices
    shotlist.yaml              # panels: full content minus page layout
    comic.yaml                 # pages, grids, panel placement, reading flow
    composition.yaml           # per panel: camera, figures, every letter's box/tail/break
    direction.yaml             # chosen narrative / cinematography / art (+ why)
    packs/                     # vendored narrative + cinematography packs
    looks/<art>/art.yaml       # vendored art pack
    looks/<art>/style.yaml     # palettes and pens for this look
  assets/<art>/                # frozen art per look; lineage in the manifest
    characters/hare/model.svg              # model-sheet reference (neutral pose)
    characters/hare/napping--sleeping.svg  # one file per (pose, expression) used
    sets/meadow.svg                        # wide backdrop
    props/watch.svg
    fonts/comic-neue/*.ttf + OFL.txt       # bundled, open-licensed
  .comicify/
    manifest.yaml              # digests & lineage (see "Staleness") — tracked
    cache/                     # LLM response cache — gitignored
  rendered/<art>/vN/           # pages (svg/png), comic.pdf, render.json
```

## Pipeline

```
prompt.md + revisions/ + sessions/
        │
   [evaluate] ──► [clarify ⟲ author Q&A] ──► sessions/*-clarify.md
        │
   [brief] ──► [direction] ──► [packs]
      │
      ├─► [product]
            ├─► [story] ──► [cast] ──► [character ×N]
            ├─► [style]
            └─► [sets/props]
                       │
                  [shotlist] ──► [layout → comic.yaml]
                       │
             [asset generation]  (character sheets: SVG; sets/props: raster)
                       │
                  [compose]  → resolved scene graph (deterministic)
                       │
            [backend: svg | png | pdf | html-slides]
                       │
                   [review]  (vision LLM critique → proposed revision file)
```

### Stages and their context

Each stage = one prompt directory (`src/comicify/prompts/<stage>/`) + one Pydantic
output model + a declared input list. Fan-out stages (one call per character,
per panel) keep context small.

| Stage | Reads | Writes | Notes |
|---|---|---|---|
| evaluate | prompt, revisions, *existing intermediates* | (in-memory) `Evaluation` | Coherence, arc sufficiency, sane cast/beat counts, gaps, comic intent. |
| clarify | evaluation, prompt, intermediates | `sessions/*-clarify.md` | Interactive. Questions are prioritised; author can skip / "you decide". |
| brief | prompt, clarifications | `brief.yaml` | Title, goal, audience, comic intent, length guidance, page format. |
| product | brief, prompt §technology | `product.yaml` | Features, rules, UI states/screens the story needs. |
| story | brief, product (summary) | `story.yaml` | Beats with purpose; which product feature each beat demonstrates. |
| cast | brief, story | `cast.yaml` | Character list + roles. |
| character | brief (style bits), one cast entry, author notes on that character | `characters/<id>.yaml` | No plot in context. Includes pose/expression *needs* derived from shotlist later. |
| style | brief, prompt §vibe | `style.yaml` | Palettes, pens, typography. |
| sets/props | brief, story (locations only), style | `sets/*.yaml`, `props/*.yaml` | Props include subject-product devices and their screens. |
| shotlist | story, cast, sets, props, product | `shotlist.yaml` | Per panel: beat, shot type, transition, set, characters (pose/expression/position/facing), balloons, props/screens. |
| layout | shotlist (sizes/weights), brief (format) | `comic.yaml` | Mostly deterministic algorithm; LLM only for emphasis hints. |
| assets | characters, props, sets, style, required poses | `assets/**` | Only for missing/stale assets. |
| compose + backends | `structured/`, `assets/` only | `rendered/vN/` | No LLM. |
| review | rendered PNGs, shotlist, brief | `revisions/NNN-review-proposed.md` | Author accepts/edits/deletes like any revision. |

### Storytelling vocabulary (borrowed, not invented)

- **Beats**: setup → inciting moment → rising action → climax → resolution, each
  beat tagged with the subject-product feature (if any) it demonstrates.
- **Comic intent** (on the brief): `pitch` | `cautionary` | `edge-case` |
  `before-after` | `explainer`. The tortoise & hare example is cautionary: the
  feature works, and an unrelated product decision (ads in notifications) sinks it.
- **Panel transitions** (McCloud): moment-to-moment, action-to-action,
  subject-to-subject, scene-to-scene, aspect-to-aspect, non-sequitur.
- **Shot types**: establishing, wide, medium, close-up, extreme close-up, insert
  (e.g. a watch screen), over-the-shoulder.
- **Text kinds**: speech, thought, whisper, shout, caption, sfx, **device**
  (notification / screen text in the subject product's UI style).

## Visual strategy (hybrid, "freeze once")

- **Characters are always SVG.** Each character gets a *sheet*: one SVG file with a
  `<symbol>` per pose, plus swappable expression layers (eyes, mouth, brows) where
  the rig allows. Panels reference `hare#sitting-smug` + `expression: sleeping`;
  compose places them with `<use>`. Poses are generated on demand: the shotlist's
  required (pose, expression) set is diffed against the sheet, and only missing ones
  are generated (LLM-authored SVG against the character's structured description
  and a reference pose for consistency), then frozen.
- **Sets, backgrounds, and complex props may be raster sprites.** Generated once
  by an image model from `sets/*.yaml` + `style.yaml`, saved under `assets/`, with
  a provenance sidecar (model, prompt, seed, input digest). SVG is preferred where
  it holds up (simple props, UI screens).
- **Subject-product UI is always SVG**, drawn in the comic's hand style from
  `product.yaml` screen definitions — never a screenshot.
- We'll revisit after seeing real SVG output; the boundary is a per-asset choice
  (`kind: svg | raster`), not an architectural one.

## Source of truth, staleness, and reconciliation

`.comicify/manifest.yaml` records for every intermediate and asset:

```yaml
structured/characters/hare.yaml:
  produced_by: character@v3          # stage + prompt version
  inputs:                            # digests of what it was generated from
    structured/brief.yaml: sha256:…
    structured/cast.yaml#hare: sha256:…
  output_digest: sha256:…            # digest at write time → detects hand edits
```

- **Hand edits are detected** (current digest ≠ `output_digest`) and those
  artifacts are treated as *pinned*: the tool proposes changes but never silently
  overwrites them.
- **Prompt changes** (`prompt.md` digest ≠ recorded) re-trigger evaluate + clarify
  in **reconcile mode**: the LLM sees the prompt diff *and* the current
  intermediates, asks only questions raised by the change, and produces a change
  plan ("update story beat 4, character hare: add sunglasses; no other changes").
  The plan is shown as a diff and applied on confirmation.
- **Downstream invalidation** follows the input digests, `make`-style: only stages
  whose inputs changed re-run.

## Editing

All edits change intermediates. Two entry points, one mechanism:

- **Revision files**: the author drops `revisions/NNN-*.md`. `comicify revise`
  applies unapplied revisions in order (manifest tracks which are applied).
- **Chat**: `comicify chat` is an interactive session where the LLM has tools to
  read intermediates and propose edits. On exit, a summary is written to
  `sessions/<date>-NN-chat.md` (decisions, changes made, open questions).

Both produce a *change plan* → per-artifact structured edits → diff → confirm →
write + manifest update → downstream invalidation.

## Rendering: pluggable backends

1. **Compose** (deterministic core): `structured/` + `assets/` → a fully resolved
   scene graph per page — absolute geometry, resolved colors, z-order, text already
   shaped and line-broken against real font metrics (HarfBuzz via `uharfbuzz`),
   balloon shapes and tails computed.
2. **Backends** consume the scene graph through a small interface:
   - `svg` — one SVG per page (the reference output)
   - `png` — rasterize SVG (resvg) → folder of page PNGs
   - `pdf` — landscape multi-page PDF
   - `html` — self-contained slideshow (one page per slide, arrow keys)

**Default page format is 16:9 landscape**, since the common case is presenting on a
call. A comic "page" is a slide. Portrait/print is a `brief.yaml` option.

### Fonts are a first-class concern

- Fonts are declared in `style.yaml` and **bundled** in `assets/fonts/`
  (open-licensed by default; license recorded).
- Text layout always uses the bundled font's metrics, so line breaks are identical
  everywhere.
- Output font modes:
  - `outline` (default): glyphs converted to paths — fully portable, deterministic.
  - `embed`: fonts embedded (PDF) or inlined as `@font-face` (SVG/HTML); text stays selectable.
  - `system`: reference fonts by name only. Requires `--local-fonts-ok` to
    acknowledge it only renders correctly on machines with those fonts installed.

## CLI sketch

```
comicify author  <project>/prompt.md   # evaluate → clarify → generate intermediates
comicify status  <project>             # stale / pinned / pending revisions
comicify revise  <project>             # apply pending revisions/
comicify chat    <project>             # interactive editing session
comicify assets  <project>             # generate missing/stale assets only
comicify render  <project> [--backend svg,png,pdf,html] [--fonts outline|embed|system] [--page 2] [--panel 5]
comicify review  <project>             # vision critique → proposed revision file
```

## Direction: mix-and-match style layers

Three independent axes, each a typed **pack** (`src/comicify/styles/<axis>/<id>.yaml`,
or a project's own `styles/<axis>/<id>.yaml`). Packs are data the code enforces,
plus prompt fragments for specific stages — not just system prompts.

| Axis | Shapes | Enforced by code |
|---|---|---|
| **narrative** (10: three-act, kishōtenketsu, story spine, PAS, BAB, rule of three, in medias res, story circle, yonkoma, Freytag) | story beats | every beat has a `slot`; slots filled in order (story integrity check) |
| **cinematography** (8: newspaper strip, nine-panel grid, manga dynamic, planimetric, film noir, widescreen, diagrammatic, documentary) | shot list, page grid, camera | grid policy and gutters (layout), Dutch-tilt limit (shot-list check), tilt and low/high angle framing (compose) |
| **art** (13: clean cartoon, pop art, Opie minimal, superhero, Sunday funnies, Rockwell-inspired, ligne claire, manga screentone, xkcd, Risograph, corporate flat, mid-century, sketchnote) | style, drawings, render | lettering faces and balloon shapes, panel borders and paper, color-count limits (style check), render effects: halftone, grain, misregistration, monochrome, posterize, wobble |

**Direction is an intermediate, not configuration.** Clarification sees the
catalogue: the evaluator states what the author's input decides or implies on
each axis, an unchosen art style is a major concern, and the author is asked
(with fitting catalogue options) about anything open. The `direction` stage
records the choices, with rationale, in `structured/direction.yaml`; the
chosen packs are **vendored** into `structured/packs/` and
`structured/looks/<art>/`, so the intermediates alone reproduce the comic. To
change the art style, edit `direction.yaml` (or add a revision) and re-render;
there are deliberately no CLI flags or config keys for it. A hand-edited
vendored pack is pinned like any other intermediate.

When the clarification prompts change (e.g. new things to resolve), `author`
notices the session's protocol version is outdated and re-clarifies, asking
only what's open.

**Art is a late, per-look layer.** The storyboard (brief → shot list → layout)
is art-agnostic: characters describe colors in words, sets describe mood. Each
look gets its own `style.yaml` (palettes and pens derived from the art pack)
and `assets/<look>/`, and renders go to `rendered/<look>/vN/`. Trying another
art style never regenerates the story, and switching back costs nothing.

Pack traits come from a research pass (see each pack's `sources`); numeric
traits (shot mixes, line weights, hex anchors) are informed estimates, meant
to be tuned.

## Composition and lettering

Lettering is planned with the staging, not fitted into leftovers. Three layers
each own one kind of decision, so a change request lands in exactly one place:

| Layer | Owns | Examples of PM edits |
|---|---|---|
| **shot list** (what) | the words and their intent: `emphasis` (bold words), sfx `intensity` 1–3 and `speaker` (its source), `stance` per figure | "stress *still*", "make BZZZT the loudest moment" |
| **cinematography** `lettering` (where/how much) | zone (top-band, edges, corners, free), speakers left-to-right, words per balloon (enforced on the shot list), headroom, frame breaks, caption placement | "let sound effects break the frame", "tighter dialogue" |
| **art** `lettering` (how it looks) | balloon shape and tail style, caption treatment (box, bar, plain), emphasis weight, sfx styling (fill, outline, halo, extrusion, rotation limit) | "pop-art sound effects", "no balloons, xkcd lines" |

The **composition** stage (`pipeline/composition.py`, code) solves each panel
into `structured/composition.yaml` — art-style independent, panel-normalized,
editable: camera framing; figures (restaged so the first speaker is on the
left, lowered or pulled back to make headroom); and every letter's box, tail
target, chaining (consecutive balloons from one speaker connect), rotation,
and whether it breaks the frame. Placement is a cost search in reading order:
near the speaker, Z-path order, never over another letter or a device screen,
never over a figure's upper silhouette unless there's truly no air (and then
it's noted). Balloon *shape* is a variable: the solver may wrap wider or
narrower to fit the air. Every non-obvious decision is written to `notes`.

**Layout is lettering-aware:** panels carrying heavy text are widened before
packing. Insert shots arrange device and lettering by panel aspect.

The renderer's **letterer** (`render/lettering.py`) draws the plan in the
look's style; balloon shapes take the art's hand-drawn effects (wobble,
misregistration) while text stays crisp; frame-breaking letters render on a
page layer above all panels and gutters. Figure geometry is shared by solver
and renderer (`render/geometry.py`), using structured facts: `stance` and the
character's silhouette `width_ratio`.

## Implementation notes (from the first tracer pass)

- **Stage framework** (`pipeline/core.py`): a stage expands into jobs; each job
  writes one file from declared inputs. The runner decides run / fresh / pinned
  / untracked per job from the manifest, runs a stage's jobs concurrently, and
  records lineage. LLM stages are declarative (`pipeline/llmstage.py`); layout
  and fonts are code stages with the same contract.
- **Integrity checks**: each LLM stage can declare cross-reference checks
  (unknown cast ids, palette colors, screens, ...). Problems go back to the
  model as a retry, so what reaches disk is schema-valid *and* referentially valid.
- **LLM-facing schemas use lists of records, never open maps** (`dict[str, X]`):
  constrained decoding can't express arbitrary keys and yields `{}`. Enforced by
  `tests/test_schemas.py`.
- **Character art = model sheet + per-pose drawings**: a neutral reference is
  drawn first; each (pose, expression) the shot list uses is drawn against it,
  as its own file and job — so a new pose costs one small call.
- **Assets are standalone SVG on fixed canvases** (`svg.py`), validated (no
  text, scripts, external refs) and inlined as namespaced `<symbol>`s.
- **Rendering** = compose (`render/compose.py`, all layout decisions) → scene
  graph (`render/scene.py`) → backends (`render/backends/`, registry). Missing
  assets render as labeled placeholders, so `render --skip-assets` gives a
  blocking pass. Screens are drawn deterministically from `product.yaml`.

## Implementation choices

- Python 3.12+, `uv`, Typer + Rich (interactive CLI, progress), Pydantic v2 models,
  Pydantic AI for LLM calls with structured output, ruamel.yaml (round-trip,
  comment-preserving, so hand edits survive), Jinja2 for prompt templates.
- Runtime prompts live in the package: `src/comicify/prompts/<stage>/{system.md,user.md.j2}`,
  versioned (bumping a stage's prompt version invalidates its outputs).
  The top-level `prompts/` directory stays as the *development* prompts for building Comicify.
- Shared "what makes a good product comic" guidance lives in one include
  (`prompts/_shared/product-comics.md`) used by the relevant system prompts.

## Proposed build order

1. Pydantic models for all intermediates + manifest/digest machinery.
2. evaluate + clarify (incl. reconcile mode stub) — try on tortoise & hare.
3. Intermediate generation stages through `shotlist.yaml`.
4. Compose + `svg` backend with placeholder ("blocking") art: labeled character
   silhouettes, FPO balloons with real text layout, fonts → outlines.
5. Layout stage → multi-page; `png`, `pdf`, `html` backends.
6. Asset generation: character SVG sheets, then raster sets/props.
7. revise / chat / review.

## Open questions

- Character rig depth: whole-pose symbols only, or articulated parts (limbs) for
  reuse across poses? Start with whole poses + expression layers.
- Should `rendered/` be committed by default? (Leaning: no, but `rendered/` gets a
  manifest so a render is reproducible from a commit.)
- Image-model provider abstraction is less standardized than chat LLMs — need a
  thin interface of our own.
