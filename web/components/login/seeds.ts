/** Deterministic pseudo-random layout for the decorative pieces (the reference's `rnd`): the same numbers on the server
 *  and in the browser, so hydration never disagrees and the scene looks identical on every visit. */
export function rnd(i: number, s: number): number {
  const x = Math.sin(i * 127.1 + s * 311.7) * 43758.5453;
  return x - Math.floor(x);
}

export type DissolveBlock = { left: string; top: string; backgroundPosition: string; animationDelay: string };

/** The intro's 12 x 10 pixel-block dissolve: each tile shows its own patch of the body image and flashes in at
 *  `start` + up to 0.6 s, in a seeded random order. */
export function dissolveGrid(start: number, seed: number): DissolveBlock[] {
  const out: DissolveBlock[] = [];
  for (let j = 0; j < 10; j++) {
    for (let i = 0; i < 12; i++) {
      const k = j * 12 + i;
      out.push({
        left: `${((i * 100) / 12).toFixed(4)}%`,
        top: `${j * 10}%`,
        backgroundPosition: `${((i / 11) * 100).toFixed(3)}% ${((j / 9) * 100).toFixed(3)}%`,
        animationDelay: `${(start + rnd(k, seed) * 0.6).toFixed(3)}s`,
      });
    }
  }
  return out;
}

export type Particle = { rotate: string; d: string; l: string; o: string };

/** 40 particles: streaks during the intro, drifting dots on the login state (the CSS reads --d / --l / --o). */
export function particles(n = 40): Particle[] {
  const out: Particle[] = [];
  for (let k = 0; k < n; k++) {
    out.push({
      rotate: `${(rnd(k, 2) * 360).toFixed(1)}deg`,
      d: rnd(k, 3).toFixed(3),
      l: `${(30 + rnd(k, 4) * 90).toFixed(0)}px`,
      o: (0.4 + rnd(k, 5) * 0.6).toFixed(2),
    });
  }
  return out;
}
