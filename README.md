# Comic Pipeline

A tool for producing product specification comics, leaning heavily on LLMs but attempting to achieve the following more determinism-friendly traits:

1. VCS-track everything
2. The tracked "thing" is editable
3. Product-development domain awareness baked in
4. A thesis of "human writes overall prompt, LLM writes structured artifacts as the durable intermediate representation, and a mostly-deterministic rendering pipeline uses those structured artifacts to render out a finished product.

The structured intermediates: 

1. The Brief, includes title, goal, context, summary, audience, length-guidance, etc
2. The story, generally a "screenplay"... this is structured into a taxonomy of storytelling that should ideally adopt a known ontology and vocabulary.
3. Visual palletes to make colors, textures (possibly even base64 artifacts), fonts, gradients, pens, etc all explicit. There is not just one, but as many as called for by the comic (for example, each "set" might have one).
4. characters, where each character is defined with as many details/attributes as necessary for repeatable renderings. This might even include structured visual artifacts like a representative SVG, dossier/character-breakdown, physical feature descriptions, etc.
5. timeline/shotlist: A panel-by-panel "shot list" or "timeline" of the comic. This is really meant to be the full content of the comic in every sense except the 2D layouts. This could include a "blocking" or generally low-fi (but probably vector/SVG) layout with characters labeled and speach boxes FPO'd - essentially the storyboard without page-level layouts. 
6. comic, assembles the timeline into "printability" concepts like pages, layouts, arrangements, with any important considerations for how panels might interrelate... 
 
The rendering pipeline will read _exclusively_ the structured intermediates (not the human input prompts) and render out a final artifact (optionally of course just a given page/panel/etc). The idea is that the editing pipeline/workflow should yield edits to the structured intermediates, and the rendering pipeline should be nearly deterministic (the final rendering won't be deterministic if any generative AI is used, of course). 

# A note on developing this project
This is early development - please feel free to work with me on this prompt itself!

# Usage (early)

```sh
uv sync
uv run comicify init my-comic                         # prompt.md skeleton + comicify.toml
cd my-comic                                     # commands default to the current directory
uv run comicify author                          # clarify (incl. direction), then generate the storyboard
uv run comicify render -b png -b pdf --appendix # build the chosen look's art, then render
uv run comicify styles                          # browse the narrative / cinematography / art catalogue
uv run comicify status                          # changed inputs; fresh/stale/pinned intermediates
uv run pytest
```

Any Pydantic AI model string works (`anthropic:…`, `openai:…`, `google-gla:…`, `ollama:…`); set it per
project in `comicify.toml`, via `COMICIFY_MODEL`, or with `--model`. `--model test` runs offline with
placeholder output. See `DESIGN.md` for the architecture.

Secrets and personal defaults go in a user-level config outside the repo,
`~/.config/comicify/config.toml` (or `$COMICIFY_CONFIG`):

```toml
[env_files]                      # file contents exported as env vars, if not already set
ANTHROPIC_API_KEY = "~/path/to/key.txt"

[llm]
model = "anthropic:claude-opus-5-5"
```
