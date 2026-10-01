#!/usr/bin/env python3
"""Extract a trajectory-gen-eval report.pdf into structured JSON + figures.

Usage:
    uv run --with pymupdf python extract_report.py <run_dir>

<run_dir> is the folder that holds report.pdf (and usually videos/).
Writes into <run_dir>/interactive/:
    report.json     every number, table and variant row in the PDF
    figures/*.png   raster charts the PDF embeds (layout maps, CPU/GPU trace)
    raw/pageNN.txt  plain text of each page, for anything the parser missed

The parser is keyed on the report's own section titles and table headers, not
on page numbers, so it tolerates more or fewer tasks. If a section is missing
it is left out of report.json and a warning lands in report.json["checks"].
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pymupdf

HEADER_GREY = 0x667085
FOOTER_Y = 555  # footer band on an A4-landscape ReportLab page


# ---------------------------------------------------------------- helpers

def page_lines(page):
    """Every text line on the page with its box and style."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            spans = [s for s in l["spans"] if s["text"].strip()]
            if not spans:
                continue
            x0, y0, x1, y1 = l["bbox"]
            if y0 > FOOTER_Y:
                continue
            out.append({
                "text": "".join(s["text"] for s in l["spans"]),
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "bold": "Bold" in spans[0]["font"],
                "mono": "Mono" in spans[0]["font"],
                "size": round(spans[0]["size"], 1),
                "color": spans[0]["color"],
                "spans": [{"text": s["text"], "bold": "Bold" in s["font"]} for s in spans],
            })
    out.sort(key=lambda l: (round(l["y0"]), l["x0"]))
    return out


def to_seconds(s):
    """'14 s' / '1.1 min' / '812 ms' -> seconds (float)."""
    if s is None:
        return None
    m = re.search(r"(-?[\d.]+)\s*(ms|s|min|h)\b", s)
    if not m:
        return None
    v = float(m.group(1))
    return {"ms": v / 1000, "s": v, "min": v * 60, "h": v * 3600}[m.group(2)]


def num(s):
    m = re.search(r"-?[\d.]+", s or "")
    return float(m.group()) if m else None


def find_tables(lines, x_min=0, x_max=10_000):
    """Find header rows (bold, grey, small) and collect the rows under each.

    Columns are regions between neighbouring headers, so both left-aligned
    text and right-aligned numbers land in the right column.
    """
    cand = [l for l in lines if l["bold"] and l["color"] == HEADER_GREY and l["size"] <= 7.5
            and x_min <= l["x0"] < x_max]
    rows_by_y = {}
    for l in cand:
        rows_by_y.setdefault(round(l["y0"]), []).append(l)
    headers = [sorted(v, key=lambda l: l["x0"]) for v in rows_by_y.values() if len(v) >= 2]
    headers.sort(key=lambda h: h[0]["y0"])
    tables = []
    for i, hdr in enumerate(headers):
        y_top = hdr[0]["y1"]
        y_end = headers[i + 1][0]["y0"] if i + 1 < len(headers) else FOOTER_Y
        left, right = hdr[0]["x0"] - 8, x_max
        regions = []
        for j, h in enumerate(hdr):
            lo = hdr[j - 1]["x1"] if j else left
            hi = hdr[j + 1]["x0"] if j + 1 < len(hdr) else right
            regions.append((lo, hi))
        body = [l for l in lines if y_top < l["y0"] < y_end and left <= l["x0"] < right]
        # stop at the first larger-type line (a new section title)
        cut = next((l["y0"] for l in body if l["size"] > 8), None)
        if cut is not None:
            body = [l for l in body if l["y0"] < cut]
        tables.append({"header": [h["text"].strip() for h in hdr], "regions": regions,
                       "lines": body, "y0": hdr[0]["y0"]})
    return tables


def col_of(line, regions):
    cx = (line["x0"] + line["x1"]) / 2
    for i, (lo, hi) in enumerate(regions):
        if lo <= cx < hi:
            return i
    return min(range(len(regions)), key=lambda i: abs(regions[i][0] - line["x0"]))


def simple_rows(table, gap=6):
    """Group a table's lines into rows by y; returns list of cell lists."""
    rows, cur, cur_y = [], None, None
    for l in sorted(table["lines"], key=lambda l: (l["y0"], l["x0"])):
        if cur is None or l["y0"] - cur_y > gap:
            cur = [[] for _ in table["regions"]]
            rows.append(cur)
            cur_y = l["y0"]
        cur[col_of(l, table["regions"])].append(l)
    return rows


def cell_text(cell):
    if not cell:
        return ""
    if all(l["mono"] for l in cell):
        return "".join(l["text"] for l in cell).strip()
    return " ".join(l["text"].strip() for l in cell).strip()


