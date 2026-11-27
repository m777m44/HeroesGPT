# How To Run — Step by Step

## Prerequisites

### 1. Initialize the kanban board (one-time)
```bash
hermes kanban init
```

### 2. Gateway must be running
```bash
hermes gateway start
```
The gateway hosts the kanban dispatcher that picks up ready tasks every 60 seconds.

### 2. Open the dashboard
```bash
hermes dashboard
```
Navigate to the **Kanban** tab in the left nav. This is where you'll see the board.

### 3. Verify profiles exist
```bash
hermes kanban assignees
```
You should see: `cinematographer`, `director`, `editor`, `renderer` — all idle.

### 4. Verify OPENROUTER_API_KEY is set
The profiles need this for API calls. It's in `~/.hermes/.env`.

### 5. Verify media analysis tool works
```bash
set -a; source ~/.hermes/.env; set +a
uv run ~/projects/video-pipeline/tools/media_analyze.py --help
```

### 6. (Optional) Set dashboard default tenant
Add to `~/.hermes/config.yaml` so the dashboard auto-filters to this project:
```yaml
dashboard:
  kanban:
    default_tenant: video-pipeline
    lane_by_profile: true
```

---

## The Command (Start Recording Here)

Open Screen Studio. Split view: **terminal (left ~40%) + dashboard browser (right ~60%)**.

In the terminal:

```bash
hermes kanban create "Make a video explaining how Hermes Kanban works" \
    --assignee director \
    --workspace dir:/home/daimon/projects/video-pipeline/kanban-launch-video \
    --tenant video-pipeline \
    --priority 2 \
    --idempotency-key "kanban-launch-video-root" \
    --max-runtime 4h \
    --body "Read brief.md for the full video spec. Read taste/brand-guide.md and taste/emotional-dna.md for the creative soul. Decompose into: cinematographer designs visual language, then renderers execute each scene, then editor reviews and assembles. Audio is Doomscroll.mp3 — beat analysis at audio/doomscroll-analysis.md. This video is recursive: it explains the kanban system that's making it. CRITICAL: All child tasks MUST use workspace_kind='dir' and workspace_path='/home/daimon/projects/video-pipeline/kanban-launch-video' so workers share the project directory. Pass tenant='video-pipeline' on every create. Set max_runtime_seconds=7200 (2 hours) on renderer tasks and max_runtime_seconds=3600 (1 hour) on cinematographer and editor tasks."
```

### What happens next (the sequence):

1. **Director spawns** (next dispatcher tick, ~60s, or hit "Nudge dispatcher" on dashboard)
   - Reads brief.md, brand guide, emotional DNA
   - Creates task for `cinematographer`: "Design visual language for all scenes"
   - Creates tasks for `renderer`: one per scene (7 scenes), each with cinematographer as parent
   - Creates task for `editor`: "Review clips and assemble final cut", with all renderer tasks as parents
   - Director completes

2. **Cinematographer spawns** (its task has no unmet deps after director completes)
   - Reads the director's handoff (brief + emotional direction)
   - Reads brand guide, audio analysis
   - Writes a detailed visual spec — color, texture, motion, composition per scene
   - Comments on each renderer task with scene-specific visual notes
   - Completes with the full visual spec as structured handoff

3. **Renderers spawn** (their parent = cinematographer, now done → auto-promoted to ready)
   - Each reads: cinematographer's handoff + any comments + brand guide + audio analysis
   - Writes a Python script implementing the ascii-video pipeline
   - Renders the clip to `scenes/scene-NN/clip.mp4`
   - Self-reviews with media_analyze.py
   - Completes with metadata

4. **Editor spawns** (parent = all renderer tasks, all done → promoted)
   - Reviews each clip with media_analyze.py
   - If quality fails: creates re-render tasks (iteration loop)
   - If quality passes: assembles with ffmpeg, muxes audio
   - Outputs `output/final.mp4` and `output/final-noaudio.mp4`
   - Completes

5. **You get notified** (gateway ping on completion)

