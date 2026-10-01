#!/usr/bin/env python3
"""Render the interactive page for one run and list the files to publish.

Usage:
    python3 build_page.py <run_dir>

Reads  <run_dir>/interactive/report.json   (from extract_report.py)
       <run_dir>/interactive/media.json    (from prepare_media.py, optional)
       <run_dir>/interactive/insights.json (written by Claude, optional)
Writes <run_dir>/interactive.html          (opens locally: paths are relative)
       <run_dir>/interactive/publish.json  ({"page", "root", "batches": [[{"path": ...}]]}),
                                           ready to pass as the Artifact tool's root + files

Every path the page references (videos/..., interactive/posters/...,
interactive/figures/...) is relative to <run_dir>, so the same file works
opened from disk and published as an Artifact with those paths in `files`.
"""
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "template.html"
BATCH_BYTES = 60 * 1024 * 1024   # one Artifact publish carries at most 64 MB
BATCH_FILES = 250                # ...and at most 255 files


def main(run_dir):
    run = Path(run_dir).resolve()
    d = run / "interactive"
    report = json.loads((d / "report.json").read_text())
    media = json.loads((d / "media.json").read_text()) if (d / "media.json").exists() else {}
    insights_path = d / "insights.json"
    insights = json.loads(insights_path.read_text()) if insights_path.exists() else {}
    if not insights:
        print("note: no interactive/insights.json; the page will render without headline, takeaways or notes")

    # sanity: every key insights refers to must exist
    keys = {f"{t['scene']}/{s['name']}/{v['id']}" for t in report["tasks"] for s in t["strategies"] for v in s["variants"]}
    scenes = {t["scene"] for t in report["tasks"]}
    refs = [r for t in insights.get("takeaways", []) for r in t.get("refs", [])]
    refs += [r for a in insights.get("anomalies", []) for r in a.get("refs", [])]
    refs += [r for t in insights.get("profiling_takeaways", []) for r in t.get("refs", [])]
    refs += list(insights.get("variant_notes", {})) + insights.get("featured", [])
    au = insights.get("author") or {}
    refs += [c["ref"] for c in au.get("clips", [])]
    refs += [r for x in au.get("failure_modes", []) + au.get("directions", []) for r in x.get("refs", [])]
    bad = [r for r in refs if r not in keys and r not in scenes and r != "profiling"]
    bad += [s for s in insights.get("task_notes", {}) if s not in scenes]
    if bad:
        sys.exit(f"insights.json refers to unknown variants/tasks: {bad}")

    payload = json.dumps({"report": report, "media": media, "insights": insights}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    html = TEMPLATE.read_text()
    html = html.replace("__TITLE__", report["run"].get("name") or run.name, 1)
    html = html.replace("__REPORT_DATA__", payload, 1)
    page = run / "interactive.html"
    page.write_text(html)

    # files the page references, as {published path: absolute source}
    files = {}
    for m in media.values():
        files[m["src"]] = str(run / m["src"])
        files[m["poster"]] = str(run / m["poster"])
    for name, p in report.get("figures", {}).items():
        if name == "cpu_gpu_trace" and report.get("trace"):
            continue  # the page draws the trace from profile_trace.json instead
        files[p] = str(run / p)
    for t in report["tasks"]:
        for s in t["strategies"]:
            if s.get("layout_map"):
                files[s["layout_map"]] = str(run / s["layout_map"])
    missing = [p for p, src in files.items() if not Path(src).exists()]
    if missing:
        sys.exit(f"missing files: {missing[:5]}")

    # small files first so the first publish already renders posters and figures
    order = sorted(files, key=lambda p: (p.endswith(".mp4"), p))
    batches, cur, size = [], {}, 0
    for p in order:
        b = Path(files[p]).stat().st_size
        if cur and (size + b > BATCH_BYTES or len(cur) >= BATCH_FILES):
            batches.append(cur)
            cur, size = {}, 0
        cur[p] = files[p]
        size += b
    if cur:
        batches.append(cur)
    (d / "publish.json").write_text(json.dumps({
        "page": str(page), "root": str(run),
        "batches": [[{"path": p} for p in b] for b in batches],
    }, indent=1))
    total = sum(Path(s).stat().st_size for s in files.values())
    print(f"wrote {page} ({page.stat().st_size / 1024:.0f} KB)")
    print(f"wrote {d / 'publish.json'}: {len(files)} files, {total / 1e6:.1f} MB in {len(batches)} publish batch(es)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