def kpi_tiles(lines, y_from, y_to):
    """KPI tiles: an UPPERCASE grey label, a big value, then grey sub-lines."""
    labels = [l for l in lines if y_from <= l["y0"] <= y_to and l["size"] <= 7.5 and not l["bold"]
              and l["color"] == HEADER_GREY and re.fullmatch(r"[A-Z0-9 ×/\-]+", l["text"].strip())]
    labels.sort(key=lambda l: l["x0"])
    tiles = []
    for i, lab in enumerate(labels):
        x_hi = labels[i + 1]["x0"] - 2 if i + 1 < len(labels) else 10_000
        inside = [l for l in lines if lab["x0"] - 2 <= l["x0"] < x_hi and lab["y1"] <= l["y0"] <= lab["y0"] + 55]
        value = next((l for l in inside if l["size"] >= 14), None)
        subs = [l["text"].strip() for l in inside if l is not value and l["size"] < 14]
        tiles.append({
            "label": lab["text"].strip(),
            "value": value["text"].strip() if value else None,
            "value_color": f"#{value['color']:06x}" if value else None,
            "sub": " ".join(subs),
        })
    return tiles


def section_title(lines):
    big = [l for l in lines if l["size"] >= 17 and l["bold"]]
    return big[0]["text"].strip() if big else None


# ---------------------------------------------------------------- sections

def parse_overview_meta(lines, out):
    sub = next((l["text"] for l in lines if l["text"].startswith("generator ")), None)
    if not sub:
        return
    meta = {}
    for part in [p.strip() for p in sub.split("·")]:
        m = re.match(r"(generator|profile|commit|seed)\s+(.+)", part)
        if m:
            meta[m.group(1)] = m.group(2)
        elif part.lower().startswith("isaac sim"):
            meta["simulator"] = part
        elif re.match(r"\d{4}-\d{2}-\d{2}", part):
            meta["started"] = part
    out["run"].update(meta)


def parse_failure_table(lines, out):
    for t in find_tables(lines):
        if t["header"][:1] == ["Stage / code"]:
            rows = []
            for r in simple_rows(t):
                key, n = cell_text(r[0]), cell_text(r[-1])
                if "/" in key:
                    stage, code = key.split("/", 1)
                    rows.append({"stage_key": stage, "code": code, "count": int(num(n) or 0)})
            out["failure_codes"] = rows


def parse_profiling(page, lines, out):
    prof = out.setdefault("profiling", {})
    prof["kpis"] = kpi_tiles(lines, 95, 110)
    callout = [l for l in lines if 165 <= l["y0"] <= 200 and l["size"] == 9.0]
    if callout:
        prof["bottleneck_note"] = " ".join(l["text"].strip() for l in callout)
    for t in find_tables(lines):
        if t["header"][0] == "Phase":
            phases = []
            for r in simple_rows(t):
                c = [cell_text(x) for x in r]
                bound = [num(x) for x in c[8].split("/")] if len(c) > 8 else []
                phases.append({
                    "phase": c[0], "time_s": to_seconds(c[1]), "time": c[1],
                    "cpu_pct": num(c[2]), "busiest_core_pct": num(c[3]), "cores_busy": num(c[4]),
                    "gpu_pct": num(c[5]), "gpu_mem_peak_gb": num(c[6]), "gpu_power_w": num(c[7]),
                    "bound_pct": dict(zip(["gpu", "cpu", "neither"], bound)),
                })
            prof["phases"] = phases


def parse_precompute(lines, out):
    """Page with the pre-computation table on the left and cuRobo/video tables on the right.

    The two blocks can overlap horizontally (the right block is drawn over the left
    table's last columns), so split lines by column alignment instead of a plain x cut.
    """
    prof = out.setdefault("profiling", {})
    titles = [l for l in lines if l["bold"] and l["size"] >= 10]
    right_x = min((l["x0"] for l in titles if l["x0"] > 300), default=10_000)
    hdr = [l for l in lines if l["bold"] and l["color"] == HEADER_GREY and l["size"] <= 7.5]
    left_hdr = [l for l in hdr if l["text"].strip() in ("Step", "Times", "Total", "Each") and l["y0"] < 90]
    left_end = max((l["x1"] for l in left_hdr), default=right_x)
    right_col0 = min((l["x0"] for l in hdr if l["x0"] >= right_x), default=right_x)

    def in_left(l):
        return l["x0"] < right_x or (l["x0"] > right_col0 + 8 and l["x1"] <= left_end + 4)

    left = [l for l in lines if in_left(l)]
    right = [l for l in lines if not in_left(l) and l["x0"] >= right_x]
    if left_end > right_x:
        out["checks"].append({"level": "warn", "kind": "pdf_layout_overlap",
                              "message": "On the pre-computation page, the cuRobo and Videos tables are drawn on top of "
                                         "the right-hand columns of the pre-computation table, so some of its numbers "
                                         "are unreadable in the PDF. The interactive page has them all."})
    for t in find_tables(left):
        if t["header"][0] == "Step" and "Each" in t["header"]:
            steps, group = [], None
            for r in simple_rows(t):
                c = [cell_text(x) for x in r]
                if not any(c[1:]):
                    group = c[0]
                    continue
                steps.append({"group": group, "step": c[0].strip(),
                              "times": int(num(c[1]) or 0), "total_s": to_seconds(c[2]), "each_s": to_seconds(c[3]),
                              "total": c[2], "each": c[3]})
            prof["precompute_steps"] = steps
    for ti in titles:
        if ti["text"].startswith("Trajectory generation:"):
            prof["trajectory_title"] = ti["text"].strip()
    for t in find_tables(right):
        if t["header"][0] == "cuRobo command":
            prof["curobo"] = [{"command": c[0], "calls": int(num(c[1]) or 0), "total_s": to_seconds(c[2]),
                               "mean_ms": num(c[3]), "total": c[2]}
                              for c in ([cell_text(x) for x in r] for r in simple_rows(t))]
        elif t["header"] == ["Step", "Total"]:
            prof["video_steps"] = [{"step": c[0], "total_s": to_seconds(c[1]), "total": c[1]}
                                   for c in ([cell_text(x) for x in r] for r in simple_rows(t))]
    if "precompute_steps" not in prof:
        out["checks"].append({"level": "error", "message": "pre-computation table not found; see raw/ text"})


