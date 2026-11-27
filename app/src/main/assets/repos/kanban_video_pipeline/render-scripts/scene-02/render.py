#!/usr/bin/env python3
"""
Scene 2: Task Creation — "Prophecies Being Written"
Time: 0:12–0:30 | Renderer: ASCII | Energy: Building, percussion enters

Tasks materialize like prophecies carved into stone. Each box has WEIGHT —
not playful, inevitable. Like watching fate write itself onto a terminal.

Pipeline: INPUT → ANALYZE → SCENE_FN → TONEMAP → SHADE → ENCODE

v2 — Heavier construction: bigger welding glow, screen shake on landing,
aura around box borders, stronger bass reactivity, dramatic stillness.
"""

import os
import sys
import time
import math
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile
from scipy.ndimage import gaussian_filter

# === CONFIGURATION ===
VW, VH = 1920, 1080
FPS = 24
DURATION = 18.0
TOTAL_FRAMES = int(DURATION * FPS)  # 432 frames
AUDIO_START = 12.0  # Scene starts at 12s in the track

# Paths
WORKDIR = "/home/daimon/projects/video-pipeline/kanban-launch-video"
AUDIO_PATH = os.path.join(WORKDIR, "audio/Doomscroll.mp3")
OUTPUT_DIR = os.path.join(WORKDIR, "scenes/scene-02")
OUTPUT_CLIP = os.path.join(OUTPUT_DIR, "clip.mp4")
CHECKPOINT_DIR = os.path.join(WORKDIR, "checkpoints")
CHECKPOINT_FRAME = os.path.join(CHECKPOINT_DIR, "scene-02-frame-001.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Brand colors (float32 for compositing)
GOLD = np.array([245, 184, 32], dtype=np.float32)
DARK_AMBER = np.array([196, 122, 26], dtype=np.float32)
BLUE = np.array([34, 34, 255], dtype=np.float32)
NAVY = np.array([0, 0, 128], dtype=np.float32)
STEEL_GREY = np.array([107, 125, 142], dtype=np.float32)
WHITE = np.array([255, 255, 255], dtype=np.float32)

# Font setup
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_PATH_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


# === AUDIO ANALYSIS ===
def extract_audio_features():
    """Extract FFT features for 0:12 - 0:31 of the track."""
    wav_path = "/tmp/doomscroll_scene02.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", AUDIO_PATH,
        "-ss", str(AUDIO_START), "-t", str(DURATION + 1.0),
        "-ar", "22050", "-ac", "1", "-f", "wav", wav_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    sr, data = wavfile.read(wav_path)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / np.iinfo(data.dtype).max

    features = {
        "rms": np.zeros(TOTAL_FRAMES),
        "bass": np.zeros(TOTAL_FRAMES),
        "sub": np.zeros(TOTAL_FRAMES),
        "mid": np.zeros(TOTAL_FRAMES),
        "hi": np.zeros(TOTAL_FRAMES),
        "beat": np.zeros(TOTAL_FRAMES),
        "kick": np.zeros(TOTAL_FRAMES),
    }

    hop = sr // FPS
    window_size = 2048
    prev_bass = 0.0
    for fi in range(TOTAL_FRAMES):
        start = fi * hop
        end = start + window_size
        if end > len(data):
            break
        chunk = data[start:end] * np.hanning(window_size)

        features["rms"][fi] = np.sqrt(np.mean(chunk**2))

        fft = np.abs(np.fft.rfft(chunk))
        freqs = np.fft.rfftfreq(window_size, 1.0/sr)

        def band_energy(lo, hi):
            mask = (freqs >= lo) & (freqs < hi)
            return np.mean(fft[mask]**2) if mask.any() else 0

        features["sub"][fi] = band_energy(20, 60)
        features["bass"][fi] = band_energy(60, 200)
        features["mid"][fi] = band_energy(200, 2000)
        features["hi"][fi] = band_energy(2000, 12000)

        # Kick detection: onset in bass band
        curr_bass = features["bass"][fi]
        if curr_bass > prev_bass * 1.5 and curr_bass > 0.0005:
            features["kick"][fi] = 1.0
        prev_bass = curr_bass

    # Normalize
    for key in features:
        mx = features[key].max()
        if mx > 0:
            features[key] /= mx

    # Beat detection from RMS onset
    rms_diff = np.diff(features["rms"], prepend=0)
    features["beat"] = np.clip(rms_diff * 6, 0, 1)

    os.remove(wav_path)
    return features


print("Extracting audio features for Scene 2...")
FEATURES = extract_audio_features()
print(f"  RMS range: {FEATURES['rms'].min():.3f} - {FEATURES['rms'].max():.3f}")
print(f"  Hi-hat peaks: {(FEATURES['hi'] > 0.5).sum()} frames")
print(f"  Kick detections: {(FEATURES['kick'] > 0.5).sum()} frames")


# === FONT SETUP ===
# Box text font (monospace, readable) — Bold for weight
TEXT_FONT_SIZE = 24
text_font = ImageFont.truetype(FONT_PATH, TEXT_FONT_SIZE)
text_asc, text_desc = text_font.getmetrics()
TEXT_CH = text_asc + text_desc
TEXT_CW = text_font.getbbox("M")[2]

# Box border font (for box-drawing chars) — Bold for heft
BORDER_FONT_SIZE = 24
border_font = ImageFont.truetype(FONT_PATH, BORDER_FONT_SIZE)
border_asc, border_desc = border_font.getmetrics()
BORDER_CH = border_asc + border_desc
BORDER_CW = border_font.getbbox("─")[2]

# Column header font
HEADER_FONT_SIZE = 16
header_font = ImageFont.truetype(FONT_PATH_REG, HEADER_FONT_SIZE)

# Background particle font
BG_FONT_SIZE = 10
bg_font = ImageFont.truetype(FONT_PATH_REG, BG_FONT_SIZE)
bg_asc, bg_desc = bg_font.getmetrics()
BG_CW = bg_font.getbbox("M")[2]
BG_CH = bg_asc + bg_desc


# === TASK BOX DEFINITIONS ===
TASK_TEXTS = ["research market", "implement core", "review PR #42", "deploy v2.0"]

# Box geometry (in characters) — slightly larger for presence
BOX_INNER_W = 24  # chars wide inside
BOX_INNER_H = 3   # lines tall inside (padding + text + padding)
BOX_W = BOX_INNER_W + 2  # +borders
BOX_H = BOX_INNER_H + 2  # +borders

# Pixel dimensions of a box
BOX_PX_W = BOX_W * BORDER_CW
BOX_PX_H = BOX_H * BORDER_CH

# Layout: kanban-style column, boxes stack in TODO column
HEADER_Y = 60
COL_HEADERS = ["TODO", "RUNNING", "DONE"]
COL_X_POSITIONS = [280, 780, 1280]

# Boxes appear in TODO column
BOX_START_X = 220  # left margin for TODO column
BOX_START_Y = 150  # below headers
BOX_SPACING_Y = BOX_PX_H + 40  # vertical spacing between boxes

# Box positions (pre-calculated)
BOX_POSITIONS = []
for i in range(4):
    bx = BOX_START_X
    by = BOX_START_Y + i * BOX_SPACING_Y
    BOX_POSITIONS.append((bx, by))

# === TIMING ===
# First beat at 0:12.75 = 0.75s into our scene
FIRST_BEAT = 0.75

# Each box: construction synced to a downbeat
# Construction: 400ms borders (spec says 400ms) + 200ms pause + text typing
# Then 2.5s stillness before next box
BOX_START_TIMES = [
    FIRST_BEAT,             # Box 0: 0.75s (percussion entrance)
    FIRST_BEAT + 4.0,       # Box 1: 4.75s
    FIRST_BEAT + 8.0,       # Box 2: 8.75s
    FIRST_BEAT + 12.0,      # Box 3: 12.75s
]

CONSTRUCTION_DURATION = 0.5   # 500ms to draw borders (400ms spec + settle)
TEXT_DELAY = 0.2              # 200ms pause before typing (spec)
TEXT_SPEED = 3.0              # 3 chars/sec (spec says 3 chars/sec)

TRANSITION_START = 16.5       # Begin transition at 16.5s
TRANSITION_END = 18.0         # End exactly at frame boundary


# === PARTICLE SYSTEM (from Scene 1 shatter remnants) ===
class ParticleField:
    """Ambient particles — remnants from Scene 1's shatter, drifting."""
    def __init__(self, n=100, seed=123):
        rng = np.random.RandomState(seed)
        self.x = rng.uniform(0, VW, n).astype(np.float32)
        self.y = rng.uniform(0, VH, n).astype(np.float32)
        self.bri = rng.uniform(0.05, 0.2, n).astype(np.float32)
        self.size = rng.choice([1, 1, 2, 2, 3], n)
        # Some are gold (from shatter), most are navy
        self.is_gold = rng.uniform(0, 1, n) < 0.25
        self.n = n
        self.rng = rng
        self.bass_boost = 0.0

    def update(self, bass_level=0.0, t=0.0):
        """Slow drift with brownian motion — upward drift."""
        self.y -= 1.2 / FPS + self.rng.uniform(-0.1, 0.1, self.n)
        self.x += self.rng.uniform(-0.15, 0.15, self.n)

        # Wrap
        reset = self.y < -5
        self.y[reset] = VH + self.rng.uniform(5, 30, reset.sum())
        self.x[reset] = self.rng.uniform(0, VW, reset.sum())

        # Gold particles slowly decay over scene
        if t > 6.0:
            fade = min(1.0, (t - 6.0) / 12.0)
            self.is_gold = self.is_gold & (self.rng.uniform(0, 1, self.n) > fade * 0.008)

        self.bass_boost = bass_level * 0.4

    def render(self, canvas):
        """Draw particles."""
        for i in range(self.n):
            px = int(self.x[i]) % VW
            py = int(self.y[i]) % VH
            bri = min(0.5, self.bri[i] + self.bass_boost)
            size = self.size[i]

            if self.is_gold[i]:
                r = int(GOLD[0] * bri * 0.5)
                g = int(GOLD[1] * bri * 0.5)
                b = int(GOLD[2] * bri * 0.5)
            else:
                r = int(bri * 4)
                g = int(bri * 6)
                b = int(bri * 100)

            for dy in range(size):
                for dx in range(size):
                    yy = py + dy
                    xx = px + dx
                    if 0 <= yy < VH and 0 <= xx < VW:
                        canvas[yy, xx, 0] = min(255, canvas[yy, xx, 0] + r)
                        canvas[yy, xx, 1] = min(255, canvas[yy, xx, 1] + g)
                        canvas[yy, xx, 2] = min(255, canvas[yy, xx, 2] + b)
        return canvas


# === SPARK SYSTEM (hi-hat reactive) ===
class SparkSystem:
    """Sparks at box corners on hi-hat hits — like welding."""
    def __init__(self):
        self.sparks = []

    def spawn(self, x, y, count=4, rng=None):
        """Spawn sparks at given position."""
        if rng is None:
            rng = np.random.RandomState()
        for _ in range(count):
            angle = rng.uniform(0, 2 * math.pi)
            speed = rng.uniform(50, 160)
            self.sparks.append({
                'x': float(x), 'y': float(y),
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed,
                'life': 1.0,
                'decay': rng.uniform(1.2, 2.5),
            })

    def update(self, dt):
        """Update and cull dead sparks."""
        alive = []
        for s in self.sparks:
            s['x'] += s['vx'] * dt
            s['y'] += s['vy'] * dt
            s['vy'] += 60 * dt  # gravity pulls sparks down
            s['life'] -= s['decay'] * dt
            if s['life'] > 0:
                alive.append(s)
        self.sparks = alive

    def render(self, canvas):
        """Draw sparks as bright white-gold dots."""
        for s in self.sparks:
            px = int(s['x'])
            py = int(s['y'])
            if 0 <= px < VW - 1 and 0 <= py < VH - 1:
                bri = s['life'] ** 0.7  # Slower falloff for visibility
                # White-hot at center, gold at edges
                r = int(min(255, 255 * bri))
                g = int(min(255, 240 * bri))
                b = int(min(255, 120 * bri))
                canvas[py, px, 0] = min(255, int(canvas[py, px, 0]) + r)
                canvas[py, px, 1] = min(255, int(canvas[py, px, 1]) + g)
                canvas[py, px, 2] = min(255, int(canvas[py, px, 2]) + b)
                # 2x2 for visibility
                canvas[py, px+1, 0] = min(255, int(canvas[py, px+1, 0]) + r // 2)
                canvas[py, px+1, 1] = min(255, int(canvas[py, px+1, 1]) + g // 2)
                canvas[py, px+1, 2] = min(255, int(canvas[py, px+1, 2]) + b // 2)
                canvas[py+1, px, 0] = min(255, int(canvas[py+1, px, 0]) + r // 2)
                canvas[py+1, px, 1] = min(255, int(canvas[py+1, px, 1]) + g // 2)
                canvas[py+1, px, 2] = min(255, int(canvas[py+1, px, 2]) + b // 2)
        return canvas


PARTICLES = ParticleField(n=100, seed=123)
SPARKS = SparkSystem()


# === BOX CONSTRUCTION STATE ===
class TaskBox:
    """Manages the animation state of a single task box."""

    def __init__(self, idx, text, x, y, start_time):
        self.idx = idx
        self.text = text
        self.x = x
        self.y = y
        self.start_time = start_time
        self.breath_phase = np.random.RandomState(idx * 7).uniform(0, 2 * math.pi)
        # Landing shake state
        self.land_time = None  # Set when construction completes

    def get_state(self, t):
        """
        Returns construction progress.
        - phase: 'hidden', 'corners', 'borders', 'text_pause', 'typing', 'done'
        - progress: 0.0-1.0 within current phase
        """
        elapsed = t - self.start_time
        if elapsed < 0:
            return 'hidden', 0.0, elapsed

        # Phase 1: Corner construction (first 100ms)
        if elapsed < 0.1:
            return 'corners', elapsed / 0.1, elapsed

        # Phase 2: Border drawing (100ms - 500ms)
        if elapsed < CONSTRUCTION_DURATION:
            return 'borders', (elapsed - 0.1) / (CONSTRUCTION_DURATION - 0.1), elapsed

        # Phase 3: Pause (500ms - 700ms) — the void holds its breath
        if elapsed < CONSTRUCTION_DURATION + TEXT_DELAY:
            return 'text_pause', (elapsed - CONSTRUCTION_DURATION) / TEXT_DELAY, elapsed

        # Phase 4: Text typing
        text_elapsed = elapsed - CONSTRUCTION_DURATION - TEXT_DELAY
        chars_needed = len(self.text)
        typing_duration = chars_needed / TEXT_SPEED
        if text_elapsed < typing_duration:
            return 'typing', text_elapsed / typing_duration, elapsed

        # Mark land time on first completion
        if self.land_time is None:
            self.land_time = self.start_time + CONSTRUCTION_DURATION + TEXT_DELAY + typing_duration

        return 'done', 1.0, elapsed


BOXES = [
    TaskBox(i, TASK_TEXTS[i], BOX_POSITIONS[i][0], BOX_POSITIONS[i][1], BOX_START_TIMES[i])
    for i in range(4)
]


# === SCREEN SHAKE ===
def get_screen_shake(t, boxes):
    """Returns (dx, dy) offset for screen shake when a box lands."""
    dx, dy = 0, 0
    for box in boxes:
        if box.land_time is not None:
            elapsed_since_land = t - box.land_time
            if 0 < elapsed_since_land < 0.15:
                # Decaying shake: 3 frames of wobble
                intensity = (1.0 - elapsed_since_land / 0.15) ** 2
                phase = elapsed_since_land * 40  # Rapid oscillation
                dx += int(math.sin(phase) * 2 * intensity)
                dy += int(math.cos(phase * 1.3) * 1.5 * intensity)
    return dx, dy


# === BORDER AURA (glow behind borders for weight) ===
def render_border_aura(canvas, box, phase, progress, bass_level):
    """Render a subtle blue glow aura behind box borders — gives them heft."""
    if phase == 'hidden':
        return canvas

    bx, by = box.x, box.y
    # Aura intensity depends on phase
    if phase in ('corners', 'borders'):
        aura_str = 0.3 + progress * 0.5  # Builds during construction
    else:
        aura_str = 0.6 + bass_level * 0.3  # Settled, bass-reactive

    # Create aura as a soft rectangle outline (gaussian blur of border shape)
    aura_w = BOX_PX_W + 20
    aura_h = BOX_PX_H + 20
    ax = max(0, bx - 10)
    ay = max(0, by - 10)
    ex = min(VW, ax + aura_w)
    ey = min(VH, ay + aura_h)

    if ex <= ax or ey <= ay:
        return canvas

    # Build thin rectangle mask
    mask = np.zeros((ey - ay, ex - ax), dtype=np.float32)
    # Top edge
    mask[8:12, 8:-8] = 1.0
    # Bottom edge
    mask[-12:-8, 8:-8] = 1.0
    # Left edge
    mask[8:-8, 8:12] = 1.0
    # Right edge
    mask[8:-8, -12:-8] = 1.0

    # Blur for glow effect
    mask = gaussian_filter(mask, sigma=6.0) * aura_str * 0.4

    # Apply as blue additive
    region = canvas[ay:ey, ax:ex].astype(np.float32)
    region[:, :, 0] += mask * BLUE[0] * 0.3
    region[:, :, 1] += mask * BLUE[1] * 0.3
    region[:, :, 2] += mask * BLUE[2] * 0.8
    canvas[ay:ey, ax:ex] = np.clip(region, 0, 255).astype(np.uint8)

    return canvas


# === PRE-RASTERIZE BOX ELEMENTS ===
def draw_box_border(draw, x, y, phase, progress, color, bass_bright=0.0):
    """
    Draw box border using box-drawing characters.
    Construction animation: corners → top → right → bottom → left
    """
    bright = 1.0 + bass_bright * 0.25
    r = int(min(255, color[0] * bright))
    g = int(min(255, color[1] * bright))
    b = int(min(255, color[2] * bright))
    col = (r, g, b)

    w = BOX_PX_W
    h = BOX_PX_H

    if phase == 'corners':
        # Corners appear with delay — building anticipation
        draw.text((x, y), "┌", fill=col, font=border_font)
        if progress > 0.3:
            draw.text((x + w - BORDER_CW, y), "┐", fill=col, font=border_font)
        if progress > 0.6:
            draw.text((x, y + h - BORDER_CH), "└", fill=col, font=border_font)
        if progress > 0.9:
            draw.text((x + w - BORDER_CW, y + h - BORDER_CH), "┘", fill=col, font=border_font)
        return

    # Full construction: borders draw in segments (top→right→bottom→left)
    top_chars = BOX_W - 2
    top_progress = min(1.0, progress / 0.25) if progress < 0.25 else 1.0
    chars_to_draw = int(top_chars * top_progress)

    draw.text((x, y), "┌", fill=col, font=border_font)
    for ci in range(chars_to_draw):
        cx = x + (ci + 1) * BORDER_CW
        draw.text((cx, y), "─", fill=col, font=border_font)
    if top_progress >= 1.0:
        draw.text((x + w - BORDER_CW, y), "┐", fill=col, font=border_font)

    # Right border
    if progress > 0.25:
        right_progress = min(1.0, (progress - 0.25) / 0.25)
        right_chars = BOX_H - 2
        chars_to_draw = int(right_chars * right_progress)
        for ci in range(chars_to_draw):
            cy = y + (ci + 1) * BORDER_CH
            draw.text((x + w - BORDER_CW, cy), "│", fill=col, font=border_font)

    # Bottom border
    if progress > 0.5:
        bot_progress = min(1.0, (progress - 0.5) / 0.25)
        bot_chars = BOX_W - 2
        chars_to_draw = int(bot_chars * bot_progress)
        draw.text((x + w - BORDER_CW, y + h - BORDER_CH), "┘", fill=col, font=border_font)
        for ci in range(chars_to_draw):
            cx = x + w - (ci + 2) * BORDER_CW
            if cx > x:
                draw.text((cx, y + h - BORDER_CH), "─", fill=col, font=border_font)

    # Left border
    if progress > 0.75:
        left_progress = min(1.0, (progress - 0.75) / 0.25)
        left_chars = BOX_H - 2
        chars_to_draw = int(left_chars * left_progress)
        draw.text((x, y + h - BORDER_CH), "└", fill=col, font=border_font)
        for ci in range(chars_to_draw):
            cy = y + h - (ci + 2) * BORDER_CH
            if cy > y:
                draw.text((x, cy), "│", fill=col, font=border_font)


def draw_box_text(draw, x, y, text, chars_visible, cursor_on=True):
    """Draw text inside box with gold typing cursor."""
    # Text position: centered vertically, left-padded
    tx = x + 2 * BORDER_CW
    ty = y + 2 * BORDER_CH  # center row

    visible_text = text[:chars_visible]
    if visible_text:
        draw.text((tx, ty), visible_text, fill=(255, 255, 255), font=text_font)

    # Gold cursor — thick block, flickers like welding torch
    if cursor_on:
        cursor_x = tx + chars_visible * TEXT_CW
        gold_col = (int(GOLD[0]), int(GOLD[1]), int(GOLD[2]))
        draw.text((cursor_x, ty), "▮", fill=gold_col, font=text_font)


# === BACKGROUND VOID TEXTURE ===
BG_COLS = VW // BG_CW
BG_ROWS = VH // BG_CH
BG_OX = (VW - BG_COLS * BG_CW) // 2
BG_OY = (VH - BG_ROWS * BG_CH) // 2

# Pre-rasterize dot character
_dot_img = Image.new("L", (BG_CW, BG_CH), 0)
ImageDraw.Draw(_dot_img).text((0, 0), "·", fill=255, font=bg_font)
BG_DOT_BM = np.array(_dot_img, dtype=np.float32) / 255.0

BG_RR = np.arange(BG_ROWS, dtype=np.float32)[:, None]
BG_CC = np.arange(BG_COLS, dtype=np.float32)[None, :]


# === SCENE FUNCTION ===
def render_frame(frame_idx):
    """
    Render a single frame of Scene 2.

    Timeline:
    0.00-0.75: Void with particles, column headers fade in
    0.75: First box constructs (synced to percussion entrance)
    4.75: Second box
    8.75: Third box
    12.75: Fourth box
    16.5-18.0: Transition — all boxes pulse gold, compress to center
    """
    t = frame_idx / FPS
    f = {k: float(FEATURES[k][min(frame_idx, TOTAL_FRAMES-1)]) for k in FEATURES}

    canvas = np.zeros((VH, VW, 3), dtype=np.uint8)

    # === LAYER 1: Atmospheric background field ===
    # Subtle drifting sine field — pressure in the void
    rms_factor = 0.4 + f["rms"] * 0.6
    v1 = np.sin(BG_CC * 0.05 + t * 0.1) * np.sin(BG_RR * 0.07 - t * 0.06)
    v2 = np.sin(BG_CC * 0.03 - t * 0.05 + BG_RR * 0.04) * 0.6
    val = np.clip((v1 * 0.5 + v2 * 0.5) * 0.5 + 0.5, 0, 1)
    val = val * 0.06 * rms_factor

    # Bass makes void texture PULSE — the void breathing
    bass_pulse = f["bass"] * 0.04
    val += bass_pulse

    threshold = 0.02
    mask = val > threshold
    rows_with_dots, cols_with_dots = np.where(mask)

    # Render as navy dots (subsample every 2nd for density)
    for idx in range(0, len(rows_with_dots), 2):
        row = rows_with_dots[idx]
        col = cols_with_dots[idx]
        y = BG_OY + row * BG_CH
        x = BG_OX + col * BG_CW
        if y + BG_CH > VH or x + BG_CW > VW:
            continue
        v = val[row, col]
        b_val = int(v * 140)
        region = canvas[y:y+BG_CH, x:x+BG_CW]
        dot_contrib = BG_DOT_BM * b_val
        new_b = np.maximum(region[:, :, 2], dot_contrib.astype(np.uint8))
        canvas[y:y+BG_CH, x:x+BG_CW, 2] = new_b

    # === LAYER 2: Ambient particles ===
    PARTICLES.update(f["bass"], t)
    PARTICLES.render(canvas)

    # === LAYER 2.5: Border aura (weight/presence behind boxes) ===
    for box in BOXES:
        phase, progress, elapsed = box.get_state(t)
        if phase != 'hidden':
            render_border_aura(canvas, box, phase, progress, f["bass"])

    # === LAYER 3: Column headers and task boxes (PIL rendering) ===
    box_img = Image.new("RGB", (VW, VH), (0, 0, 0))
    box_draw = ImageDraw.Draw(box_img)

    # Column headers fade in during first 2 seconds
    header_alpha = min(1.0, t / 2.0)
    if header_alpha > 0:
        for ci, (header_text, hx) in enumerate(zip(COL_HEADERS, COL_X_POSITIONS)):
            bri = header_alpha * 0.35
            col = (int(STEEL_GREY[0] * bri), int(STEEL_GREY[1] * bri), int(STEEL_GREY[2] * bri))
            box_draw.text((hx, HEADER_Y), header_text, fill=col, font=header_font)

        # Subtle separator line
        line_bri = header_alpha * 0.12
        line_col = (int(STEEL_GREY[0] * line_bri), int(STEEL_GREY[1] * line_bri), int(STEEL_GREY[2] * line_bri))
        for lx in range(200, 1700, 4):
            box_draw.text((lx, HEADER_Y + 25), "─", fill=line_col, font=bg_font)

    # Transition state
    in_transition = t >= TRANSITION_START
    transition_progress = 0.0
    if in_transition:
        transition_progress = min(1.0, (t - TRANSITION_START) / (TRANSITION_END - TRANSITION_START))

    # Cursor blink timing (530ms on / 530ms off)
    cursor_period_ms = 1060
    cursor_on = (int(t * 1000) % cursor_period_ms) < 530

    # Track which boxes are actively constructing (for welding glow)
    constructing_boxes = []

    # Screen shake
    shake_dx, shake_dy = get_screen_shake(t, BOXES)

    # Draw each box based on its state
    for box in BOXES:
        phase, progress, elapsed = box.get_state(t)

        if phase == 'hidden':
            continue

        bx, by = box.x + shake_dx, box.y + shake_dy

        # During transition: boxes slide toward center and pulse gold
        if in_transition:
            center_x = VW // 2 - BOX_PX_W // 2
            center_y = VH // 2 - BOX_PX_H // 2
            # Ease-in cubic — starts slow, accelerates (pulled by gravity)
            tp = transition_progress ** 2.5
            bx = int(box.x + (center_x - box.x) * tp)
            by = int(box.y + (center_y - box.y) * tp)

            # Gold pulse: all boxes flash blue→gold, then hold pulsing gold
            if transition_progress < 0.08:
                flash_t = transition_progress / 0.08
                border_color = BLUE * (1 - flash_t) + GOLD * flash_t
            else:
                gold_pulse = 0.7 + 0.3 * math.sin(transition_progress * math.pi * 8)
                border_color = GOLD * gold_pulse

            border_color = np.clip(border_color, 0, 255)

            # Shrink and compress
            if transition_progress > 0.75:
                # Nearly compressed — bright gold cluster
                cx = VW // 2
                cy = VH // 2
                bright = (1.0 - (transition_progress - 0.75) / 0.25) * 1.5 + 0.5
                # Draw a radiant cluster
                for dy in range(-12, 13):
                    for dx in range(-12, 13):
                        dist = math.sqrt(dx*dx + dy*dy)
                        if dist < 12 and 0 <= cy+dy < VH and 0 <= cx+dx < VW:
                            d_bri = max(0, 1.0 - dist/12) ** 1.5 * bright
                            pr = int(min(255, GOLD[0] * d_bri))
                            pg = int(min(255, GOLD[1] * d_bri))
                            pb = int(min(255, GOLD[2] * d_bri))
                            box_draw.point((cx+dx, cy+dy), fill=(pr, pg, pb))
                continue

            # Draw border with transition color
            draw_box_border(box_draw, bx, by, 'borders', 1.0, border_color, f["bass"])

            # Draw text (fading out during transition)
            text_alpha = max(0, 1.0 - transition_progress * 2.5)
            if text_alpha > 0:
                tx = bx + 2 * BORDER_CW
                ty = by + 2 * BORDER_CH
                col_r = int(255 * text_alpha)
                box_draw.text((tx, ty), box.text, fill=(col_r, col_r, col_r), font=text_font)

        else:
            # Normal rendering
            draw_box_border(box_draw, bx, by, phase, progress, BLUE, f["bass"])

            # Track constructing boxes for welding glow
            if phase in ('corners', 'borders'):
                constructing_boxes.append((box, phase, progress))

            # Text (only during typing/done phases)
            if phase in ('typing', 'done'):
                if phase == 'typing':
                    text_elapsed = elapsed - CONSTRUCTION_DURATION - TEXT_DELAY
                    chars_visible = int(text_elapsed * TEXT_SPEED)
                    chars_visible = min(chars_visible, len(box.text))
                else:
                    chars_visible = len(box.text)

                draw_box_text(box_draw, bx, by, box.text, chars_visible,
                            cursor_on=(cursor_on and phase == 'typing'))

            # Micro-breathing for completed boxes (scale = subtle brightness var)
            if phase == 'done' and cursor_on:
                # Faint cursor at end, blinking
                tx = bx + 2 * BORDER_CW + len(box.text) * TEXT_CW
                ty = by + 2 * BORDER_CH
                # Dimmer gold cursor when done
                gold_dim = (int(GOLD[0] * 0.5), int(GOLD[1] * 0.5), int(GOLD[2] * 0.5))
                box_draw.text((tx, ty), "▮", fill=gold_dim, font=text_font)

    # Composite box layer onto canvas (maximum blend)
    box_arr = np.array(box_img, dtype=np.uint8)
    canvas = np.maximum(canvas, box_arr)

    # === LAYER 3.5: WELDING GLOW (construction hot point) ===
    for box, phase, progress in constructing_boxes:
        bx, by = box.x, box.y
        if phase == 'corners':
            corner_idx = int(progress * 4)
            corners = [
                (bx + 4, by + 4),
                (bx + BOX_PX_W - 6, by + 4),
                (bx + 4, by + BOX_PX_H - 6),
                (bx + BOX_PX_W - 6, by + BOX_PX_H - 6),
            ]
            if corner_idx < 4:
                hot_x, hot_y = corners[corner_idx]
                # LARGER glow — 30px radius for weight
                glow_r = 30
                for dy in range(-glow_r, glow_r + 1, 2):
                    for dx in range(-glow_r, glow_r + 1, 2):
                        dist = math.sqrt(dx*dx + dy*dy)
                        if dist < glow_r:
                            yy = int(hot_y + dy)
                            xx = int(hot_x + dx)
                            if 0 <= yy < VH and 0 <= xx < VW:
                                bri = (1.0 - dist / glow_r) ** 2 * 0.7
                                # White-hot center, blue at edges
                                if dist < glow_r * 0.3:
                                    # White hot
                                    canvas[yy, xx, 0] = min(255, int(canvas[yy, xx, 0] + 220 * bri))
                                    canvas[yy, xx, 1] = min(255, int(canvas[yy, xx, 1] + 230 * bri))
                                    canvas[yy, xx, 2] = min(255, int(canvas[yy, xx, 2] + 255 * bri))
                                else:
                                    # Blue glow
                                    canvas[yy, xx, 0] = min(255, int(canvas[yy, xx, 0] + BLUE[0] * bri * 0.6))
                                    canvas[yy, xx, 1] = min(255, int(canvas[yy, xx, 1] + BLUE[1] * bri * 0.6))
                                    canvas[yy, xx, 2] = min(255, int(canvas[yy, xx, 2] + BLUE[2] * bri * 0.8))
        else:
            # Border drawing — welding torch follows the edge
            edge_progress = progress
            if edge_progress < 0.25:
                frac = edge_progress / 0.25
                hot_x = bx + int(frac * BOX_PX_W)
                hot_y = by
            elif edge_progress < 0.5:
                frac = (edge_progress - 0.25) / 0.25
                hot_x = bx + BOX_PX_W
                hot_y = by + int(frac * BOX_PX_H)
            elif edge_progress < 0.75:
                frac = (edge_progress - 0.5) / 0.25
                hot_x = bx + BOX_PX_W - int(frac * BOX_PX_W)
                hot_y = by + BOX_PX_H
            else:
                frac = (edge_progress - 0.75) / 0.25
                hot_x = bx
                hot_y = by + BOX_PX_H - int(frac * BOX_PX_H)

            # LARGER welding glow — 25px radius
            glow_r = 25
            for dy in range(-glow_r, glow_r + 1, 2):
                for dx in range(-glow_r, glow_r + 1, 2):
                    dist = math.sqrt(dx*dx + dy*dy)
                    if dist < glow_r:
                        yy = int(hot_y + dy)
                        xx = int(hot_x + dx)
                        if 0 <= yy < VH and 0 <= xx < VW:
                            bri = (1.0 - dist / glow_r) ** 2.5 * 0.8
                            # White-hot core (inner 20%), blue outer
                            if dist < glow_r * 0.2:
                                canvas[yy, xx, 0] = min(255, int(canvas[yy, xx, 0] + 240 * bri))
                                canvas[yy, xx, 1] = min(255, int(canvas[yy, xx, 1] + 245 * bri))
                                canvas[yy, xx, 2] = min(255, int(canvas[yy, xx, 2] + 255 * bri))
                            else:
                                canvas[yy, xx, 0] = min(255, int(canvas[yy, xx, 0] + 100 * bri))
                                canvas[yy, xx, 1] = min(255, int(canvas[yy, xx, 1] + 120 * bri))
                                canvas[yy, xx, 2] = min(255, int(canvas[yy, xx, 2] + 255 * bri))

    # === LAYER 4: Sparks (hi-hat reactive) ===
    if f["hi"] > 0.2 or f["beat"] > 0.35:
        rng = np.random.RandomState(frame_idx)
        for box in BOXES:
            phase, progress, elapsed = box.get_state(t)
            if phase in ('corners', 'borders'):
                bx, by = box.x, box.y
                # Determine hot point for spark origin
                if phase == 'corners':
                    corners = [
                        (bx, by), (bx + BOX_PX_W, by),
                        (bx, by + BOX_PX_H), (bx + BOX_PX_W, by + BOX_PX_H)
                    ]
                    chosen = corners[min(int(progress * 4), 3)]
                else:
                    # Spark at current welding point
                    ep = progress
                    if ep < 0.25:
                        chosen = (bx + int(ep/0.25 * BOX_PX_W), by)
                    elif ep < 0.5:
                        chosen = (bx + BOX_PX_W, by + int((ep-0.25)/0.25 * BOX_PX_H))
                    elif ep < 0.75:
                        chosen = (bx + BOX_PX_W - int((ep-0.5)/0.25 * BOX_PX_W), by + BOX_PX_H)
                    else:
                        chosen = (bx, by + BOX_PX_H - int((ep-0.75)/0.25 * BOX_PX_H))

                spark_count = int(max(f["hi"], f["beat"]) * 8) + 2
                SPARKS.spawn(chosen[0], chosen[1], count=spark_count, rng=rng)

            elif phase == 'done' and f["beat"] > 0.5:
                # Occasional edge sparks on completed boxes
                bx, by = box.x, box.y
                edge_pos = rng.choice(['top', 'right', 'bottom', 'left'])
                if edge_pos == 'top':
                    sx, sy = bx + rng.randint(0, BOX_PX_W), by
                elif edge_pos == 'right':
                    sx, sy = bx + BOX_PX_W, by + rng.randint(0, BOX_PX_H)
                elif edge_pos == 'bottom':
                    sx, sy = bx + rng.randint(0, BOX_PX_W), by + BOX_PX_H
                else:
                    sx, sy = bx, by + rng.randint(0, BOX_PX_H)
                SPARKS.spawn(sx, sy, count=2, rng=rng)

    SPARKS.update(1.0 / FPS)
    SPARKS.render(canvas)

    # === LAYER 5: Bass brightness pulse (global) ===
    if f["bass"] > 0.3:
        pulse = 1.0 + f["bass"] * 0.05
        canvas = np.clip(canvas.astype(np.float32) * pulse, 0, 255).astype(np.uint8)

    # === LAYER 6: Kick drum frame flash ===
    if f["kick"] > 0.5:
        flash = 1.0 + f["kick"] * 0.07
        canvas = np.clip(canvas.astype(np.float32) * flash, 0, 255).astype(np.uint8)

    # === LAYER 7: Box landing brightness pulse ===
    for box in BOXES:
        if box.land_time is not None:
            elapsed_since_land = t - box.land_time
            if 0 < elapsed_since_land < 0.12:
                # Bright flash that decays — stone landing impact
                intensity = (1.0 - elapsed_since_land / 0.12) ** 3 * 0.08
                canvas = np.clip(canvas.astype(np.float32) * (1.0 + intensity), 0, 255).astype(np.uint8)

    # === LAYER 8: Transition glow at center ===
    if in_transition and transition_progress > 0.4:
        glow_str = (transition_progress - 0.4) * 1.67
        cy, cx = VH // 2, VW // 2
        yy = np.arange(VH)[:, None] - cy
        xx = np.arange(VW)[None, :] - cx
        dist = np.sqrt(yy**2 + xx**2)
        glow_radius = 100 * (1.0 - transition_progress * 0.6)
        glow = np.clip(1.0 - dist / max(glow_radius, 1), 0, 1) ** 2
        glow *= glow_str * 0.5

        canvas[:, :, 0] = np.clip(canvas[:, :, 0].astype(np.float32) + glow * GOLD[0], 0, 255).astype(np.uint8)
        canvas[:, :, 1] = np.clip(canvas[:, :, 1].astype(np.float32) + glow * GOLD[1], 0, 255).astype(np.uint8)
        canvas[:, :, 2] = np.clip(canvas[:, :, 2].astype(np.float32) + glow * GOLD[2], 0, 255).astype(np.uint8)

    return canvas


# === TONEMAP ===
def tonemap(canvas, gamma=0.75):
    """
    Adaptive tone mapping for a mostly-void scene.
    Preserves void while normalizing lit content.
    """
    f = canvas.astype(np.float32)
    nonzero_mask = f.max(axis=2) > 3
    if nonzero_mask.any():
        lit_pixels = f[nonzero_mask]
        lo = np.percentile(lit_pixels, 2)
        hi = np.percentile(lit_pixels, 98)
    else:
        lo, hi = 0, 255
    if hi - lo < 12:
        hi = lo + 12
    f = np.clip((f - lo) / (hi - lo), 0, 1)
    np.power(f, gamma, out=f)
    return (f * 255).astype(np.uint8)


# === RENDER PIPELINE ===
def render_preview():
    """Render key frame for QA."""
    print("Rendering preview frame...")

    global PARTICLES, SPARKS
    PARTICLES = ParticleField(n=100, seed=123)
    SPARKS = SparkSystem()

    # Render sequentially up to target (t=10.0: 3 boxes visible)
    target_frame = int(10.0 * FPS)
    for fi in range(target_frame):
        if fi == target_frame - 1:
            canvas = render_frame(fi)
            canvas = tonemap(canvas, gamma=0.75)
        else:
            # Advance state
            t = fi / FPS
            f_bass = float(FEATURES["bass"][min(fi, TOTAL_FRAMES-1)])
            PARTICLES.update(f_bass, t)
            SPARKS.update(1.0 / FPS)
            # Update box land_time state
            for box in BOXES:
                box.get_state(t)

    img = Image.fromarray(canvas, "RGB")
    img.save(CHECKPOINT_FRAME)
    print(f"  Preview saved: {CHECKPOINT_FRAME}")
    print(f"  Mean brightness: {canvas.astype(float).mean():.1f}")
    print(f"  Max pixel: {canvas.max()}")
    lit = (canvas.max(axis=2) > 5).mean() * 100
    print(f"  Lit pixels: {lit:.1f}%")


def render_clip():
    """Render full 18-second clip (no audio embedded)."""
    print(f"\nRendering {TOTAL_FRAMES} frames ({DURATION}s @ {FPS}fps)...")

    global PARTICLES, SPARKS
    PARTICLES = ParticleField(n=100, seed=123)
    SPARKS = SparkSystem()
    # Reset box state
    for box in BOXES:
        box.land_time = None

    stderr_path = os.path.join(OUTPUT_DIR, "ffmpeg_stderr.log")
    stderr_fh = open(stderr_path, "w")

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{VW}x{VH}", "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-pix_fmt", "yuv420p",
        OUTPUT_CLIP
    ]

    pipe = subprocess.Popen(
        cmd, stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=stderr_fh
    )

    start_time = time.time()

    for fi in range(TOTAL_FRAMES):
        canvas = render_frame(fi)
        canvas = tonemap(canvas, gamma=0.75)
        pipe.stdin.write(canvas.tobytes())

        if fi % 48 == 0:
            elapsed = time.time() - start_time
            fps_actual = (fi + 1) / max(elapsed, 0.01)
            print(f"  Frame {fi}/{TOTAL_FRAMES} ({fi/FPS:.1f}s) — {fps_actual:.1f} fps")

    pipe.stdin.close()
    pipe.wait()
    stderr_fh.close()

    elapsed = time.time() - start_time
    print(f"\nRender complete: {elapsed:.1f}s ({TOTAL_FRAMES/max(elapsed,0.01):.1f} fps)")

    if os.path.exists(OUTPUT_CLIP):
        size = os.path.getsize(OUTPUT_CLIP)
        print(f"Output: {OUTPUT_CLIP} ({size/1024/1024:.2f} MB)")
    else:
        print("ERROR: Output file not created!")
        sys.exit(1)

    return elapsed


if __name__ == "__main__":
    render_preview()
    render_time = render_clip()

    print(f"\n{'='*50}")
    print(f"Scene 02 — Task Creation — COMPLETE")
    print(f"  Output: {OUTPUT_CLIP}")
    print(f"  Preview: {CHECKPOINT_FRAME}")
    print(f"  Duration: {DURATION}s")
    print(f"  Resolution: {VW}x{VH} @ {FPS}fps")
    print(f"  Render time: {render_time:.1f}s")
    print(f"{'='*50}")
