import { ApiError } from "@/api/client"
import { usersApi } from "@/api/endpoints/users"
import { authUtils, dispatchAuthChange } from "@/utils/auth"

const MIN_CHECK_INTERVAL_MS = 30_000
const VISIBLE_POLL_INTERVAL_MS = 15 * 60 * 1000

let lastCheckAt = 0
let checkSessionPromise: Promise<void> | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let started = false

function isPageVisible(): boolean {
    return typeof document !== "undefined" && document.visibilityState === "visible"
}

async function checkSessionIfNeeded(): Promise<void> {
    if (!authUtils.hasToken() || !isPageVisible()) return

    const now = Date.now()
    if (now - lastCheckAt < MIN_CHECK_INTERVAL_MS) return

    if (!checkSessionPromise) {
        checkSessionPromise = (async () => {
            lastCheckAt = Date.now()
            try {
                const res = await usersApi.getMe()
                if ((res.code === 0 || res.code === 200) && res.data) {
                    const name = typeof res.data.name === "string" ? res.data.name.trim() : ""
                    const username = typeof res.data.username === "string" ? res.data.username.trim() : ""
                    const displayName = name || username
                    if (displayName && displayName !== authUtils.getUser()) {
                        authUtils.setUser(displayName)
                        dispatchAuthChange()
                    }
                }
            } catch (error) {
                if (error instanceof ApiError && error.status === 401) {
                    return
                }
            }
        })().finally(() => {
            checkSessionPromise = null
        })
    }

    await checkSessionPromise
}

function onVisibilityOrFocus() {
    if (!isPageVisible()) return
    void checkSessionIfNeeded()
}

function onPollTick() {
    if (!isPageVisible()) return
    void checkSessionIfNeeded()
}

export function startSessionActivityMonitor(): void {
    if (started || typeof window === "undefined") return
    started = true

    document.addEventListener("visibilitychange", onVisibilityOrFocus)
    window.addEventListener("focus", onVisibilityOrFocus)
    pollTimer = setInterval(onPollTick, VISIBLE_POLL_INTERVAL_MS)

    if (isPageVisible()) {
        void checkSessionIfNeeded()
    }
}

export function stopSessionActivityMonitor(): void {
    if (!started || typeof window === "undefined") return
    started = false

    document.removeEventListener("visibilitychange", onVisibilityOrFocus)
    window.removeEventListener("focus", onVisibilityOrFocus)
    if (pollTimer !== null) {
        clearInterval(pollTimer)
        pollTimer = null
    }
}
