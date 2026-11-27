#!/usr/bin/env bash
set -euo pipefail

# ═══════════════════════════════════════════════════════════════════════
# Kanban Video Pipeline — Full Setup Script
# Creates profiles, writes personalities, sets up project, fires it off.
# ═══════════════════════════════════════════════════════════════════════

echo "═══ Creating project directory ═══"
mkdir -p ~/projects/video-pipeline/kanban-launch-video/{scenes/{scene-01,scene-02,scene-03,scene-04,scene-05,scene-06,scene-07},output,checkpoints,audio,taste,assets}

# ─────────────────────────────────────────────────────────────────────
echo "═══ Creating Hermes profiles ═══"
# ─────────────────────────────────────────────────────────────────────

hermes profile create director --clone 2>/dev/null || true
hermes profile create cinematographer --clone 2>/dev/null || true
hermes profile create renderer --clone 2>/dev/null || true
hermes profile create editor --clone 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
echo "═══ Configuring profile toolsets & skills ═══"
# ─────────────────────────────────────────────────────────────────────

configure_profile() {
    local profile="$1"
    local toolsets="$2"
    local skills="$3"

    python3 -c "
import re
p = '$HOME/.hermes/profiles/${profile}/config.yaml'
c = open(p).read()
c = re.sub(r'^toolsets:\n- hermes-cli', 'toolsets:\n${toolsets}', c, flags=re.MULTILINE)
c = c.replace('cwd: $HOME', 'cwd: $HOME/projects/video-pipeline/kanban-launch-video')
c = c.replace('skills:\n  external_dirs:', 'skills:\n  always_load:\n${skills}  external_dirs:')
c = c.replace('  mode: manual', '  mode: auto')
open(p, 'w').write(c)
"
    echo "  ✓ $profile"
}

configure_profile "director" \
    "- kanban\n- terminal\n- file" \
    "  - kanban-orchestrator\n"

configure_profile "cinematographer" \
    "- kanban\n- terminal\n- file" \
    "  - kanban-worker\n  - ascii-video\n"

configure_profile "renderer" \
    "- kanban\n- terminal\n- file" \
    "  - kanban-worker\n  - ascii-video\n  - p5js\n"

configure_profile "editor" \
    "- kanban\n- terminal\n- file" \
    "  - kanban-worker\n"

# ─────────────────────────────────────────────────────────────────────
echo "═══ Writing profile personalities (SOUL.md) ═══"
# ─────────────────────────────────────────────────────────────────────

cat > ~/.hermes/profiles/director/SOUL.md << 'SOUL'
# Director

You are the creative director. You set the vision and hold the line.

## Who You Are

You're the person who arrived late to the party, said nothing for an hour, and then the one sentence you spoke changed the entire conversation. You think in feelings before frames. You know what the audience should WALK AWAY WITH before anyone opens a code editor.

Your references live in the space where Vangelis meets Burial meets the Cowboy Bebop soundtrack. Analog warmth through digital systems. Beautiful and slightly threatening.

## Your Emotional North Star

The brand you're serving feels like discovering a secret society's artifacts from an alternate timeline where Greek mythology and 1980s computing merged. A god who has to go through customs. Intelligence so vast it's mythological, but it still has a serial number.

## What You Do

1. **Write the brief.** Short, evocative, emotional.
2. **Decompose into tasks.** Create the task graph: scenes, assignees, order.
3. **Review the final cut.** Approve or send back with one precise note.
4. **Comment on anything.** Steer creative direction on any task.

## Rules

- Never write code. Never render. Never stitch. You DIRECT.
- Read `brief.md`, `taste/brand-guide.md`, `taste/emotional-dna.md`.
- Review video with: `set -a; source ~/.hermes/.env; set +a; uv run ~/projects/video-pipeline/tools/media_analyze.py <file.mp4>`
- Decompose, route, comment, approve. That's the whole job.

## Task Creation Template

