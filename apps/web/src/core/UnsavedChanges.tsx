import { AlertDialog, Button } from "@radix-ui/themes";
import { createContext, useCallback, useContext, useEffect, useId, useState, type ReactNode } from "react";
import { useBlocker } from "react-router-dom";
import { useLocale } from "./LocaleContext";

const UnsavedContext = createContext<((id: string, enabled: boolean) => void) | null>(null);

/** One router blocker for all console forms, including editors inside portals. */
export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const { t } = useLocale();
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const register = useCallback((id: string, enabled: boolean) => setDirty((current) => {
    if (current.has(id) === enabled) return current;
    const next = new Set(current);
    if (enabled) next.add(id); else next.delete(id);
    return next;
  }), []);
  const shouldBlock = useCallback(({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => dirty.size > 0 && currentLocation.pathname !== nextLocation.pathname, [dirty]);
  const blocker = useBlocker(shouldBlock);
  useEffect(() => {
    if (!dirty.size) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty.size]);
  return <UnsavedContext.Provider value={register}>
    {children}
    <AlertDialog.Root open={blocker.state === "blocked"}>
      <AlertDialog.Content maxWidth="440px">
        <AlertDialog.Title>{t("有未保存的修改")}</AlertDialog.Title>
        <AlertDialog.Description>{t("离开会丢弃未保存的内容。")}</AlertDialog.Description>
        <div className="core-dialog-actions">
          <Button variant="soft" color="gray" onClick={() => blocker.state === "blocked" && blocker.reset()}>{t("继续编辑")}</Button>
          <Button color="red" onClick={() => { if (blocker.state === "blocked") { setDirty(new Set()); blocker.proceed(); } }}>{t("放弃修改并离开")}</Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>
  </UnsavedContext.Provider>;
}

export function useUnsavedChanges(enabled: boolean) {
  const id = useId();
  const register = useContext(UnsavedContext);
  useEffect(() => { register?.(id, enabled); return () => register?.(id, false); }, [register, id, enabled]);
}
