export type SaveState = "READ_ONLY" | "SAVING" | "FAILED" | "UNSAVED" | "SAVED";

export function saveState({ readOnly, saving, dirty, failed }: {
  readOnly: boolean; saving: boolean; dirty: boolean; failed: boolean;
}): SaveState {
  if (readOnly) return "READ_ONLY";
  if (saving) return "SAVING";
  if (failed && dirty) return "FAILED";
  return dirty ? "UNSAVED" : "SAVED";
}

/** Only discard the exact edits acknowledged by the server, never newer typing. */
export function acknowledgeEdits<T extends object>(current: Record<string, T>, submitted: Record<string, T>): Record<string, T> {
  return Object.fromEntries(Object.entries(current).filter(([id, edit]) => edit !== submitted[id]));
}
