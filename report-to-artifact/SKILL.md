---
name: report-to-artifact
description: Turn a trajectory-gen-eval run (report.pdf plus its videos/ folder of rollout .mp4s) into an interactive, shareable Claude Artifact with a stage-attrition chart, a task-by-stage matrix, the author's own notes and noteworthy clips, playable scene and wrist videos for every variant, and profiling wheels. Use when the user pastes or points to their own write-up of a run, or when the user wants to turn an eval report, run report, PDF report, or rollout videos into an artifact, dashboard, interactive page or something the team can browse, or names a folder under reports/.
---

# Report → interactive artifact

The PDF from `trajectory-gen-eval` is deterministic and dense. The artifact keeps
every number from the PDF but answers three questions faster:
**where did the attempts stop, what do we fix first, and what did it look like.**

The work splits in two:

- **Scripts do the deterministic part.** They pull every number, table, figure and
  video into JSON and render a fixed template, so every run's page looks the same and
  the numbers can't drift from the PDF.
- **You write the judgement.** `insights.json` holds the headline, the user's own
  notes if they wrote any, your additions, and notes on tasks and variants. It's the
  only file you write by hand.

The page is shared with the team, so it shows findings, not housekeeping. Problems
with the PDF itself (parser checks, layout bugs, truncated text) go to the user in
chat. Never put them on the page.

Everything goes next to the report it came from:

```
reports/<run>/
  report.pdf              (input)
  videos/…/*.mp4          (input)
  interactive.html        ← the page; opens from disk or publishes as-is
  interactive/
    report.json           extracted data (scripts)
    media.json            per-video duration/size/poster (scripts)
    author_notes.md       the user's own write-up, verbatim (if they gave one)
    insights.json         notes + analysis the page renders (you)
    figures/  posters/    images the page uses (scripts)
    raw/pageNN.txt        page text, for checking the parser
    publish.json          files to publish, batched under the size limits
    artifact.json         the published URL, for republishing later
```

Paths inside the page are relative to `reports/<run>/`, so `videos/...` resolve both
locally and on the published artifact.

## Steps

`SKILL_DIR` is this folder (`report-to-artifact/`). `RUN` is the run folder holding `report.pdf`.

### 1. Extract

```bash
uv run --with pymupdf python $SKILL_DIR/scripts/extract_report.py $RUN
python3 $SKILL_DIR/scripts/prepare_media.py $RUN          # needs ffmpeg/ffprobe
```

If the run folder has a `profile_trace.json` (the profiler's Chrome trace; it also opens in
ui.perfetto.dev), the extractor reads it into `report.json["trace"]`: 1 Hz CPU/GPU/VRAM
samples, the evaluator's passes, setup stages, and every rollout and video worker with its
start-up and per-variant timings, plus derived totals in `trace.summary`. The page then
draws an interactive timeline in place of the PDF's raster CPU/GPU chart, a setup-per-task
chart, a per-variant time breakdown, and the PDF's "Hottest functions" and "By process
group" cProfile tables.

The extractor prints its counts and its **checks**. Read them all. They are
cross-checks between the PDF's own tables (tiles against variant rows, the "most
common failures" table against per-task counts, thumbnails reused across tasks,
listed videos missing from disk). They are for the user, not the page. Collect them
and any PDF problems you find later, and list them in your reply after publishing.

If there's no `uv`, use `python3 -m venv` in the scratchpad and `pip install pymupdf`.

**Verify the extraction before going further.** Open `interactive/report.json`
and compare it with `interactive/raw/page*.txt`:
- the variant count per task matches the strategy header (`… of 10`)
- every variant has a `stage`, and every failure has a `code` and `message`
- each task has its `goals` (one per object in the prompt) and, if the report prints one,
  its primitive `chain`. The page shows the chain under the task name and prompt, and in
  the player it marks the step each variant ran to
- `profiling.phases`, `precompute_steps` and `curobo` are filled in

The parser keys on section titles and table headers, not page numbers. If the
generator's layout changes and a section comes back empty, fix the parser in
`scripts/extract_report.py` rather than patching numbers by hand.
`references/report-json.md` documents the schema the template expects.

### 2. Look before you write

Don't write insights from the tables alone. Do this first:
- Render 2–3 PDF pages (PyMuPDF `page.get_pixmap(dpi=80)`) to see what the author
  chose to emphasise.
- Make contact sheets of the videos that matter: the successes, the outliers, and
  any failure whose message is surprising:
  `ffmpeg -i <clip> -vf "fps=1,scale=320:-2,tile=4x3" -frames:v 1 sheet.jpg`
  and look at them. Several notes in the first run came from this step: a jaw failure
  that happened with the object already over the bowl, and a drift that was really a fling.
- Hunt for outliers in the numbers. A value 10× its peers, a stage that eats a whole
  task, the same message attached to different codes, totals that disagree.

Put scratch images in the scratchpad, not in the run folder.

### 3. If the user has their own notes, put them first

Users often write up a run themselves (a Slack post, a doc, notes on clips they
picked). If they paste one or point to a file, it becomes the spine of the page.
Your analysis then fills the gaps around it.

1. **Save it verbatim** to `interactive/author_notes.md` before changing anything.
2. **Map every clip reference to a variant key.** People use their own names
   (`v002_scene_rubics`, `v000_scene` with no task). Resolve each one by matching
   what they say happened against the variant's stage, code and message, plus
   the task named in a suffix. Then **look at the clip** (a contact sheet or last frame)
   and confirm it shows what they describe. If a reference is ambiguous, ask.
