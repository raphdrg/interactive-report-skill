# interactive-report-skill

A Claude Code skill that turns a `trajectory-gen-eval` run (`report.pdf` plus its
`videos/` folder) into an interactive Claude Artifact you can share with the team.

## Use

Put a run under `reports/<run>/`:

```
reports/<run>/
  report.pdf
  videos/<scene>/<task>/<strategy>/<variant>_<camera>.mp4
```

Then ask Claude Code to turn it into an artifact, for example
"make an interactive report from reports/<run>". If you have your own write-up of
the run, paste it in and it goes on the page as your notes.

The page is written to `reports/<run>/interactive.html` and published as a private
Artifact. `reports/` is git-ignored.

## Requirements

- `uv`, or Python 3 with `pymupdf`
- `ffmpeg` and `ffprobe`

## Layout

```
report-to-artifact/        the skill
  SKILL.md                 instructions Claude follows
  scripts/                 PDF extraction, video posters, page build
  assets/template.html     the page template
  references/              data and notes formats
.claude/skills/            symlink so Claude Code finds the skill
```
