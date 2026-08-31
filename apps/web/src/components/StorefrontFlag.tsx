import type { StorefrontLocale } from "../types";

function FlagArtwork({ locale }: { locale: StorefrontLocale }) {
  switch (locale) {
    case "en-US":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#b22234" />
          {[1.23, 3.69, 6.15, 8.61, 11.07, 13.53].map((y) => (
            <rect key={y} y={y} width="24" height="1.23" fill="#fff" />
          ))}
          <rect width="10.5" height="8.62" fill="#3c3b6e" />
          {[2, 5, 8].flatMap((x) => [1.6, 4.2, 6.8].map((y) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r=".42" fill="#fff" />
          )))}
        </svg>
      );
    case "es":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#aa151b" />
          <rect y="4" width="24" height="8" fill="#f1bf00" />
          <rect x="7" y="6.1" width="1.7" height="3.8" rx=".35" fill="#aa151b" />
          <circle cx="7.85" cy="5.7" r=".65" fill="#aa151b" />
        </svg>
      );
    case "tr":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#e30a17" />
          <circle cx="9.5" cy="8" r="4" fill="#fff" />
          <circle cx="11" cy="7.6" r="3.25" fill="#e30a17" />
          <path d="m14.2 8 2.45-.8-1.5 2.08.02-2.57 1.48 2.1Z" fill="#fff" />
        </svg>
      );
    case "ar":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#006c35" />
          <path d="M5 5.2h14M6.5 6.8h11M8 4v4M11 4v4M14 4v4M17 4v4" stroke="#fff" strokeWidth=".55" strokeLinecap="round" />
          <path d="M5.5 11.2h12.4l1-.65M8.3 10.45v1.5" stroke="#fff" strokeWidth=".72" strokeLinecap="round" />
        </svg>
      );
    case "ja":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#fff" />
          <circle cx="12" cy="8" r="4.15" fill="#bc002d" />
        </svg>
      );
    case "ko":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#fff" />
          <path d="M8.8 8a3.2 3.2 0 0 1 6.4 0c-1.05-1.1-2.15-1.1-3.2 0s-2.15 1.1-3.2 0Z" fill="#cd2e3a" />
          <path d="M15.2 8a3.2 3.2 0 0 1-6.4 0c1.05 1.1 2.15 1.1 3.2 0s2.15-1.1 3.2 0Z" fill="#0047a0" />
          <g fill="#111">
            <rect x="5.1" y="3.6" width="3.6" height=".55" transform="rotate(-35 6.9 3.9)" />
            <rect x="5.8" y="4.6" width="3.6" height=".55" transform="rotate(-35 7.6 4.9)" />
            <rect x="15.3" y="11.8" width="3.6" height=".55" transform="rotate(-35 17.1 12.1)" />
            <rect x="14.6" y="10.8" width="3.6" height=".55" transform="rotate(-35 16.4 11.1)" />
          </g>
        </svg>
      );
    case "pt":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#ff0000" />
          <rect width="9.6" height="16" fill="#046a38" />
          <circle cx="9.6" cy="8" r="3" fill="#ffcc29" />
          <path d="M8.2 6.3h2.8v3.5H8.2Z" fill="#fff" stroke="#d21034" strokeWidth=".45" />
        </svg>
      );
    case "fr":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="8" height="16" fill="#0055a4" />
          <rect x="8" width="8" height="16" fill="#fff" />
          <rect x="16" width="8" height="16" fill="#ef4135" />
        </svg>
      );
    case "fa":
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="5.34" fill="#239f40" />
          <rect y="5.33" width="24" height="5.34" fill="#fff" />
          <rect y="10.66" width="24" height="5.34" fill="#da0000" />
          <path d="M12 5.95c1.2 1.08 1.55 2.17 1.05 3.25-.25.53-.6.88-1.05 1.05-.45-.17-.8-.52-1.05-1.05-.5-1.08-.15-2.17 1.05-3.25Z" fill="#da0000" />
          <path d="M3 5.05h18M3 10.95h18" stroke="#fff" strokeWidth=".34" strokeDasharray=".65 .45" />
        </svg>
      );
    case "zh-CN":
    default:
      return (
        <svg viewBox="0 0 24 16" focusable="false">
          <rect width="24" height="16" fill="#ee1c25" />
          <path d="m5 2.3.9 1.85 2.05.3-1.48 1.43.35 2.03L5 6.96 3.18 7.9l.35-2.03-1.48-1.43 2.05-.3Z" fill="#ffde00" />
          <circle cx="9.2" cy="2.6" r=".55" fill="#ffde00" />
          <circle cx="10.4" cy="4.2" r=".55" fill="#ffde00" />
          <circle cx="10.1" cy="6.2" r=".55" fill="#ffde00" />
          <circle cx="8.7" cy="7.6" r=".55" fill="#ffde00" />
        </svg>
      );
  }
}

export function StorefrontFlag({
  locale,
  className = "",
}: {
  locale: StorefrontLocale;
  className?: string;
}) {
  return (
    <span className={`storefront-flag${className ? ` ${className}` : ""}`} aria-hidden="true">
      <FlagArtwork locale={locale} />
    </span>
  );
}