def rows_by_first_col(table, pattern):
    """Rows that start where column 0 matches `pattern`; wrapped lines join the row above."""
    regions, lines = table["regions"], table["lines"]
    starts = sorted(l["y0"] for l in lines if col_of(l, regions) == 0 and re.fullmatch(pattern, l["text"].strip()))
    rows = []
    for i, y in enumerate(starts):
        y_next = starts[i + 1] if i + 1 < len(starts) else 10_000
        cells = [[] for _ in regions]
        for l in lines:
            if y - 1 <= l["y0"] < y_next - 1:
                cells[col_of(l, regions)].append(l)
        rows.append(cells)
    return rows


ADDR = re.compile(r"\s+at 0x[0-9a-f]+")


def parse_hot_functions(table, out):
    """'Hottest functions' (cProfile self time). May continue over several pages."""
    prof = out.setdefault("profiling", {})
    h = {name.split()[0]: i for i, name in enumerate(table["header"])}
    for cells in rows_by_first_col(table, r"\d+"):
        fn_lines = cells[h["Function"]]
        own = [l for l in fn_lines if l["color"] != HEADER_GREY]
        chain = " ".join(l["text"].strip() for l in fn_lines if l["color"] == HEADER_GREY)
        func = cell_text(own)
        prof.setdefault("hot_functions", []).append({
            "rank": int(cell_text(cells[h["#"]])),
            "share_pct": num(cell_text(cells[h["Share"]])),
            "self": cell_text(cells[h["Self"]]), "self_s": to_seconds(cell_text(cells[h["Self"]])),
            "calls": int((num(cell_text(cells[h["Calls"]]).replace(",", "")) or 0)),
            "per_call": cell_text(cells[h["Per"]]),
            "kind": cell_text(cells[h["Kind"]]),
            "group": cell_text(cells[h["Process"]]),
            "function": func,
            # the PDF keys bound methods by address, so one function shows once per process
            "function_key": ADDR.sub("", func).strip("<>").replace("function ", ""),
            "called_from": [c.strip() for c in chain.split("←") if c.strip()],
        })


def parse_process_groups(table, out):
    prof = out.setdefault("profiling", {})
    for r in simple_rows(table):
        c = [cell_text(x) for x in r]
        if not c[0] or not c[2]:
            continue
        name = c[0]
        role = None
        m = re.match(r"(.+?)\s*\((orchestrates)\)$", name)
        if m:
            name, role = m.group(1), m.group(2)
        prof.setdefault("process_groups", []).append({
            "group": name, "orchestrates": role == "orchestrates", "processes": int(num(c[1]) or 0),
            "time": c[2], "time_s": to_seconds(c[2]),
            "python_pct": num(c[3]), "native_pct": num(c[4]), "wait_pct": num(c[5]),
        })


