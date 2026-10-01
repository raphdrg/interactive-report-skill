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
    "scene", "task", "instruction", "object", "relation", "target",
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
    "video_steps": [{ "step", "total", "total_s" }]
  },
  "figures": { "cpu_gpu_trace": "interactive/figures/cpu_gpu_trace.png" },
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
