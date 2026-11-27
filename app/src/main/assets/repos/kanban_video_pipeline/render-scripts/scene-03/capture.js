#!/usr/bin/env node
/**
 * Scene 03 Frame Capture - uses puppeteer-core with system Chrome
 */
const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const SKETCH = path.resolve(__dirname, 'sketch.html');
const FRAMES_DIR = path.resolve(__dirname, 'frames');
const CHECKPOINT_DIR = path.resolve(__dirname, '../../checkpoints');
const W = 1920;
const H = 1080;
const TOTAL_FRAMES = 456; // 19s * 24fps

// Find Chrome
const CHROME_PATH = '/usr/bin/google-chrome';

async function main() {
  // Parse args
  const args = process.argv.slice(2);
  let framesToCapture = TOTAL_FRAMES;
  let previewOnly = false;
  
  if (args.includes('--preview')) {
    framesToCapture = 1;
    previewOnly = true;
  } else if (args.includes('--frames')) {
    framesToCapture = parseInt(args[args.indexOf('--frames') + 1]) || TOTAL_FRAMES;
  }

  fs.mkdirSync(FRAMES_DIR, { recursive: true });
  fs.mkdirSync(CHECKPOINT_DIR, { recursive: true });

  console.log(`Capturing ${framesToCapture} frames from Scene 03`);
  console.log(`Resolution: ${W}x${H}`);
  console.log(`Chrome: ${CHROME_PATH}`);

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-web-security',
      '--allow-file-access-from-files',
    ],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });

  const fileUrl = `file://${SKETCH}`;
  await page.goto(fileUrl, { waitUntil: 'networkidle0', timeout: 30000 });

  // Wait for p5.js sketch to be ready
  await page.waitForSelector('canvas', { timeout: 10000 });
  await page.waitForFunction('window._p5Ready === true', { timeout: 10000 });
  console.log('Sketch ready (deterministic mode)');

  const startTime = Date.now();

  for (let i = 0; i < framesToCapture; i++) {
    // Advance one frame
    await page.evaluate(() => { redraw(); });
    await new Promise(r => setTimeout(r, 30)); // settle

    const frameName = `frame-${String(i).padStart(4, '0')}.png`;
    const framePath = path.join(FRAMES_DIR, frameName);

    const canvas = await page.$('canvas');
    // Use toDataURL to avoid Chrome compositor alpha issues
    const dataUrl = await page.evaluate(() => {
      return document.querySelector('canvas').toDataURL('image/png');
    });
    const base64Data = dataUrl.replace(/^data:image\/png;base64,/, '');
    fs.writeFileSync(framePath, Buffer.from(base64Data, 'base64'));

    // Save first frame as checkpoint preview
    if (i === 0) {
      const checkpointPath = path.join(CHECKPOINT_DIR, 'scene-03-frame-001.png');
      fs.copyFileSync(framePath, checkpointPath);
      console.log(`  Checkpoint saved: ${checkpointPath}`);
    }
    
    // Save beat drop frame (frame 24 = 2 frames after explosion start, where it's visible)
    if (i === 24) {
      const checkpointPath = path.join(CHECKPOINT_DIR, 'scene-03-beat-drop.png');
      fs.copyFileSync(framePath, checkpointPath);
      console.log(`  Beat drop checkpoint: ${checkpointPath}`);
    }
    
    // Save pre-explosion swell (frame 20)
    if (i === 20) {
      const checkpointPath = path.join(CHECKPOINT_DIR, 'scene-03-pre-explosion.png');
      fs.copyFileSync(framePath, checkpointPath);
      console.log(`  Pre-explosion checkpoint: ${checkpointPath}`);
    }
    
    // Save arrived state (frame 340 ~14s)
    if (i === 340) {
      const checkpointPath = path.join(CHECKPOINT_DIR, 'scene-03-arrived.png');
      fs.copyFileSync(framePath, checkpointPath);
      console.log(`  Arrived checkpoint: ${checkpointPath}`);
    }
    
    // Save mid-scene frame
    if (i === 228) { // ~9.5s in
      const checkpointPath = path.join(CHECKPOINT_DIR, 'scene-03-mid.png');
      fs.copyFileSync(framePath, checkpointPath);
      console.log(`  Mid-scene checkpoint: ${checkpointPath}`);
    }

    // Progress
    if (i % 24 === 0 || i === framesToCapture - 1) {
      const pct = ((i + 1) / framesToCapture * 100).toFixed(1);
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      const fps = (i + 1) / ((Date.now() - startTime) / 1000);
      process.stdout.write(`\r  Frame ${i + 1}/${framesToCapture} (${pct}%) — ${elapsed}s — ${fps.toFixed(1)} fps`);
    }
  }

  const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\n  Done in ${totalTime}s`);
  await browser.close();
  
  if (previewOnly) {
    console.log(`Preview saved to: ${path.join(CHECKPOINT_DIR, 'scene-03-frame-001.png')}`);
    return;
  }
  
  console.log(`Frames saved to: ${FRAMES_DIR}/`);
  console.log(`Total frames: ${framesToCapture}`);
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