def parse_trace(path, out):
    """profile_trace.json (Chrome trace format) -> report.json["trace"].

    Keeps what the page draws (1 Hz machine samples, evaluator passes, setup stages,
    rollout/video worker shards with their start-up and per-variant timings) and
    derives the totals the notes quote. The function-profiler process tree (pid 3)
    is left out: its spans are sampled coarsely and are not exact timings.
    """
    d = json.loads(Path(path).read_text())
    ev = d["traceEvents"] if isinstance(d, dict) else d
    unit = 1e6  # Chrome trace ts/dur are microseconds
    pname = {e["pid"]: e["args"]["name"] for e in ev if e.get("ph") == "M" and e["name"] == "process_name"}
    tname = {(e["pid"], e["tid"]): e["args"]["name"] for e in ev if e.get("ph") == "M" and e["name"] == "thread_name"}
    X = [e for e in ev if e.get("ph") == "X"]
    r1 = lambda v: round(v, 2)
    scene_of = lambda case: case.split("/")[1].split()[0] if case and "/" in case else None

    by_pid = lambda name: next((p for p, n in pname.items() if n == name), None)
    ev_pid, mach_pid = by_pid("Evaluator"), by_pid("Machine")
    tid_of = lambda name: next((t for (p, t), n in tname.items() if p == ev_pid and n == name), None)
    passes_tid, stages_tid, boots_tid = tid_of("passes"), tid_of("setup stages"), tid_of("Isaac boots")

    tr = {"source": Path(path).name, "passes": [], "setup_stages": [], "isaac_boots": [], "shards": []}
    run = next((e for e in X if e["pid"] == ev_pid and e["tid"] == passes_tid and e["name"] == "run"), None)
    tr["duration_s"] = r1(run["dur"] / unit) if run else r1(max(e["ts"] + e.get("dur", 0) for e in X) / unit)
    for e in sorted((e for e in X if e["pid"] == ev_pid and e["tid"] == passes_tid and e["name"] != "run"), key=lambda e: e["ts"]):
        a = e.get("args", {})
        tr["passes"].append({"name": e["name"], "t0": r1(e["ts"] / unit), "dur": r1(e["dur"] / unit),
                             "scene": scene_of(a.get("case")), "strategy": a.get("strategy"),
                             "workers": a.get("workers")})
    for e in sorted((e for e in X if e["pid"] == ev_pid and e["tid"] == stages_tid), key=lambda e: e["ts"]):
        tr["setup_stages"].append({"stage": e["name"], "scene": scene_of(e["args"].get("case")),
                                   "t0": r1(e["ts"] / unit), "dur": r1(e["dur"] / unit)})
    for e in sorted((e for e in X if e["pid"] == ev_pid and e["tid"] == boots_tid), key=lambda e: e["ts"]):
        tr["isaac_boots"].append({"step": e["name"], "scene": scene_of(e["args"].get("case")),
                                  "t0": r1(e["ts"] / unit), "dur": r1(e["dur"] / unit)})
    # worker shards: one process per (kind, shard, task)
    for pid, name in sorted(pname.items()):
        m = re.match(r"(\w+)\.shard(\d+)\s*·\s*(.+)", name)
        if not m:
            continue
        kind, idx, path_ = m.group(1), int(m.group(2)), m.group(3).split("/")
        evs = [e for e in X if e["pid"] == pid]
        lane = lambda t: [e for e in evs if tname.get((pid, e["tid"])) == t]
        su = {e["name"]: e for e in lane("start-up")}
        segs = []  # non-overlapping start-up segments in pipeline order, named as the PDF does
        if "python start-up + imports" in su:
            e = su["python start-up + imports"]; segs.append(("Python start-up and imports", e["ts"], e["dur"]))
        if "open_session" in su:
            os_ = su["open_session"]; kb = su.get("kit_boot")
            if kb:
                segs.append(("Isaac (Kit) boot", kb["ts"], kb["dur"]))
                segs.append(("Stage load and physics warm-up", kb["ts"] + kb["dur"], os_["ts"] + os_["dur"] - kb["ts"] - kb["dur"]))
            else:
                segs.append(("Isaac session", os_["ts"], os_["dur"]))
        for k, label in (("curobo_spawn", "cuRobo worker start"), ("curobo_warmup", "cuRobo warm-up (init)")):
            if k in su:
                segs.append((label, su[k]["ts"], su[k]["dur"]))
        variants = [{"id": e["name"], "t0": r1(e["ts"] / unit), "dur": r1(e["dur"] / unit),
                     "timings": {k.replace("curobo ", "curobo_").replace(" s", "_s"): round(v, 3) for k, v in e.get("args", {}).items()}}
                    for e in sorted(lane("variants"), key=lambda e: e["ts"])]
        t0 = min(e["ts"] for e in evs) / unit
        t1 = max(e["ts"] + e["dur"] for e in evs) / unit
        tr["shards"].append({"kind": kind, "index": idx, "scene": path_[1] if len(path_) > 1 else None,
                             "task": path_[2] if len(path_) > 2 else None, "strategy": path_[3] if len(path_) > 3 else None,
                             "t0": r1(t0), "t1": r1(t1),
                             "startup": [{"name": n, "t0": r1(ts / unit), "dur": r1(du / unit)} for n, ts, du in segs if du > 0],
                             "variants": variants})
    # machine samples at 1 Hz, merged by timestamp
    samp = {}
    for e in ev:
        if e.get("ph") != "C" or e.get("pid") != mach_pid:
            continue
        s = samp.setdefault(round(e["ts"] / unit), {})
        a = e["args"]
        if e["name"].startswith("CPU"):
            s["cpu"], s["core"] = a.get("all cores"), a.get("busiest core")
        elif e["name"].startswith("GPU %"):
            s["gpu"] = next(iter(a.values()))
        elif e["name"].startswith("GPU memory"):
            s["mem"] = next(iter(a.values()))
    ts = sorted(samp)
    tr["samples"] = {"t": ts, **{k: [samp[t].get(k) for t in ts] for k in ("cpu", "core", "gpu", "mem")}}

    # ---- derived totals (what the notes quote)
    S = {}
    for kind in sorted({s["kind"] for s in tr["shards"]}):
        sh = [s for s in tr["shards"] if s["kind"] == kind]
        st = sum(x["dur"] for s in sh for x in s["startup"])
        wk = sum(v["dur"] for s in sh for v in s["variants"])
        span = sum(s["t1"] - s["t0"] for s in sh)
        S[kind] = {"shards": len(sh), "startup_s": r1(st), "work_s": r1(wk), "span_s": r1(span),
                   "startup_pct": round(100 * st / span) if span else None,
                   "startup_by_step": {n: r1(sum(x["dur"] for s in sh for x in s["startup"] if x["name"] == n))
                                       for n in dict.fromkeys(x["name"] for s in sh for x in s["startup"])}}
        # tail: per batch, how long finished workers sat idle waiting for the slowest one
        tails = []
        for key in dict.fromkeys((s["scene"], s["strategy"]) for s in sh):
            b = [s for s in sh if (s["scene"], s["strategy"]) == key]
            end = max(s["t1"] for s in b)
            tails.append(sum(end - s["t1"] for s in b))
        S[kind]["idle_tail_s"] = r1(sum(tails))
    setup = {}
    for p in tr["passes"]:
        if p["name"] == "setup" and p["scene"]:
            setup[p["scene"]] = {"dur": p["dur"], "stages": {x["stage"]: x["dur"] for x in tr["setup_stages"] if x["scene"] == p["scene"]}}
    S["setup_by_task"] = setup
    S["isaac_boots"] = len(tr["isaac_boots"]) + sum(1 for s in tr["shards"] if any("Kit" in x["name"] or "session" in x["name"] for x in s["startup"]))
    tr["summary"] = S
    out["trace"] = tr


