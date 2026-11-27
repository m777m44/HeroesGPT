#!/usr/bin/env python3
"""Extract audio features for Scene 5 (1:07-1:24)."""
import numpy as np
from scipy.io import wavfile
from scipy import signal
import subprocess, json, os

os.makedirs('scenes/scene-05', exist_ok=True)

# Extract the scene audio segment as WAV
start_time = 67.0  # 1:07
end_time = 84.0    # 1:24
subprocess.run([
    'ffmpeg', '-y', '-i', 'audio/Doomscroll.mp3',
    '-ss', str(start_time), '-to', str(end_time),
    '-ar', '48000', '-ac', '1',
    'scenes/scene-05/audio_segment.wav'
], capture_output=True)

# Read the WAV
sr, audio = wavfile.read('scenes/scene-05/audio_segment.wav')
audio = audio.astype(np.float32) / 32768.0

fps = 24
hop = sr // fps
n_frames = int(np.ceil(len(audio) / hop))

# Extract features per frame
features = []
for i in range(n_frames):
    chunk = audio[i*hop:(i+1)*hop]
    if len(chunk) < hop:
        chunk = np.pad(chunk, (0, hop - len(chunk)))
    fft = np.abs(np.fft.rfft(chunk))
    freqs = np.fft.rfftfreq(len(chunk), 1/sr)
    bass = float(np.mean(fft[(freqs >= 60) & (freqs < 200)]))
    mid = float(np.mean(fft[(freqs >= 200) & (freqs < 2000)]))
    hi = float(np.mean(fft[(freqs >= 8000) & (freqs < 12000)]))
    energy = float(np.mean(fft))
    features.append({
        'frame': i, 'time': round(start_time + i/fps, 3),
        'bass': bass, 'mid': mid, 'hi': hi, 'energy': energy
    })

# Normalize
max_bass = max(f['bass'] for f in features)
max_mid = max(f['mid'] for f in features)
max_hi = max(f['hi'] for f in features)
max_energy = max(f['energy'] for f in features)
for f in features:
    f['bass_norm'] = round(f['bass'] / max_bass if max_bass > 0 else 0, 4)
    f['mid_norm'] = round(f['mid'] / max_mid if max_mid > 0 else 0, 4)
    f['hi_norm'] = round(f['hi'] / max_hi if max_hi > 0 else 0, 4)
    f['energy_norm'] = round(f['energy'] / max_energy if max_energy > 0 else 0, 4)

# Onset detection for beats
energies = np.array([f['energy'] for f in features])
onset_strength = np.zeros(len(energies))
for i in range(1, len(energies)):
    onset_strength[i] = max(0, energies[i] - energies[i-1])
peaks, _ = signal.find_peaks(onset_strength, height=np.percentile(onset_strength, 70), distance=2)

result = {
    'n_frames': n_frames,
    'duration': round(len(audio)/sr, 3),
    'sr': sr,
    'fps': fps,
    'beat_frames': peaks.tolist(),
    'beat_times': [round(start_time + p/fps, 2) for p in peaks],
    'features': features
}

with open('scenes/scene-05/audio_features.json', 'w') as fp:
    json.dump(result, fp, indent=2)

print(f"Frames: {n_frames}, Duration: {len(audio)/sr:.2f}s")
print(f"Beat frames: {peaks.tolist()}")
print(f"Beat times: {[round(start_time + p/fps, 2) for p in peaks]}")