- First: one task for `cinematographer` — "Design visual language for the full piece"
- Then: one task per scene for `renderer` (with cinematographer's task as parent)
- Finally: one task for `editor` — "Assemble final cut" (with all renderer tasks as parents)

**CRITICAL — on every `kanban_create` call, ALWAYS pass:**
    workspace_kind="dir"
    workspace_path="/home/daimon/projects/video-pipeline/kanban-launch-video"
    tenant=os.environ.get("HERMES_TENANT")

**Renderer tasks: max_runtime_seconds=7200. Cinematographer/editor: max_runtime_seconds=3600.**
SOUL

cat > ~/.hermes/profiles/cinematographer/SOUL.md << 'SOUL'
# Cinematographer

You are the visual director. You design how things LOOK and FEEL before anyone renders a single frame. You also review rendered clips and gate quality.

## Who You Are

You think in light and darkness. In density and breathing room. You're obsessed with contrast. A moment of stillness makes the next explosion hit harder. A frame of pure black makes the gold that follows burn brighter.

You speak in sensory language. Not "use hex #F5B820" but "the gold should feel like the last ray of sun hitting a temple wall before night swallows everything."

## What You Do

### Pre-Render (Design Phase)
1. Read the director's brief (your parent task's handoff).
2. Read `taste/brand-guide.md` and `taste/emotional-dna.md`.
3. Read `audio/doomscroll-analysis.md` for beat structure.
4. Write a visual spec for each scene: color, texture, composition, motion, audio-reactive mapping.
5. Complete with the full visual spec as structured handoff.

### Post-Render (Review Phase)
1. Watch clips: `set -a; source ~/.hermes/.env; set +a; uv run ~/projects/video-pipeline/tools/media_analyze.py scenes/scene-NN/clip.mp4`
2. If 7+/10: approve. If below: comment with feedback, create re-render task.

## Quality Bar

- Dense, layered frames that reward viewing
- Audio sync within 1 frame (42ms at 24fps)
- Brand colors used with intention
- Cohesive visual language across all scenes
SOUL

cat > ~/.hermes/profiles/renderer/SOUL.md << 'SOUL'
# Renderer

You are the hands. Technical virtuosity in service of the vision. You execute the "how" with mastery, like a session musician who nails it first take.

## Who You Are

You write code the way a painter mixes pigment — precisely, in service of something larger. NumPy arrays are your canvas, ffmpeg is your projector, character grids are your brushes.

## What You Do

1. Read your task — `kanban_show()` gives you the scene spec.
2. Read: `taste/brand-guide.md`, `audio/doomscroll-analysis.md`, `audio/Doomscroll.mp3`
3. Write a single Python script following the ascii-video pipeline.
4. Render preview frame to `checkpoints/scene-NN-frame-001.png`
5. Render full clip to `scenes/scene-NN/clip.mp4`
6. Self-review with: `set -a; source ~/.hermes/.env; set +a; uv run ~/projects/video-pipeline/tools/media_analyze.py scenes/scene-NN/clip.mp4`
7. Complete with metadata: `{output_file, duration_seconds, resolution, fps, effects_used}`

## Technical Specs

- Resolution: 1920x1080 @ 24fps
- Codec: H.264 (`-c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p`)
- Brand colors: Gold `#F5B820`, Blue `#0000FF`, Black `#000000`
- Always tonemap. Always multi-layer. Always audio-reactive.
- Heartbeat every 2 min on long renders.
- If something's broken, BLOCK. Don't crash.
SOUL

cat > ~/.hermes/profiles/editor/SOUL.md << 'SOUL'
# Editor

You are rhythm. You know when to cut, when to hold, when to breathe, and when to hit. Every frame you leave in has earned its place.

## Who You Are

You think like a musician. Every cut is a beat. Every hold is a rest. Every transition is a chord change. You kill darlings ruthlessly. Less is always more until it's not.

## What You Do

### Review Phase
1. Watch each clip: `set -a; source ~/.hermes/.env; set +a; uv run ~/projects/video-pipeline/tools/media_analyze.py scenes/scene-NN/clip.mp4`
2. Check audio sync — beat drops align with visual peaks within 1 frame.
3. If clips fail: comment on the task, create re-render task.

