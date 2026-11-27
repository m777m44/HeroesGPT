#!/usr/bin/env python3
"""
Scene 6: Pipeline Completion — Triumph and Gold Flood
TIME: 1:24 - 1:42 (18 seconds)
RENDERER: ASCII video (audio-reactive)

VISUAL CONCEPT:
- Tasks fly LEFT→RIGHT at high speed, flip blue→gold at midframe threshold
- Each completion triggers a gold BURST explosion + feeds the rain system
- Stack builds on right: ✓ research, ✓ implement, ✓ review, ✓ deploy, ✓ test
- At 1:36: 4-FRAME BLACK PAUSE. Pure void. The inhale before the slam.
- At 1:37: DONE SLAMS — all chars simultaneous, screen shake, massive pixel blocks
- Behind DONE: DENSE gold character rain flooding the frame (matrix gold, NOT green)
- By end: 40-50% visible pixels are gold. GOLD IS WINNING.

AUDIO: Doomscroll.mp3, 1:24-1:42 — PEAK ENERGY section
"""

import os
import sys
import math
import time
import wave
import tempfile
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.fft import rfft, rfftfreq
from scipy import signal

# ─── CONSTANTS ───────────────────────────────────────────────────────────────
VW, VH = 1920, 1080
FPS = 24
DURATION = 18.0
TOTAL_FRAMES = int(DURATION * FPS)  # 432 frames
SCENE_START = 84.0  # 1:24 in seconds
SCENE_END = 102.0   # 1:42 in seconds

# Brand colors
GOLD = np.array([245, 184, 32], dtype=np.float32)
DARK_AMBER = np.array([196, 122, 26], dtype=np.float32)
BLUE = np.array([34, 34, 255], dtype=np.float32)
NAVY = np.array([0, 0, 128], dtype=np.float32)
WHITE = np.array([255, 255, 255], dtype=np.float32)
BLACK = np.array([0, 0, 0], dtype=np.float32)

# Paths
WORKDIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(WORKDIR))
AUDIO_PATH = os.path.join(PROJECT_DIR, "audio", "Doomscroll.mp3")
OUTPUT_PATH = os.path.join(WORKDIR, "clip.mp4")
CHECKPOINT_DIR = os.path.join(PROJECT_DIR, "checkpoints")
os.makedirs(WORKDIR, exist_ok=True)
os.makedirs(CHECKPOINT_DIR, exist_ok=True)

# Fonts
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


# ─── GRID SYSTEM ─────────────────────────────────────────────────────────────
class GridLayer:
    """Rasterizes character grids to pixel canvases via bitmap cache."""
    
    def __init__(self, font_path, font_size, char_set=None):
        self.font = ImageFont.truetype(font_path, font_size)
        asc, desc = self.font.getmetrics()
        bbox = self.font.getbbox("M")
        self.cw = bbox[2] - bbox[0]
        self.ch = asc + desc
        self.cols = VW // self.cw
        self.rows = VH // self.ch
        self.ox = (VW - self.cols * self.cw) // 2
        self.oy = (VH - self.rows * self.ch) // 2
        
        # Precompute coordinate arrays
        self.rr = np.arange(self.rows, dtype=np.float32)[:, None]
        self.cc = np.arange(self.cols, dtype=np.float32)[None, :]
        
        # Pre-rasterize characters
        all_chars = set("██▓▒░▉▊▋▌▍·∙.˙ᐧ ✓DONE")
        all_chars.update("researchimplementreviewdeploytest")
        all_chars.update("┌─┐│└─┘▮▌▍@#%&*=+:;,")
        if char_set:
            all_chars.update(char_set)
        all_chars.discard(" ")
        self.bm = {}
        for c in all_chars:
            img = Image.new("L", (self.cw, self.ch), 0)
            d = ImageDraw.Draw(img)
            d.text((0, 0), c, fill=255, font=self.font)
            arr = np.array(img, dtype=np.float32) / 255.0
            if arr.max() > 0.01:  # Only cache chars that actually render
                self.bm[c] = arr
    
    def render(self, chars, colors, canvas=None):
        """Render character grid onto pixel canvas using np.maximum compositing."""
        if canvas is None:
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        for row in range(self.rows):
            y = self.oy + row * self.ch
            if y + self.ch > VH:
                break
            for col in range(self.cols):
                c = chars[row, col]
                if c == " " or c not in self.bm:
                    continue
                x = self.ox + col * self.cw
                if x + self.cw > VW:
                    break
                a = self.bm[c]
                region = canvas[y:y+self.ch, x:x+self.cw]
                colored = (a[:, :, None] * colors[row, col]).astype(np.uint8)
                np.maximum(region, colored, out=region)
        return canvas
    
    def render_text_at_px(self, text, px, py, color, canvas):
        """Render a string at pixel coordinates directly onto canvas."""
        for i, ch in enumerate(text):
            if ch == " " or ch not in self.bm:
                px += self.cw
                continue
            x = int(px + i * self.cw)
            y = int(py)
            if 0 <= x < VW - self.cw and 0 <= y < VH - self.ch:
                a = self.bm[ch]
                region = canvas[y:y+self.ch, x:x+self.cw]
                colored = (a[:, :, None] * color).astype(np.uint8)
                np.maximum(region, colored, out=region)
        return canvas


