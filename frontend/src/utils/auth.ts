/** 未登录或登出后的落地页（与路由 `/` 一致；`/index` 仍为同一首页） */
export const AUTH_LANDING_PATH = "/"
const AUTH_API_PREFIX = "/v1"

/** 登录/登出后通知各页面刷新列表（如项目下拉选项） */
export function dispatchAuthChange() {
    if (typeof window === "undefined") return
    window.dispatchEvent(new CustomEvent("eco-auth-change"))
}

/** 401 会话失效时通知全局 LoginModal 弹出（不跳转页面） */
export const AUTH_LOGIN_REQUIRED_EVENT = "eco-auth-login-required"
export type LoginRequiredReason = "unauthorized" | "idle_timeout"
export interface LoginRequiredDetail {
    reason: LoginRequiredReason
    idleTimeoutSeconds: number
}

const SESSION_IDLE_TIMEOUT_KEY = "authSessionIdleTimeoutSeconds"
const SESSION_LAST_ACTIVITY_KEY = "authSessionLastActivityAt"
const SESSION_ACTIVITY_EVENT = "eco-auth-session-activity"

let loginRequiredDispatchPending = false

/**
 * Clear auth state and prompt login modal on the current page.
 * Idempotent until resetLoginRequiredDispatch(): repeated 401s must not
 * re-fire auth-change events, or listeners refetch and loop on 401 forever.
 */
export function dispatchLoginRequired(reason: LoginRequiredReason = "unauthorized") {
    if (typeof window === "undefined") return
    if (loginRequiredDispatchPending) return
    loginRequiredDispatchPending = true
    const detail: LoginRequiredDetail = {
        reason,
        idleTimeoutSeconds: authUtils.getIdleTimeoutSeconds(),
    }
    authUtils.clearAuth()
    window.dispatchEvent(new CustomEvent<LoginRequiredDetail>(AUTH_LOGIN_REQUIRED_EVENT, { detail }))
}

/** Allow a subsequent 401 to open the login modal again. */
export function resetLoginRequiredDispatch() {
    loginRequiredDispatchPending = false
}

function resolveApiBaseUrlForAuth(): string {
    const explicit = import.meta.env.VITE_API_BASE_URL as string | undefined
    if (explicit != null && String(explicit).trim() !== "") {
        return String(explicit).replace(/\/$/, "")
    }
    if (import.meta.env.DEV) {
        return "/api"
    }
    const originOnly = import.meta.env.VITE_API_URL as string | undefined
    if (originOnly != null && String(originOnly).trim() !== "") {
        const o = String(originOnly).trim().replace(/\/$/, "")
        return o.endsWith("/api") ? o : `${o}/api`
    }
    return "/api"
}

/** Clear auth state and redirect to landing page. */
export function clearAuthAndRedirectToIndex() {
    authUtils.clearAuth()
    if (typeof window === "undefined") return
    window.location.assign(AUTH_LANDING_PATH)
}

/** Logout current refresh session and always clear local auth state. */
export async function logoutAndRedirectToIndex() {
    const logoutUrl = `${resolveApiBaseUrlForAuth()}${AUTH_API_PREFIX}/auth-tokens/current`
    try {
        await fetch(logoutUrl, {
            method: "DELETE",
            credentials: "include",
        })
    } catch {
        // Ignore network errors and continue clearing local state.
    } finally {
        clearAuthAndRedirectToIndex()
    }
}

export async function expireIdleSession() {
    const logoutUrl = `${resolveApiBaseUrlForAuth()}${AUTH_API_PREFIX}/auth-tokens/current`
    try {
        await fetch(logoutUrl, {
            method: "DELETE",
            credentials: "include",
        })
    } catch {
        // The local session must still expire when the network is unavailable.
    } finally {
        dispatchLoginRequired("idle_timeout")
    }
}

export const authUtils = {
    getToken: () => localStorage.getItem("accessToken"),
    hasToken: () => Boolean(localStorage.getItem("accessToken")),
    setToken: (token: string) => localStorage.setItem("accessToken", token),
    removeToken: () => localStorage.removeItem("accessToken"),

    getUser: () => localStorage.getItem("loggedInUser"),
    setUser: (username: string) => localStorage.setItem("loggedInUser", username),
    removeUser: () => localStorage.removeItem("loggedInUser"),

    getIdleTimeoutSeconds: () => Number(localStorage.getItem(SESSION_IDLE_TIMEOUT_KEY) ?? 0),
    getLastActivityAt: () => Number(localStorage.getItem(SESSION_LAST_ACTIVITY_KEY) ?? 0),
    setIdleTimeoutSeconds: (seconds: number) => {
        const normalized = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0
        localStorage.setItem(SESSION_IDLE_TIMEOUT_KEY, String(normalized))
        if (normalized > 0) {
            localStorage.setItem(SESSION_LAST_ACTIVITY_KEY, String(Date.now()))
        } else {
            localStorage.removeItem(SESSION_LAST_ACTIVITY_KEY)
        }
        window.dispatchEvent(new CustomEvent(SESSION_ACTIVITY_EVENT))
    },
    markSessionActivity: () => {
        if (Number(localStorage.getItem(SESSION_IDLE_TIMEOUT_KEY) ?? 0) <= 0) return
        localStorage.setItem(SESSION_LAST_ACTIVITY_KEY, String(Date.now()))
        window.dispatchEvent(new CustomEvent(SESSION_ACTIVITY_EVENT))
    },

    clearAuth: () => {
        // Idempotent: skip the auth-change broadcast when nothing is stored,
        // so repeated logout paths don't trigger redundant refetch cascades.
        const hadAuth =
            localStorage.getItem("accessToken") !== null ||
            localStorage.getItem("loggedInUser") !== null ||
            localStorage.getItem(SESSION_IDLE_TIMEOUT_KEY) !== null ||
            localStorage.getItem(SESSION_LAST_ACTIVITY_KEY) !== null
        if (!hadAuth) return
        localStorage.removeItem("accessToken")
        localStorage.removeItem("loggedInUser")
        localStorage.removeItem(SESSION_IDLE_TIMEOUT_KEY)
        localStorage.removeItem(SESSION_LAST_ACTIVITY_KEY)
        dispatchAuthChange()
    }
}
