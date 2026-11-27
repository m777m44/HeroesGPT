#!/usr/bin/env python3
"""
Scene 7: Logo Reveal — Convergence and Dispersal
Time: 1:42 - 2:00 (18 seconds)
The breath after. Characters converge to the Nous badge like iron filings
to a magnet. Then dispersal. Form to void. The parenthesis closes.
"""

import os
import sys
import time
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile
from scipy.signal import butter, sosfilt
from scipy.ndimage import binary_erosion, gaussian_filter

# ─── Config ──────────────────────────────────────────────────────────────────
VW, VH = 1920, 1080
FPS = 24
DURATION = 18.0
TOTAL_FRAMES = int(DURATION * FPS)  # 432

# Audio time range
AUDIO_START = 102.0  # 1:42
AUDIO_END = 120.0    # 2:00

# Brand colors
GOLD = np.array([245, 184, 32], dtype=np.uint8)
DARK_AMBER = np.array([196, 122, 26], dtype=np.uint8)
WHITE = np.array([220, 220, 220], dtype=np.uint8)
BLACK = np.array([0, 0, 0], dtype=np.uint8)

# Paths
WORKDIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(WORKDIR))
AUDIO_PATH = os.path.join(PROJECT_ROOT, "audio", "Doomscroll.mp3")
OUTPUT_PATH = os.path.join(WORKDIR, "clip.mp4")
CHECKPOINT_PATH = os.path.join(PROJECT_ROOT, "checkpoints", "scene-07-frame-001.png")

# Fonts
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_PATH_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# Character palettes
PAL_BADGE_BORDER = "██▓█▓██▓"
PAL_BADGE_FILL = "▓▒@#%&*+▒▓"
PAL_PARTICLE_LIGHT = "·∙˙.·"
PAL_ATMOSPHERE = "·∙."


# ─── Audio Analysis ──────────────────────────────────────────────────────────

