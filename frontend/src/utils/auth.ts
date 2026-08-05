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

let loginRequiredDispatchPending = false

/**
 * Clear auth state and prompt login modal on the current page.
 * Idempotent until resetLoginRequiredDispatch(): repeated 401s must not
 * re-fire auth-change events, or listeners refetch and loop on 401 forever.
 */
export function dispatchLoginRequired() {
    if (typeof window === "undefined") return
    if (loginRequiredDispatchPending) return
    loginRequiredDispatchPending = true
    authUtils.clearAuth()
    window.dispatchEvent(new CustomEvent(AUTH_LOGIN_REQUIRED_EVENT))
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

export const authUtils = {
    getToken: () => localStorage.getItem("accessToken"),
    hasToken: () => Boolean(localStorage.getItem("accessToken")),
    setToken: (token: string) => localStorage.setItem("accessToken", token),
    removeToken: () => localStorage.removeItem("accessToken"),

    getUser: () => localStorage.getItem("loggedInUser"),
    setUser: (username: string) => localStorage.setItem("loggedInUser", username),
    removeUser: () => localStorage.removeItem("loggedInUser"),

    clearAuth: () => {
        // Idempotent: skip the auth-change broadcast when nothing is stored,
        // so repeated logout paths don't trigger redundant refetch cascades.
        const hadAuth =
            localStorage.getItem("accessToken") !== null ||
            localStorage.getItem("loggedInUser") !== null
        if (!hadAuth) return
        localStorage.removeItem("accessToken")
        localStorage.removeItem("loggedInUser")
        dispatchAuthChange()
    }
}
