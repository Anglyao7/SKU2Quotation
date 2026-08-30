const BLOCKED_ELEMENTS = [
  "script",
  "iframe",
  "frame",
  "frameset",
  "object",
  "embed",
  "applet",
  "base",
  "meta[http-equiv]",
].join(",");

const URL_ATTRIBUTES = new Set([
  "href",
  "src",
  "poster",
  "xlink:href",
  "action",
  "formaction",
]);

const SAFE_DATA_IMAGE = /^data:image\/(?:png|gif|jpe?g|webp|avif|svg\+xml);/i;
const UNSAFE_SCHEME = /^(?:javascript|vbscript):/i;

function unwrapForms(document: Document) {
  document.querySelectorAll("form").forEach((form) => {
    form.replaceWith(...Array.from(form.childNodes));
  });
}

function sanitizeAttributes(document: Document) {
  document.querySelectorAll("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim();
      if (name.startsWith("on") || name === "srcdoc") {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (!URL_ATTRIBUTES.has(name)) continue;
      if (UNSAFE_SCHEME.test(value)) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (value.toLowerCase().startsWith("data:") && !SAFE_DATA_IMAGE.test(value)) {
        element.removeAttribute(attribute.name);
      }
    }
    if (element instanceof HTMLAnchorElement) {
      element.target = "_blank";
      element.rel = "noopener noreferrer nofollow";
    }
  });
}

export function prepareStorefrontCustomPageHtml(source: string, title: string) {
  const document = new DOMParser().parseFromString(source, "text/html");
  document.querySelectorAll(BLOCKED_ELEMENTS).forEach((element) => element.remove());
  unwrapForms(document);
  sanitizeAttributes(document);

  document.documentElement.lang ||= "en";
  document.title = title;

  const viewport = document.createElement("meta");
  viewport.name = "viewport";
  viewport.content = "width=device-width, initial-scale=1, viewport-fit=cover";

  const contentSecurityPolicy = document.createElement("meta");
  contentSecurityPolicy.httpEquiv = "Content-Security-Policy";
  contentSecurityPolicy.content = [
    "default-src 'none'",
    "script-src 'none'",
    "connect-src 'none'",
    "object-src 'none'",
    "frame-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
    "img-src https: http: data: blob:",
    "media-src https: http: data: blob:",
    "font-src https: http: data:",
    "style-src 'unsafe-inline' https: http:",
  ].join("; ");

  const compatibilityStyle = document.createElement("style");
  compatibilityStyle.dataset.aitradeCompatibility = "responsive";
  compatibilityStyle.textContent = `
    :root { color-scheme: light dark; }
    html { width: 100%; max-width: 100%; box-sizing: border-box; overflow-x: hidden; }
    *, *::before, *::after { box-sizing: inherit; }
    body { width: 100%; max-width: 100%; min-height: 1px; margin: 0; overflow-x: hidden; }
    img, picture, video, canvas, svg { max-width: 100%; height: auto; }
    table { display: block; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    pre, code { max-width: 100%; overflow-wrap: anywhere; white-space: pre-wrap; }
    iframe, object, embed { display: none !important; }
    @media (max-width: 767px) {
      body { min-width: 0 !important; }
      [style*="min-width"] { min-width: 0 !important; }
    }
  `;

  document.head.prepend(compatibilityStyle);
  document.head.prepend(viewport);
  document.head.prepend(contentSecurityPolicy);
  return `<!doctype html>\n${document.documentElement.outerHTML}`;
}
