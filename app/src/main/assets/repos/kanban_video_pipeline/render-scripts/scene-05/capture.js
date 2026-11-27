#!/usr/bin/env node
/**
 * Scene 5 — Headless frame capture with audio feature injection.
 * Uses puppeteer-core + system Chrome.
 */
const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

const SKETCH_PATH = path.resolve(__dirname, 'sketch.html');
const AUDIO_FEATURES_PATH = path.resolve(__dirname, 'audio_features.json');
const FRAMES_DIR = path.resolve(__dirname, 'frames');
const WIDTH = 1920;
const HEIGHT = 1080;
const TOTAL_FRAMES = 408;

// Parse CLI args
const args = process.argv.slice(2);
let startFrame = 0;
let endFrame = TOTAL_FRAMES;
let previewOnly = false;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--preview') previewOnly = true;
  if (args[i] === '--start') startFrame = parseInt(args[++i]);
  if (args[i] === '--end') endFrame = parseInt(args[++i]);
}

async function main() {
  // Load audio features
  let audioFeatures = null;
  if (fs.existsSync(AUDIO_FEATURES_PATH)) {
    audioFeatures = JSON.parse(fs.readFileSync(AUDIO_FEATURES_PATH, 'utf8'));
    console.log(`Loaded audio features: ${audioFeatures.n_frames} frames`);
  } else {
    console.log('WARNING: No audio features found, using defaults');
  }

  // Create frames directory
  fs.mkdirSync(FRAMES_DIR, { recursive: true });

  // Launch browser
  const browser = await puppeteer.launch({
    executablePath: '/usr/bin/google-chrome',
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
  await page.setViewport({ width: WIDTH, height: HEIGHT, deviceScaleFactor: 1 });

  // Navigate to sketch
  await page.goto(`file://${SKETCH_PATH}`, { waitUntil: 'networkidle0', timeout: 30000 });

  // Wait for p5.js to initialize
  await page.waitForSelector('canvas', { timeout: 10000 });
  await page.waitForFunction('window._p5Ready === true', { timeout: 10000 });
  console.log('Sketch ready (noLoop mode)');

  // Inject audio features
  if (audioFeatures) {
    await page.evaluate((features) => {
      window.AUDIO_FEATURES = features;
      // Also set it on the global audioFeatures variable
      if (typeof audioFeatures !== 'undefined') {
        audioFeatures = features;
      }
      // Force the sketch variable
      window.audioFeatures = features;
    }, audioFeatures);
    
    // Patch the sketch's audioFeatures reference
    await page.evaluate((features) => {
      // Direct assignment to p5 sketch scope via a workaround
      // The draw() function reads from window.AUDIO_FEATURES or audioFeatures
      // Let's make both work by setting a global
      window.audioFeatures = features;
    }, audioFeatures);
    console.log('Audio features injected');
  }

  const framesToCapture = previewOnly ? 1 : (endFrame - startFrame);
  let skipFrames = previewOnly ? Math.floor(TOTAL_FRAMES * 0.7) : startFrame; // preview at 70% - most action
  
  // Allow --frame N for specific preview frame
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--frame') skipFrames = parseInt(args[++i]);
  }
  
  console.log(`Capturing ${framesToCapture} frames (skip ${skipFrames} first)...`);
  const startTime = Date.now();

  // Advance to start frame if needed
  if (skipFrames > 0) {
    console.log(`  Advancing ${skipFrames} frames...`);
    for (let i = 0; i < skipFrames; i++) {
      await page.evaluate(() => { redraw(); });
      // Batch: skip delay for speed, add minimal delays every 50 frames
      if (i % 50 === 49) await new Promise(r => setTimeout(r, 5));
    }
    await new Promise(r => setTimeout(r, 50));
    console.log(`  At frame ${skipFrames}, starting capture`);
  }

  for (let i = 0; i < framesToCapture; i++) {
    const globalFrame = startFrame + i;
    
    // Advance one frame
    await page.evaluate(() => { redraw(); });
    // Brief settle time
    await new Promise(r => setTimeout(r, 10));

    const frameName = previewOnly
      ? 'preview.png'
      : `frame-${String(globalFrame).padStart(4, '0')}.png`;
    const framePath = path.join(FRAMES_DIR, frameName);

    const canvas = await page.$('canvas');
    await canvas.screenshot({ path: framePath, type: 'png' });

    // Progress
    if (i % 24 === 0 || i === framesToCapture - 1) {
      const pct = ((i + 1) / framesToCapture * 100).toFixed(1);
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      const fps = ((i + 1) / ((Date.now() - startTime) / 1000)).toFixed(1);
      process.stdout.write(`\r  Frame ${i + 1}/${framesToCapture} (${pct}%) — ${elapsed}s [${fps} fps]`);
    }
  }

  const totalTime = ((Date.now() - startTime) / 1000).toFixed(1);
  console.log(`\nCapture complete in ${totalTime}s`);
  
  if (previewOnly) {
    console.log(`Preview saved: ${path.join(FRAMES_DIR, 'preview.png')}`);
  } else {
    console.log(`Frames saved to: ${FRAMES_DIR}/`);
  }

  await browser.close();
}

main().catch(err => {
  console.error('Error:', err.message);
  process.exit(1);
});
