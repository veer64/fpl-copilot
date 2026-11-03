// Prompt W1: measure where the strong beats of the intro song are, to propose AUDIO_START_OFFSET (a beat on the 5.3 s
// flash). The laptop has no ffmpeg or librosa, so the browser decodes the file: Playwright opens the dev server, fetches
// /intro/love-me-again.mp3, decodes it with Web Audio and runs a simple onset detector (10 ms frames, positive change of
// log energy, local peaks). Usage: node scripts/audio_onsets.mjs [baseUrl]   (needs `npm run dev` on :3000)
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:3000";
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage();
await page.goto(`${base}/login`);
const result = await page.evaluate(async () => {
  const res = await fetch("/intro/love-me-again.mp3");
  if (!res.ok) return { error: `HTTP ${res.status}` };
  const buf = await res.arrayBuffer();
  const ctx = new OfflineAudioContext(1, 1, 44100);
  const audio = await ctx.decodeAudioData(buf.slice(0));
  const sr = audio.sampleRate;
  const n = audio.numberOfChannels;
  const len = audio.length;
  const mono = new Float32Array(len);
  for (let c = 0; c < n; c++) {
    const d = audio.getChannelData(c);
    for (let i = 0; i < len; i++) mono[i] += d[i] / n;
  }
  const hop = Math.round(sr * 0.01);
  const win = hop * 4;
  const frames = Math.floor((len - win) / hop);
  const loud = new Float32Array(frames);
  for (let f = 0; f < frames; f++) {
    let s = 0;
    const o = f * hop;
    for (let i = 0; i < win; i++) s += mono[o + i] * mono[o + i];
    loud[f] = Math.log10(s / win + 1e-9);
  }
  // onset strength: positive change over 30 ms, then peaks that are the max within ±150 ms and above a threshold
  const flux = new Float32Array(frames);
  for (let f = 3; f < frames; f++) flux[f] = Math.max(0, loud[f] - loud[f - 3]);
  const peaks = [];
  for (let f = 15; f < frames - 15; f++) {
    let isMax = flux[f] > 0.25;
    for (let k = -15; k <= 15 && isMax; k++) if (k !== 0 && flux[f + k] >= flux[f]) isMax = false;
    if (isMax) peaks.push({ t: +(f * 0.01).toFixed(2), strength: +flux[f].toFixed(3), level: +loud[f].toFixed(2) });
  }
  const top = [...peaks].sort((a, b) => b.strength - a.strength).slice(0, 40).sort((a, b) => a.t - b.t);
  return { duration: +audio.duration.toFixed(2), sampleRate: sr, channels: n, onsets: peaks.length, top };
});
await browser.close();
if (result.error) {
  console.error(result.error);
  process.exit(1);
}
console.log(JSON.stringify({ duration: result.duration, sampleRate: result.sampleRate, channels: result.channels, onsets: result.onsets }));
console.log("strongest onsets (t s, strength, level dB-ish) and the offset that would put each on the 5.3 s flash:");
for (const p of result.top) {
  const off = p.t - 5.3;
  console.log(`  t=${p.t.toFixed(2).padStart(7)}  strength=${p.strength.toFixed(3)}  level=${p.level.toFixed(2)}  -> offset ${off >= 0 ? off.toFixed(2) : "n/a"}`);
}
