// Keep the original URL (including its version) so the detail gallery can reuse
// the same browser cache. This queue controls downloads, not image resolution.
export type CatalogImagePriority = 0 | 1 | 2; // visible, next row, next page
type Listener = { priority: CatalogImagePriority; done: (loaded: boolean) => void };
type ImageJob = {
  url: string;
  listeners: Set<Listener>;
  active: boolean;
  startedPriority: CatalogImagePriority;
};

export function canPrefetchStorefrontResources() {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  return !connection?.saveData && document.visibilityState === "visible";
}

export class StorefrontImageQueue {
  private jobs = new Map<string, ImageJob>();
  private completed = new Map<string, number>();
  private scheduled = false;

  constructor(private createImage: () => HTMLImageElement = () => new Image()) {}

  request(url: string, priority: CatalogImagePriority, done: Listener["done"] = () => {}) {
    const listener: Listener = { priority, done };
    const completedAt = this.completed.get(url);
    if (completedAt !== undefined && Date.now() - completedAt < 120_000) {
      let cancelled = false;
      queueMicrotask(() => { if (!cancelled) done(true); });
      return { cancel: () => { cancelled = true; }, setPriority: (_priority: CatalogImagePriority) => {} };
    }
    this.completed.delete(url);
    let job = this.jobs.get(url);
    if (!job) {
      job = { url, listeners: new Set(), active: false, startedPriority: priority };
      this.jobs.set(url, job);
    }
    job.listeners.add(listener);
    this.schedule();
    return {
      cancel: () => {
        job.listeners.delete(listener);
        // Already-started downloads finish within the same four slots. Removing
        // queued work avoids fetching pages/categories the visitor has left.
        if (!job.active && !job.listeners.size && this.jobs.get(url) === job) this.jobs.delete(url);
        this.schedule();
      },
      setPriority: (next: CatalogImagePriority) => {
        listener.priority = next;
        this.schedule();
      },
    };
  }

  private priority(job: ImageJob): CatalogImagePriority {
    return job.listeners.size
      ? Math.min(...Array.from(job.listeners, (listener) => listener.priority)) as CatalogImagePriority
      : job.startedPriority;
  }

  private schedule() {
    if (this.scheduled) return;
    this.scheduled = true;
    // Batch both IntersectionObserver callbacks before assigning slots.
    setTimeout(() => { this.scheduled = false; this.pump(); }, 0);
  }

  private pump() {
    const active = Array.from(this.jobs.values()).filter((job) => job.active);
    let count = active.length;
    let nearCount = active.filter((job) => this.priority(job) === 1).length;
    let backgroundCount = active.filter((job) => this.priority(job) === 2).length;
    const waiting = Array.from(this.jobs.values())
      .filter((job) => !job.active && job.listeners.size)
      .sort((a, b) => this.priority(a) - this.priority(b));
    for (const job of waiting) {
      if (count >= 4) break;
      const priority = this.priority(job);
      if (priority === 1 && nearCount >= 2) continue;
      // Next-page originals trickle in one at a time, never ahead of this page.
      if (priority === 2 && (backgroundCount >= 1 || waiting.some((item) => (
        item !== job && !item.active && this.priority(item) < 2
      )))) continue;
      count += 1;
      if (priority === 1) nearCount += 1;
      if (priority === 2) backgroundCount += 1;
      this.start(job, priority);
    }
  }

  private start(job: ImageJob, priority: CatalogImagePriority) {
    job.active = true;
    job.startedPriority = priority;
    const image = this.createImage();
    image.decoding = "async";
    image.fetchPriority = priority === 0 ? "high" : "low";
    let settled = false;
    const finish = (loaded: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      image.onload = null;
      image.onerror = null;
      this.jobs.delete(job.url);
      if (loaded) {
        this.completed.set(job.url, Date.now());
        if (this.completed.size > 128) this.completed.delete(this.completed.keys().next().value!);
      }
      for (const listener of job.listeners) listener.done(loaded);
      this.schedule();
    };
    const timeout = setTimeout(() => {
      image.removeAttribute("src");
      finish(false);
    }, 45_000);
    image.onload = () => finish(true);
    image.onerror = () => finish(false);
    image.src = job.url;
  }
}

export const storefrontImageQueue = new StorefrontImageQueue();

// Shared observers for the entire grid, rather than one pair per product.
type WatchedImage = { visible: boolean; near: boolean; update: (priority: 0 | 1 | null) => void };
const watchedImages = new Map<Element, WatchedImage>();
let visibleObserver: IntersectionObserver | undefined;
let nearObserver: IntersectionObserver | undefined;

export function observeCatalogImage(element: Element, update: WatchedImage["update"]) {
  if (typeof IntersectionObserver === "undefined") {
    // Older browsers still defer off-screen sources; native lazy thresholds are
    // deliberately not used, because they can fetch an entire page at once.
    const measure = () => {
      const bounds = element.getBoundingClientRect();
      update(bounds.bottom > 0 && bounds.top < window.innerHeight ? 0
        : bounds.bottom > 0 && bounds.top < window.innerHeight + 320 ? 1 : null);
    };
    measure();
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
    };
  }
  const handle = (kind: "visible" | "near") => (entries: IntersectionObserverEntry[]) => {
    for (const entry of entries) {
      const item = watchedImages.get(entry.target);
      if (!item) continue;
      item[kind] = entry.isIntersecting;
      item.update(item.visible ? 0 : item.near ? 1 : null);
    }
  };
  visibleObserver ??= new IntersectionObserver(handle("visible"));
  nearObserver ??= new IntersectionObserver(handle("near"), { rootMargin: "0px 0px 320px 0px" });
  watchedImages.set(element, { visible: false, near: false, update });
  visibleObserver.observe(element);
  nearObserver.observe(element);
  return () => {
    visibleObserver?.unobserve(element);
    nearObserver?.unobserve(element);
    watchedImages.delete(element);
    if (!watchedImages.size) {
      visibleObserver?.disconnect();
      nearObserver?.disconnect();
      visibleObserver = undefined;
      nearObserver = undefined;
    }
  };
}

export function prefetchCatalogImages(urls: (string | null | undefined)[]) {
  if (!canPrefetchStorefrontResources()) return () => {};
  // Enough for the next screen on desktop, without downloading all 24 originals.
  const requests = [...new Set(urls.filter((url): url is string => Boolean(url)))]
    .slice(0, 8).map((url) => storefrontImageQueue.request(url, 2));
  return () => requests.forEach((request) => request.cancel());
}