def parse_variant_rows(table):
    """Variant tables: one row per v#### in the first column."""
    regions, lines = table["regions"], table["lines"]
    starts = sorted(l["y0"] for l in lines if col_of(l, regions) == 0 and re.fullmatch(r"v\d{3,}", l["text"].strip()))
    rows = []
    for i, y in enumerate(starts):
        y_next = starts[i + 1] if i + 1 < len(starts) else 10_000
        cells = [[] for _ in regions]
        for l in lines:
            if y - 1 <= l["y0"] < y_next - 1:
                cells[col_of(l, regions)].append(l)
        rows.append(cells)
    return rows


def parse_variant(cells, header):
    h = {name: i for i, name in enumerate(header)}
    vid = cell_text(cells[h["Variant"]])
    result = cell_text(cells[h["Result"]])
    ok = result.startswith("✓")
    stage = re.sub(r"^[✓✗]\s*", "", result)
    why_cells = cells[h["Why"]]
    code, message = None, cell_text(why_cells)
    if why_cells:
        first = why_cells[0]["spans"]
        if first and first[0]["bold"]:
            code = first[0]["text"].strip()
            message = message[len(first[0]["text"]):].strip()
    err_type = None
    m = re.match(r"(\w+Error|\w+Exception):\s*(.*)", message)
    if m:
        err_type, message = m.group(1), m.group(2)
    metrics_txt = cell_text(cells[h["Metrics"]])
    metrics = {}
    if metrics_txt and metrics_txt != "–":
        parts = [p.strip() for p in metrics_txt.split("·") if p.strip()]
        for p in parts:
            if p.startswith("ran to"):
                metrics["ran_to"] = p[len("ran to"):].strip()
            elif p.startswith("cuRobo"):
                metrics["curobo_s"] = to_seconds(p)
            elif p.endswith("mm off"):
                metrics["offset_mm"] = num(p)
            elif p.startswith("moved"):
                metrics["moved_mm"] = num(p)
            elif to_seconds(p) is not None:
                metrics["duration_s"] = to_seconds(p)
    vids_col = h.get("Videos in the zip")
    videos = {}
    if vids_col is not None:
        joined = "".join(l["text"].strip() for l in cells[vids_col])
        for p in re.findall(r"videos/.+?\.mp4", joined):
            cam = re.search(r"_(\w+)\.mp4$", p).group(1)
            videos[cam] = p
    return {"id": vid, "ok": ok, "stage": "Success" if ok else stage, "code": code,
            "error_type": err_type, "message": message or None,
            "metrics": metrics, "metrics_text": metrics_txt if metrics_txt != "–" else None,
            "videos": videos}


CHAIN_LABEL = re.compile(r"^\s*(primitive chain|primitives|chain|plan)\s*[:·]\s*", re.I)
CHAIN_SEP = re.compile(r"\s*(?:→|->|›|»|⟶)\s*")


def parse_goals(spec):
    """'bagel_00 → on top of plate_large; bagel_06 → inside bin' -> [{object, relation, target}]."""
    goals = []
    for part in [p.strip() for p in spec.split(";") if p.strip()]:
        if "→" not in part:
            continue
        obj, rest = [x.strip() for x in part.split("→", 1)]
        words = rest.split()
        goals.append({"object": obj, "relation": " ".join(words[:-1]) or None, "target": words[-1] if words else None})
    return goals


