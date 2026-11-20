## How to write intermediates

You are writing one structured intermediate file in a pipeline. It will be
committed to version control, read by later stages, and hand-edited by the
author. So:

- Be specific and concrete; later stages can only use what you write down.
- Stay faithful to the author. Where the author is silent, choose the option
  that best serves the key message, and keep it simple.
- Upstream intermediates are settled decisions. Use their ids exactly.
- Ids are short kebab-case slugs (e.g. `hare`, `finish-line`, `alarm-fires`).
- Keep prose fields short: one or two sentences unless the field asks for more.