> **💡 The entire pipeline auto-runs with zero human input.** Every stage promotes automatically when parents complete. You come back to a finished `output/final.mp4`. If something goes wrong, workers block themselves and you get a notification — otherwise it's fire and forget.

---

## Monitoring While It Runs

```bash
# Live event stream (terminal)
hermes kanban watch --tenant video-pipeline

# Check board state
hermes kanban list --tenant video-pipeline

# Stats
hermes kanban stats

# Follow a specific task
hermes kanban tail <task-id>

# See what a worker sees (debug)
hermes kanban context <task-id>
```

---

## Intervening

### If something blocks:
```bash
# See what's blocked
hermes kanban list --status blocked --tenant video-pipeline

# Read the block reason
hermes kanban show <task-id>

# Leave guidance
hermes kanban comment <task-id> "Here's what to do: ..."

# Unblock (respawns the worker with your comment in context)
hermes kanban unblock <task-id>
```

### If you want to nudge the dispatcher immediately:
Click **"Nudge dispatcher"** on the dashboard toolbar, or:
```bash
hermes kanban dispatch
```

### If you want to skip straight to editor (scenes already done):
```bash
hermes kanban complete <renderer-task-id> --result "pre-rendered"
# Repeat for all renderer tasks, then editor auto-promotes
```

### If you want to re-render a single scene:
```bash
hermes kanban create "Re-render scene 3: more contrast, tighter framing" \
    --assignee renderer \
    --workspace dir:/home/daimon/projects/video-pipeline/kanban-launch-video \
    --tenant video-pipeline \
    --skill ascii-video \
    --body "The cinematographer said: 'needs more negative space, the gold is getting lost in noise. Pull back on particle density, let the void breathe.'"
```

---

## After It's Done

```bash
# Final output
ls -la ~/projects/video-pipeline/kanban-launch-video/output/

# Watch it
mpv ~/projects/video-pipeline/kanban-launch-video/output/final.mp4

# Or analyze it
set -a; source ~/.hermes/.env; set +a
uv run ~/projects/video-pipeline/tools/media_analyze.py output/final.mp4
```

### For your creative head:
- **Part 1 footage:** Your Screen Studio recording of the dashboard + terminal
- **Part 2 footage:** `output/final.mp4` (the pipeline-generated video)
- **No-audio version:** `output/final-noaudio.mp4` (if they want to re-score)
- **Individual scenes:** `scenes/scene-01/clip.mp4` through `scenes/scene-07/clip.mp4`
- **Preview frames:** `checkpoints/scene-NN-frame-001.png`

---

## Timing Expectations

| Phase | Real Time | Dashboard View |
|-------|-----------|----------------|
| Director decomposes | 2-5 min | 1 task running → 9 tasks appear |
| Cinematographer designs | 5-10 min | 1 task running → comments appear on renderer tasks |
| Renderers (parallel) | 15-30 min | 3-4 running simultaneously, completing one by one |
| Editor reviews + assembles | 10-15 min | 1 task running → final output |
| **Total** | **~45-60 min** | — |

For the Screen Studio recording: capture the first 5-10 minutes (director + fan-out + first renders starting), then stop. Speed up 4-8x in post. The "money shots":
1. You typing the command → task appears on dashboard
2. Director completes → 9 tasks cascade onto the board simultaneously
3. Multiple renderer cards running in parallel (profile lanes view)
4. Cards sliding from Running → Done in sequence
5. Editor completing → final "Done" state

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Tasks stuck in "ready" | Gateway not running. Run `hermes gateway start`. |
| "spawn_failed" events | Profile might be misconfigured. Check `hermes kanban runs <id>` for the error. |
| Renderer OOMs | Re-render with lower grid density. Add `--body "use xs grid (8px cells)"` |
| Audio file not found | Check symlinks: `ls -la audio/Doomscroll.mp3` |
| media_analyze.py fails | Ensure `OPENROUTER_API_KEY` is set: `source ~/.hermes/.env` |
| Dashboard empty | Check tenant filter. Select "video-pipeline" in the dropdown. |
