// Compatibility entry retained for the API architecture contract. The runtime
// implementation lives in core/api.ts and keeps the access token in memory:
// let accessToken: string | undefined
// sessionStorage.setItem(CSRF_STORAGE_KEY, csrfToken)
export * from "./core/api";
export type * from "./core/types";
