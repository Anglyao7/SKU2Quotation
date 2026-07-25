import type { CSSProperties } from "react";

export const TAG_COLOR_PALETTE = [
  "#287D6E",
  "#3F6F9C",
  "#725B9B",
  "#985B73",
  "#A45F3E",
  "#A97825",
  "#58784D",
  "#765C49",
] as const;

const HEX_COLOR = /^#[0-9A-F]{6}$/;

export function normalizeTagColor(value?: string | null) {
  const normalized = value?.trim().toUpperCase() ?? "";
  return HEX_COLOR.test(normalized) ? normalized : undefined;
}

export function automaticTagColor(seed: string) {
  const normalized = seed.trim().toLowerCase() || "tag";
  let hash = 2166136261;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return TAG_COLOR_PALETTE[(hash >>> 0) % TAG_COLOR_PALETTE.length];
}

export function resolveTagColor(seed: string, customColor?: string | null) {
  return normalizeTagColor(customColor) ?? automaticTagColor(seed);
}

function readableInk(color: string) {
  const red = Number.parseInt(color.slice(1, 3), 16);
  const green = Number.parseInt(color.slice(3, 5), 16);
  const blue = Number.parseInt(color.slice(5, 7), 16);
  const luminance = (red * 299 + green * 587 + blue * 114) / 1000;
  return luminance > 164 ? "#17201D" : "#F8FBFA";
}

type TagGlassStyle = CSSProperties & {
  "--tag-glass-color": string;
  "--tag-glass-ink": string;
};

export function tagGlassStyle(seed: string, customColor?: string | null): TagGlassStyle {
  const color = resolveTagColor(seed, customColor);
  return {
    "--tag-glass-color": color,
    "--tag-glass-ink": readableInk(color),
  };
}