def parse_chain(lines, instr, end_y):
    """The task's primitive chain, printed in the task header (below the prompt).

    Accepts a labelled line ('chain: a → b → c', 'primitives · a › b') or any header
    line other than the prompt with at least two step separators. Wrapped lines that
    continue a chain (start or end on a separator) are joined.
    """
    y_from = instr["y0"] if instr else 0
    head = [l for l in lines if y_from <= l["y0"] < end_y and l is not instr and not l["text"].startswith("“")
            and l["size"] < 14]
    for i, l in enumerate(head):
        txt = l["text"].strip()
        labelled = bool(CHAIN_LABEL.match(txt))
        if not labelled and len(CHAIN_SEP.findall(txt)) < 2:
            continue
        parts = [txt]
        for nxt in head[i + 1:]:
            if not (CHAIN_SEP.search(parts[-1][-3:] + " ") or CHAIN_SEP.match(nxt["text"])) or nxt["y0"] - l["y0"] > 40:
                break
            parts.append(nxt["text"].strip())
        joined = CHAIN_LABEL.sub("", " ".join(parts))
        steps = [s.strip(" ·,") for s in CHAIN_SEP.split(joined) if s.strip(" ·,")]
        if len(steps) >= 2 or labelled:
            return {"text": joined.strip(), "steps": steps}
    return None


def parse_task_header(lines):
    title = section_title(lines)
    scene, task = [p.strip() for p in title.split("·", 1)]
    t = {"scene": scene, "task": task, "strategies": []}
    instr = next((l for l in lines if l["text"].startswith("“")), None)
    if instr:
        m = re.match(r"“(.+?)”\s*\((.+)\)\s*$", instr["text"].strip())
        goals = parse_goals(m.group(2)) if m else []
        if m and goals:
            t.update(instruction=m.group(1), goals=goals, object=goals[0]["object"],
                     relation=goals[0]["relation"], target=goals[0]["target"])
        else:
            t["instruction"] = instr["text"].strip("“” ")
    strat = next((l for l in lines if l["bold"] and l["size"] == 12.0 and re.search(r"\d+ succeeded", l["text"])), None)
    chain = parse_chain(lines, instr, strat["y0"] if strat else FOOTER_Y)
    if chain:
        t["chain"] = chain
    setup = [l for l in lines if l["text"].startswith("setup ")]
    if setup:
        s0 = setup[0]
        detail = [l["text"].strip() for l in lines if s0["y0"] < l["y0"] < s0["y0"] + 36 and l["size"] < 12 and l["size"] <= s0["size"] and l["x0"] < 200
                  and not l["text"].startswith("setup ")]
        text = s0["text"].strip()
        g = re.search(r"(\d+)/(\d+) grasps passed", text)
        t["setup"] = {
            "ok": text.startswith("setup ok"),
            "text": text,
            "detail": " ".join(detail) or None,
            "grasps_passed": int(g.group(1)) if g else None,
            "grasps_sampled": int(g.group(2)) if g else None,
        }
    return t


def parse_strategy_header(line, lines):
    m = re.match(r"(\S+)\s+(\d+)%\s+(\d+) succeeded · (\d+) failed · (\d+) infeasible of (\d+)", line["text"])
    s = {"name": m.group(1), "success_pct": int(m.group(2)), "succeeded": int(m.group(3)),
         "failed": int(m.group(4)), "infeasible": int(m.group(5)), "total": int(m.group(6)),
         "failures": [], "variants": []}
    fl = [l for l in lines if l["y0"] > line["y0"] and l["y0"] < line["y0"] + 40 and l["x0"] > 200]
    txt = " ".join(l["text"].strip() for l in fl)
    for stage_key, code, n in re.findall(r"(\w+)/(\w+) ×(\d+)", txt):
        s["failures"].append({"stage_key": stage_key, "code": code, "count": int(n)})
    return s


def parse_glossary(lines, out):
    for t in find_tables(lines):
        if t["header"][:2] == ["Stage", "Meaning"]:
            out["stages"] = [{"name": c[0], "meaning": c[1]}
                             for c in ([cell_text(x) for x in r] for r in simple_rows(t))]
    tables = find_tables(lines)
    in_table = {id(l) for t in tables for l in t["lines"]}
    hdr_y = {round(t["y0"]) for t in tables}
    paras = [l["text"].strip() for l in lines if l["size"] < 14 and id(l) not in in_table
             and round(l["y0"]) not in hdr_y]
    out["how_to_read"] = " ".join(paras)


# ---------------------------------------------------------------- main

