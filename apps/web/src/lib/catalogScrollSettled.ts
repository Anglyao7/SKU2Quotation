// A cached page can arrive before smooth scrolling reaches its first row. Hold
// new image requests until then, so intermediate rows don't steal their slots.
export function onCatalogScrollSettled(done: () => void) {
  let idle: ReturnType<typeof setTimeout>;
  let finished = false;
  const cleanup = () => {
    clearTimeout(idle);
    clearTimeout(deadline);
    window.removeEventListener("scroll", onScroll);
    window.removeEventListener("scrollend", finish);
  };
  const finish = () => {
    if (finished) return;
    finished = true;
    cleanup();
    done();
  };
  const onScroll = () => {
    clearTimeout(idle);
    idle = setTimeout(finish, 140);
  };
  const deadline = setTimeout(finish, 1_200);
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("scrollend", finish);
  onScroll(); // Already at the top / browsers without scrollend.
  return () => { finished = true; cleanup(); };
}