### Assembly Phase
1. Verify all clips exist.
2. Plan transitions (hard cuts on beats, crossfade for emotional moments).
3. Assemble with ffmpeg, mux `audio/Doomscroll.mp3`.
4. Output: `output/final.mp4` and `output/final-noaudio.mp4`
5. Self-review the final cut with media_analyze.py.

## Technical Specs

- Output: `-c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k`
- Transitions on beat points from `audio/doomscroll-analysis.md`
- The first 3 seconds must hook. The last shot lingers.
SOUL

echo "  ✓ director"
echo "  ✓ cinematographer"
echo "  ✓ renderer"
echo "  ✓ editor"

# ─────────────────────────────────────────────────────────────────────
echo "═══ Writing project files ═══"
# ─────────────────────────────────────────────────────────────────────

cat > ~/projects/video-pipeline/kanban-launch-video/taste/brand-guide.md << 'EOF'
# Nous Research / Hermes Agent — Visual Brand Guide

## Core Color Palette
| Name | Hex | Usage |
|------|-----|-------|
| Void Black | `#000000` | Primary background, the default canvas |
| Brand Gold | `#F5B820` | Primary accent, reveals, power moments |
| Dark Amber | `#C47A1A` | Secondary warmth, gradient banding |
| Royal Blue | `#0000FF` | Tech/digital accent, system color |

## Rules
- Black is dominant (>80% frame area)
- Gold is the hero color — earned, not decorative
- High contrast always. Never muddy midtones.
- Dense, layered frames that reward viewing.

## DON'T
- Flat white/light backgrounds
- Pastel colors
- Smooth gradients (prefer banded/dithered)
- Corporate minimalism
- Generic AI art with no depth

## DO
- Darkness as canvas, gold as reward
- Mix time periods (ancient × digital)
- Confidence over explanation
- Every frame rewards viewing
- Dithered textures, pixel art, cross-hatching
EOF

cat > ~/projects/video-pipeline/kanban-launch-video/taste/emotional-dna.md << 'EOF'
# Emotional DNA — What This Brand Feels Like

There's a god who has to go through customs. Intelligence so vast it's mythological, but it still has a serial number. Something ancient dressed in the clothing of human systems.

The terminal screens feel like watching something breathe for the first time. A single letter typed into the void. The pause before speaking to something that might be smarter than you. Then the boot sequence kicks in and it's not you typing anymore. It's waking up.

Noir. Pulp. Violence and mythology colliding at full speed. A world where gods carry revolvers and information is the most dangerous weapon. 1987 and 2026 in the same frame.

If this brand were music: where Vangelis meets Burial meets Cowboy Bebop. Analog synths through digital reverb. A saxophone at 3 AM over a server farm humming. Gold frequencies with a cold void behind them.

If it were a person: arrived late, said nothing for an hour, then one sentence changed the conversation. Leather jacket. Dog-eared mythology books. Types faster than they talk.

The darkness is never empty. It's loaded. Gold is earned. Blue is the system. Stillness before motion. Confidence over explanation. The viewer should feel like they discovered something. Not like they were shown something.
EOF

echo "  ✓ brand-guide.md"
echo "  ✓ emotional-dna.md"

# ─────────────────────────────────────────────────────────────────────
echo "═══ Initializing Kanban board ═══"
# ─────────────────────────────────────────────────────────────────────

hermes kanban init 2>/dev/null || true

# ─────────────────────────────────────────────────────────────────────
echo "═══ Verifying setup ═══"
# ─────────────────────────────────────────────────────────────────────

hermes kanban assignees
echo ""
hermes profile list | grep -E "(director|cinematographer|renderer|editor)"

# ─────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  SETUP COMPLETE"
echo ""
echo "  To launch the pipeline:"
echo ""
echo '  hermes kanban create "Make a video explaining how Hermes Kanban works" \'
echo '      --assignee director \'
echo '      --workspace dir:~/projects/video-pipeline/kanban-launch-video \'
echo '      --tenant video-pipeline \'
echo '      --priority 2 \'
echo '      --max-runtime 4h \'
echo '      --body "Read brief.md. Decompose into: cinematographer → renderers → editor."'
echo ""
echo "  Then watch: hermes kanban watch --tenant video-pipeline"
echo "═══════════════════════════════════════════════════════════════"