def extract_audio_features():
    """Extract FFT features from the audio for our time range."""
    wav_path = "/tmp/scene07_audio.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", AUDIO_PATH,
        "-ss", str(AUDIO_START), "-t", str(DURATION),
        "-ar", "22050", "-ac", "1", wav_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    sr, data = wavfile.read(wav_path)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / max(1, np.abs(data).max())
    
    hop = sr // FPS
    features = {
        "bass": np.zeros(TOTAL_FRAMES),
        "mid": np.zeros(TOTAL_FRAMES),
        "hi": np.zeros(TOTAL_FRAMES),
        "energy": np.zeros(TOTAL_FRAMES),
    }
    
    # Bandpass filters
    sos_bass = butter(4, [60, 200], btype='band', fs=sr, output='sos')
    sos_mid = butter(4, [200, 2000], btype='band', fs=sr, output='sos')
    sos_hi = butter(4, [6000, min(10000, sr//2 - 1)], btype='band', fs=sr, output='sos')
    
    bass_signal = sosfilt(sos_bass, data)
    mid_signal = sosfilt(sos_mid, data)
    hi_signal = sosfilt(sos_hi, data)
    
    for i in range(TOTAL_FRAMES):
        start = i * hop
        end = min(start + hop, len(data))
        if start >= len(data):
            break
        chunk = end - start
        if chunk == 0:
            break
        features["bass"][i] = np.sqrt(np.mean(bass_signal[start:end]**2))
        features["mid"][i] = np.sqrt(np.mean(mid_signal[start:end]**2))
        features["hi"][i] = np.sqrt(np.mean(hi_signal[start:end]**2))
        features["energy"][i] = np.sqrt(np.mean(data[start:end]**2))
    
    # Normalize
    for k in features:
        mx = features[k].max()
        if mx > 0:
            features[k] /= mx
    
    return features


# ─── Grid System ─────────────────────────────────────────────────────────────

class GridLayer:
    def __init__(self, font_path, font_size):
        self.font = ImageFont.truetype(font_path, font_size)
        asc, desc = self.font.getmetrics()
        bbox = self.font.getbbox("M")
        self.cw = bbox[2] - bbox[0]
        self.ch = asc + desc
        self.cols = VW // self.cw
        self.rows = VH // self.ch
        self.ox = (VW - self.cols * self.cw) // 2
        self.oy = (VH - self.rows * self.ch) // 2
        
        # Pre-rasterize characters
        self.bm = {}
        chars_to_render = set("██▓▒░@#%&*=+:;,.·∙˙ᐧ─│┌┐└┘✧✦")
        chars_to_render.update("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789./:")
        chars_to_render.update("ΩΔΣΠΘψφλ∞⊕⊗")
        chars_to_render.discard(" ")
        
        for c in chars_to_render:
            img = Image.new("L", (self.cw, self.ch), 0)
            ImageDraw.Draw(img).text((0, 0), c, fill=255, font=self.font)
            arr = np.array(img, dtype=np.float32) / 255.0
            if arr.max() > 0:
                self.bm[c] = arr
    
    def render(self, chars, colors, canvas=None):
        """Render character grid to pixel canvas using np.maximum blending."""
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
                a = self.bm[c]  # float32 (ch, cw)
                color = colors[row, col]  # (3,) uint8
                region = canvas[y:y+self.ch, x:x+self.cw]
                colored = (a[:, :, None] * color.astype(np.float32)).astype(np.uint8)
                np.maximum(region, colored, out=region)
        return canvas


# ─── Badge Shape ─────────────────────────────────────────────────────────────

def create_badge_shape(rows, cols):
    """Create the Nous badge as a tall rounded rectangle.
    Compensates for non-square character cells (cell_w != cell_h).
    Returns: badge_mask, border_mask, inner_mask, bounds, nous_text_positions"""
    
    # Cell aspect ratio compensation
    # Cells are ~10px wide, ~19px tall. A 'circle' in grid coords is an ellipse in pixels.
    # To get proper 0.72 W:H pixel ratio, we need cell-corrected dimensions.
    cell_aspect = 10.0 / 19.0  # cw/ch ≈ 0.526
    
    # Badge fills 65% of grid height
    badge_h = int(rows * 0.65)
    # Width in cells to achieve 0.72 pixel aspect ratio
    # pixel_w / pixel_h = 0.72 → (badge_w * cw) / (badge_h * ch) = 0.72
    # badge_w = badge_h * 0.72 / cell_aspect
    badge_w = int(badge_h * 0.72 / cell_aspect)
    
    # Cap width
    if badge_w > int(cols * 0.55):
        badge_w = int(cols * 0.55)
        badge_h = int(badge_w * cell_aspect / 0.72)
    
    cx, cy = cols // 2, rows // 2
    x0 = cx - badge_w // 2
    x1 = cx + badge_w // 2
    y0 = cy - badge_h // 2
    y1 = cy + badge_h // 2
    corner_r = max(3, badge_w // 8)  # radius in cell units (wide cells)
    
    # Vectorized rounded rectangle
    rr = np.arange(rows)[:, None]
    cc = np.arange(cols)[None, :]
    
    # Base rectangle
    in_rect = ((rr >= y0) & (rr <= y1) & (cc >= x0) & (cc <= x1))
    mask = in_rect.astype(np.float32)
    
    # Carve out corners (aspect-corrected: corners appear circular in pixel space)
    # In grid space, horizontal distance is scaled by cell_aspect to appear circular
    corner_r_h = corner_r  # horizontal radius in cells
    corner_r_v = int(corner_r * cell_aspect)  # vertical radius (fewer cells because cells are tall)
    
    corners = [
        (y0 + corner_r_v, x0 + corner_r_h),  # TL center
        (y0 + corner_r_v, x1 - corner_r_h),  # TR center
        (y1 - corner_r_v, x0 + corner_r_h),  # BL center
        (y1 - corner_r_v, x1 - corner_r_h),  # BR center
    ]
    corner_regions = [
        (y0, y0 + corner_r_v, x0, x0 + corner_r_h),
        (y0, y0 + corner_r_v, x1 - corner_r_h, x1),
        (y1 - corner_r_v, y1, x0, x0 + corner_r_h),
        (y1 - corner_r_v, y1, x1 - corner_r_h, x1),
    ]
    
    for (cr, cc_c), (r_lo, r_hi, c_lo, c_hi) in zip(corners, corner_regions):
        in_region = (rr >= r_lo) & (rr <= r_hi) & (cc >= c_lo) & (cc <= c_hi)
        # Aspect-corrected distance: normalize to make circle appear round in pixel space
        dr = (rr - cr).astype(np.float32) / max(corner_r_v, 1)
        dc = (cc - cc_c).astype(np.float32) / max(corner_r_h, 1)
        dist = np.sqrt(dr**2 + dc**2)
        outside = in_region & (dist > 1.0)
        mask[outside] = 0.0
    
    # Border: erode mask to get inner, subtract
    struct = np.ones((5, 5))
    inner_mask = binary_erosion(mask > 0.5, structure=struct).astype(np.float32)
    border_mask = np.clip(mask - inner_mask, 0, 1)
    
    # "NOUS" text positions in upper ~20% of badge
    # Create large block-letter NOUS using multiple cells per letter
    # Each letter is ~5 cells wide, 5 cells tall
    NOUS_LETTERS = {
        'N': [
            "█  █",
            "██ █",
            "█▓██",
            "█ ██",
            "█  █",
        ],
        'O': [
            " ██ ",
            "█  █",
            "█  █",
            "█  █",
            " ██ ",
        ],
        'U': [
            "█  █",
            "█  █",
            "█  █",
            "█  █",
            " ██ ",
        ],
        'S': [
            " ███",
            "█   ",
            " ██ ",
            "   █",
            "███ ",
        ],
    }
    
    text_row_start = y0 + 3  # 3 cells from top of badge
    letter_spacing = 1
    total_letter_w = 4 * 4 + 3 * letter_spacing  # 4 letters * 4 wide + 3 gaps
    text_col_start = cx - total_letter_w // 2
    
    nous_positions = []
    col_cursor = text_col_start
    for letter in "NOUS":
        pattern = NOUS_LETTERS[letter]
        for dr, row_str in enumerate(pattern):
            for dc, ch in enumerate(row_str):
                if ch != " ":
                    r = text_row_start + dr
                    c = col_cursor + dc
                    if 0 <= r < rows and 0 <= c < cols:
                        nous_positions.append((r, c, ch))
                        # Mark in border mask for priority rendering
                        border_mask[r, c] = 1.0
                        inner_mask[r, c] = 0.0
        col_cursor += len(pattern[0]) + letter_spacing
    
    # Create a 1-cell gap around NOUS text (clear zone for readability)
    for r, c, _ in nous_positions:
        # Mark surrounding cells as neither border nor fill (empty gap)
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    if (nr, nc) not in set((rr, cc) for rr, cc, _ in nous_positions):
                        inner_mask[nr, nc] = 0.0
                        # Don't remove from border mask (border should still be there)
    
    bounds = (x0, y0, x1, y1, cx, cy, badge_w, badge_h)
    return mask, border_mask, inner_mask, bounds, nous_positions


# ─── Particle System ─────────────────────────────────────────────────────────

def create_particle_arrays(grid_rows, grid_cols, badge_mask, border_mask, inner_mask, bounds, nous_positions, n=400):
    """Create vectorized particle arrays for performance."""
    x0, y0, x1, y1, cx, cy, bw, bh = bounds
    
    # Gather target positions
    border_pos = np.argwhere(border_mask > 0.5)  # (N, 2) — row, col
    inner_pos = np.argwhere(inner_mask > 0.5)
    
    # Create set of NOUS positions for fast lookup
    nous_set = set((r, c) for r, c, _ in nous_positions)
    nous_char_map = {(r, c): ch for r, c, ch in nous_positions}
    
    # Allocate particles: NOUS cells + border + fill
    n_nous = len(nous_positions)
    n_border = min(len(border_pos), n // 3)
    n_fill = min(len(inner_pos), n - n_border - n_nous)
    total = n_nous + n_border + n_fill
    
    # Arrays
    px = np.zeros(total, dtype=np.float64)  # current x (col)
    py = np.zeros(total, dtype=np.float64)  # current y (row)
    tx = np.zeros(total, dtype=np.float64)  # target x
    ty = np.zeros(total, dtype=np.float64)  # target y
    angle_offset = np.random.uniform(0, 2*np.pi, total)
    orbit_radius = np.zeros(total, dtype=np.float64)
    fade = np.ones(total, dtype=np.float64)
    alive = np.ones(total, dtype=bool)
    is_border = np.zeros(total, dtype=bool)
    
    # Character and color indices
    chars = np.empty(total, dtype="U1")
    color_r = np.zeros(total, dtype=np.uint8)
    color_g = np.zeros(total, dtype=np.uint8)
    color_b = np.zeros(total, dtype=np.uint8)
    
    # === NOUS letter particles (highest priority, brightest) ===
    for i, (tr, tc, ch) in enumerate(nous_positions):
        ty[i] = tr
        tx[i] = tc
        is_border[i] = True
        chars[i] = ch  # Use the block letter character
        # Full bright gold for NOUS
        color_r[i], color_g[i], color_b[i] = 255, 200, 40  # Extra bright gold
    
    # === Border particles (excluding NOUS positions) ===
    # Filter out border positions that are already NOUS
    border_pos_filtered = [p for p in border_pos if (p[0], p[1]) not in nous_set]
    n_border_actual = min(len(border_pos_filtered), n_border)
    if n_border_actual > 0:
        border_idx = np.random.choice(len(border_pos_filtered), n_border_actual, 
                                       replace=len(border_pos_filtered) < n_border_actual)
        for ii, idx in enumerate(border_idx):
            i = n_nous + ii
            pos = border_pos_filtered[idx]
            ty[i] = pos[0]
            tx[i] = pos[1]
            is_border[i] = True
            chars[i] = PAL_BADGE_BORDER[np.random.randint(len(PAL_BADGE_BORDER))]
            color_r[i], color_g[i], color_b[i] = GOLD
    
    # === Fill particles ===
    offset = n_nous + n_border_actual
    n_fill_actual = min(len(inner_pos), total - offset)
    if n_fill_actual > 0 and len(inner_pos) > 0:
        fill_idx = np.random.choice(len(inner_pos), n_fill_actual, 
                                     replace=len(inner_pos) < n_fill_actual)
        for ii, idx in enumerate(fill_idx):
            j = offset + ii
            if j >= total:
                break
            ty[j] = inner_pos[idx, 0]
            tx[j] = inner_pos[idx, 1]
            chars[j] = PAL_BADGE_FILL[np.random.randint(len(PAL_BADGE_FILL))]
            if np.random.random() > 0.45:
                color_r[j], color_g[j], color_b[j] = GOLD
            else:
                color_r[j], color_g[j], color_b[j] = DARK_AMBER
    
    # Initial positions: scattered around edges (spiral starting points)
    for i in range(total):
        angle = angle_offset[i]
        radius = max(grid_cols, grid_rows) * (0.5 + np.random.random() * 0.3)
        px[i] = cx + radius * np.cos(angle)
        py[i] = cy + radius * np.sin(angle)
        orbit_radius[i] = np.sqrt((px[i] - tx[i])**2 + (py[i] - ty[i])**2)
    
    # Dispersal properties (pre-computed)
    disp_angle = np.zeros(total, dtype=np.float64)
    disp_speed = np.random.uniform(0.4, 1.0, total)
    dist_from_center = np.sqrt((tx - cx)**2 + (ty - cy)**2)
    # Normalize for stagger delay
    max_dist = dist_from_center.max() if dist_from_center.max() > 0 else 1.0
    disp_delay = (1.0 - dist_from_center / max_dist) * 2.5  # inner particles disperse later
    
    return {
        'px': px, 'py': py, 'tx': tx, 'ty': ty,
        'angle_offset': angle_offset, 'orbit_radius': orbit_radius,
        'fade': fade, 'alive': alive, 'is_border': is_border,
        'chars': chars, 'color_r': color_r, 'color_g': color_g, 'color_b': color_b,
        'disp_angle': disp_angle, 'disp_speed': disp_speed, 'disp_delay': disp_delay,
        'total': total, 'cx': float(cx), 'cy': float(cy),
        'dispersal_started': np.zeros(total, dtype=bool),
    }


def update_particles_vectorized(P, t, features, frame_idx):
    """Vectorized particle update."""
    bass = features["bass"][min(frame_idx, len(features["bass"])-1)]
    cx, cy = P['cx'], P['cy']
    total = P['total']
    
    if t < 8.0:
        # ═══ CONVERGENCE — spiral inward ═══
        progress = t / 8.0
        # Smooth ease-in acceleration
        eased = progress * progress * (3 - 2 * progress)
        
        # Orbital radius decreases
        current_radius = P['orbit_radius'] * (1.0 - eased)
        
        # Spiral speed increases as particles get closer
        spiral_speed = 0.4 + eased * 2.5
        angle = P['angle_offset'] + t * spiral_speed
        
        # Position via spiral
        P['px'] = P['tx'] + current_radius * np.cos(angle)
        P['py'] = P['ty'] + current_radius * np.sin(angle) * 0.55  # aspect squish
        
        # Snap to target in final 1.5s (border snaps first)
        if t > 6.5:
            snap_t = (t - 6.5) / 1.5
            snap_ease = snap_t * snap_t  # quadratic ease-in
            # Border particles snap faster
            snap_border = np.minimum(snap_ease * 1.5, 1.0)
            snap_fill = snap_ease * 0.8
            snap = np.where(P['is_border'], snap_border, snap_fill)
            P['px'] = P['px'] * (1 - snap) + P['tx'] * snap
            P['py'] = P['py'] * (1 - snap) + P['ty'] * snap
        
        P['fade'][:] = 0.7 + 0.3 * eased  # particles brighten as they converge
    
    elif t < 13.0:
        # ═══ SETTLED — badge formed, gentle breathing ═══
        P['px'][:] = P['tx']
        P['py'][:] = P['ty']
        # Subtle brightness pulsing with bass
        breath = 0.92 + 0.08 * np.sin(t * 1.2) + bass * 0.06
        P['fade'][:] = breath
    
    elif t < 17.0:
        # ═══ DISPERSAL — particles drift outward from edges ═══
        local_t = t - 13.0
        
        # Initialize dispersal angles on first frame
        if not P['dispersal_started'].any():
            # Angle away from center with some randomness
            P['disp_angle'] = np.arctan2(P['ty'] - cy, P['tx'] - cx) + \
                              np.random.uniform(-0.6, 0.6, total)
            P['dispersal_started'][:] = True
        
        # Each particle has a delay based on distance from center (outer first)
        active_t = local_t - P['disp_delay']
        active = active_t > 0
        
        # Particles that haven't started yet stay in place
        P['px'][~active] = P['tx'][~active]
        P['py'][~active] = P['ty'][~active]
        P['fade'][~active] = np.maximum(0.0, 1.0 - local_t * 0.1)  # slight dim while waiting
        
        # Active dispersing particles
        if active.any():
            at = active_t[active]
            # Decelerating drift
            drift = at * P['disp_speed'][active] * np.maximum(0, 1.0 - at / 5.0)
            P['px'][active] = P['tx'][active] + drift * np.cos(P['disp_angle'][active])
            P['py'][active] = P['ty'][active] + drift * np.sin(P['disp_angle'][active])
            # Fade out as they drift
            P['fade'][active] = np.clip(1.0 - at / 3.0, 0.0, 1.0)
            # Change chars to lighter ones for fading particles
            fading = active & (P['fade'] < 0.4)
            for i in np.where(fading)[0]:
                P['chars'][i] = PAL_PARTICLE_LIGHT[np.random.randint(len(PAL_PARTICLE_LIGHT))]
    
    else:
        # ═══ FINAL FADE — everything dims to black ═══
        fade_progress = (t - 17.0) / 1.0
        P['fade'][:] = np.maximum(0.0, 1.0 - fade_progress)
        P['alive'][P['fade'] <= 0] = False


# ─── Tonemap ─────────────────────────────────────────────────────────────────

def tonemap(canvas, gamma=0.70):
    """Adaptive tone mapping."""
    f = canvas.astype(np.float32)
    sub = f[::4, ::4]
    lo = np.percentile(sub, 1)
    hi = np.percentile(sub, 99.5)
    if hi - lo < 10:
        hi = lo + 10
    f = np.clip((f - lo) / (hi - lo), 0.0, 1.0)
    np.power(f, gamma, out=f)
    return (f * 255).astype(np.uint8)


# ─── Frame Rendering ─────────────────────────────────────────────────────────

def render_frame(grid, grid_sm, P, t, features, frame_idx):
    """Render one frame."""
    canvas = np.zeros((VH, VW, 3), dtype=np.uint8)
    
    bass = features["bass"][min(frame_idx, len(features["bass"])-1)]
    hi = features["hi"][min(frame_idx, len(features["hi"])-1)]
    energy = features["energy"][min(frame_idx, len(features["energy"])-1)]
    
    # ═══ Layer 1: Atmospheric void texture (very subtle) ═══
    if t < 17.0:
        bg_fade = 1.0 if t < 16.0 else max(0, 17.0 - t)
        # Scattered ultra-dim dots — void is breathing
        rng_state = np.random.RandomState(frame_idx * 7 + 13)
        noise = rng_state.random((grid_sm.rows, grid_sm.cols))
        threshold = 0.994 - bass * 0.004
        bg_mask = noise > threshold
        
        bg_chars = np.full((grid_sm.rows, grid_sm.cols), " ", dtype="U1")
        bg_chars[bg_mask] = "·"
        
        bg_colors = np.zeros((grid_sm.rows, grid_sm.cols, 3), dtype=np.uint8)
        navy_intensity = int(35 * bg_fade + bass * 25)
        bg_colors[bg_mask, 2] = navy_intensity  # navy blue dots
        
        canvas = grid_sm.render(bg_chars, bg_colors, canvas)
    
    # ═══ Layer 2: Main particles ═══
    chars = np.full((grid.rows, grid.cols), " ", dtype="U1")
    colors = np.zeros((grid.rows, grid.cols, 3), dtype=np.uint8)
    
    alive_mask = P['alive'] & (P['fade'] > 0.01)
    alive_indices = np.where(alive_mask)[0]
    
    for i in alive_indices:
        col = int(round(P['px'][i]))
        row = int(round(P['py'][i]))
        if 0 <= row < grid.rows and 0 <= col < grid.cols:
            f = min(P['fade'][i], 1.0)
            chars[row, col] = P['chars'][i]
            colors[row, col, 0] = min(255, int(P['color_r'][i] * f))
            colors[row, col, 1] = min(255, int(P['color_g'][i] * f))
            colors[row, col, 2] = min(255, int(P['color_b'][i] * f))
    
    canvas = grid.render(chars, colors, canvas)
    
    # ═══ Layer 3: URL text (nousresearch.com) ═══
    if 9.0 < t < 15.5:
        url_text = "nousresearch.com"
        url_fade = 1.0
        if t < 10.0:
            url_fade = (t - 9.0) / 1.0  # fade in over 1s
        elif t > 14.5:
            url_fade = (15.5 - t) / 1.0  # fade out
        
        _, _, _, _, _, _, _, badge_h_val = bounds_global
        url_row = int(P['cy']) + badge_h_val // 2 + 3
        url_col_start = int(P['cx']) - len(url_text) // 2
        
        url_chars = np.full((grid.rows, grid.cols), " ", dtype="U1")
        url_colors = np.zeros((grid.rows, grid.cols, 3), dtype=np.uint8)
        
        if 0 <= url_row < grid.rows:
            for i, c in enumerate(url_text):
                cc = url_col_start + i
                if 0 <= cc < grid.cols:
                    url_chars[url_row, cc] = c
                    intensity = int(200 * url_fade)
                    url_colors[url_row, cc] = (intensity, intensity, intensity)
        
        canvas = grid.render(url_chars, url_colors, canvas)
    
    # ═══ Layer 4: Hi-hat triggered sparkles ═══
    if hi > 0.35 and t < 16.0 and t > 1.0:
        n_sparkles = int(hi * 4)
        sparkle_chars = np.full((grid_sm.rows, grid_sm.cols), " ", dtype="U1")
        sparkle_colors = np.zeros((grid_sm.rows, grid_sm.cols, 3), dtype=np.uint8)
        for _ in range(n_sparkles):
            sr = np.random.randint(0, grid_sm.rows)
            sc = np.random.randint(0, grid_sm.cols)
            sparkle_chars[sr, sc] = "✧" if "✧" in grid_sm.bm else "*"
            sparkle_colors[sr, sc] = (int(180 * hi), int(140 * hi), int(25 * hi))
        canvas = grid_sm.render(sparkle_chars, sparkle_colors, canvas)
    
    # ═══ Tonemap ═══
    if canvas.max() > 3:
        canvas = tonemap(canvas, gamma=0.68)
    
    # ═══ Bloom / Glow — gold characters emit light ═══
    if canvas.max() > 10 and t < 17.5:
        # Extract bright areas and blur them for glow
        bright = canvas.astype(np.float32)
        # Threshold: only bloom the brightest parts
        bloom_mask = (bright.max(axis=2) > 80)
        bloom = np.where(bloom_mask[:, :, None], bright, 0)
        # Gaussian blur for glow
        bloom[:, :, 0] = gaussian_filter(bloom[:, :, 0], sigma=8)
        bloom[:, :, 1] = gaussian_filter(bloom[:, :, 1], sigma=8)
        bloom[:, :, 2] = gaussian_filter(bloom[:, :, 2], sigma=8)
        # Screen blend the bloom
        canvas_f = canvas.astype(np.float32) / 255.0
        bloom_f = bloom / (bloom.max() + 1e-6) * 0.4  # bloom intensity
        result = 1.0 - (1.0 - canvas_f) * (1.0 - bloom_f)
        canvas = np.clip(result * 255, 0, 255).astype(np.uint8)
    
    # ═══ Vignette — subtle darkening at edges (pre-computed) ═══
    if t < 17.0:
        canvas = (canvas.astype(np.float32) * vignette_map[:, :, None]).astype(np.uint8)
    
    # ═══ Global fade for final second ═══
    if t > 17.0:
        fade_val = max(0, 1.0 - (t - 17.0) / 1.0)
        canvas = (canvas.astype(np.float32) * fade_val).astype(np.uint8)
    
    return canvas


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    global bounds_global, vignette_map
    
    print("=" * 60, flush=True)
    print("  Scene 7: Logo Reveal — Convergence and Dispersal", flush=True)
    print("=" * 60, flush=True)
    print(f"  Resolution: {VW}x{VH} @ {FPS}fps", flush=True)
    print(f"  Duration: {DURATION}s ({TOTAL_FRAMES} frames)", flush=True)
    print(flush=True)
    
    t_start = time.time()
    
    # ─── Initialize grids ───
    print("[1/6] Initializing grids...", flush=True)
    grid = GridLayer(FONT_PATH, 16)
    grid_sm = GridLayer(FONT_PATH_REGULAR, 10)
    print(f"       Main grid (md): {grid.cols}x{grid.rows} (cell {grid.cw}x{grid.ch})", flush=True)
    print(f"       Small grid (sm): {grid_sm.cols}x{grid_sm.rows}", flush=True)
    
    # ─── Create badge shape ───
    print("[2/6] Creating badge shape...", flush=True)
    badge_mask, border_mask, inner_mask, bounds, nous_pos = create_badge_shape(grid.rows, grid.cols)
    bounds_global = bounds
    x0, y0, x1, y1, cx, cy, bw, bh = bounds
    print(f"       Badge: {bw}x{bh} cells, center: ({cx},{cy})", flush=True)
    print(f"       Border cells: {int(border_mask.sum())}, Fill cells: {int(inner_mask.sum())}", flush=True)
    print(f"       NOUS text at row {nous_pos[0][0]}, cols {nous_pos[0][1]}-{nous_pos[-1][1]}", flush=True)
    
    # ─── Extract audio ───
    print("[3/6] Extracting audio features...", flush=True)
    features = extract_audio_features()
    print(f"       Bass: avg={features['bass'].mean():.3f}, max={features['bass'].max():.3f}", flush=True)
    print(f"       Energy: avg={features['energy'].mean():.3f}, decays to {features['energy'][-48:].mean():.3f}", flush=True)
    
    # ─── Create particles ───
    print("[4/6] Creating particle system...", flush=True)
    np.random.seed(42)
    # Use enough particles to fill the badge completely
    n_particles = int(border_mask.sum() + inner_mask.sum())
    n_particles = min(n_particles, 1500)  # cap for performance
    P = create_particle_arrays(grid.rows, grid.cols, badge_mask, border_mask, inner_mask, bounds, nous_pos, n=n_particles)
    print(f"       {P['total']} particles ({P['is_border'].sum()} border, {(~P['is_border']).sum()} fill)", flush=True)
    
    # ─── Render preview ───
    print("[5/6] Rendering preview frame (t=9.5s, badge settled)...", flush=True)
    
    # Pre-compute vignette (needed by render_frame)
    yy = np.linspace(-1, 1, VH)[:, None]
    xx = np.linspace(-1, 1, VW)[None, :]
    vignette_map = 1.0 - np.sqrt(xx**2 + yy**2) * 0.25
    vignette_map = np.clip(vignette_map, 0.55, 1.0).astype(np.float32)
    
    # Fast-forward particles to t=9.5
    P_preview = create_particle_arrays(grid.rows, grid.cols, badge_mask, border_mask, inner_mask, bounds, nous_pos, n=n_particles)
    for fi in range(int(9.5 * FPS)):
        update_particles_vectorized(P_preview, fi / FPS, features, fi)
    
    preview = render_frame(grid, grid_sm, P_preview, 9.5, features, int(9.5 * FPS))
    Image.fromarray(preview).save(CHECKPOINT_PATH)
    print(f"       Saved: {CHECKPOINT_PATH}", flush=True)
    print(f"       Brightness: mean={preview.mean():.1f}, max={preview.max()}", flush=True)
    
    # ─── Render full clip ───
    print("[6/6] Rendering full clip...", flush=True)
    np.random.seed(42)
    P = create_particle_arrays(grid.rows, grid.cols, badge_mask, border_mask, inner_mask, bounds, nous_pos, n=n_particles)
    
    # (vignette_map already computed in step 5)
    
    # ffmpeg pipe
    ffmpeg_log = open(os.path.join(WORKDIR, "ffmpeg_stderr.log"), "w")
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{VW}x{VH}", "-r", str(FPS),
        "-i", "pipe:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "slow",
        "-pix_fmt", "yuv420p",
        OUTPUT_PATH
    ]
    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=ffmpeg_log)
    
    frame_times = []
    
    for fi in range(TOTAL_FRAMES):
        t = fi / FPS
        ft_start = time.time()
        
        update_particles_vectorized(P, t, features, fi)
        canvas = render_frame(grid, grid_sm, P, t, features, fi)
        pipe.stdin.write(canvas.tobytes())
        
        frame_times.append(time.time() - ft_start)
        
        if fi % 48 == 0 or fi == TOTAL_FRAMES - 1:
            elapsed = time.time() - t_start
            rate = (fi + 1) / elapsed
            eta = (TOTAL_FRAMES - fi - 1) / rate if rate > 0 else 0
            print(f"       Frame {fi+1:>4}/{TOTAL_FRAMES} | t={t:5.2f}s | "
                  f"{frame_times[-1]*1000:5.0f}ms/f | ETA {eta:.0f}s", flush=True)
    
    pipe.stdin.close()
    pipe.wait()
    ffmpeg_log.close()
    
    total_time = time.time() - t_start
    
    print(flush=True)
    print("─" * 60, flush=True)
    print(f"  ✓ COMPLETE", flush=True)
    print(f"  Output:      {OUTPUT_PATH}", flush=True)
    print(f"  Duration:    {DURATION}s @ {FPS}fps", flush=True)
    print(f"  Render time: {total_time:.1f}s", flush=True)
    print(f"  Avg frame:   {np.mean(frame_times)*1000:.0f}ms", flush=True)
    print("─" * 60, flush=True)
    
    return total_time


if __name__ == "__main__":
    render_time = main()
