#!/usr/bin/env python3
"""
Scene 4: Workers Processing — The Hive Mind Breathes
TIME: 0:49 - 1:07 (18 seconds)
RENDERER: ASCII video (audio-reactive)

5 terminals running simultaneously. Each panel scrolls independently but they share
a synchronized heartbeat (border flash every 2 seconds on kick drum).
Connecting data lines between panels pulse with bass.
Transition out: panels overlay/slide toward center at 1:07.

Brand: Gold #F5B820, Blue #0000FF/#2222FF, Black #000000
"""

import os
import sys
import time
import struct
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile
from scipy.signal import butter, sosfilt
from scipy.ndimage import gaussian_filter

# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════
VW, VH = 1920, 1080
FPS = 24
DURATION = 18.0  # seconds
TOTAL_FRAMES = int(DURATION * FPS)  # 432 frames
AUDIO_START = 49.0  # scene starts at 0:49 in the track
AUDIO_END = 67.0    # scene ends at 1:07

# Brand Colors (RGB tuples)
GOLD = (245, 184, 32)       # #F5B820
DARK_AMBER = (196, 122, 26) # #C47A1A
BLUE = (34, 34, 255)        # #2222FF
NAVY = (0, 0, 16)           # #000010 (panel background per spec)
PURE_BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
STEEL = (107, 125, 142)     # #6B7D8E

