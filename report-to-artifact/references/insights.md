# insights.json

The only hand-written input. Every field is optional; the page hides what's missing.

```jsonc
{
  "headline": "1 of 50 attempts succeeded. 20 never got past setup, and two scene fixes would put all 20 back in play.",
  "summary": "2–3 sentences: the success(es), the grasp-hold rate, run time and bottleneck.",
  "takeaways": [{
    "kind": "scene config",          // short lowercase label: scene config, grasp sampling, grasp physics, planning, physics, robot model, run time
    "title": "Track lemon_01 in fruits_in_basket",   // an action or a finding, ≤ 8 words
    "body": "What happened → likely cause → what to try. 2–4 sentences, real numbers.",
    "attempts": 10,                  // attempts this could win back; omit for non-outcome items (profiling)
    "stages": ["Setup"],             // stage names exactly as in the PDF
    "refs": ["fruits_in_basket", "two_bin/all_movable/v0003", "profiling"]
  }],
  "task_notes":    { "<scene>": "one sentence on what dominates this task" },
  "variant_notes": { "<scene>/<strategy>/<vid>": "what to look for in this clip" },
  "featured":      ["<scene>/<strategy>/<vid>"],      // flagged tiles: successes and must-watch clips, ≤ 4
  "profiling_takeaways": [{        // run-time fixes, shown in the profiling section; needs profile_trace.json or the cProfile tables
    "kind": "worker start-up",       // short label: fail fast, worker start-up, shake test, pipelining, cuRobo, evaluator
    "title": "Boot each worker once, not once per task and pass",
    "saves": "≈150 s of wall clock",  // say wall clock or worker time; summed worker time is not wall time
    "body": "What the trace shows → why → what to change. Real numbers from report.json trace/profiling.",
    "refs": ["profiling", "<scene>", "<scene>/<strategy>/<vid>"]
  }],
  "takeaways_title": "Also in the data",            // optional; use this title when author notes exist
  "takeaways_sub": "Smaller things the numbers show that the notes above don't cover.",

  "author": {                                        // only when the user gave their own write-up
    "name": "Raphael Drag", "subtitle": "Notes on this run",
    "intro": ["paragraph", "paragraph"],
    "failure_modes": [{ "label": "their words", "count": "16 attempts", "evidence": "what the data shows", "refs": ["…"] }],
    "directions_title": "Where I'd put effort next",
    "directions": [{ "title": "…", "body": "their reasoning",
                     "evidence": { "value": "26 of 49", "text": "failures in this run are about grasping…" }, "refs": ["…"] }],
    "clips": [{ "ref": "<scene>/<strategy>/<vid>", "file": "their file name", "theme": "Counting success", "text": "their note" }],
    "clips_intro": "one line above the clip grid",
    "profiling_note": "their profiling observations",
    "closing": "their sign-off / ask for feedback"
  }
}
```

The author block renders as a "Notes" section under the headline. Their clips become
"Noteworthy clips" (flagged on the tiles too), and their profiling note sits in the
profiling section. In the player, their clip note is labelled with their first name,
and your `variant_notes` appear under it. Write in their first person ("I picked…"),
since it's their page.

## Ranking takeaways

Order them by **attempts recoverable**, earliest stage first when tied, because a
setup fix unblocks everything downstream. Count honestly:
- A setup failure blocks the whole task, so fixing it recovers the task's attempts
  for the *next* stage, not as guaranteed successes. Say what's likely to fail next
  (for example, a tiny grasp-survival ratio).
- Group failures that share a cause, even across stages or tasks (grasp planning
  plus pre-place reachability on the same task).
- Infrastructure failures that happened late (`ran to lower`) are lost near-successes.
  Check the video and say so.
- Put a profiling or run-time item last, without `attempts`. When the run has a
  `profile_trace.json`, put run-time fixes in `profiling_takeaways` instead, ranked by
  time saved.

## Reading the profiler

With `report.json["trace"]`, look for:
- **Setup spent on tasks that produced nothing.** `summary.setup_by_task` against tasks
  whose variants all stopped in Setup. A check that fails after setup (like
  `object_not_tracked`) and could run before it is a direct saving.
- **Start-up against work.** `summary.<kind>.startup_pct` and `startup_by_step`. In wall
  clock, the gap between a rollout/video pass's `t0` and its first variant's `t0`.
- **Serial passes.** Setup of the next task waiting on rollout and video of this one, with
  the GPU mostly idle (`samples` averaged over each pass).
- **Expensive failures.** Per-variant `timings`: failed plans that burn more cuRobo time
  than successes. Unusual per-call costs (`attach_held` against `plan_pose`).
- **The cProfile tables.** Merge `hot_functions` by `function_key`. Large Python self
  time in an orchestrator that should only wait suggests a busy-poll loop.
Keep wall clock and summed worker time apart in every sentence.

## Writing

The readers are robotics engineers on the team. Use their terms (cuRobo, pre-place
hover, shake test, jaw stroke) and the run's own identifiers (scene names, codes,
variant ids) in monospace-able form.

- Lead with the finding. "8 of 10 cube variants slipped during the lift", not "There were some slips".
- Use real numbers with units. Write mm and s the way the PDF does.
- Mark inferences: "likely", "suggests". Give the evidence: "the banana is over the bowl when…".
- Use short declarative sentences. Avoid em-dash asides, "not X but Y" constructions and filler like "it's worth noting".
- Don't restate what the chart already shows. Say why it happened and what to try.

## Anomalies to look for (tell the user; don't put them on the page)

- Values far outside their peers (a 1,739 mm drift next to 56–62 mm).
- The same error message under different codes, or a message that contradicts its code.
- Two numbers for the same thing on different pages (wall time against summed worker time).
- Truncated or cut-off text in the PDF.
- Thumbnails or figures that show the wrong task. The extractor flags reused images,
  so confirm against a video frame.
- Success counted differently in different places (the extractor cross-checks the tiles).
