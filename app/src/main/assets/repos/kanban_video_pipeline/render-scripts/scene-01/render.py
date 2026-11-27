#!/usr/bin/env python3
"""
Scene 1: Title Card — "Stillness Before Creation"
Time: 0:00–0:12 | Renderer: ASCII | Energy: Atmospheric intro

The void. A cursor blinks. "HERMES KANBAN" types itself into existence,
then ignites from white to gold. Ambient particles drift in navy darkness.
Restraint is the point — 95% of frame is black, but what IS there glows.

Pipeline: INPUT → ANALYZE → SCENE_FN → TONEMAP → SHADE → ENCODE
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
DURATION = 12.0
TOTAL_FRAMES = int(DURATION * FPS)

# Paths
WORKDIR = "/home/daimon/projects/video-pipeline/kanban-launch-video"
AUDIO_PATH = os.path.join(WORKDIR, "audio/Doomscroll.mp3")
OUTPUT_DIR = os.path.join(WORKDIR, "scenes/scene-01")
OUTPUT_CLIP = os.path.join(OUTPUT_DIR, "clip.mp4")
CHECKPOINT_DIR = os.path.join(WORKDIR, "checkpoints")
CHECKPOINT_FRAME = os.path.join(CHECKPOINT_DIR, "scene-01-frame-001.png")

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Brand colors
GOLD = np.array([245, 184, 32], dtype=np.float32)
DARK_AMBER = np.array([196, 122, 26], dtype=np.float32)
NAVY = np.array([0, 0, 128], dtype=np.float32)
WHITE = np.array([255, 255, 255], dtype=np.float32)

# Font setup
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_PATH_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


# === AUDIO ANALYSIS ===
def extract_audio_features():
    """Extract FFT features for the first 12+ seconds."""
    wav_path = "/tmp/doomscroll_scene01.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", AUDIO_PATH,
        "-t", "13", "-ar", "22050", "-ac", "1", "-f", "wav", wav_path
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
    }
    
    hop = sr // FPS
    window_size = 2048
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
    
    # Normalize
    for key in features:
        mx = features[key].max()
        if mx > 0:
            features[key] /= mx
    
    # Beat detection
    rms_diff = np.diff(features["rms"], prepend=0)
    features["beat"] = np.clip(rms_diff * 5, 0, 1)
    
    os.remove(wav_path)
    return features


print("Extracting audio features...")
FEATURES = extract_audio_features()
print(f"  RMS range: {FEATURES['rms'].min():.3f} - {FEATURES['rms'].max():.3f}")


# === TITLE TEXT SETUP ===
TITLE_TEXT = "HERMES KANBAN"
TITLE_FONT_SIZE = 72
title_font = ImageFont.truetype(FONT_PATH, TITLE_FONT_SIZE)

# Pre-calculate title geometry
_tmp_img = Image.new("L", (VW, VH), 0)
_tmp_draw = ImageDraw.Draw(_tmp_img)
_bbox = _tmp_draw.textbbox((0, 0), TITLE_TEXT, font=title_font)
TITLE_W = _bbox[2] - _bbox[0]
TITLE_H = _bbox[3] - _bbox[1]
TITLE_X = (VW - TITLE_W) // 2
TITLE_Y = int(VH * 0.38) - TITLE_H // 2  # Golden ratio positioning

# Per-character X positions
CHAR_X = []
_x = TITLE_X
for ch in TITLE_TEXT:
    CHAR_X.append(_x)
    _bb = title_font.getbbox(ch)
    _x += _bb[2] - _bb[0]

# Title mask for glow (pre-rendered at full resolution)
_title_img = Image.new("L", (VW, VH), 0)
_title_draw = ImageDraw.Draw(_title_img)
_title_draw.text((TITLE_X, TITLE_Y), TITLE_TEXT, fill=255, font=title_font)
TITLE_MASK = np.array(_title_img, dtype=np.float32) / 255.0
# Pre-compute blurred glow mask
TITLE_GLOW = gaussian_filter(TITLE_MASK, sigma=15)
TITLE_GLOW = np.clip(TITLE_GLOW * 4, 0, 0.5)


# === PARTICLE SYSTEM ===
class ParticleField:
    """Navy atmospheric particles with Brownian drift."""
    def __init__(self, n=120, seed=42):
        rng = np.random.RandomState(seed)
        self.x = rng.uniform(0, VW, n).astype(np.float32)
        self.y = rng.uniform(0, VH, n).astype(np.float32)
        self.bri = rng.uniform(0.15, 0.45, n).astype(np.float32)
        self.size = rng.choice([1, 2, 2, 3], n)  # pixel sizes
        self.n = n
        self.rng = rng
    
    def update(self, bass_level=0.0):
        """Drift upward at ~2px/sec with brownian jitter."""
        self.y -= 2.0 / FPS + self.rng.uniform(-0.2, 0.2, self.n)
        self.x += self.rng.uniform(-0.3, 0.3, self.n)
        
        # Wrap particles that drift off top
        reset = self.y < -5
        self.y[reset] = VH + self.rng.uniform(5, 30, reset.sum())
        self.x[reset] = self.rng.uniform(0, VW, reset.sum())
        
        # Bass makes brightness pulse
        self.bass_boost = bass_level * 0.4
    
    def render(self, canvas):
        """Draw particles as navy dots."""
        for i in range(self.n):
            px = int(self.x[i]) % VW
            py = int(self.y[i]) % VH
            bri = min(0.6, self.bri[i] + self.bass_boost)
            size = self.size[i]
            
            # Color: navy with slight variation
            r = int(bri * 5)
            g = int(bri * 8)
            b = int(bri * 160)
            
            for dy in range(size):
                for dx in range(size):
                    yy = py + dy
                    xx = px + dx
                    if 0 <= yy < VH and 0 <= xx < VW:
                        # Additive blend
                        canvas[yy, xx, 0] = min(255, canvas[yy, xx, 0] + r)
                        canvas[yy, xx, 1] = min(255, canvas[yy, xx, 1] + g)
                        canvas[yy, xx, 2] = min(255, canvas[yy, xx, 2] + b)
        return canvas


PARTICLES = ParticleField(n=100, seed=42)


# === BACKGROUND TEXTURE GRID ===
# Small grid for subtle sine field background
bg_font = ImageFont.truetype(FONT_PATH_REG, 10)
asc, desc = bg_font.getmetrics()
BG_CW = bg_font.getbbox("M")[2]
BG_CH = asc + desc
BG_COLS = VW // BG_CW
BG_ROWS = VH // BG_CH
BG_OX = (VW - BG_COLS * BG_CW) // 2
BG_OY = (VH - BG_ROWS * BG_CH) // 2

# Pre-rasterize the dot character for background
_dot_img = Image.new("L", (BG_CW, BG_CH), 0)
ImageDraw.Draw(_dot_img).text((0, 0), "·", fill=255, font=bg_font)
BG_DOT_BM = np.array(_dot_img, dtype=np.float32) / 255.0

# Grid coordinate arrays
BG_RR = np.arange(BG_ROWS, dtype=np.float32)[:, None]
BG_CC = np.arange(BG_COLS, dtype=np.float32)[None, :]


# === SHATTER FRAGMENTS ===
class ShatterSystem:
    def __init__(self):
        self.fragments = None
    
    def init_fragments(self):
        """Create fragment particles from each title character."""
        self.fragments = []
        rng = np.random.RandomState(777)
        for i, ch in enumerate(TITLE_TEXT):
            if ch == " ":
                continue
            cx = CHAR_X[i] + 25
            cy = TITLE_Y + TITLE_H // 2
            n_frags = rng.randint(4, 7)
            for _ in range(n_frags):
                angle = rng.uniform(0, 2 * math.pi)
                speed = rng.uniform(150, 500)
                self.fragments.append({
                    'x': float(cx), 'y': float(cy),
                    'vx': math.cos(angle) * speed,
                    'vy': math.sin(angle) * speed - 50,  # slight upward bias
                    'size': rng.randint(2, 5),
                    'life': 1.0,
                })
    
    def update(self, dt, progress):
        """Update fragment positions and life."""
        if self.fragments is None:
            return
        for f in self.fragments:
            f['x'] += f['vx'] * dt * (0.5 + progress * 0.5)
            f['y'] += f['vy'] * dt * (0.5 + progress * 0.5)
            f['vy'] += 30 * dt  # slight gravity
            f['life'] = max(0, 1.0 - progress * 0.7)
    
    def render(self, canvas):
        """Draw fragments as gold pixel blocks."""
        if self.fragments is None:
            return canvas
        for frag in self.fragments:
            if frag['life'] <= 0:
                continue
            px = int(frag['x'])
            py = int(frag['y'])
            size = frag['size']
            bri = frag['life']
            
            r = int(GOLD[0] * bri)
            g = int(GOLD[1] * bri)
            b = int(GOLD[2] * bri)
            
            for dy in range(size):
                for dx in range(size):
                    yy = py + dy
                    xx = px + dx
                    if 0 <= yy < VH and 0 <= xx < VW:
                        canvas[yy, xx] = np.maximum(
                            canvas[yy, xx],
                            np.array([r, g, b], dtype=np.uint8)
                        )
        return canvas


SHATTER = ShatterSystem()


# === SCENE FUNCTION ===
def render_frame(frame_idx):
    """
    Render a single frame of Scene 1.
    
    Timeline:
    0:00-0:03: Pure void + blinking cursor + particles fade in
    0:03-0:06: Text types in white
    0:06-0:08: Characters ignite to gold (L→R cascade, 150ms each)
    0:08-0:11.5: Full gold, breathing glow, audio-reactive particles
    0:11.5-0:12: Text shatters, fragments scatter
    """
    t = frame_idx / FPS
    f = {k: float(FEATURES[k][min(frame_idx, TOTAL_FRAMES-1)]) for k in FEATURES}
    
    canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
    
    # === LAYER 1: Atmospheric particle field ===
    # Particles fade in over first 2 seconds
    particle_alpha = min(1.0, t / 2.0)
    if particle_alpha > 0:
        PARTICLES.update(f["bass"])
        if particle_alpha < 1.0:
            # Render to temp and blend
            temp = np.zeros_like(canvas)
            PARTICLES.render(temp)
            canvas = (temp.astype(np.float32) * particle_alpha).astype(np.uint8)
        else:
            PARTICLES.render(canvas)
    
    # === LAYER 2: Subtle sine field background (INTENSITY 1-2) ===
    # Only after 1.5s, very subtle navy texture
    if t > 1.5:
        bg_fade = min(1.0, (t - 1.5) / 2.5)
        # Layered sine for organic feel
        v1 = np.sin(BG_CC * 0.08 + t * 0.15) * np.sin(BG_RR * 0.12 - t * 0.1)
        v2 = np.sin(BG_CC * 0.05 - t * 0.08 + BG_RR * 0.06) * 0.5
        val = np.clip((v1 * 0.5 + v2 * 0.5) * 0.5 + 0.5, 0, 1)
        val = val * 0.08 * bg_fade * (0.4 + f["rms"] * 0.6)
        
        # Render as navy dots (only where val > threshold)
        threshold = 0.02
        mask = val > threshold
        
        # Vectorized render of background dots
        rows_with_dots, cols_with_dots = np.where(mask)
        for idx in range(len(rows_with_dots)):
            row = rows_with_dots[idx]
            col = cols_with_dots[idx]
            y = BG_OY + row * BG_CH
            x = BG_OX + col * BG_CW
            if y + BG_CH > VH or x + BG_CW > VW:
                continue
            v = val[row, col]
            # Navy blue color
            b_val = int(v * 200)
            region = canvas[y:y+BG_CH, x:x+BG_CW]
            dot_contrib = BG_DOT_BM * b_val
            # Only blue channel for navy
            new_b = np.maximum(region[:, :, 2], dot_contrib.astype(np.uint8))
            canvas[y:y+BG_CH, x:x+BG_CW, 2] = new_b
    
    # === LAYER 3: Title text ===
    # Timeline parameters
    TYPING_START = 3.0
    CHARS_PER_SEC = 4.0
    IGNITE_START = 6.0
    IGNITE_PER_CHAR = 0.15  # 150ms per char cascade
    BREATHING_START = 8.0
    SHATTER_START = 11.5
    
    # How many chars typed so far
    chars_typed = 0
    if t >= TYPING_START:
        chars_typed = min(len(TITLE_TEXT), int((t - TYPING_START) * CHARS_PER_SEC))
    
    # Cursor blink: 530ms on / 530ms off
    cursor_period_ms = 1060
    cursor_on = (int(t * 1000) % cursor_period_ms) < 530
    
    # Render title via PIL
    title_img = Image.new("RGB", (VW, VH), (0, 0, 0))
    title_draw = ImageDraw.Draw(title_img)
    
    # Breathing oscillation for gold phase
    if t >= BREATHING_START:
        breath = 0.85 + 0.15 * math.sin((t - BREATHING_START) * math.pi)
    else:
        breath = 1.0
    
    # Shatter fade factor
    shatter_fade = 1.0
    if t >= SHATTER_START:
        shatter_progress = (t - SHATTER_START) / (DURATION - SHATTER_START)
        shatter_fade = max(0, 1.0 - shatter_progress * 1.5)
    
    for i in range(chars_typed):
        ch = TITLE_TEXT[i]
        if ch == " ":
            continue
        
        x = CHAR_X[i]
        
        # Determine color based on timeline
        char_ignite_time = IGNITE_START + i * IGNITE_PER_CHAR
        
        if t < char_ignite_time:
            # White phase
            color = (255, 255, 255)
        elif t < char_ignite_time + 0.15:
            # Igniting: white → gold transition
            progress = (t - char_ignite_time) / 0.15
            r = int(255 + (GOLD[0] - 255) * progress)
            g = int(255 + (GOLD[1] - 255) * progress)
            b = int(255 + (GOLD[2] - 255) * progress)
            color = (max(0, r), max(0, g), max(0, b))
        else:
            # Gold phase with breathing
            r = int(GOLD[0] * breath * shatter_fade)
            g = int(GOLD[1] * breath * shatter_fade)
            b = int(GOLD[2] * breath * shatter_fade)
            color = (r, g, b)
        
        title_draw.text((x, TITLE_Y), ch, fill=color, font=title_font)
    
    # Cursor
    if cursor_on:
        if chars_typed < len(TITLE_TEXT) and t >= TYPING_START:
            cursor_x = CHAR_X[chars_typed]
        elif t < TYPING_START:
            cursor_x = CHAR_X[0]
        else:
            cursor_x = None
        
        if cursor_x is not None and (t < SHATTER_START):
            title_draw.text((cursor_x, TITLE_Y), "▮", fill=(255, 255, 255), font=title_font)
    
    # Composite title onto canvas (maximum blend)
    title_arr = np.array(title_img, dtype=np.uint8)
    canvas = np.maximum(canvas, title_arr)
    
    # === LAYER 4: Gold glow halo ===
    # Appears after ignition begins, pulses with breath
    if t > IGNITE_START + 0.5:
        glow_intensity = min(1.0, (t - IGNITE_START - 0.5) / 2.0)
        glow_intensity *= breath * shatter_fade
        
        # Apply pre-computed glow mask
        glow_strength = glow_intensity * 0.25
        glow_r = np.clip(TITLE_GLOW * GOLD[0] * glow_strength, 0, 255).astype(np.uint8)
        glow_g = np.clip(TITLE_GLOW * GOLD[1] * glow_strength, 0, 255).astype(np.uint8)
        glow_b = np.clip(TITLE_GLOW * GOLD[2] * glow_strength, 0, 255).astype(np.uint8)
        
        # Additive blend
        canvas[:, :, 0] = np.maximum(canvas[:, :, 0], glow_r)
        canvas[:, :, 1] = np.maximum(canvas[:, :, 1], glow_g)
        canvas[:, :, 2] = np.maximum(canvas[:, :, 2], glow_b)
    
    # === LAYER 5: Shatter fragments ===
    if t >= SHATTER_START:
        if SHATTER.fragments is None:
            SHATTER.init_fragments()
        progress = (t - SHATTER_START) / (DURATION - SHATTER_START)
        SHATTER.update(1.0 / FPS, progress)
        SHATTER.render(canvas)
    
    # === GLOBAL: Bass brightness pulse ===
    if f["beat"] > 0.3 or f["bass"] > 0.5:
        pulse = 1.0 + min(f["beat"], f["bass"]) * 0.05
        canvas = np.clip(canvas.astype(np.float32) * pulse, 0, 255).astype(np.uint8)
    
    # === GLOBAL: Hi-hat micro-particle spawns ===
    if f["hi"] > 0.4 and t > 1.0:
        rng = np.random.RandomState(frame_idx)
        n_sparks = int(f["hi"] * 3)
        for _ in range(n_sparks):
            sx = rng.randint(0, VW - 1)
            sy = rng.randint(0, VH - 1)
            # White dot that's barely visible
            bri = int(f["hi"] * 80)
            canvas[sy, sx] = np.maximum(
                canvas[sy, sx],
                np.array([bri, bri, bri], dtype=np.uint8)
            )
    
    return canvas


# === TONEMAP ===
def tonemap(canvas, gamma=0.80):
    """Adaptive tone mapping for this dark scene."""
    f = canvas.astype(np.float32)
    sub = f[::4, ::4]
    lo = np.percentile(sub, 1)
    hi = np.percentile(sub, 99.5)
    if hi - lo < 10:
        hi = lo + 10
    # For this mostly-void scene, we want minimal tonemapping
    # Just gamma to lift the glow slightly without crushing the void
    f = np.clip((f - lo) / (hi - lo), 0, 1)
    np.power(f, gamma, out=f)
    return (f * 255).astype(np.uint8)


# === RENDER PIPELINE ===
def render_preview():
    """Render key frames for QA."""
    print("Rendering preview frames...")
    
    # Reset state
    global PARTICLES, SHATTER
    PARTICLES = ParticleField(n=100, seed=42)
    SHATTER = ShatterSystem()
    
    # Need to advance particles to the preview timestamp
    target_frame = int(7.0 * FPS)  # t=7.0 — gold ignition complete
    for fi in range(target_frame):
        PARTICLES.update(float(FEATURES["bass"][fi]))
    
    canvas = render_frame(target_frame)
    canvas = tonemap(canvas, gamma=0.80)
    
    img = Image.fromarray(canvas, "RGB")
    img.save(CHECKPOINT_FRAME)
    print(f"  Preview saved: {CHECKPOINT_FRAME}")
    print(f"  Mean brightness: {canvas.astype(float).mean():.1f}")
    print(f"  Max: {canvas.max()}")


def render_clip():
    """Render full 12-second clip."""
    print(f"\nRendering {TOTAL_FRAMES} frames ({DURATION}s @ {FPS}fps)...")
    
    # Reset state
    global PARTICLES, SHATTER
    PARTICLES = ParticleField(n=100, seed=42)
    SHATTER = ShatterSystem()
    
    stderr_path = os.path.join(OUTPUT_DIR, "ffmpeg_stderr.log")
    stderr_fh = open(stderr_path, "w")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{VW}x{VH}", "-r", str(FPS),
        "-i", "pipe:0",
        "-i", AUDIO_PATH,
        "-t", str(DURATION),
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        OUTPUT_CLIP
    ]
    
    pipe = subprocess.Popen(
        cmd, stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=stderr_fh
    )
    
    start_time = time.time()
    
    for fi in range(TOTAL_FRAMES):
        canvas = render_frame(fi)
        canvas = tonemap(canvas, gamma=0.80)
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
    print(f"Scene 01 — Title Card — COMPLETE")
    print(f"  Output: {OUTPUT_CLIP}")
    print(f"  Preview: {CHECKPOINT_FRAME}")
    print(f"  Duration: {DURATION}s")
    print(f"  Resolution: {VW}x{VH} @ {FPS}fps")
    print(f"  Render time: {render_time:.1f}s")
    print(f"{'='*50}")
