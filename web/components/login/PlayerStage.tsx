"use client";

/* eslint-disable @next/next/no-img-element -- the players are stacked, CSS-masked, 3D-transformed layers sized by the
   duo's aspect ratio; next/image's wrapper and srcset add nothing here, and the files are preloaded by the page. */
import { useMemo, useState, type CSSProperties, type RefObject } from "react";
import { dissolveGrid, particles } from "./seeds";

export type Phase = "intro" | "login";

export const PLAYER_IMAGES = {
  vandijkBody: "/players/vandijk-body.webp",
  vandijkHead: "/players/vandijk-head.webp",
  haalandBody: "/players/haaland-body.webp",
  haalandHead: "/players/haaland-head.webp",
  ball: "/players/ball.webp",
} as const;

type Props = {
  phase: Phase;
  tiltV: RefObject<HTMLDivElement | null>;
  tiltH: RefObject<HTMLDivElement | null>;
  ball: RefObject<HTMLDivElement | null>;
  cam: RefObject<HTMLDivElement | null>;
  showNames?: boolean;
};

const FIGURE = (
  <svg viewBox="0 0 200 320" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M90 78 L124 80 L112 174 L86 168 Z" fill="currentColor" fillOpacity="0.14" strokeWidth="1.5" />
    <circle cx="114" cy="44" r="17" fill="currentColor" fillOpacity="0.14" strokeWidth="1.5" />
    <path d="M122 82 L140 118 L156 92 M92 82 L72 106 L62 138 M108 172 L146 206 L138 262 L154 266 M90 170 L84 236 L56 294 L46 302" strokeWidth="2" />
  </svg>
);

/** The scene behind the UI: pitch grid, particles, the two player stacks (Haaland behind, Van Dijk in front, four
 *  same-frame images), the ball and the name tags. Parallax is written to the refs by the page (rAF-throttled). */
export function PlayerStage({ phase, tiltV, tiltH, ball, cam, showNames = true }: Props) {
  const [missing, setMissing] = useState(false);
  const blocksV = useMemo(() => dissolveGrid(0.3, 1), []);
  const blocksH = useMemo(() => dissolveGrid(0.6, 7), []);
  const parts = useMemo(() => particles(40), []);
  const onImgError = () => setMissing(true);
  // a server-rendered image can fail before React attaches onError; the ref callback runs at mount and catches that case
  const bodyRef = (img: HTMLImageElement | null) => {
    if (img && img.complete && img.naturalWidth === 0) setMissing(true);
  };

  return (
    <>
      <div className="world" aria-hidden="true">
        <div className="cam" ref={cam}>
          <div className="pitch">
            <div className="pitch-circle" />
            <div className="pitch-half" />
          </div>
        </div>
        <div className="parts">
          {parts.map((p, k) => (
            <i
              key={k}
              className="pt"
              style={{ transform: `rotate(${p.rotate})`, "--d": p.d, "--l": p.l, "--o": p.o } as CSSProperties}
            >
              <b />
            </i>
          ))}
        </div>

        <div className="duo" data-phase={phase}>
          {!missing ? (
            <>
              <div className="pl pl-h">
                <div className="gl">
                  <div className="holo">
                    <div className="tilt" ref={tiltH}>
                      <img ref={bodyRef} className="ly ly-body" src={PLAYER_IMAGES.haalandBody} alt="" draggable={false} onError={onImgError} />
                      <div className="sheen sheen-h" />
                      <img className="ly ly-head" src={PLAYER_IMAGES.haalandHead} alt="" draggable={false} />
                    </div>
                  </div>
                  <img className="ghost" src={PLAYER_IMAGES.haalandBody} alt="" draggable={false} />
                </div>
                <div className="dz dz-h">
                  {blocksH.map((b, i) => (
                    <b key={i} style={b} />
                  ))}
                </div>
              </div>
              <div className="pl pl-v">
                <div className="gl">
                  <div className="holo">
                    <div className="tilt" ref={tiltV}>
                      <img ref={bodyRef} className="ly ly-body" src={PLAYER_IMAGES.vandijkBody} alt="" draggable={false} onError={onImgError} />
                      <div className="sheen sheen-v" />
                      <img className="ly ly-head" src={PLAYER_IMAGES.vandijkHead} alt="" draggable={false} />
                    </div>
                  </div>
                  <img className="ghost" src={PLAYER_IMAGES.vandijkBody} alt="" draggable={false} />
                </div>
                <div className="dz dz-v">
                  {blocksV.map((b, i) => (
                    <b key={i} style={b} />
                  ))}
                </div>
              </div>
              <div className="ball">
                <div className="ball-p" ref={ball}>
                  <div className="ball-in">
                    <img src={PLAYER_IMAGES.ball} alt="" draggable={false} />
                  </div>
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="ath" style={{ left: "10%" }}>{FIGURE}</div>
              <div className="ath" style={{ left: "54%", color: "#3BE8FF" }}>{FIGURE}</div>
            </>
          )}
          {showNames && (
            <>
              <div className="tag tag-v mono">
                <span className="tag-line" />
                <span>CB · 04</span>
                <strong>VAN DIJK</strong>
              </div>
              <div className="tag tag-h mono">
                <span className="tag-line" />
                <span>ST · 09</span>
                <strong>HAALAND</strong>
              </div>
            </>
          )}
        </div>
      </div>
      <div className="flash" aria-hidden="true" />
    </>
  );
}
