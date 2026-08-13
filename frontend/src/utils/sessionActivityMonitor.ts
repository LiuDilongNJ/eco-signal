import { authUtils, expireIdleSession } from "@/utils/auth"

let timeoutTimer: ReturnType<typeof setTimeout> | null = null
let started = false

function isPageVisible(): boolean {
    return typeof document !== "undefined" && document.visibilityState === "visible"
}

function scheduleExpiryCheck(): void {
    if (timeoutTimer !== null) {
        clearTimeout(timeoutTimer)
        timeoutTimer = null
    }
    if (!authUtils.hasToken()) return

    const timeoutSeconds = authUtils.getIdleTimeoutSeconds()
    const lastActivityAt = authUtils.getLastActivityAt()
    if (timeoutSeconds <= 0 || lastActivityAt <= 0) return

    const remaining = lastActivityAt + timeoutSeconds * 1000 - Date.now()
    if (remaining <= 0) {
        void expireIdleSession()
        return
    }
    timeoutTimer = setTimeout(() => {
        timeoutTimer = null
        scheduleExpiryCheck()
    }, remaining)
}

function onVisibilityOrFocus() {
    if (!isPageVisible()) return
    scheduleExpiryCheck()
}

function onStorage(event: StorageEvent) {
    if (event.key === "authSessionLastActivityAt" || event.key === "authSessionIdleTimeoutSeconds") {
        scheduleExpiryCheck()
    }
}

function onAuthChange() {
    scheduleExpiryCheck()
}

export function startSessionActivityMonitor(): void {
    if (started || typeof window === "undefined") return
    started = true

    document.addEventListener("visibilitychange", onVisibilityOrFocus)
    window.addEventListener("focus", onVisibilityOrFocus)
    window.addEventListener("storage", onStorage)
    window.addEventListener("eco-auth-change", onAuthChange)
    window.addEventListener("eco-auth-session-activity", onAuthChange)

    if (isPageVisible()) {
        scheduleExpiryCheck()
    }
}

export function stopSessionActivityMonitor(): void {
    if (!started || typeof window === "undefined") return
    started = false

    document.removeEventListener("visibilitychange", onVisibilityOrFocus)
    window.removeEventListener("focus", onVisibilityOrFocus)
    window.removeEventListener("storage", onStorage)
    window.removeEventListener("eco-auth-change", onAuthChange)
    window.removeEventListener("eco-auth-session-activity", onAuthChange)
    if (timeoutTimer !== null) {
        clearTimeout(timeoutTimer)
        timeoutTimer = null
    }
}
