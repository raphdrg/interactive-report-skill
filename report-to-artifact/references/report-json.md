# report.json (written by extract_report.py, read by the template)

```jsonc
{
  "source":   { "pdf": "report.pdf", "pages": 15, "title", "author", "created" },
  "run":      { "name", "subtitle", "generator", "profile", "simulator", "commit", "seed", "started" },
  "headline": { "attempted", "succeeded", "failed", "infeasible", "success_rate_pct",
                "grasps_held", "grasps_reached", "wall_clock_s", "tasks", "strategies",
                "tiles_p1": [{label, value, value_color, sub}], "tiles_p2": [...] },
  "failure_codes":     [{ "stage_key", "code", "count" }],   // the PDF's table (may be truncated)
  "failure_codes_all": [{ "stage_key", "code", "count" }],   // recomputed from every task
  "tasks": [{
    "scene", "task", "instruction",
    "goals": [{ "object", "relation", "target" }],   // one per "obj → relation target" in the prompt; multi-object tasks have several
    "object", "relation", "target",                  // the first goal, kept for older code
    "chain": { "text": "plan_grasp → approach → …", "steps": ["plan_grasp", "approach", …] },   // primitive chain, if the task page prints one
    "setup": { "ok", "text", "detail", "grasps_passed", "grasps_sampled" },
    "strategies": [{
      "name", "success_pct", "succeeded", "failed", "infeasible", "total",
      "failures": [{ "stage_key", "code", "count" }],
      "layout_map": "interactive/figures/map_<scene>_<strategy>.png",
      "variants": [{
        "id": "v0000", "ok": false, "stage": "Transfer", "code": "dropped_during_transfer",
        "error_type": "RuntimeError", "message": "…",
        "metrics": { "ran_to", "duration_s", "curobo_s", "offset_mm", "moved_mm" },
        "metrics_text": "ran to lower · 14 s · cuRobo 5.6 s",
        "videos": { "scene": "videos/…_scene.mp4", "wrist": "videos/…_wrist.mp4" }
      }]
    }]
  }],
  "profiling": {
    "kpis": [{label, value, sub}], "bottleneck_note",
    "phases": [{ "phase", "time", "time_s", "cpu_pct", "busiest_core_pct", "cores_busy",
                 "gpu_pct", "gpu_mem_peak_gb", "gpu_power_w", "bound_pct": {gpu, cpu, neither} }],
    "precompute_steps": [{ "group", "step", "times", "total", "total_s", "each", "each_s" }],
    "trajectory_title", "curobo": [{ "command", "calls", "total", "total_s", "mean_ms" }],
    "video_steps": [{ "step", "total", "total_s" }],
    "hot_intro": "…",                                   // "Hottest functions" (cProfile) intro text
    "hot_functions": [{ "rank", "share_pct", "self", "self_s", "calls", "per_call", "kind",   // python | native | wait
                        "group", "function", "function_key", "called_from": ["caller", …] }],
                        // function_key drops "at 0x…": the PDF splits one bound method per process
    "process_groups": [{ "group", "orchestrates", "processes", "time", "time_s", "python_pct", "native_pct", "wait_pct" }]
  },
  "trace": {                       // only when <run>/profile_trace.json exists (Chrome trace format)
    "source": "profile_trace.json", "duration_s",
    "samples": { "t": [s…], "cpu": [%…], "core": [%…], "gpu": [%…], "mem": [GB…] },   // 1 Hz machine samples
    "passes": [{ "name", "t0", "dur", "scene", "strategy", "workers" }],   // load_scenes, sample, previews, setup, grasp_draw, rollout, video, trim
    "setup_stages": [{ "stage", "scene", "t0", "dur" }],                    // colliders, robot, scene, base, annotate, occupancy, grasp, dr
    "isaac_boots": [{ "step", "scene", "t0", "dur" }],
    "shards": [{ "kind": "rollout|video", "index", "scene", "task", "strategy", "t0", "t1",
                 "startup": [{ "name", "t0", "dur" }],      // Kit boot, stage load, cuRobo warm-up… (named as the PDF does)
                 "variants": [{ "id", "t0", "dur", "timings": { "apply_s", "settle_s", "sim_s", "gripper_s",
                                "curobo_plan_grasp_s", "curobo_plan_pose_s", "curobo_attach_held_s", "curobo_detach_held_s",
                                "replay_s", "encode_s" } }] }],
    "summary": { "rollout"/"video": { "shards", "startup_s", "work_s", "span_s", "startup_pct", "startup_by_step", "idle_tail_s" },
                 "setup_by_task": { "<scene>": { "dur", "stages": { "<stage>": s } } }, "isaac_boots" }
  },
  "figures": { "cpu_gpu_trace": "interactive/figures/cpu_gpu_trace.png" },   // not published when "trace" exists
  "stages":  [{ "name", "meaning" }],     // from "How to read this report"
  "how_to_read": "…",
  "checks":  [{ "level": "error|warn|info", "kind", "message" }]
}
```

Stage names are the PDF's: Sampling, Setup, Grasp planning, Grasp hold, Transfer
planning, Transfer, Place, Infrastructure (plus "Success" for `ok` variants). The
`stage_key`s in codes map as setup, grasp_plan, grasp_physical, transfer_plan,
transfer, place, infra. The template's `STAGES` table ties the names, keys and
colours together. Add a row there if the generator adds a stage.

The variant key used everywhere (insights refs, deep links) is
`<scene>/<strategy>/<id>`. The page deep-links a variant as
`#v-<scene>-<strategy>-<id>` (non-alphanumerics become `-`).

`trace` times are seconds from the start of the run. The function profiler's process
tree (pid 3 in the trace) is not extracted: its spans come in ~30 s steps, so they are
not exact timings. Use the evaluator and shard spans instead.

The primitive chain is read from the task page's header block (between the prompt and the
first strategy header): a line labelled `chain:`, `primitives:` or `primitive chain ·`, or
any line other than the prompt with two or more `→` / `->` / `›` separators. Wrapped lines
are joined. A step matches a variant's `metrics.ran_to` by its first word, so `lift` and
`lift(mustard)` both match `ran to lift`. The extractor flags tasks with no chain and
`ran to` values that aren't steps of the chain.
