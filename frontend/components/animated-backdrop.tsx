"use client";

/**
 * Page-wide gradient backdrop — fixed behind every route.
 *
 * Modelled on the diabrowser.com hero: a near-white canvas with a single
 * large grapefruit-red wash anchored in one corner, plus a pale blue
 * accent on the opposite side. Heavily blurred, very low opacity, slow
 * drift. The goal is a tasteful warm atmosphere — not a colour-mesh
 * light show.
 *
 * `prefers-reduced-motion` freezes the drift (see globals.css).
 */
export function AnimatedBackdrop() {
  return (
    <div
      aria-hidden="true"
      className="dia-mesh-fixed pointer-events-none fixed inset-0 -z-10"
    >
      <div className="dia-mesh-blob dia-mesh-blob-1" />
      <div className="dia-mesh-blob dia-mesh-blob-2" />
    </div>
  );
}