# Paths
WORKSPACE = "/home/daimon/projects/video-pipeline/kanban-launch-video"
AUDIO_PATH = os.path.join(WORKSPACE, "audio/Doomscroll.mp3")
OUTPUT_DIR = os.path.join(WORKSPACE, "scenes/scene-04")
CHECKPOINT_DIR = os.path.join(WORKSPACE, "checkpoints")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "clip.mp4")
PREVIEW_FILE = os.path.join(CHECKPOINT_DIR, "scene-04-frame-001.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Font
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# ═══════════════════════════════════════════════════════════════
# AUDIO ANALYSIS
# ═══════════════════════════════════════════════════════════════
def extract_audio_features():
    """Extract FFT features from audio for scene's time range."""
    print("[1/6] Extracting audio features...", flush=True)
    
    # Convert mp3 to wav for scipy
    wav_tmp = "/tmp/doomscroll_scene04.wav"
    if not os.path.exists(wav_tmp):
        subprocess.run([
            "ffmpeg", "-y", "-i", AUDIO_PATH,
            "-ss", str(AUDIO_START), "-t", str(DURATION),
            "-ar", "44100", "-ac", "1", "-f", "wav", wav_tmp
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    sr, data = wavfile.read(wav_tmp)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / np.iinfo(data.dtype).max
    
    # Compute per-frame features
    hop = sr // FPS  # samples per frame
    features = {
        "bass": np.zeros(TOTAL_FRAMES),
        "mids": np.zeros(TOTAL_FRAMES),
        "highs": np.zeros(TOTAL_FRAMES),
        "kick": np.zeros(TOTAL_FRAMES),
        "energy": np.zeros(TOTAL_FRAMES),
    }
    
    # Band filters
    def bandpass(lo, hi, sr, order=4):
        nyq = sr / 2
        sos = butter(order, [lo/nyq, hi/nyq], btype='band', output='sos')
        return sos
    
    bass_sos = bandpass(30, 200, sr)
    mid_sos = bandpass(200, 2000, sr)
    high_sos = bandpass(4000, 12000, sr)
    kick_sos = bandpass(30, 100, sr)
    
    bass_signal = sosfilt(bass_sos, data)
    mid_signal = sosfilt(mid_sos, data)
    high_signal = sosfilt(high_sos, data)
    kick_signal = sosfilt(kick_sos, data)
    
    for i in range(TOTAL_FRAMES):
        start = i * hop
        end = min(start + hop, len(data))
        if start >= len(data):
            break
        
        features["bass"][i] = np.sqrt(np.mean(bass_signal[start:end]**2))
        features["mids"][i] = np.sqrt(np.mean(mid_signal[start:end]**2))
        features["highs"][i] = np.sqrt(np.mean(high_signal[start:end]**2))
        features["kick"][i] = np.sqrt(np.mean(kick_signal[start:end]**2))
        features["energy"][i] = np.sqrt(np.mean(data[start:end]**2))
    
    # Normalize each feature to [0, 1]
    for key in features:
        mx = features[key].max()
        if mx > 0:
            features[key] /= mx
    
    # Compute beat/kick detection (simple peak detection)
    from scipy.signal import find_peaks
    kick_env = features["kick"].copy()
    # Smooth slightly
    from scipy.ndimage import uniform_filter1d
    kick_smooth = uniform_filter1d(kick_env, size=3)
    peaks, _ = find_peaks(kick_smooth, height=0.4, distance=8)  # ~every 2 sec at 24fps
    features["kick_peaks"] = peaks
    
    print(f"  Audio: {len(data)/sr:.1f}s, {TOTAL_FRAMES} frames, {len(peaks)} kick peaks detected", flush=True)
    return features


# ═══════════════════════════════════════════════════════════════
# TERMINAL PANEL DEFINITIONS
# ═══════════════════════════════════════════════════════════════

PANEL_PROFILES = [
    {"name": "@researcher", "scroll_speed": 2.2,  # lines/sec
     "content": [
        "scanning arxiv/2024...",
        "found 47 relevant papers",
        "filtering by citation count",
        "  → top-k: attention, RLHF, scaling",
        "synthesizing abstracts...",
        "cluster 1: alignment methods",
        "cluster 2: efficiency gains",
        "  note: contradicts prior work",
        "extracting key findings...",
        "cross-referencing claims",
        "building knowledge graph",
        "  nodes: 142, edges: 891",
        "semantic similarity > 0.87",
        "flagging novel contributions",
        "summary: 3 major themes",
        "writing synthesis report...",
        "done. 12 sources cited.",
     ]},
    {"name": "@engineer", "scroll_speed": 1.8,
     "content": [
        "def process_batch(items):",
        "    pool = Pool(n_workers)",
        "    results = pool.map(",
        "        transform, items",
        "    )",
        "    return aggregate(results)",
        "",
        "class Pipeline:",
        "    def __init__(self, stages):",
        "        self.stages = stages",
        "        self.state = {}",
        "",
        "    async def run(self):",
        "        for s in self.stages:",
        "            await s.execute(",
        "                self.state",
        "            )",
        "        return self.state",
        "",
        "# TODO: add retry logic",
        "# TODO: circuit breaker",
     ]},
    {"name": "@reviewer", "scroll_speed": 2.5,
     "content": [
        "--- a/core/pipeline.py",
        "+++ b/core/pipeline.py",
        "@@ -42,7 +42,9 @@",
        "-    return raw_output",
        "+    validated = schema.check(",
        "+        raw_output",
        "+    )",
        "+    return validated",
        "",
        "  LGTM: error handling",
        "  WARN: missing timeout",
        "  ───────────────────",
        "  nit: rename `x` → `ctx`",
        "  Q: thread-safe? verify",
        "  approved with comments",
        "  ✓ no security issues",
        "  ✓ tests cover new path",
     ]},
    {"name": "@deployer", "scroll_speed": 1.5,
     "content_type": "progress"},
    {"name": "@tester", "scroll_speed": 2.8,
     "content": [
        "Running test suite...",
        "  ✓ test_init (0.02s)",
        "  ✓ test_connect (0.15s)",
        "  ✓ test_auth (0.08s)",
        "  ✓ test_query (0.31s)",
        "  ✓ test_transform (0.12s)",
        "  ✓ test_validate (0.05s)",
        "  ✓ test_pipeline (0.44s)",
        "  ✓ test_retry (0.22s)",
        "  ✓ test_timeout (1.01s)",
        "  ✓ test_concurrent (0.67s)",
        "  ✓ test_edge_case (0.09s)",
        "  ✓ test_integration (2.1s)",
        "",
        "12/12 passed (5.26s)",
        "Coverage: 94.2%",
     ]},
]

# Panel layout: 3 top, 2 bottom
# Each panel defined by (x, y, w, h) in pixel coords
PANEL_MARGIN = 12
PANEL_GAP = 8
TOP_H = int(VH * 0.52)  # top row height
BOT_H = int(VH * 0.44)  # bottom row height
TOP_Y = PANEL_MARGIN
BOT_Y = TOP_Y + TOP_H + PANEL_GAP

# 3 columns on top
top_total_w = VW - 2 * PANEL_MARGIN - 2 * PANEL_GAP
top_panel_w = top_total_w // 3
# 2 columns on bottom (wider)
bot_total_w = VW - 2 * PANEL_MARGIN - PANEL_GAP
bot_panel_w = bot_total_w // 2

PANEL_RECTS = [
    # Top row: 3 panels
    (PANEL_MARGIN, TOP_Y, top_panel_w, TOP_H),
    (PANEL_MARGIN + top_panel_w + PANEL_GAP, TOP_Y, top_panel_w, TOP_H),
    (PANEL_MARGIN + 2*(top_panel_w + PANEL_GAP), TOP_Y, top_panel_w, TOP_H),
    # Bottom row: 2 panels
    (PANEL_MARGIN, BOT_Y, bot_panel_w, BOT_H),
    (PANEL_MARGIN + bot_panel_w + PANEL_GAP, BOT_Y, bot_panel_w, BOT_H),
]

# Header height for profile name
HEADER_H = 28


# ═══════════════════════════════════════════════════════════════
# RENDERING ENGINE
# ═══════════════════════════════════════════════════════════════

class TerminalRenderer:
    """Renders the 5-panel hive mind scene."""
    
    def __init__(self, features):
        self.features = features
        self.font_sm = ImageFont.truetype(FONT_PATH, 13)
        self.font_md = ImageFont.truetype(FONT_PATH, 15)
        self.font_header = ImageFont.truetype(FONT_BOLD_PATH, 16)
        self.font_lg = ImageFont.truetype(FONT_BOLD_PATH, 14)
        
        # Pre-compute line heights
        asc, desc = self.font_md.getmetrics()
        self.line_h = asc + desc + 2  # small gap between lines
        
        # Cursor blink phases (different per panel)
        self.cursor_phases = [0.0, 0.37, 0.62, 0.15, 0.83]
        
        # Progress bar state for deployer panel
        self.deploy_progress = 0.0
        
        # Connecting line endpoints (between panels)
        self.connections = self._compute_connections()
        
        # Spark particles traveling on connections
        self.sparks = []
        
    def _compute_connections(self):
        """Compute thin connecting lines between panels."""
        conns = []
        # Connect top panels horizontally
        for i in range(2):
            x0, y0, w0, h0 = PANEL_RECTS[i]
            x1, y1, w1, h1 = PANEL_RECTS[i+1]
            # Right edge of panel i to left edge of panel i+1
            conns.append(((x0 + w0, y0 + h0//2), (x1, y1 + h1//2)))
        # Connect top to bottom
        conns.append(((PANEL_RECTS[0][0] + PANEL_RECTS[0][2]//2, PANEL_RECTS[0][1] + PANEL_RECTS[0][3]),
                      (PANEL_RECTS[3][0] + PANEL_RECTS[3][2]//2, PANEL_RECTS[3][1])))
        conns.append(((PANEL_RECTS[2][0] + PANEL_RECTS[2][2]//2, PANEL_RECTS[2][1] + PANEL_RECTS[2][3]),
                      (PANEL_RECTS[4][0] + PANEL_RECTS[4][2]//2, PANEL_RECTS[4][1])))
        # Connect bottom panels
        x0, y0, w0, h0 = PANEL_RECTS[3]
        x1, y1, w1, h1 = PANEL_RECTS[4]
        conns.append(((x0 + w0, y0 + h0//2), (x1, y1 + h1//2)))
        return conns
    
    def render_frame(self, frame_idx):
        """Render a single frame. Returns numpy array (VH, VW, 3) uint8."""
        t = frame_idx / FPS
        f = {k: float(self.features[k][frame_idx]) if k != "kick_peaks" else self.features[k]
             for k in self.features}
        
        # Create canvas - pure black
        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        
        # Draw each panel (backgrounds + borders + content)
        for i, (profile, rect) in enumerate(zip(PANEL_PROFILES, PANEL_RECTS)):
            canvas = self._draw_panel(canvas, i, profile, rect, t, f)
        
        # Draw connecting lines between panels (AFTER panels so they're visible in gaps)
        canvas = self._draw_connections(canvas, t, f)
        
        # Draw sparks on connections (on top of everything)
        canvas = self._draw_sparks(canvas, t, f)
        
        # Background bass pulse - subtle brightness modulation
        bass_pulse = f["bass"] * 0.08
        if bass_pulse > 0.01:
            canvas = np.clip(canvas.astype(np.float32) * (1.0 + bass_pulse), 0, 255).astype(np.uint8)
        
        # Transition out: panels slide toward center at the end (last 1.5 sec)
        transition_start = DURATION - 1.5
        if t > transition_start:
            canvas = self._apply_transition(canvas, t, transition_start)
        
        return canvas
    
    def _draw_panel(self, canvas, panel_idx, profile, rect, t, f):
        """Draw a single terminal panel."""
        x, y, w, h = rect
        
        # Heartbeat: every ~2 seconds, sync to kick drums
        heartbeat_intensity = self._get_heartbeat(t, f)
        
        # Panel breathing (subtle scale oscillation - all same phase for unity)
        breath = 1.0 + 0.008 * np.sin(2 * np.pi * t / 4.0)  # 4-sec cycle
        
        # Panel background - navy tinted (#000010)
        panel_bg = np.array(canvas[y:y+h, x:x+w], dtype=np.float32)
        panel_bg[:, :, 0] = NAVY[0]
        panel_bg[:, :, 1] = NAVY[1]
        panel_bg[:, :, 2] = NAVY[2]
        
        # Melodic-driven background brightness variation per panel
        mel_factor = 1.0 + f["mids"] * 0.15 * ((panel_idx + 1) / 5.0)
        panel_bg = np.clip(panel_bg * mel_factor, 0, 255)
        canvas[y:y+h, x:x+w] = panel_bg.astype(np.uint8)
        
        # Draw border
        border_color = self._get_border_color(heartbeat_intensity, panel_idx)
        self._draw_box_border(canvas, x, y, w, h, border_color, thickness=2)
        
        # Draw header with profile name
        header_color = GOLD
        # Gold header brightness follows melody contour
        mel_bright = 0.7 + 0.3 * f["mids"]
        header_color = tuple(int(c * mel_bright) for c in GOLD)
        self._draw_header(canvas, x, y, w, profile["name"], header_color)
        
        # Draw terminal content
        content_y = y + HEADER_H + 4
        content_h = h - HEADER_H - 8
        content_x = x + 8
        content_w = w - 16
        
        if profile.get("content_type") == "progress":
            self._draw_progress_panel(canvas, content_x, content_y, content_w, content_h, t, f)
        else:
            self._draw_text_panel(canvas, panel_idx, profile, content_x, content_y, 
                                  content_w, content_h, t, f)
        
        # Cursor blink (per-panel phase)
        cursor_phase = self.cursor_phases[panel_idx]
        cursor_visible = ((t + cursor_phase) % 1.06) < 0.53
        if cursor_visible:
            self._draw_cursor(canvas, panel_idx, content_x, content_y, content_h, t)
        
        return canvas
    
    def _get_heartbeat(self, t, f):
        """Synchronized heartbeat every ~2 seconds on kick."""
        # Use kick energy with fast decay
        kick_val = f["kick"]
        # Also check if we're near a 2-second boundary (BPM ~100 means beat every 0.6s)
        # Heartbeat at fixed 2-second intervals synced to kick
        phase = t % 2.0
        if phase < 0.08:  # brief flash window
            return 1.0
        elif phase < 0.15:
            return max(0, 1.0 - (phase - 0.08) / 0.07)  # fast decay
        # Also flash on strong kicks
        if kick_val > 0.7:
            return kick_val * 0.6
        return 0.0
    
    def _get_border_color(self, heartbeat, panel_idx):
        """Get border color based on heartbeat state."""
        # Normal: vivid blue. Heartbeat flash: gold.
        if heartbeat > 0.1:
            # Interpolate blue -> gold
            r = int(BLUE[0] + (GOLD[0] - BLUE[0]) * heartbeat)
            g = int(BLUE[1] + (GOLD[1] - BLUE[1]) * heartbeat)
            b = int(BLUE[2] + (GOLD[2] - BLUE[2]) * heartbeat)
            return (min(255, r), min(255, g), min(255, b))
        # Vivid blue - brighter than the base BLUE constant
        return (40, 40, 255)
    
    def _draw_box_border(self, canvas, x, y, w, h, color, thickness=2):
        """Draw a rectangular border with subtle glow."""
        r, g, b = color
        # Inner glow (1px inside border, dimmer)
        glow_r, glow_g, glow_b = r // 3, g // 3, b // 3
        # Glow layer (3px total border appearance)
        gt = thickness + 1
        # Top glow
        canvas[max(0,y-1):y, x:x+w, 0] = glow_r
        canvas[max(0,y-1):y, x:x+w, 1] = glow_g
        canvas[max(0,y-1):y, x:x+w, 2] = glow_b
        # Bottom glow
        canvas[y+h:min(VH,y+h+1), x:x+w, 0] = glow_r
        canvas[y+h:min(VH,y+h+1), x:x+w, 1] = glow_g
        canvas[y+h:min(VH,y+h+1), x:x+w, 2] = glow_b
        
        # Main border
        # Top
        canvas[y:y+thickness, x:x+w, 0] = r
        canvas[y:y+thickness, x:x+w, 1] = g
        canvas[y:y+thickness, x:x+w, 2] = b
        # Bottom
        canvas[y+h-thickness:y+h, x:x+w, 0] = r
        canvas[y+h-thickness:y+h, x:x+w, 1] = g
        canvas[y+h-thickness:y+h, x:x+w, 2] = b
        # Left
        canvas[y:y+h, x:x+thickness, 0] = r
        canvas[y:y+h, x:x+thickness, 1] = g
        canvas[y:y+h, x:x+thickness, 2] = b
        # Right
        canvas[y:y+h, x+w-thickness:x+w, 0] = r
        canvas[y:y+h, x+w-thickness:x+w, 1] = g
        canvas[y:y+h, x+w-thickness:x+w, 2] = b
    
    def _draw_header(self, canvas, x, y, w, name, color):
        """Draw profile name header in gold."""
        # Create small image for text rendering
        img = Image.fromarray(canvas[y+3:y+HEADER_H, x+8:x+w-8])
        draw = ImageDraw.Draw(img)
        draw.text((4, 2), name, fill=color, font=self.font_header)
        canvas[y+3:y+HEADER_H, x+8:x+w-8] = np.array(img)
    
    def _draw_text_panel(self, canvas, panel_idx, profile, cx, cy, cw, ch, t, f):
        """Draw scrolling text content for a panel."""
        content = profile["content"]
        scroll_speed = profile["scroll_speed"]
        
        # Percussion drives scroll speed modulation
        speed_mod = 1.0 + f["energy"] * 0.4
        effective_scroll = scroll_speed * speed_mod
        
        # Compute which lines are visible (scrolling upward)
        total_lines = len(content)
        # Scroll offset in lines (fractional)
        scroll_offset = t * effective_scroll
        
        # Number of visible lines
        max_visible = ch // self.line_h
        
        # Render visible lines
        img = Image.fromarray(canvas[cy:cy+ch, cx:cx+cw])
        draw = ImageDraw.Draw(img)
        
        for i in range(max_visible + 1):
            line_idx = int(scroll_offset + i) % total_lines
            # Y position with sub-pixel scroll
            frac_offset = scroll_offset - int(scroll_offset)
            ly = int((i - frac_offset) * self.line_h)
            
            if ly < -self.line_h or ly >= ch:
                continue
            
            line = content[line_idx]
            
            # Color: mostly white, special chars get gold/blue
            if line.startswith("  ✓") or line.startswith("✓"):
                color = GOLD
            elif line.startswith("+") or "done" in line.lower():
                color = (200, 245, 200)  # light green tint
            elif line.startswith("-"):
                color = (245, 150, 150)  # light red tint
            elif line.startswith("  →") or line.startswith("#"):
                color = (180, 180, 220)  # light blue
            else:
                # Standard white with slight variation
                bright = 180 + int(40 * (0.5 + 0.5 * np.sin(line_idx * 0.7)))
                color = (bright, bright, bright)
            
            draw.text((4, ly), line, fill=color, font=self.font_md)
        
        canvas[cy:cy+ch, cx:cx+cw] = np.array(img)
    
    def _draw_progress_panel(self, canvas, cx, cy, cw, ch, t, f):
        """Draw deployer progress bars."""
        img = Image.fromarray(canvas[cy:cy+ch, cx:cx+cw])
        draw = ImageDraw.Draw(img)
        
        # Multiple progress bars at different stages
        tasks = [
            ("Building image", min(1.0, t / 6.0)),
            ("Pushing registry", min(1.0, max(0, (t - 3.0) / 5.0))),
            ("Rolling update", min(1.0, max(0, (t - 6.0) / 7.0))),
            ("Health checks", min(1.0, max(0, (t - 10.0) / 4.0))),
            ("DNS propagate", min(1.0, max(0, (t - 13.0) / 4.0))),
        ]
        
        ly = 8
        for label, progress in tasks:
            # Non-linear progress (fast start, slow middle, fast end)
            if progress > 0 and progress < 1:
                progress = progress ** 0.7  # faster feeling
            
            draw.text((4, ly), label, fill=(180, 180, 180), font=self.font_sm)
            ly += self.line_h
            
            # Progress bar
            bar_w = cw - 40
            bar_h = 12
            filled = int(bar_w * progress)
            
            # Bar background
            draw.rectangle([4, ly, 4 + bar_w, ly + bar_h], fill=(20, 20, 30))
            
            # Bar fill - gold
            if filled > 0:
                # Gradient from dark amber to gold
                for px in range(filled):
                    frac = px / max(1, bar_w)
                    r = int(DARK_AMBER[0] + (GOLD[0] - DARK_AMBER[0]) * frac)
                    g = int(DARK_AMBER[1] + (GOLD[1] - DARK_AMBER[1]) * frac)
                    b = int(DARK_AMBER[2] + (GOLD[2] - DARK_AMBER[2]) * frac)
                    draw.line([(4 + px, ly), (4 + px, ly + bar_h)], fill=(r, g, b))
            
            # Percentage
            pct = f"{int(progress * 100)}%"
            draw.text((bar_w + 10, ly - 1), pct, fill=GOLD if progress >= 1.0 else WHITE, font=self.font_sm)
            
            ly += bar_h + 10
            
            if progress >= 1.0:
                draw.text((4, ly - 6), "  ✓ complete", fill=GOLD, font=self.font_sm)
                ly += 4
        
        canvas[cy:cy+ch, cx:cx+cw] = np.array(img)
    
    def _draw_cursor(self, canvas, panel_idx, cx, cy, ch, t):
        """Draw blinking cursor at the current write position."""
        # Place cursor at a line position that seems active
        profile = PANEL_PROFILES[panel_idx]
        scroll_speed = profile["scroll_speed"]
        scroll_offset = t * scroll_speed
        
        # Cursor at the "current" line
        current_line = int(scroll_offset) % max(1, len(profile.get("content", [""])))
        cursor_y = cy + (ch // 2) + int(4 * np.sin(t * 0.5))
        cursor_x = cx + 8 + (current_line % 20) * 8
        
        # Gold cursor block
        if cursor_y + 14 < cy + ch and cursor_x + 8 < cx + (PANEL_RECTS[panel_idx][2] - 16):
            canvas[cursor_y:cursor_y+14, cursor_x:cursor_x+8, 0] = GOLD[0]
            canvas[cursor_y:cursor_y+14, cursor_x:cursor_x+8, 1] = GOLD[1]
            canvas[cursor_y:cursor_y+14, cursor_x:cursor_x+8, 2] = GOLD[2]
    
    def _draw_connections(self, canvas, t, f):
        """Draw connecting lines between panels with pulsing data flow."""
        bass_intensity = f["bass"]
        
        for ci, (p0, p1) in enumerate(self.connections):
            x0, y0 = p0
            x1, y1 = p1
            
            # Base color: vivid blue, pulsing with bass
            brightness = 0.6 + 0.4 * bass_intensity
            color = (
                int(30 * brightness),
                int(30 * brightness),
                int(min(255, 220 * brightness))
            )
            
            # Draw line using Bresenham-like approach on numpy
            steps = max(abs(x1-x0), abs(y1-y0), 1)
            xs = np.linspace(x0, x1, steps).astype(int)
            ys = np.linspace(y0, y1, steps).astype(int)
            
            # Clip to bounds
            valid = (xs >= 0) & (xs < VW) & (ys >= 0) & (ys < VH)
            xs, ys = xs[valid], ys[valid]
            
            # Draw with 5px thickness for visibility
            for offset in range(-2, 3):
                if abs(x1 - x0) > abs(y1 - y0):
                    # Mostly horizontal - offset vertically
                    ys_off = np.clip(ys + offset, 0, VH-1)
                    fade = 1.0 - abs(offset) * 0.25
                    c0 = int(color[0] * fade)
                    c1 = int(color[1] * fade)
                    c2 = int(color[2] * fade)
                    canvas[ys_off, xs, 0] = np.maximum(canvas[ys_off, xs, 0], c0)
                    canvas[ys_off, xs, 1] = np.maximum(canvas[ys_off, xs, 1], c1)
                    canvas[ys_off, xs, 2] = np.maximum(canvas[ys_off, xs, 2], c2)
                else:
                    # Mostly vertical - offset horizontally
                    xs_off = np.clip(xs + offset, 0, VW-1)
                    fade = 1.0 - abs(offset) * 0.25
                    c0 = int(color[0] * fade)
                    c1 = int(color[1] * fade)
                    c2 = int(color[2] * fade)
                    canvas[ys, xs_off, 0] = np.maximum(canvas[ys, xs_off, 0], c0)
                    canvas[ys, xs_off, 1] = np.maximum(canvas[ys, xs_off, 1], c1)
                    canvas[ys, xs_off, 2] = np.maximum(canvas[ys, xs_off, 2], c2)
            
            # Pulsing data flow dot traveling along the line
            pulse_speed = 0.7 + ci * 0.15  # different speed per connection
            pulse_pos = (t * pulse_speed + ci * 0.3) % 1.0
            pulse_idx = int(pulse_pos * len(xs))
            if pulse_idx < len(xs):
                px, py = xs[pulse_idx], ys[pulse_idx]
                # Draw brighter dot at pulse position (larger glow)
                for dy in range(-4, 5):
                    for dx in range(-4, 5):
                        ppx, ppy = px + dx, py + dy
                        if 0 <= ppx < VW and 0 <= ppy < VH:
                            d = np.sqrt(dx*dx + dy*dy)
                            if d < 4.5:
                                intens = (1.0 - d / 4.5) ** 1.5
                                canvas[ppy, ppx, 0] = min(255, int(canvas[ppy, ppx, 0]) + int(80 * intens))
                                canvas[ppy, ppx, 1] = min(255, int(canvas[ppy, ppx, 1]) + int(80 * intens))
                                canvas[ppy, ppx, 2] = min(255, int(canvas[ppy, ppx, 2]) + int(255 * intens))
        
        return canvas
    
    def _draw_sparks(self, canvas, t, f):
        """Draw spark particles traveling along connections on hi-hat hits."""
        highs = f["highs"]
        
        # Spawn new spark on hi-hat hits
        if highs > 0.5 and np.random.random() < 0.3:
            conn_idx = np.random.randint(len(self.connections))
            self.sparks.append({
                "conn": conn_idx,
                "pos": 0.0,
                "speed": 0.8 + np.random.random() * 0.4,
                "born": t,
            })
        
        # Update and draw sparks
        alive_sparks = []
        for spark in self.sparks:
            spark["pos"] += spark["speed"] / FPS
            if spark["pos"] > 1.0:
                continue  # spark has arrived
            alive_sparks.append(spark)
            
            # Interpolate position along connection
            (x0, y0), (x1, y1) = self.connections[spark["conn"]]
            sx = int(x0 + (x1 - x0) * spark["pos"])
            sy = int(y0 + (y1 - y0) * spark["pos"])
            
            # Draw spark as bright gold dot with glow
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    px, py = sx + dx, sy + dy
                    if 0 <= px < VW and 0 <= py < VH:
                        dist = np.sqrt(dx*dx + dy*dy)
                        if dist < 3.5:
                            intensity = max(0, 1.0 - dist / 3.5)
                            canvas[py, px, 0] = min(255, int(canvas[py, px, 0]) + int(GOLD[0] * intensity))
                            canvas[py, px, 1] = min(255, int(canvas[py, px, 1]) + int(GOLD[1] * intensity))
                            canvas[py, px, 2] = min(255, int(canvas[py, px, 2]) + int(GOLD[2] * intensity * 0.3))
        
        self.sparks = alive_sparks
        return canvas
    
    def _apply_transition(self, canvas, t, trans_start):
        """Apply exit transition: panels slide toward center and overlay."""
        progress = (t - trans_start) / 1.5  # 0 to 1
        # Ease-in (accelerate)
        progress = progress * progress
        
        # Fade connections to bright gold
        gold_overlay = np.zeros_like(canvas)
        center_x, center_y = VW // 2, VH // 2
        
        # Create a radial pull effect - darken edges, brighten center
        Y, X = np.mgrid[0:VH, 0:VW]
        dist_from_center = np.sqrt((X - center_x)**2 + (Y - center_y)**2)
        max_dist = np.sqrt(center_x**2 + center_y**2)
        pull = np.clip(1.0 - dist_from_center / max_dist, 0, 1) * progress
        
        # Darken based on distance from center
        darkness = 1.0 - pull * 0.5
        canvas = (canvas.astype(np.float32) * darkness[:, :, None]).astype(np.uint8)
        
        # Add blue edge glow at panel borders converging
        edge_glow = pull * 0.3
        canvas[:, :, 2] = np.clip(canvas[:, :, 2].astype(np.float32) + edge_glow * 80, 0, 255).astype(np.uint8)
        
        return canvas


# ═══════════════════════════════════════════════════════════════
# TONE MAPPING
# ═══════════════════════════════════════════════════════════════

def tonemap(canvas, gamma=0.80):
    """Adaptive tone-mapping: normalizes + gamma-corrects."""
    f = canvas.astype(np.float32)
    sub = f[::4, ::4]
    lo = np.percentile(sub, 1)
    hi = np.percentile(sub, 99.5)
    if hi - lo < 10:
        hi = lo + 10
    f = np.clip((f - lo) / (hi - lo), 0, 1)
    np.power(f, gamma, out=f)
    return (f * 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════
# SHADER POST-PROCESSING
# ═══════════════════════════════════════════════════════════════

def apply_vignette(canvas, strength=0.4):
    """Subtle vignette to focus attention on panels."""
    Y, X = np.mgrid[0:VH, 0:VW].astype(np.float32)
    cx, cy = VW / 2.0, VH / 2.0
    dist = np.sqrt((X - cx)**2 / (cx**2) + (Y - cy)**2 / (cy**2))
    vignette = 1.0 - np.clip(dist - 0.7, 0, 1) * strength
    return (canvas.astype(np.float32) * vignette[:, :, None]).astype(np.uint8)


def apply_scanlines(canvas, intensity=0.06):
    """Subtle CRT scanline effect."""
    scanline = np.ones(VH, dtype=np.float32)
    scanline[::2] = 1.0 - intensity
    return (canvas.astype(np.float32) * scanline[:, None, None]).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════
# MAIN RENDER PIPELINE
# ═══════════════════════════════════════════════════════════════

def main():
    start_time = time.time()
    
    # Step 1: Audio analysis
    features = extract_audio_features()
    
    # Step 2: Initialize renderer
    print("[2/6] Initializing terminal renderer...", flush=True)
    renderer = TerminalRenderer(features)
    
    # Step 3: Render preview frame
    print("[3/6] Rendering preview frame...", flush=True)
    preview_frame = renderer.render_frame(int(FPS * 5.5))  # frame at t=5.5s (between heartbeats)
    preview_frame = tonemap(preview_frame, gamma=0.78)
    preview_frame = apply_vignette(preview_frame)
    preview_frame = apply_scanlines(preview_frame)
    
    Image.fromarray(preview_frame).save(PREVIEW_FILE)
    print(f"  Preview saved: {PREVIEW_FILE}", flush=True)
    
    # Step 4: Render all frames
    print(f"[4/6] Rendering {TOTAL_FRAMES} frames...", flush=True)
    
    # Open ffmpeg pipe
    ffmpeg_log = os.path.join(OUTPUT_DIR, "ffmpeg_stderr.log")
    stderr_fh = open(ffmpeg_log, "w")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{VW}x{VH}", "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-pix_fmt", "yuv420p",
        OUTPUT_FILE
    ]
    
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=stderr_fh)
    
    frame_times = []
    for fi in range(TOTAL_FRAMES):
        t0 = time.time()
        
        canvas = renderer.render_frame(fi)
        
        # Tonemap
        canvas = tonemap(canvas, gamma=0.78)
        
        # Post-processing shaders
        canvas = apply_vignette(canvas, strength=0.3)
        canvas = apply_scanlines(canvas, intensity=0.04)
        
        # Write to pipe
        pipe.stdin.write(canvas.tobytes())
        
        dt = time.time() - t0
        frame_times.append(dt)
        
        if fi % 48 == 0:
            avg_ms = np.mean(frame_times[-48:]) * 1000
            eta = avg_ms * (TOTAL_FRAMES - fi) / 1000
            print(f"  Frame {fi}/{TOTAL_FRAMES} ({fi*100//TOTAL_FRAMES}%) "
                  f"- {avg_ms:.0f}ms/frame, ETA: {eta:.0f}s", flush=True)
    
    pipe.stdin.close()
    pipe.wait()
    stderr_fh.close()
    
    render_time = time.time() - start_time
    
    # Step 5: Verify output
    print("[5/6] Verifying output...", flush=True)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", 
         "format=duration,size", "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1", OUTPUT_FILE],
        capture_output=True, text=True
    )
    print(f"  {result.stdout.strip()}", flush=True)
    
    print(f"[6/6] Done! Render time: {render_time:.1f}s", flush=True)
    print(f"  Output: {OUTPUT_FILE}", flush=True)
    print(f"  Preview: {PREVIEW_FILE}", flush=True)
    print(f"  Avg frame time: {np.mean(frame_times)*1000:.0f}ms", flush=True)


if __name__ == "__main__":
    main()
