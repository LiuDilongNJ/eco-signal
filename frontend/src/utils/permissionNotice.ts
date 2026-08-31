/**
 * Broadcast channel for "permission denied" (HTTP 403) responses.
 *
 * The API client cannot import the UI toast directly without creating an import
 * cycle, so it emits this event and PermissionDeniedWatcher renders the notice.
 * Unlike a 401 this must never start the login flow: the session is valid, the
 * user simply lacks the grant.
 */

export const PERMISSION_DENIED_EVENT = "eco-permission-denied"

export const DEFAULT_PERMISSION_DENIED_MESSAGE =
    "You do not have permission to perform this action"

export interface PermissionDeniedDetail {
    endpoint: string
    message: string
}

/** Server details are echoed verbatim; anything unhelpful falls back to the generic text. */
export function resolvePermissionDeniedMessage(data: unknown): string {
    const detail = data && typeof data === "object"
        ? (data as Record<string, unknown>).detail
        : undefined
    if (typeof detail === "string" && detail.trim() !== "") return detail
    return DEFAULT_PERMISSION_DENIED_MESSAGE
}

export function dispatchPermissionDenied(endpoint: string, data: unknown): void {
    if (typeof window === "undefined") return
    const detail: PermissionDeniedDetail = {
        endpoint,
        message: resolvePermissionDeniedMessage(data),
    }
    window.dispatchEvent(new CustomEvent<PermissionDeniedDetail>(PERMISSION_DENIED_EVENT, { detail }))
}
