# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=1.0",
# ]
# ///
"""
Media analysis CLI via OpenRouter's Gemini (multimodal audio + video).

Usage:
    uv run media_analyze.py <file> [--prompt "..."] [--model MODEL]

Supports audio (mp3, wav, m4a, etc.) and video (mp4, webm, mov) files.
Audio uses `input_audio` content type, video uses `video_url` with base64 data URL.

Requires OPENROUTER_API_KEY env var.
"""

import argparse
import base64
import os
import sys
from pathlib import Path

from openai import OpenAI


AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg", "flac", "aiff"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "mpeg", "avi", "mkv"}

DEFAULT_AUDIO_PROMPT = """Analyze this audio track for use in a video production pipeline. Provide:

1. **BPM & Time Signature** — estimated tempo and meter
2. **Energy Arc** — describe how intensity changes over time (e.g. "builds from 0:00-0:30, drops at 0:31, sustains high energy 0:31-1:45, outro fade 1:45-2:00")
3. **Key Sections** — timestamp each distinct section (intro, verse, chorus, bridge, drop, outro) with start/end times
4. **Beat Drop / Transition Points** — exact timestamps where major energy changes happen (good cut points for video transitions)
5. **Mood & Atmosphere** — overall emotional tone, darkness/brightness, tension/release
6. **Instruments & Texture** — what's in the mix (synths, drums, bass, vocals, pads, etc.)
7. **Frequency Character** — is it bass-heavy? treble-bright? mid-forward? Where does the energy live spectrally?
8. **Suggested Visual Sync Points** — timestamps where visual effects should trigger (beat drops, swells, silence gaps, rhythmic patterns)
9. **Color Temperature Suggestion** — based on mood, suggest warm/cool/neutral palette direction

Format timestamps as MM:SS or MM:SS.ms for precision."""

DEFAULT_VIDEO_PROMPT = """Analyze this video for a creative review pipeline. Provide:

1. **Visual Style** — describe the aesthetic (colors, textures, contrast, lighting, composition)
2. **Pacing & Rhythm** — how are cuts timed? Fast/slow? Regular/irregular? Match to any audio?
3. **Color Palette** — dominant colors, temperature, contrast approach
4. **Motion & Energy** — how does movement work? Camera moves? Subject motion? Particle effects?
5. **Typography** — any text on screen? Style, animation, timing?
6. **Transitions** — how does it move between scenes? Hard cuts? Fades? Glitch? Wipes?
7. **Mood & Emotion** — what feeling does this evoke? What story is being told?
8. **Technical Quality** — resolution feel, frame rate smoothness, any artifacts?
9. **What Works** — strongest visual moments, most effective techniques
10. **What Could Improve** — weakest moments, missed opportunities, suggestions

Be specific with timestamps (MM:SS) for all observations."""


def encode_audio(path: Path) -> tuple[str, str]:
    """Read and base64-encode an audio file. Returns (base64_data, format)."""
    suffix = path.suffix.lower().lstrip(".")
    format_map = {
        "mp3": "mp3", "wav": "wav", "m4a": "m4a", "aac": "aac",
        "ogg": "ogg", "flac": "flac", "aiff": "aiff",
    }
    fmt = format_map.get(suffix, "mp3")
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    size_mb = len(data) / 1024 / 1024
    print(f"Encoded {path.name} ({size_mb:.1f} MB) as audio/{fmt}", file=sys.stderr)
    return b64, fmt


def encode_video(path: Path) -> str:
    """Read and base64-encode a video file. Returns data URL string."""
    suffix = path.suffix.lower().lstrip(".")
    mime_map = {
        "mp4": "video/mp4", "webm": "video/webm", "mov": "video/mov",
        "mpeg": "video/mpeg", "avi": "video/mp4", "mkv": "video/mp4",
    }
    mime = mime_map.get(suffix, "video/mp4")
    data = path.read_bytes()
    b64 = base64.standard_b64encode(data).decode("ascii")
    size_mb = len(data) / 1024 / 1024
    print(f"Encoded {path.name} ({size_mb:.1f} MB) as {mime}", file=sys.stderr)
    if size_mb > 20:
        print(f"WARNING: File is {size_mb:.0f} MB — may exceed model limits. Consider compressing.", file=sys.stderr)
    return f"data:{mime};base64,{b64}"


def detect_media_type(path: Path) -> str:
    """Detect if file is audio or video based on extension."""
    suffix = path.suffix.lower().lstrip(".")
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    elif suffix in VIDEO_EXTENSIONS:
        return "video"
    else:
        print(f"Unknown extension '.{suffix}', trying as video", file=sys.stderr)
        return "video"


def analyze(media_path: Path, prompt: str, model: str, media_type: str = None) -> str:
    """Send media to OpenRouter for analysis."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("Error: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    if media_type is None:
        media_type = detect_media_type(media_path)

    # Build content array
    content = [{"type": "text", "text": prompt}]

    if media_type == "audio":
        b64_data, fmt = encode_audio(media_path)
        content.append({
            "type": "input_audio",
            "input_audio": {"data": b64_data, "format": fmt},
        })
    elif media_type == "video":
        data_url = encode_video(media_path)
        content.append({
            "type": "video_url",
            "video_url": {"url": data_url},
        })

    print(f"Sending to {model}...", file=sys.stderr)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=4096,
    )

    return response.choices[0].message.content


def main():
    parser = argparse.ArgumentParser(
        description="Analyze audio/video via OpenRouter multimodal models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Audio analysis (BPM, beats, mood, sync points)
  uv run media_analyze.py track.mp3

  # Video analysis (style, pacing, color, quality)
  uv run media_analyze.py clip.mp4

  # Custom prompt
  uv run media_analyze.py track.mp3 --prompt "What's the BPM and where are the drops?"
  uv run media_analyze.py scene.mp4 --prompt "Rate the visual quality 1-10 and explain why"

  # Force media type
  uv run media_analyze.py file.dat --type audio

  # Different model
  uv run media_analyze.py clip.mp4 --model google/gemini-2.5-flash
        """,
    )
    parser.add_argument("media_file", type=Path, help="Path to audio or video file")
    parser.add_argument("--prompt", "-p", default=None,
                       help="Analysis prompt (default: auto-selected based on media type)")
    parser.add_argument("--model", "-m", default="google/gemini-2.5-flash",
                       help="Model to use (default: google/gemini-2.5-flash)")
    parser.add_argument("--type", "-t", choices=["audio", "video"], default=None,
                       help="Force media type detection (default: auto from extension)")
    parser.add_argument("--output", "-o", type=Path,
                       help="Save output to file instead of stdout")

    args = parser.parse_args()

    if not args.media_file.exists():
        print(f"Error: {args.media_file} not found", file=sys.stderr)
        sys.exit(1)

    media_type = args.type or detect_media_type(args.media_file)

    # Select default prompt based on media type
    if args.prompt is None:
        prompt = DEFAULT_AUDIO_PROMPT if media_type == "audio" else DEFAULT_VIDEO_PROMPT
    else:
        prompt = args.prompt

    result = analyze(args.media_file, prompt, args.model, media_type)

    if args.output:
        args.output.write_text(result)
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
