# Video Pipeline — Architecture

## The Team

Four creative profiles that communicate through kanban comments, structured handoffs, and shared workspace files.

```
┌────────────────────────────────────────────────────────────────┐
│                        DIRECTOR                                  │
│  Sets the vision. Decomposes into task graph. Final approval.    │
│  "It should feel like waking up at 3 AM and seeing something     │
│   you can't unsee."                                              │
└──────────────────────────────┬─────────────────────────────────┘
                               │ creates tasks, comments on anything
              ┌────────────────┼────────────────┐
              ▼                                 ▼
┌──────────────────────┐            ┌──────────────────────┐
│   CINEMATOGRAPHER    │            │       EDITOR         │
│                      │            │                      │
│ Designs visual spec  │            │ Reviews rendered     │
│ per scene: color,    │            │ clips for pacing,    │
│ texture, composition,│            │ rhythm, audio sync.  │
│ motion vocabulary.   │            │ Assembles final cut. │
│                      │            │ Kills darlings.      │
│ Reviews rendered     │            │                      │
│ clips for visual     │            │ Tools:               │
│ quality + brand      │            │ media_analyze.py     │
│ alignment.           │            │ ffmpeg               │
│                      │            │                      │
│ Tools:               │            │                      │
│ media_analyze.py     │            │                      │
└──────────┬───────────┘            └──────────▲───────────┘
           │ spec as handoff                    │ all clips done
           │ + comments on                      │ (dependency gate)
           │ renderer tasks                     │
           ▼                                    │
┌──────────────────────────────────────────────┐│
│                  RENDERER                     ││
│                                              ││
│ Executes the cinematographer's vision.       ││
│ Writes Python (ascii-video) or HTML (p5.js). ││
│ Renders to scenes/scene-NN/clip.mp4          │┘
│ Self-reviews with media_analyze.py           │
│                                              │
│ Skills loaded per task:                      │
│   --skill ascii-video  (default)             │
│   --skill p5js         (generative scenes)   │
│                                              │
│ Reads: parent handoff (cinematographer spec) │
│        + comment thread (director/DP notes)  │
│        + brand guide + audio analysis        │
└──────────────────────────────────────────────┘
```

## Communication Model

Profiles communicate via **three channels** built into the kanban system:

### 1. Structured Handoffs (parent → child)
When a task completes with `summary` + `metadata`, every child task automatically receives that handoff in its worker context. This is the primary data channel.

- Director → Cinematographer: the emotional brief, what the piece should FEEL like
- Cinematographer → Renderer: the visual spec (colors, textures, composition, motion)
- Renderer → Editor: clip metadata (duration, resolution, effects used)

### 2. Comments (any profile → any task)
Any worker can `kanban_comment(task_id=<any_task>, body="...")` on any task. The comment thread is read by whatever worker next picks up that task.

- Cinematographer → Renderer tasks (before they run): "Use tighter framing in scene 3"
- Editor → Renderer tasks (after reviewing): "0:34 is dead, energy drops when beat says GO"
- Director → any task: steering notes, creative nudges

### 3. Shared Workspace Files
All tasks use `workspace: dir:~/projects/video-pipeline/kanban-launch-video`. Workers can leave files for each other:

- Cinematographer writes `scenes/scene-03/VISUAL_SPEC.md`
- Renderer reads it before coding
- Renderer writes `scenes/scene-03/clip.mp4`
- Editor reads all clips for assembly

## Task Graph

```
T0: director           "Decompose video brief"
 │   reads: brief.md, taste/brand-guide.md, taste/emotional-dna.md
 │   creates: T1, T2a-T2g, T3
 │
 ├── T1: cinematographer  "Design visual language for all scenes"  (parent: T0)
 │    │   reads: director's handoff + brand guide + audio analysis
 │    │   outputs: visual spec per scene (in handoff + comments on renderer tasks)
 │    │
 │    ├── T2a: renderer  "Scene 1: Title card"                     (parent: T1)
 │    ├── T2b: renderer  "Scene 2: Task creation"                  (parent: T1)
 │    ├── T2c: renderer  "Scene 3: Fan-out visualization"          (parent: T1)
 │    ├── T2d: renderer  "Scene 4: Workers processing"             (parent: T1)
 │    ├── T2e: renderer  "Scene 5: Dependencies resolving"         (parent: T1)
 │    ├── T2f: renderer  "Scene 6: Pipeline completion"            (parent: T1)
 │    └── T2g: renderer  "Scene 7: Logo reveal"                    (parent: T1)
 │
 └── T3: editor          "Review clips and assemble final cut"     (parents: T2a-T2g)
          reads: all scene clips + audio file
          reviews: each clip for pacing, sync, quality
          outputs: output/final.mp4, output/final-noaudio.mp4
```

## Iteration Loops

### Loop 1: Cinematographer ↔ Renderer
If the cinematographer reviews a rendered clip and it doesn't meet the visual bar:
1. Cinematographer comments on the renderer task with specific feedback
2. Cinematographer creates a NEW re-render task assigned to `renderer`, with the original cinematographer task as parent
3. New task body includes the feedback
4. If the re-render task should gate the editor, link it as a parent of the editor task

### Loop 2: Editor ↔ Renderer
If the editor reviews clips for pacing/timing and one doesn't work:
1. Editor comments on the specific renderer task ("scene 3 timing is off at 0:34")
2. Editor creates a re-render task or blocks until fixed
3. Editor only proceeds to assembly when ALL clips pass

### Loop 3: Director ↔ Anyone
The director can intervene at any point via comments:
- "The cinematographer's spec for scene 5 is too busy. Simplify."
- "Scene 2 needs to feel MORE recursive — show actual kanban tasks forming."
- "Editor: make the logo hold 1 second longer."

## Media Analysis Tool

All profiles that review output use:
```bash
set -a; source ~/.hermes/.env; set +a
uv run ~/projects/video-pipeline/tools/media_analyze.py <file> [--prompt "..."]
```

- **Audio files** (mp3, wav, etc.): Analyzed for BPM, beats, mood, sync points
- **Video files** (mp4, webm, etc.): Analyzed for pacing, color, energy, quality
- Model: `google/gemini-2.5-flash` (fast, multimodal, video-capable)
- Requires `OPENROUTER_API_KEY` in environment

## Profile Summary

| Profile | Model | Toolsets | Skills | CWD |
|---------|-------|----------|--------|-----|
| `director` | claude-opus-4.6 | kanban, terminal, file | kanban-orchestrator | project dir |
| `cinematographer` | claude-opus-4.6 | kanban, terminal, file | kanban-worker, ascii-video | project dir |
| `renderer` | claude-opus-4.6 | kanban, terminal, file | kanban-worker, ascii-video, p5js | project dir |
| `editor` | claude-opus-4.6 | kanban, terminal, file | kanban-worker | project dir |

## Renderer Flexibility

One `renderer` profile handles all visual styles. The task's `--skill` flag controls which creative skill is loaded:

```bash
# ASCII video scene (default):
hermes kanban create "Scene 3" --assignee renderer --skill ascii-video

# p5.js generative scene:
hermes kanban create "Scene 5" --assignee renderer --skill p5js

# Remotion motion graphics (future):
hermes kanban create "Scene 2" --assignee renderer --skill remotion
```

The renderer has all creative skills installed (`ascii-video`, `p5js`). The per-task skill pin means it loads the relevant reference material for that specific job.