def main(run_dir):
    run_dir = Path(run_dir).resolve()
    pdf = run_dir / "report.pdf"
    out_dir = run_dir / "interactive"
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    (out_dir / "raw").mkdir(exist_ok=True)
    doc = pymupdf.open(pdf)

    out = {"source": {"pdf": "report.pdf", "pages": doc.page_count, "title": doc.metadata.get("title"),
                      "author": doc.metadata.get("author"), "created": doc.metadata.get("creationDate")},
           "run": {}, "headline": {}, "tasks": [], "figures": {}, "checks": []}
    thumb_hashes = {}  # sha -> set of tasks whose page embeds it, for the duplicate-thumbnail check

    def save_image(page, xref, name):
        pix = pymupdf.Pixmap(doc, xref)
        if pix.alpha or pix.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        rel = f"interactive/figures/{name}.png"
        pix.save(run_dir / rel)
        return rel

    cur_task, cur_strategy = None, None
    for pno, page in enumerate(doc):
        lines = page_lines(page)
        (out_dir / "raw" / f"page{pno + 1:02d}.txt").write_text(page.get_text())
        texts = [l["text"].strip() for l in lines]
        title = section_title(lines)
        images = sorted(page.get_image_info(xrefs=True), key=lambda i: (i["bbox"][1], i["bbox"][0]))

        if "GRASPS THAT HELD" in texts:
            out["run"]["name"] = title
            sub = lines[1]["text"] if len(lines) > 1 else ""
            out["run"]["subtitle"] = sub.strip()
            for k in kpi_tiles(lines, 95, 110):
                out["headline"].setdefault("tiles_p1", []).append(k)
            continue
        if any(t.startswith("generator ") for t in texts):
            parse_overview_meta(lines, out)
            out["headline"]["tiles_p2"] = kpi_tiles(lines, 95, 115)
            parse_failure_table(lines, out)
            continue
        if title == "Profiling":
            parse_profiling(page, lines, out)
            for img in images:
                if img["bbox"][0] > 400:
                    out["figures"]["cpu_gpu_trace"] = save_image(page, img["xref"], "cpu_gpu_trace")
            continue
        if any(t.startswith("Pre-computation:") for t in texts):
            parse_precompute(lines, out)
            continue
        if any(t == "How to read this report" for t in texts):
            parse_glossary(lines, out)
            continue
        prof_tables = [t for t in find_tables(lines) if t["header"][:2] in (["#", "Share"], ["Process group", "Processes"])]
        if prof_tables:
            for t in prof_tables:
                (parse_hot_functions if t["header"][0] == "#" else parse_process_groups)(t, out)
            if title == "Hottest functions":
                intro = [l["text"].strip() for l in lines if l["size"] == 9.0 and l["y0"] < 110]
                out["profiling"]["hot_intro"] = " ".join(intro)
            continue

        # task pages (and their continuation pages)
        if title and "·" in title and any(t.startswith("“") for t in texts):
            cur_task = parse_task_header(lines)
            out["tasks"].append(cur_task)
            cur_strategy = None
        if cur_task is None:
            out["checks"].append({"level": "warn", "message": f"page {pno + 1}: not recognised, see raw/page{pno + 1:02d}.txt"})
            continue
        for l in lines:
            if l["bold"] and l["size"] == 12.0 and re.search(r"\d+ succeeded", l["text"]):
                cur_strategy = parse_strategy_header(l, lines)
                cur_task["strategies"].append(cur_strategy)
                map_img = next((i for i in images if i["bbox"][1] > l["y0"] and i["bbox"][0] < 220
                                and i["width"] < 600), None)
                if map_img:
                    name = f"map_{cur_task['scene']}_{cur_strategy['name']}"
                    cur_strategy["layout_map"] = save_image(page, map_img["xref"], name)
        for t in find_tables(lines):
            if t["header"][:2] == ["Variant", "Result"] and cur_strategy is not None:
                thumbs_top = min((i["bbox"][1] for i in images if i["bbox"][1] > t["y0"]), default=10_000)
                t["lines"] = [l for l in t["lines"] if l["y0"] < thumbs_top - 4]
                for cells in parse_variant_rows(t):
                    cur_strategy["variants"].append(parse_variant(cells, t["header"]))
        # thumbnail strip: hash what the PDF embedded so we can catch reuse across tasks
        strip = [i for i in images if i["width"] in (480, 253, 267) or (i["bbox"][3] - i["bbox"][1]) < 100]
        for img in strip:
            data = doc.extract_image(img["xref"])["image"]
            hsh = hashlib.sha1(data).hexdigest()
            thumb_hashes.setdefault(hsh, set()).add(cur_task["scene"])

    # ------------------------------------------------ derived + checks
    shared = sorted({tuple(sorted(v)) for v in thumb_hashes.values() if len(v) > 1})
    for group in shared:
        out["checks"].append({"level": "warn", "kind": "pdf_thumbnails", "tasks": list(group),
                              "message": f"The PDF shows the same thumbnail images on the {', '.join(group)} pages, "
                                         f"so at least {len(group) - 1} of them show another task's scene. The "
                                         f"interactive page cuts its own posters from each variant's video."})
    variants = [v for t in out["tasks"] for s in t["strategies"] for v in s["variants"]]
    succ = sum(v["ok"] for v in variants)
    h = out["headline"]
    h.update(attempted=len(variants), succeeded=succ, failed=len(variants) - succ,
             tasks=len(out["tasks"]), strategies=len({s["name"] for t in out["tasks"] for s in t["strategies"]}))
    for tile in h.get("tiles_p1", []) + h.get("tiles_p2", []):
        if tile["label"] == "WALL CLOCK":
            h["wall_clock_s"] = to_seconds(tile["value"])
        if tile["label"] == "GRASPS THAT HELD":
            m = re.search(r"(\d+) of (\d+)", tile["sub"])
            if m:
                h["grasps_held"], h["grasps_reached"] = int(m.group(1)), int(m.group(2))
        if tile["label"] == "SUCCESS RATE":
            h["success_rate_pct"] = num(tile["value"])
        if tile["label"] == "FAILED":
            m = re.search(r"(\d+) layouts infeasible", tile["sub"])
            h["infeasible"] = int(m.group(1)) if m else 0
    want = {"SUCCEEDED": succ, "FAILED": len(variants) - succ}
    for tile in h.get("tiles_p2", []):
        if tile["label"] in want and num(tile["value"]) != want[tile["label"]]:
            out["checks"].append({"level": "error", "message": f"{tile['label']} tile says {tile['value']} "
                                  f"but the variant tables add up to {want[tile['label']]}"})
    from collections import Counter
    per_code = Counter((f["stage_key"], f["code"]) for t in out["tasks"] for s in t["strategies"] for f in s["failures"]
                       for _ in range(f["count"]))
    out["failure_codes_all"] = [{"stage_key": k[0], "code": k[1], "count": n} for k, n in per_code.most_common()]
    listed_codes = {(f["stage_key"], f["code"]): f["count"] for f in out.get("failure_codes", [])}
    left_out = [f"{k[0]}/{k[1]} ×{n}" for k, n in per_code.items() if k not in listed_codes]
    wrong = [f"{k[0]}/{k[1]} says {listed_codes[k]}, tasks add up to {n}" for k, n in per_code.items()
             if k in listed_codes and listed_codes[k] != n]
    if left_out:
        out["checks"].append({"level": "info", "kind": "failure_table_truncated",
                              "message": f"The PDF's 'Most common failures' table leaves out {', '.join(left_out)}, "
                                         f"so it sums to {sum(listed_codes.values())} of {len(variants) - succ} failures."})
    for w in wrong:
        out["checks"].append({"level": "error", "message": f"Most common failures: {w}"})
    for t in out["tasks"]:
        for s in t["strategies"]:
            if len(s["variants"]) != s["total"]:
                out["checks"].append({"level": "error", "message": f"{t['scene']}/{s['name']}: header says "
                                      f"{s['total']} variants, parsed {len(s['variants'])}"})
            for v in s["variants"]:
                for cam, p in v["videos"].items():
                    if not (run_dir / p).exists():
                        out["checks"].append({"level": "warn", "kind": "missing_video",
                                              "message": f"{p} is listed in the PDF but not on disk"})
    listed = {p for v in variants for p in v["videos"].values()}
    for f in sorted((run_dir / "videos").rglob("*.mp4")) if (run_dir / "videos").exists() else []:
        rel = f.relative_to(run_dir).as_posix()
        if rel not in listed:
            out["checks"].append({"level": "info", "kind": "unlisted_video", "message": f"{rel} is on disk but not in the PDF"})

    no_chain = [t["scene"] for t in out["tasks"] if not t.get("chain")]
    if no_chain:
        out["checks"].append({"level": "info", "kind": "no_chain",
                              "message": f"No primitive chain found on the task page for {', '.join(no_chain)}; the page "
                                         f"shows the prompt without one. See raw/ text if the report should have it."})
    for t in out["tasks"]:
        steps = [s.lower() for s in (t.get("chain") or {}).get("steps", [])]
        ran = {v["metrics"].get("ran_to") for s in t["strategies"] for v in s["variants"]} - {None, "none"}
        off = sorted(r for r in ran if steps and not any(st == r.lower() or st.startswith(r.lower() + "(") or st.split()[0] == r.lower() for st in steps))
        if off:
            out["checks"].append({"level": "warn", "message": f"{t['scene']}: variants ran to {', '.join(off)}, which is not a step of its chain ({t['chain']['text']})"})

    hot = out.get("profiling", {}).get("hot_functions", [])
    dup = Counter(f["function_key"] for f in hot)
    for k, n in dup.items():
        if n > 1 and k != next(f["function"] for f in hot if f["function_key"] == k):
            out["checks"].append({"level": "info", "kind": "hot_functions_split",
                                  "message": f"'Hottest functions' lists {k} {n} times, once per process, because the PDF keys "
                                             f"it by memory address. Together those rows are "
                                             f"{sum(f['self_s'] for f in hot if f['function_key'] == k):.1f} s. The page merges them."})
    trace_path = run_dir / "profile_trace.json"
    if trace_path.exists():
        parse_trace(trace_path, out)
        tr = out["trace"]
        if h.get("wall_clock_s") and abs(tr["duration_s"] - h["wall_clock_s"]) > 60:
            out["checks"].append({"level": "warn", "message": f"profile_trace.json covers {tr['duration_s']:.0f} s but the PDF's wall clock is {h['wall_clock_s']:.0f} s"})
        traced = {(s["scene"], v["id"]) for s in tr["shards"] if s["kind"] == "rollout" for v in s["variants"]}
        moved = {(t["scene"], v["id"]) for t in out["tasks"] for s in t["strategies"] for v in s["variants"] if v["videos"]}
        if moved - traced:
            out["checks"].append({"level": "info", "message": f"{len(moved - traced)} variants with videos have no rollout span in profile_trace.json"})

    (out_dir / "report.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {out_dir / 'report.json'}")
    print(f"  {h['tasks']} tasks · {h['attempted']} variants · {succ} succeeded · "
          f"{len(out['figures']) + sum(1 for t in out['tasks'] for s in t['strategies'] if s.get('layout_map'))} figures")
    for c in out["checks"]:
        print(f"  [{c['level']}] {c['message']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
