"use client";

import { useMemo } from "react";

// Per-period ambient decoration. CSS-only effects; this component just renders the
// DOM (all 6 layers always present, activated via [data-theme] in globals.css).
// Rendered inside <main> so it covers the main body area and never the sidebar.

// Deterministic PRNG (mulberry32) so the server and client render identical stars
// (no hydration mismatch). Seeded once; positions are stable across renders.
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

type Star = {
  top: string;
  left: string;
  size: string;
  opacity: number;
  duration: string;
  delay: string;
};

function makeStars(count: number): Star[] {
  const rand = mulberry32(0x5eed);
  const stars: Star[] = [];
  for (let i = 0; i < count; i += 1) {
    const opacity = 0.4 + rand() * 0.6; // 0.4–1
    const size = 1 + rand() * 1.5; // 1–2.5px
    stars.push({
      top: `${(rand() * 100).toFixed(3)}%`,
      left: `${(rand() * 100).toFixed(3)}%`,
      size: `${size.toFixed(2)}px`,
      opacity: Number(opacity.toFixed(3)),
      duration: `${(2 + rand() * 3).toFixed(2)}s`, // 2–5s
      delay: `${(rand() * 5).toFixed(2)}s`,
    });
  }
  return stars;
}

export function AmbientLayer() {
  const stars = useMemo(() => makeStars(120), []);

  return (
    <div className="ambient-root" aria-hidden="true">
      {/* NIGHT — scattered twinkling stars + a rare shooting star */}
      <div className="ambient-layer ambient-night">
        {stars.map((s, i) => (
          <span
            key={i}
            className="star"
            style={
              {
                top: s.top,
                left: s.left,
                width: s.size,
                height: s.size,
                opacity: s.opacity,
                "--star-opacity": s.opacity,
                "--star-duration": s.duration,
                animationDelay: s.delay,
              } as React.CSSProperties
            }
          />
        ))}
        <span className="shooting-star" />
      </div>

      {/* PRE-DAWN — static crescent moon + soft glow, upper-right */}
      <div className="ambient-layer ambient-predawn">
        <div className="predawn-moon">
          <div className="predawn-glow" />
          <div className="predawn-crescent">
            <div className="predawn-crescent-mask" />
          </div>
        </div>
      </div>

      {/* SUNRISE — warm bloom rising from bottom-center */}
      <div className="ambient-layer ambient-sunrise">
        <div className="sunrise-bloom" />
      </div>

      {/* DAYTIME — overhead sky glow + slow concentric pulse rings */}
      <div className="ambient-layer ambient-daytime">
        <div className="day-glow" />
        <div className="day-ring day-ring-1" />
        <div className="day-ring day-ring-2" />
        <div className="day-ring day-ring-3" />
      </div>

      {/* DUSK — amber horizon band across the lower third */}
      <div className="ambient-layer ambient-dusk">
        <div className="dusk-band" />
        <div className="dusk-horizon" />
      </div>

      {/* SUNSET — warm pink-orange bloom, center-right */}
      <div className="ambient-layer ambient-sunset">
        <div className="sunset-bloom" />
      </div>

      {/* PHANTOM — drifting crimson + navy blobs over grain (manual-only theme) */}
      <div className="ambient-layer ambient-phantom">
        <div className="ph-blob ph-blob-red" />
        <div className="ph-blob ph-blob-navy" />
        <div className="ph-blob ph-blob-red-2" />
        <div className="ph-noise" />
      </div>

      {/* Scroll glow — global, all themes. Invisible at rest; fades in with scroll
          depth (--scroll-depth). Sits outside the per-theme layers. */}
      <div className="scroll-glow-left" aria-hidden="true" />
      <div className="scroll-glow-right" aria-hidden="true" />
      <div className="scroll-glow-top" aria-hidden="true" />
    </div>
  );
}