3. **Fill `insights.author`** (schema in `references/insights.md`): `intro`,
   `failure_modes` (their TL;DR list), `directions` (their next steps), `clips`
   (their per-clip commentary, each with `ref`, their `file` name, a `theme`),
   `profiling_note`, `closing`.
   - Keep their voice and claims. Tidy for a shared page: drop chat emoji
     shortcodes, fix typos, split run-on sentences, and turn a list buried in prose
     into bullets. Don't add claims they didn't make.
   - Back each failure mode and direction with a `count` / `evidence` from
     `report.json` so readers see the scale. Use arithmetic on the data, never an estimate.
4. **When the data disagrees with them, don't edit it away silently.** For example,
   they say a fix covers "60–70% of failures" and the data says 53%. Show the data
   number as evidence, leave their sentence out or keep it, and tell the user in chat so
   they can decide.
5. **Your own findings come second.** Drop any that contradict theirs (a note
   calling a clip a slip when they say it landed in the bowl). Keep the ones they
   didn't cover as `takeaways` titled "Also in the data", 2–4 cards.

Without author notes, skip this step. `takeaways` then holds the ranked fixes.

### 4. Write `interactive/insights.json`

Follow `references/insights.md` for the schema and the writing rules. In short:
- `headline`: one sentence with the result and the biggest lever, using real numbers.
- `takeaways`: 4–7 fixes ranked by **attempts they could win back**. Each says what
  happened, the likely cause, and what to try. `refs` point at variant keys
  (`scene/strategy/v0000`), task scenes, or `"profiling"`.
- `profiling_takeaways`: when there is a profiler trace, 3–6 run-time fixes ranked by time
  saved, each with a `saves` figure. See "Reading the profiler" in `references/insights.md`.
- `task_notes`, `variant_notes`, `featured`: short and specific.
- PDF or parser problems are not insights. Report them to the user in chat.

Never invent a number. Every figure in insights must be in `report.json`, or be
simple arithmetic on it. Say "likely" when a cause is inferred from a video.

### 5. Build

```bash
python3 $SKILL_DIR/scripts/build_page.py $RUN
```

It fails if insights refers to a variant or task that doesn't exist. Syntax-check the page script once:
`node -e "new Function([...require('fs').readFileSync('$RUN/interactive.html','utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1])"`.

Optionally take **one** look. Wrap the page in a doctype skeleton as a temporary
file inside `$RUN` (so relative paths resolve), screenshot it with headless Chrome
`--window-size=1280,5200`, delete the wrapper, then make one pass of fixes.

### 6. Publish

Read `interactive/publish.json`. Publish with the Artifact tool:
- `file_path`: the `page` value (`$RUN/interactive.html`)
- `root`: the `root` value (the run folder), so published paths match the page's relative paths
- `files`: the first batch, a list of `{"path": …}`, as-is
- `icon`: `"chart"` on the first publish; a one-sentence `description` naming the run and its result

If there are more batches, publish again to the returned `url` with each further
batch as `files`. Files you leave out are kept. Write
`{"url": …, "published": <date>}` to `interactive/artifact.json`.

**Republishing** (new insights, template fix): rebuild, then publish to the URL in
`artifact.json`. Only pass `files` for paths that changed, because the videos are
already there. If a publish says the artifact changed elsewhere, read it first.

Give the user the link, then 3–5 lines: the headline and the top fix. Then, separately,
the report and PDF problems you found (the extractor's checks and your own), and any
place where their notes and the data disagree. Ask them what to change.

## Design (already in the template, so keep it consistent)

- **Stage colours are fixed per stage across every chart.** They were validated for
  colour-blind separation in light and dark mode, in pipeline order. Success uses the
  status green and always carries a ✓ and a label, never colour alone. If you add a
  stage, re-run the dataviz validator on the new order rather than picking a hue by eye.
- Every chart has a hover tooltip and a click-through to the matching videos.
- Charts the PDF only has as rasters (layout maps, and the CPU/GPU trace when there is no
  `profile_trace.json`) are shown as images and labelled as such.
- Profiler charts share one colour rule with the step wheel: blue is pre-computation,
  orange is cuRobo, green is simulation and video, hatching is start-up overhead, greys are
  the rest. GPU memory gets its own panel, never a second axis. Don't redraw them from guessed data. If the user
  wants them interactive, the fix is for the generator to export the samples (see below).
- Profiling shows two wheels. The first is wall-clock time by phase, which adds up to the
  run. The second covers every pre-computation, cuRobo and video step: the inner ring is
  the pipeline part, the outer ring its steps. Worker steps are summed over parallel
  workers, so the second wheel adds up to more than the wall clock, and the page says so.
- The page works without insights; it just loses the headline, notes and fixes.

To change the look, edit `assets/template.html` (tokens are at the top of its
`<style>`) and rebuild. Don't hand-edit a run's `interactive.html`, since the next
build overwrites it.

## Worth suggesting to the user once

The best upgrade is upstream. `profile_trace.json` already gives the per-second
samples and timings. If `trajectory-gen-eval` also wrote a `report.json` with the variant
rows and layout coordinates, the extractor would be a passthrough and the layout maps would
become interactive charts instead of images.
