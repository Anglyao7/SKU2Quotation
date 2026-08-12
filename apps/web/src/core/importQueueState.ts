export interface ImportFileIdentity {
  name: string;
  size: number;
  lastModified: number;
}

export function importFileIdentity(file: ImportFileIdentity) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

export function selectUniqueImportFiles<T extends ImportFileIdentity>(
  currentFiles: readonly ImportFileIdentity[],
  selectedFiles: readonly T[],
  limit = 100,
) {
  const known = new Set(currentFiles.map(importFileIdentity));
  const unique: T[] = [];
  let duplicateCount = 0;

  selectedFiles.forEach((file) => {
    const identity = importFileIdentity(file);
    if (known.has(identity)) {
      duplicateCount += 1;
      return;
    }
    known.add(identity);
    unique.push(file);
  });

  const capacityRemaining = Math.max(0, limit - currentFiles.length);
  return {
    acceptedFiles: unique.slice(0, capacityRemaining),
    capacityRemaining,
    duplicateCount,
    overflowCount: Math.max(0, unique.length - capacityRemaining),
  };
}

export function resetFailedImportItem<T>(item: T) {
  return {
    ...item,
    status: "checking" as const,
    progress: 0,
    detection: undefined,
    job: undefined,
    error: undefined,
  };
}

export function removeImportItem<T extends { id: string }>(
  items: readonly T[],
  itemId: string,
) {
  return items.filter((item) => item.id !== itemId);
}