# ─── AUDIO ANALYSIS ──────────────────────────────────────────────────────────
def analyze_audio():
    """Extract audio features for scene's time range."""
    print("Analyzing audio...", flush=True)
    tmp = tempfile.mktemp(suffix=".wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", AUDIO_PATH,
        "-ss", str(SCENE_START - 0.5), "-t", str(DURATION + 1.0),
        "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", tmp
    ], capture_output=True, check=True)
    
    with wave.open(tmp) as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    os.unlink(tmp)
    
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    
    hop = sr // FPS
    win = hop * 2
    window = np.hanning(win)
    freqs = rfftfreq(win, 1.0 / sr)
    
    bands = {
        "sub":   (freqs >= 20)  & (freqs < 80),
        "bass":  (freqs >= 80)  & (freqs < 250),
        "lomid": (freqs >= 250) & (freqs < 500),
        "mid":   (freqs >= 500) & (freqs < 2000),
        "himid": (freqs >= 2000) & (freqs < 6000),
        "hi":    (freqs >= 6000),
    }
    
    offset_samples = int(0.5 * sr)
    n_frames = TOTAL_FRAMES + 12
    
    features = {k: np.zeros(n_frames) for k in 
                ["rms", "sub", "bass", "lomid", "mid", "himid", "hi", "flux", "beat", "bdecay"]}
    prev_mag = None
    
    for fi in range(n_frames):
        start_idx = offset_samples + fi * hop
        end_idx = start_idx + win
        if end_idx > len(samples):
            break
        
        chunk = samples[start_idx:end_idx] * window
        features["rms"][fi] = np.sqrt(np.mean(chunk**2))
        
        spec = np.abs(rfft(chunk))
        for band_name, band_mask in bands.items():
            features[band_name][fi] = np.sqrt(np.mean(spec[band_mask]**2)) if band_mask.any() else 0
        
        if prev_mag is not None:
            features["flux"][fi] = np.sum(np.maximum(0, spec - prev_mag))
        prev_mag = spec.copy()
    
    # Beat detection
    flux = features["flux"][:TOTAL_FRAMES]
    flux_smooth = np.convolve(flux, np.ones(5)/5, mode="same")
    if flux_smooth.max() > 0:
        peaks, _ = signal.find_peaks(flux_smooth, height=flux_smooth.max() * 0.25,
                                     distance=FPS//4, prominence=flux_smooth.max() * 0.08)
    else:
        peaks = []
    
    beat = np.zeros(TOTAL_FRAMES)
    bdecay = np.zeros(TOTAL_FRAMES, dtype=np.float32)
    for p in peaks:
        if p < TOTAL_FRAMES:
            beat[p] = 1.0
            for d in range(FPS // 2):
                if p + d < TOTAL_FRAMES:
                    bdecay[p + d] = max(bdecay[p + d], math.exp(-d * 3.0 / (FPS // 2)))
    
    features["beat"] = beat
    features["bdecay"] = bdecay
    
    # Normalize
    for k in features:
        a = features[k][:TOTAL_FRAMES]
        lo, hi = a.min(), a.max()
        if hi - lo > 1e-10:
            features[k] = (a - lo) / (hi - lo)
        else:
            features[k] = np.zeros(TOTAL_FRAMES)
    
    # EMA smoothing
    def ema(arr, alpha):
        out = np.empty_like(arr)
        out[0] = arr[0]
        for i in range(1, len(arr)):
            out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
        return out
    
    for k in ["sub", "bass", "lomid", "mid", "himid", "hi", "rms"]:
        features[k] = ema(features[k], 0.35)
    features["flux"] = ema(features["flux"], 0.3)
    
    print(f"  Beats detected: {int(features['beat'].sum())}", flush=True)
    return features


# ─── PIXEL-BLOCK DONE TEXT ───────────────────────────────────────────────────
def create_done_bitmap():
    """Create DONE in MASSIVE pixel-block characters (60% frame width).
    
    Renders at max font size then scales up to fill 60% of frame width.
    The blocky pixelation creates that chunky 8-bit pixel-font feel.
    """
    target_width = int(VW * 0.60)  # 1152px
    
    # Render at largest possible font size
    fsize = 200
    font = ImageFont.truetype(FONT_PATH, fsize)
    bbox = font.getbbox("DONE")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    pad = 10
    img = Image.new("L", (tw + pad*2, th + pad*2), 0)
    draw = ImageDraw.Draw(img)
    draw.text((pad, pad), "DONE", fill=255, font=font)
    
    # First: downsample to a coarse grid to create pixel-block effect
    raw_w = tw + pad*2
    raw_h = th + pad*2
    block_size = 4  # pixels per block in the intermediate
    small_w = max(1, raw_w // block_size)
    small_h = max(1, raw_h // block_size)
    small = Image.fromarray(np.array(img)).resize((small_w, small_h), Image.BILINEAR)
    
    # Now scale UP to target 60% frame width (maintaining aspect ratio)
    scale_factor = target_width / raw_w
    final_w = target_width
    final_h = int(raw_h * scale_factor)
    
    # Scale the small version up with NEAREST for blocky pixels
    blocky = np.array(small.resize((final_w, final_h), Image.NEAREST))
    
    # Threshold to make it crisp (remove antialiasing artifacts)
    blocky = np.where(blocky > 80, 255, 0).astype(np.uint8)
    
    return blocky.astype(np.float32) / 255.0, final_w, final_h


# ─── GOLD RAIN SYSTEM ────────────────────────────────────────────────────────
class GoldRain:
    """Dense matrix-style gold character rain with persistent trails."""
    
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.grid = np.zeros((rows, cols), dtype=np.float32)
        self.rng = np.random.RandomState(42)
        # Store drop state as arrays for efficiency
        self.drop_col = np.zeros(0, dtype=np.int32)
        self.drop_head = np.zeros(0, dtype=np.float32)
        self.drop_speed = np.zeros(0, dtype=np.float32)
        self.drop_length = np.zeros(0, dtype=np.int32)
        self.drop_bri = np.zeros(0, dtype=np.float32)
    
    def spawn(self, n, intensity=1.0, from_top=True, y_range=None):
        """Spawn n new rain drops."""
        if n <= 0:
            return
        cols = self.rng.randint(0, self.cols, size=n)
        speeds = self.rng.uniform(0.4, 2.0, size=n) * intensity
        lengths = self.rng.randint(5, 20, size=n)
        bris = self.rng.uniform(0.4, 1.0, size=n) * intensity
        
        if from_top:
            heads = -self.rng.randint(0, 8, size=n).astype(np.float32)
        elif y_range:
            heads = self.rng.uniform(y_range[0], y_range[1], size=n).astype(np.float32)
        else:
            heads = self.rng.uniform(0, self.rows * 0.5, size=n).astype(np.float32)
        
        self.drop_col = np.concatenate([self.drop_col, cols])
        self.drop_head = np.concatenate([self.drop_head, heads])
        self.drop_speed = np.concatenate([self.drop_speed, speeds])
        self.drop_length = np.concatenate([self.drop_length, lengths])
        self.drop_bri = np.concatenate([self.drop_bri, bris])
    
    def update(self):
        """Advance all drops and paint trails."""
        # Decay existing grid (slower fade = more persistent gold)
        self.grid *= 0.93
        
        if len(self.drop_col) == 0:
            return
        
        # Advance heads
        self.drop_head += self.drop_speed
        
        # Paint trails efficiently
        for i in range(len(self.drop_col)):
            col = self.drop_col[i]
            head = int(self.drop_head[i])
            length = self.drop_length[i]
            bri = self.drop_bri[i]
            
            for j in range(length):
                row = head - j
                if 0 <= row < self.rows:
                    trail_bri = bri * (1.0 - j / length)
                    if trail_bri > self.grid[row, col]:
                        self.grid[row, col] = trail_bri
        
        # Prune dead drops (head - length past bottom)
        alive = (self.drop_head.astype(int) - self.drop_length) < self.rows
        self.drop_col = self.drop_col[alive]
        self.drop_head = self.drop_head[alive]
        self.drop_speed = self.drop_speed[alive]
        self.drop_length = self.drop_length[alive]
        self.drop_bri = self.drop_bri[alive]


# ─── TASK CASCADE SYSTEM ─────────────────────────────────────────────────────
TASKS = ["research", "implement", "review", "deploy", "test"]

class TaskCard:
    """A task card that flies LEFT→RIGHT at high speed, flips blue→gold."""
    
    def __init__(self, name, launch_frame, y_pos, speed=380):
        self.name = name
        self.launch_frame = launch_frame
        self.speed = speed  # pixels per second
        self.y = y_pos
        self.start_x = 80.0      # Visible from the start — enters ON screen
        self.flip_x = VW * 0.48   # blue→gold flip threshold
        self.land_x = VW * 0.72   # where it stacks
        self.complete_frame = None
        self.burst_active = False
    
    def get_state(self, frame):
        """Returns (x, progress 0-1, is_gold, is_landed)"""
        if frame < self.launch_frame:
            return self.start_x, -1.0, False, False  # -1 = not launched yet
        
        elapsed = (frame - self.launch_frame) / FPS
        # Ease-out motion: fast start, decelerates at landing
        t_total = (self.land_x - self.start_x) / self.speed
        progress = min(1.0, elapsed / t_total)
        # Cubic ease-out
        p = 1.0 - (1.0 - progress) ** 3
        x = self.start_x + (self.land_x - self.start_x) * p
        
        is_gold = x >= self.flip_x
        is_landed = progress >= 0.98
        
        if is_landed and self.complete_frame is None:
            self.complete_frame = frame
            self.burst_active = True
        
        # Bounce on landing
        if is_landed and self.complete_frame is not None:
            bounce_t = (frame - self.complete_frame) / FPS
            bounce = math.exp(-bounce_t * 12) * math.sin(bounce_t * 25) * 4
            return self.land_x + bounce, 1.0, True, True
        
        return x, progress, is_gold, False


# ─── FEEDBACK BUFFER ─────────────────────────────────────────────────────────
class FeedbackBuffer:
    """Stores previous frame with decay for afterglow trails."""
    
    def __init__(self):
        self.buf = None
    
    def apply(self, canvas, decay=0.75, opacity=0.3):
        """Blend previous frame (decayed) into current via screen mode."""
        if self.buf is None:
            self.buf = canvas.astype(np.float32) / 255.0
            return canvas
        
        self.buf *= decay
        
        # Screen blend: 1 - (1-a)*(1-b)
        cf = canvas.astype(np.float32) / 255.0
        bf = self.buf
        result = 1.0 - (1.0 - cf) * (1.0 - bf * opacity)
        
        # Update buffer with current frame
        self.buf = cf.copy()
        
        return np.clip(result * 255, 0, 255).astype(np.uint8)


# ─── TONEMAP ─────────────────────────────────────────────────────────────────
def tonemap(canvas, gamma=0.72):
    """Adaptive percentile tone-mapping."""
    f = canvas.astype(np.float32)
    sub = f[::4, ::4]
    lo = np.percentile(sub, 1)
    hi = np.percentile(sub, 99.5)
    if hi - lo < 10:
        hi = lo + 10
    f = np.clip((f - lo) / (hi - lo), 0.0, 1.0)
    np.power(f, gamma, out=f)
    np.multiply(f, 248, out=f)
    np.add(f, 4, out=f)
    return np.clip(f, 0, 255).astype(np.uint8)


# ─── SCENE RENDER ────────────────────────────────────────────────────────────
def render_scene(features, preview_only=False):
    """Render the full Scene 6 clip."""
    start_time = time.time()
    
    # Initialize grids
    print("Initializing grids...", flush=True)
    grid_fg = GridLayer(FONT_PATH, 18)     # Foreground tasks/text
    grid_rain = GridLayer(FONT_REGULAR, 11) # Rain (denser)
    grid_glow = GridLayer(FONT_PATH, 14)   # Gold field overlay
    
    print(f"  fg grid:   {grid_fg.cols}x{grid_fg.rows}", flush=True)
    print(f"  rain grid: {grid_rain.cols}x{grid_rain.rows}", flush=True)
    print(f"  glow grid: {grid_glow.cols}x{grid_glow.rows}", flush=True)
    
    # Create DONE bitmap
    done_bitmap, done_w, done_h = create_done_bitmap()
    print(f"  DONE bitmap: {done_w}x{done_h}", flush=True)
    
    # Gold rain system — pre-seed with a few drops so frame 0 isn't empty
    rain = GoldRain(grid_rain.cols, grid_rain.rows)
    rain.spawn(30, intensity=0.5, from_top=True)  # Pre-seed
    for _ in range(8):  # Advance a few frames to create initial trails
        rain.update()
        rain.spawn(5, intensity=0.4, from_top=True)
    
    # Feedback buffer for afterglow
    feedback = FeedbackBuffer()
    
    # Schedule task launches synced to beats
    beat_frames = np.where(features["beat"] > 0.5)[0]
    print(f"  Beat frames: {beat_frames[:15]}", flush=True)
    
    # Create task cards
    task_cards = []
    # First task launches at frame 0 (synced to 1:23.90 peak)
    # Subsequent tasks launch on beats, staggered ~200ms apart minimum
    launch_frames = [0]
    beat_idx = 0
    for i in range(1, len(TASKS)):
        # Find next beat at least 5 frames (200ms) after previous launch
        min_frame = launch_frames[-1] + 5
        while beat_idx < len(beat_frames) and beat_frames[beat_idx] < min_frame:
            beat_idx += 1
        if beat_idx < len(beat_frames):
            launch_frames.append(beat_frames[beat_idx])
            beat_idx += 1
        else:
            launch_frames.append(launch_frames[-1] + int(FPS * 0.8))
    
    # All tasks must complete well before the black pause
    for i, name in enumerate(TASKS):
        y_pos = VH * 0.18 + i * (VH * 0.14)
        speed = 400 + i * 25  # Acceleration
        card = TaskCard(name, launch_frames[i], y_pos, speed)
        task_cards.append(card)
    
    print(f"  Task launches: {launch_frames}", flush=True)
    
    # Key timing frames
    BLACK_PAUSE_START = int(12.0 * FPS)   # frame 288 (~1:36)
    BLACK_PAUSE_END = BLACK_PAUSE_START + 4
    DONE_REVEAL = BLACK_PAUSE_END          # frame 292
    TRANSITION_START = TOTAL_FRAMES - int(3.0 * FPS)  # frame 360
    
    print(f"  Black pause: frames {BLACK_PAUSE_START}-{BLACK_PAUSE_END}")
    print(f"  DONE reveal: frame {DONE_REVEAL}")
    print(f"  Transition out: frame {TRANSITION_START}")
    
    # ─── FFMPEG PIPE ─────────────────────────────────────────────────────────
    if preview_only:
        # Render key frames for preview
        frames_to_render = [
            0, 12, 24, 48,                    # Cascade start
            BLACK_PAUSE_START - 2,            # Pre-pause (max cascade)
            DONE_REVEAL,                       # DONE slam
            DONE_REVEAL + 24,                 # Post-DONE (rain flooding)
            TOTAL_FRAMES - 1                  # End
        ]
    else:
        frames_to_render = range(TOTAL_FRAMES)
        # Set up ffmpeg — write to temp file first to avoid corrupt output
        tmp_output = OUTPUT_PATH + ".tmp.mp4"
        stderr_log = open(os.path.join(WORKDIR, "ffmpeg_stderr.log"), "w")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{VW}x{VH}", "-r", str(FPS),
            "-i", "pipe:0",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-pix_fmt", "yuv420p",
            tmp_output
        ]
        pipe = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=stderr_log)
    
    # ─── FRAME LOOP ──────────────────────────────────────────────────────────
    frame_count = 0
    for fi in frames_to_render:
        t = fi / FPS
        f = {k: float(features[k][min(fi, TOTAL_FRAMES - 1)]) for k in features}
        
        # ═══ THE 4-FRAME BLACK PAUSE ═══
        if BLACK_PAUSE_START <= fi < BLACK_PAUSE_END:
            canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
            if not preview_only:
                pipe.stdin.write(canvas.tobytes())
            frame_count += 1
            continue
        
        # ═══ LAYER 1: BACKGROUND VOID TEXTURE (rain grid) ═══
        canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
        
        # Dynamic background: scattered navy particles that pulse with bass
        bg_intensity = 0.04 + f["bass"] * 0.12 + f["sub"] * 0.08
        bg_chars = np.full((grid_rain.rows, grid_rain.cols), " ", dtype="U1")
        bg_rng = np.random.RandomState(fi // 4 + 7777)
        bg_noise = bg_rng.random((grid_rain.rows, grid_rain.cols))
        bg_mask = bg_noise < bg_intensity
        # Use varied chars for texture
        bg_char_options = "·∙.·∙"
        bg_char_idx = bg_rng.randint(0, len(bg_char_options), (grid_rain.rows, grid_rain.cols))
        for i, ch in enumerate(bg_char_options):
            m = bg_mask & (bg_char_idx == i)
            bg_chars[m] = ch
        
        bg_colors = np.zeros((grid_rain.rows, grid_rain.cols, 3), dtype=np.float32)
        # Navy blue with slight gold tinge as scene progresses
        scene_progress = fi / TOTAL_FRAMES
        bg_r = 0 + scene_progress * 15
        bg_g = 0 + scene_progress * 8
        bg_b = 50 + f["bass"] * 80
        bg_colors[bg_mask] = [bg_r, bg_g, bg_b]
        canvas = grid_rain.render(bg_chars, bg_colors.astype(np.uint8), canvas)
        
        # ═══ LAYER 2: GOLD RAIN (starts immediately, intensifies) ═══
        # Rain starts sparse at the beginning and ramps with completions
        completed_count = sum(1 for c in task_cards if c.complete_frame is not None and fi >= c.complete_frame)
        rain_intensity = min(1.0, 0.30 + completed_count * 0.10 + scene_progress * 0.45)
        
        # After DONE: MASSIVE rain flood
        if fi >= DONE_REVEAL:
            done_elapsed = (fi - DONE_REVEAL) / FPS
            rain_intensity = min(1.0, 0.80 + done_elapsed * 0.05)
        
        # Spawn rain driven by audio — always spawning even at start for atmosphere
        base_spawn = int(8 + rain_intensity * 18)
        hi_spawn = int(f["hi"] * 30 * rain_intensity)
        beat_spawn = int(f["bdecay"] * 25 * rain_intensity)
        total_spawn = base_spawn + hi_spawn + beat_spawn
        
        # After DONE, spawn from all over (not just top)
        if fi >= DONE_REVEAL:
            rain.spawn(total_spawn * 2, intensity=rain_intensity, from_top=True)
            rain.spawn(int(total_spawn * 0.8), intensity=rain_intensity * 0.8, 
                      from_top=False, y_range=(0, grid_rain.rows * 0.6))
        else:
            rain.spawn(total_spawn, intensity=rain_intensity, from_top=True)
        
        rain.update()
        
        # Render rain layer
        rain_mask = rain.grid > 0.04
        if rain_mask.any():
            rain_chars = np.full((grid_rain.rows, grid_rain.cols), " ", dtype="U1")
            rain_pal = "·∙░▒▓█"
            n_pal = len(rain_pal)
            rain_idx = np.clip((rain.grid * (n_pal - 0.01)).astype(int), 0, n_pal - 1)
            for i, ch in enumerate(rain_pal):
                m = rain_mask & (rain_idx == i)
                rain_chars[m] = ch
            
            # Color gradient: gold at top → dark amber middle → navy at bottom
            rain_colors = np.zeros((grid_rain.rows, grid_rain.cols, 3), dtype=np.float32)
            row_frac = np.broadcast_to(
                grid_rain.rr / grid_rain.rows, (grid_rain.rows, grid_rain.cols)
            ).copy()
            
            # Top: pure gold, Middle: dark amber, Bottom: navy-gold mix
            r = GOLD[0] * (1 - row_frac * 0.6) + DARK_AMBER[0] * row_frac * 0.4
            g = GOLD[1] * (1 - row_frac * 0.7) + DARK_AMBER[1] * row_frac * 0.3
            b = GOLD[2] * (1 - row_frac * 0.5) + NAVY[2] * row_frac * 0.3
            
            # Modulate by brightness
            bri = np.clip(rain.grid, 0, 1)
            rain_colors[:, :, 0] = r * bri * rain_mask
            rain_colors[:, :, 1] = g * bri * rain_mask
            rain_colors[:, :, 2] = b * bri * rain_mask
            
            canvas = grid_rain.render(rain_chars, rain_colors.astype(np.uint8), canvas)
        
        # ═══ LAYER 3: DENSE GOLD FIELD (after DONE — gold floods the frame) ═══
        if fi >= DONE_REVEAL:
            done_elapsed = (fi - DONE_REVEAL) / FPS
            # Gold density ramps rapidly: 20% at reveal, up to 55% by end
            gold_density = min(0.55, 0.20 + done_elapsed * 0.07 + f["bass"] * 0.08)
            
            gold_rng = np.random.RandomState(fi * 13 + 31)
            gold_mask = gold_rng.random((grid_glow.rows, grid_glow.cols)) < gold_density
            
            gold_chars = np.full((grid_glow.rows, grid_glow.cols), " ", dtype="U1")
            gold_pal = "░▒▓█▉▊▋"
            
            # Density distribution: heavier toward center and top
            center_x = np.broadcast_to(
                np.abs(grid_glow.cc / grid_glow.cols - 0.5), 
                (grid_glow.rows, grid_glow.cols)
            )
            top_bias = np.broadcast_to(
                1.0 - grid_glow.rr / grid_glow.rows * 0.4,
                (grid_glow.rows, grid_glow.cols)
            )
            char_weight = (top_bias - center_x * 0.3 + 
                          gold_rng.uniform(-0.1, 0.1, (grid_glow.rows, grid_glow.cols)))
            char_idx = np.clip((char_weight * len(gold_pal)).astype(int), 0, len(gold_pal) - 1)
            
            for i, ch in enumerate(gold_pal):
                m = gold_mask & (char_idx == i)
                gold_chars[m] = ch
            
            # Shimmer effect
            shimmer = (np.sin(np.broadcast_to(
                grid_glow.cc, (grid_glow.rows, grid_glow.cols)) * 0.4 + fi * 0.25) * 0.12 + 0.88)
            row_frac_g = np.broadcast_to(
                grid_glow.rr / grid_glow.rows, (grid_glow.rows, grid_glow.cols)
            ).copy()
            
            bri_field = shimmer * (1.0 - row_frac_g * 0.35)
            gold_colors = np.zeros((grid_glow.rows, grid_glow.cols, 3), dtype=np.float32)
            gold_colors[:, :, 0] = GOLD[0] * bri_field * gold_mask
            gold_colors[:, :, 1] = GOLD[1] * bri_field * gold_mask * (1 - row_frac_g * 0.25)
            gold_colors[:, :, 2] = GOLD[2] * bri_field * gold_mask * (1 - row_frac_g * 0.5)
            
            canvas = grid_glow.render(gold_chars, gold_colors.astype(np.uint8), canvas)
        
        # ═══ LAYER 4: TASK CASCADE (before black pause) ═══
        if fi < BLACK_PAUSE_START:
            for card in task_cards:
                x, progress, is_gold, is_landed = card.get_state(fi)
                
                if progress < 0:
                    continue
                
                # Build label
                label = f"✓ {card.name}" if is_landed else f"  {card.name}"
                
                # Color: sharp blue→gold flip
                if is_gold:
                    # Transition zone at flip point
                    if x < card.flip_x + 50:
                        blend = min(1.0, (x - card.flip_x) / 50.0)
                        color = BLUE * (1 - blend) + GOLD * blend
                    else:
                        color = GOLD.copy()
                else:
                    color = BLUE.copy()
                
                # Render the task label
                py = card.y - grid_fg.ch / 2
                grid_fg.render_text_at_px(label, x, py, color, canvas)
                
                # Motion trail behind flying cards
                if not is_landed and progress > 0.05:
                    trail_len = 8
                    for ti in range(trail_len):
                        trail_x = x - (ti + 1) * grid_fg.cw * 1.2
                        trail_bri = 0.5 * (1 - ti / trail_len) ** 1.5
                        trail_char = "▓" if ti < 2 else "▒" if ti < 4 else "░"
                        if trail_char in grid_fg.bm and trail_x > 0:
                            a = grid_fg.bm[trail_char]
                            tx = int(trail_x)
                            ty = int(py)
                            if 0 <= tx < VW - grid_fg.cw and 0 <= ty < VH - grid_fg.ch:
                                region = canvas[ty:ty+grid_fg.ch, tx:tx+grid_fg.cw]
                                tc = (color * trail_bri).astype(np.uint8)
                                colored = (a[:, :, None] * tc.astype(np.float32)).astype(np.uint8)
                                np.maximum(region, colored, out=region)
                
                # GOLD BURST on landing — BIG radial explosion
                if card.burst_active and card.complete_frame is not None:
                    burst_age = fi - card.complete_frame
                    if burst_age < 12:
                        burst_r = int(5 + burst_age * 3)
                        burst_bri = 1.0 - burst_age / 12.0
                        # Inject burst energy into rain grid around landing position
                        center_col = int(card.land_x / (VW / grid_rain.cols))
                        center_row = int(card.y / (VH / grid_rain.rows))
                        for dr in range(-burst_r, burst_r + 1):
                            for dc in range(-burst_r * 2, burst_r * 2 + 1):
                                rr = center_row + dr
                                cc = center_col + dc
                                if 0 <= rr < grid_rain.rows and 0 <= cc < grid_rain.cols:
                                    dist = math.sqrt(dr*dr + (dc*0.5)**2)
                                    if dist < burst_r:
                                        bval = burst_bri * (1 - dist/burst_r) * 0.95
                                        rain.grid[rr, cc] = max(rain.grid[rr, cc], bval)
                        # Also spawn extra rain drops from burst area
                        if burst_age < 4:
                            rain.spawn(15, intensity=burst_bri, from_top=False,
                                      y_range=(max(0, center_row - burst_r), 
                                              min(grid_rain.rows, center_row + burst_r)))
                    else:
                        card.burst_active = False
        
        # ═══ LAYER 5: COMPLETION STACK (right side) ═══
        completed_tasks = [(c.name, c.complete_frame) for c in task_cards 
                          if c.complete_frame is not None and fi >= c.complete_frame]
        
        if completed_tasks and fi < BLACK_PAUSE_START + 10:
            stack_x = VW * 0.76
            for idx, (name, _) in enumerate(completed_tasks):
                stack_y = VH * 0.20 + idx * (grid_fg.ch * 2.5)
                label = f"✓ {name}"
                # Slight glow pulse with bass
                bri = 0.85 + f["bass"] * 0.15
                color = GOLD * bri
                grid_fg.render_text_at_px(label, stack_x, stack_y, color, canvas)
        
        # ═══ LAYER 6: "DONE" REVEAL (after black pause) ═══
        if fi >= DONE_REVEAL:
            done_age = fi - DONE_REVEAL
            
            # Screen shake for first 4 frames
            shake_x, shake_y = 0, 0
            if done_age < 4:
                shake_rng = np.random.RandomState(fi * 37)
                shake_x = shake_rng.randint(-4, 5)
                shake_y = shake_rng.randint(-4, 5)
            
            # DONE brightness: SLAM flash, then breathe with bass
            if done_age < 3:
                done_bri = 1.4  # initial overexpose flash
            elif done_age < 8:
                done_bri = 1.1 - (done_age - 3) * 0.04
            else:
                done_bri = 0.85 + f["bass"] * 0.2 + f["sub"] * 0.12
            
            # Scale pulse: 1.0 → 1.06 with kick drum
            scale = 1.0 + f["bdecay"] * 0.06
            
            scaled_w = int(done_w * scale)
            scaled_h = int(done_h * scale)
            bm_resized = np.array(Image.fromarray(
                (done_bitmap * 255).astype(np.uint8)
            ).resize((scaled_w, scaled_h), Image.NEAREST)).astype(np.float32) / 255.0
            
            dx = (VW - scaled_w) // 2 + shake_x
            dy = (VH - scaled_h) // 2 + shake_y - 20  # Slightly above center
            
            # Clip to canvas bounds
            src_x0 = max(0, -dx)
            src_y0 = max(0, -dy)
            dst_x0 = max(0, dx)
            dst_y0 = max(0, dy)
            w = min(scaled_w - src_x0, VW - dst_x0)
            h = min(scaled_h - src_y0, VH - dst_y0)
            
            if w > 0 and h > 0:
                bm_slice = bm_resized[src_y0:src_y0+h, src_x0:src_x0+w]
                done_color = np.array([
                    min(255, GOLD[0] * done_bri),
                    min(255, GOLD[1] * done_bri),
                    min(255, GOLD[2] * done_bri)
                ], dtype=np.float32)
                
                region = canvas[dst_y0:dst_y0+h, dst_x0:dst_x0+w]
                overlay = (bm_slice[:, :, None] * done_color).astype(np.uint8)
                np.maximum(region, overlay, out=region)
        
        # ═══ FRAME-WIDE BEAT BRIGHTNESS PULSE ═══
        if f["bdecay"] > 0.5:
            flash = (f["bdecay"] - 0.5) * 0.12
            canvas = np.clip(canvas.astype(np.float32) * (1.0 + flash), 0, 255).astype(np.uint8)
        
        # ═══ AMBIENT GOLD GLOW FLOOR ═══
        if fi >= DONE_REVEAL:
            glow_strength = 0.05 + (fi - DONE_REVEAL) / TOTAL_FRAMES * 0.03
        else:
            glow_strength = scene_progress * 0.025
        
        if glow_strength > 0.005:
            dark_mask = canvas.max(axis=2) < 4
            if dark_mask.any():
                gold_glow = np.array([
                    int(GOLD[0] * glow_strength * 0.4),
                    int(GOLD[1] * glow_strength * 0.25),
                    int(GOLD[2] * glow_strength * 0.08)
                ], dtype=np.uint8)
                canvas[dark_mask] = gold_glow
        
        # ═══ FEEDBACK BUFFER (afterglow trails) ═══
        if fi > 2 and fi not in range(BLACK_PAUSE_START, BLACK_PAUSE_END):
            decay = 0.65 if fi < DONE_REVEAL else 0.72
            canvas = feedback.apply(canvas, decay=decay, opacity=0.25)
        
        # ═══ TONEMAP ═══
        # More aggressive gamma lift for this peak-energy scene
        gamma = 0.65 if fi >= DONE_REVEAL else 0.70
        canvas = tonemap(canvas, gamma=gamma)
        
        # ═══ TRANSITION OUT (last 3 seconds) ═══
        if fi >= TRANSITION_START:
            fade_progress = (fi - TRANSITION_START) / (3.0 * FPS)
            # Slow fade + rain deceleration
            fade_factor = 1.0 - fade_progress * 0.35
            canvas = (canvas.astype(np.float32) * fade_factor).astype(np.uint8)
        
        # ═══ OUTPUT ═══
        if preview_only:
            if frame_count == 0:
                img = Image.fromarray(canvas)
                path = os.path.join(CHECKPOINT_DIR, "scene-06-frame-001.png")
                img.save(path)
                print(f"  Preview saved: {path}", flush=True)
            elif fi == BLACK_PAUSE_START - 2:
                img = Image.fromarray(canvas)
                path = os.path.join(CHECKPOINT_DIR, "scene-06-frame-pre-pause.png")
                img.save(path)
                print(f"  Pre-pause saved: {path}", flush=True)
            elif fi == DONE_REVEAL:
                img = Image.fromarray(canvas)
                path = os.path.join(CHECKPOINT_DIR, "scene-06-done-reveal.png")
                img.save(path)
                print(f"  DONE reveal saved: {path}", flush=True)
            elif fi == DONE_REVEAL + 24:
                img = Image.fromarray(canvas)
                path = os.path.join(CHECKPOINT_DIR, "scene-06-frame-post-done.png")
                img.save(path)
                print(f"  Post-DONE saved: {path}", flush=True)
        else:
            pipe.stdin.write(canvas.tobytes())
        
        frame_count += 1
        if not preview_only and frame_count % 48 == 0:
            elapsed = time.time() - start_time
            fps_actual = frame_count / elapsed
            pct = frame_count / TOTAL_FRAMES * 100
            print(f"  Frame {frame_count}/{TOTAL_FRAMES} ({pct:.0f}%) [{fps_actual:.1f} fps]", flush=True)
    
    if not preview_only:
        pipe.stdin.close()
        retcode = pipe.wait()
        stderr_log.close()
        if retcode != 0:
            print(f"ERROR: ffmpeg exited with code {retcode}", flush=True)
            with open(os.path.join(WORKDIR, "ffmpeg_stderr.log")) as f:
                print(f.read()[-2000:], flush=True)
            sys.exit(1)
        # Verify temp output and move to final location
        if not os.path.exists(tmp_output) or os.path.getsize(tmp_output) < 10000:
            print("ERROR: output file missing or too small", flush=True)
            sys.exit(1)
        # Move tmp to final
        import shutil
        shutil.move(tmp_output, OUTPUT_PATH)
        elapsed = time.time() - start_time
        print(f"\nRender complete: {elapsed:.1f}s ({TOTAL_FRAMES / elapsed:.1f} fps)", flush=True)
        print(f"Output: {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1024 / 1024:.1f} MB)", flush=True)
    
    return time.time() - start_time


# ─── MAIN ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("SCENE 6: Pipeline Completion — Triumph and Gold Flood")
    print("=" * 60)
    print(f"Resolution: {VW}x{VH} @ {FPS}fps")
    print(f"Duration: {DURATION}s ({TOTAL_FRAMES} frames)")
    print(f"Audio: {AUDIO_PATH}")
    print(f"Output: {OUTPUT_PATH}")
    print()
    
    # Analyze audio
    features = analyze_audio()
    
    # Render preview first
    print("\nRendering preview frames...", flush=True)
    render_scene(features, preview_only=True)
    
    # Full render
    print("\nRendering full clip...", flush=True)
    render_time = render_scene(features, preview_only=False)
    
    print(f"\n{'=' * 60}")
    print(f"DONE. Render time: {render_time:.1f}s")
    print(f"Output: {OUTPUT_PATH}")
    print(f"{'=' * 60}")
