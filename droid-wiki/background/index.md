# Background

This section explains why the project is shaped the way it is, and where the sharp edges are. It answers "why was this decided" and "why is this code weird" rather than describing how things work; the how lives in [Overview](../overview/index.md), [Data pipeline](../systems/data-pipeline/index.md), and [Patterns and conventions](../how-to-contribute/patterns-and-conventions.md).

Two pages:

- [Design decisions](design-decisions.md): the load-bearing decisions (deal sources, stack, corpus cutoff, OA classification, the standalone author path) with their reasons, where they landed in code, and later fates, including the reversals the register itself does not record.
- [Pitfalls](pitfalls.md): danger zones for anyone changing the code or operating a deployment. The live-stack rule, route registration order, work-retirement semantics, and several data traps that look like bugs but are deliberate.

One source caveat applies to both pages: `docs/decisions.md` (untracked) is the full decision register, numbered D1 onward, and the tracked condensation in `docs/data-pipeline/OVERVIEW.md` §5 covers D1-D26. Because `docs/` left version control (commit `2d65f23`, October 23, 2026), the decision text has no git history; only the commit hashes recorded in the register and on these pages tie decisions back to code. For the narrative version of the same story, see [Lore](../lore.md).
