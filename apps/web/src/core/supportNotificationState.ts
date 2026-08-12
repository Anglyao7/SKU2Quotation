export type HumanRequestIdentity = {
  conversationId: string;
  requestedAt: string;
};

export type HumanRequestTracker = {
  knownKeys: ReadonlySet<string>;
  newestRequestedAt: number | null;
};

export function humanRequestKey(request: HumanRequestIdentity) {
  return `${request.conversationId}:${request.requestedAt}`;
}

function requestedAtMillis(request: HumanRequestIdentity) {
  const value = Date.parse(request.requestedAt);
  return Number.isFinite(value) ? value : null;
}

export function mergeHumanRequestSnapshot<T extends HumanRequestIdentity>(
  tracker: HumanRequestTracker | null,
  requests: readonly T[],
  notify: boolean,
): { tracker: HumanRequestTracker; arrivals: T[] } {
  const knownKeys = new Set(tracker?.knownKeys ?? []);
  const previousNewest = tracker?.newestRequestedAt ?? null;
  const arrivals = tracker && notify
    ? requests.filter((request) => {
        if (knownKeys.has(humanRequestKey(request))) return false;
        const requestedAt = requestedAtMillis(request);
        return requestedAt !== null
          && (previousNewest === null || requestedAt >= previousNewest);
      })
    : [];

  let newestRequestedAt = previousNewest;
  requests.forEach((request) => {
    knownKeys.add(humanRequestKey(request));
    const requestedAt = requestedAtMillis(request);
    if (
      requestedAt !== null
      && (newestRequestedAt === null || requestedAt > newestRequestedAt)
    ) {
      newestRequestedAt = requestedAt;
    }
  });

  return {
    tracker: { knownKeys, newestRequestedAt },
    arrivals,
  };
}
