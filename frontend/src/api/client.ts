/**
 * API Client - 统一的 HTTP 请求封装
 *
 * 特性:
 * - 自动附加 baseURL
 * - 请求/响应拦截
 * - 统一错误处理
 * - Token 自动注入
 * - 类型安全
 */

/**
 * 解析 API 根路径（与后端 FastAPI 的 `API_V1_STR` 前缀一致，一般为 `/api`）。
 * - `VITE_API_BASE_URL` 优先：如 `/api` 或 `https://host.example.com/api`
 * - 生产 / preview：`VITE_API_URL` 仅写后端 origin 时自动补 `/api`
 * - **开发 `npm run dev`**：未显式设置 `VITE_API_BASE_URL` 时固定为 `/api`，走 Vite 代理、与页面同源，
 *   避免 `127.0.0.1:5173` 页面直连 `localhost:8000` 触发浏览器 CORS。
 */
export function resolveApiBaseUrl(): string {
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

const API_BASE_URL = resolveApiBaseUrl()

export class ApiError extends Error {
    constructor(
        public status: number,
        public statusText: string,
        public data?: unknown
    ) {
        // 优先显示 detail，因为 detail 通常包含更具体的错误描述（如表单校验失败原因）
        let errorMsg = ""
        const errorData = data && typeof data === "object" ? data as Record<string, unknown> : undefined
        const detail = errorData?.detail
        if (detail) {
            if (typeof detail === "string") {
                errorMsg = detail
            } else if (Array.isArray(detail)) {
                // 处理 FastAPI 默认的数组格式 detail
                errorMsg = detail.map((item) => {
                    const issue = item && typeof item === "object" ? item as Record<string, unknown> : {}
                    const location = Array.isArray(issue.loc) ? issue.loc.join(".") : "request"
                    return `${location}: ${String(issue.msg ?? "invalid value")}`
                }).join("; ")
            } else {
                errorMsg = JSON.stringify(detail)
            }
        }
        
        if (!errorMsg) {
            errorMsg = typeof errorData?.message === "string" ? errorData.message : `API Error: ${status} ${statusText}`
        }

        super(errorMsg)
        this.name = "ApiError"
    }

}

type QueryParams = object

export interface DownloadResponse {
    blob: Blob
    filename?: string
}

interface RequestConfig extends Omit<RequestInit, "body"> {
    params?: QueryParams
    body?: unknown
    ignoreUnauthorized?: boolean
}

export function parseContentDispositionFilename(contentDisposition: string | null): string | undefined {
    if (!contentDisposition) return undefined

    const utf8Match = contentDisposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)
    if (utf8Match?.[1]) {
        try {
            return decodeURIComponent(utf8Match[1].trim().replace(/^"(.*)"$/, "$1"))
        } catch {
            return utf8Match[1].trim().replace(/^"(.*)"$/, "$1")
        }
    }

    const basicMatch = contentDisposition.match(/filename\s*=\s*([^;]+)/i)
    if (!basicMatch?.[1]) return undefined

    return basicMatch[1].trim().replace(/^"(.*)"$/, "$1")
}

/**
 * 构建带查询参数的 URL
 */
function buildUrl(endpoint: string, params?: RequestConfig["params"]): string {
    const url = new URL(`${API_BASE_URL}${endpoint}`, window.location.origin)
    if (params) {
        Object.entries(params).forEach(([key, value]) => {
            if (value !== undefined) {
                url.searchParams.set(key, String(value))
            }
        })
    }
    return url.toString()
}

import { authUtils, dispatchAuthChange, dispatchLoginRequired } from "../utils/auth"
import { dispatchPermissionDenied } from "../utils/permissionNotice"

/** 登录接口 401 不触发登录跳转（密码错误等）。 */
let refreshAccessTokenPromise: Promise<string | null> | null = null

function shouldIgnore401Redirect(endpoint: string): boolean {
    return endpoint.includes("/auth-tokens") || endpoint.includes("/auth-token-refreshes")
}

function onUnauthorized(status: number, endpoint: string, data: unknown, ignoreRedirect = false) {
    if (shouldIgnore401Redirect(endpoint) || ignoreRedirect) return

    if (status === 401) {
        console.warn(`[apiClient] Unauthorized (401) on endpoint: ${endpoint}. Prompting login...`)
        dispatchLoginRequired()
        return
    }

    // 403 表示会话有效但权限不足：只提示，不能触发登录流程。
    // 403 means the session is valid but the grant is missing: notify only,
    // never start the login flow.
    console.warn(`[apiClient] Forbidden (403) on endpoint: ${endpoint}.`)
    dispatchPermissionDenied(endpoint, data)
}

function shouldAttemptRefresh(endpoint: string): boolean {
    return !endpoint.includes("/auth-tokens") && !endpoint.includes("/auth-token-refreshes")
}

type AccessTokenResponse = {
    access_token?: string
    session_idle_timeout_seconds?: number
    data?: {
        access_token?: string
        session_idle_timeout_seconds?: number
    }
}

function extractAccessToken(payload: AccessTokenResponse | null): string | null {
    const token = payload?.data?.access_token ?? payload?.access_token
    return typeof token === "string" && token.length > 0 ? token : null
}

function storeAccessTokenResponse(payload: AccessTokenResponse | null): string | null {
    const token = extractAccessToken(payload)
    if (!token) return null
    const timeout = payload?.data?.session_idle_timeout_seconds ?? payload?.session_idle_timeout_seconds ?? 0
    authUtils.setToken(token)
    authUtils.setIdleTimeoutSeconds(timeout)
    return token
}

function isIdleTimeoutResponse(response: Response): boolean {
    return response.headers.get("X-Auth-Reason") === "idle_timeout"
}

export async function refreshAccessToken(): Promise<string | null> {
    if (!refreshAccessTokenPromise) {
        refreshAccessTokenPromise = (async () => {
            const response = await fetch(buildUrl("/v1/auth-token-refreshes"), {
                method: "POST",
                credentials: "include",
            })
            if (!response.ok) {
                if (response.status === 401 && isIdleTimeoutResponse(response)) {
                    dispatchLoginRequired("idle_timeout")
                }
                return null
            }
            const payload = (await response.json().catch(() => null)) as AccessTokenResponse | null
            return storeAccessTokenResponse(payload)
        })().finally(() => {
            refreshAccessTokenPromise = null
        })
    }
    return refreshAccessTokenPromise
}

/**
 * 应用启动时的会话静默恢复：localStorage 中没有 access token（如被浏览器清理）
 * 但 refresh cookie 可能仍有效时，先尝试刷新一次，避免误判为未登录。
 * 失败时静默忽略，保持未登录状态。
 */
export async function bootstrapSessionFromRefreshCookie(): Promise<void> {
    if (authUtils.hasToken()) return
    try {
        const token = await refreshAccessToken()
        if (!token) return
        // A cookie-recovered session is also a new session from this tab's
        // perspective and must notify other tabs of an account change.
        authUtils.setSessionVersion()
        const res = await fetch(buildUrl("/v1/current-user"), {
            headers: { Authorization: `Bearer ${token}` },
            credentials: "include",
            cache: "no-store",
        })
        if (res.ok) {
            const payload = await res.json().catch(() => null)
            const name = payload?.data?.name
            const username = payload?.data?.username
            const displayName =
                typeof name === "string" && name.trim().length > 0
                    ? name.trim()
                    : typeof username === "string" && username.trim().length > 0
                        ? username.trim()
                        : ""
            if (displayName.length > 0) {
                authUtils.setUser(displayName)
            }
        }
        dispatchAuthChange()
    } catch {
        // Network failure during bootstrap: stay logged out silently.
    }
}

function handleUnauthorizedAndThrow(
    response: Response,
    endpoint: string,
    data: unknown,
    ignoreUnauthorized?: boolean
): never {
    if (response.status === 401 || response.status === 403) {
        if (response.status === 401 && isIdleTimeoutResponse(response) && !ignoreUnauthorized) {
            dispatchLoginRequired("idle_timeout")
        } else {
            onUnauthorized(response.status, endpoint, data, ignoreUnauthorized)
        }
    }
    throw new ApiError(response.status, response.statusText, data)
}

/**
 * 获取认证 Token（可按需修改获取方式）
 */
export function getAuthToken(): string | null {
    return authUtils.getToken()
}

/**
 * 通用请求方法
 */
async function request<T>(
    endpoint: string,
    config: RequestConfig = {}
): Promise<T> {
    const { params, body, headers: customHeaders, ...restConfig } = config

    const url = buildUrl(endpoint, params)
    const token = getAuthToken()

    const isFormData = body instanceof FormData || body instanceof URLSearchParams;

    const headers: HeadersInit = {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...customHeaders,
    }

    if (token) {
        ; (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`
    }

    const doFetch = async (tokenOverride?: string) => {
        const requestHeaders = { ...headers } as Record<string, string>
        if (tokenOverride) {
            requestHeaders.Authorization = `Bearer ${tokenOverride}`
        }
        return fetch(url, {
            ...restConfig,
            headers: requestHeaders,
            credentials: "include",
            cache: "no-store",
            body: body ? (isFormData ? (body as BodyInit) : JSON.stringify(body)) : undefined,
        })
    }

    if (token) {
        authUtils.markSessionActivity()
    }
    let response = await doFetch(token ?? undefined)
    let alreadyHandledUnauthorized = false

    if (response.status === 401 && token && shouldAttemptRefresh(endpoint) && !config.ignoreUnauthorized) {
        const refreshedToken = await refreshAccessToken()
        if (refreshedToken) {
            response = await doFetch(refreshedToken)
        } else {
            dispatchLoginRequired()
            alreadyHandledUnauthorized = true
        }
    }

    if (!response.ok) {
        const data = await response.json().catch(() => null)
        if (alreadyHandledUnauthorized) {
            throw new ApiError(response.status, response.statusText, data)
        }
        handleUnauthorizedAndThrow(response, endpoint, data, config.ignoreUnauthorized)
    }

    // 204 No Content
    if (response.status === 204) {
        return undefined as T
    }

    return response.json()
}

/**
 * 通用 Blob 请求方法
 */
async function requestBlob(
    endpoint: string,
    config: RequestConfig = {}
): Promise<DownloadResponse> {
    const { params, body, headers: customHeaders, method = "GET" } = config

    const url = buildUrl(endpoint, params)
    const token = getAuthToken()

    const headers: HeadersInit = { ...customHeaders }
    if (token) {
        ; (headers as Record<string, string>)["Authorization"] = `Bearer ${token}`
    }

    const doFetch = async (tokenOverride?: string) => {
        const requestHeaders = { ...headers } as Record<string, string>
        if (tokenOverride) {
            requestHeaders.Authorization = `Bearer ${tokenOverride}`
        }
        return fetch(url, {
            method,
            headers: requestHeaders,
            credentials: "include",
            cache: "no-store",
            body: body ? JSON.stringify(body) : undefined,
        })
    }

    if (token) {
        authUtils.markSessionActivity()
    }
    let response = await doFetch(token ?? undefined)
    let alreadyHandledUnauthorized = false

    if (response.status === 401 && token && shouldAttemptRefresh(endpoint) && !config.ignoreUnauthorized) {
        const refreshedToken = await refreshAccessToken()
        if (refreshedToken) {
            response = await doFetch(refreshedToken)
        } else {
            dispatchLoginRequired()
            alreadyHandledUnauthorized = true
        }
    }

    if (!response.ok) {
        const data = await response.json().catch(() => null)
        if (alreadyHandledUnauthorized) {
            throw new ApiError(response.status, response.statusText, data)
        }
        handleUnauthorizedAndThrow(response, endpoint, data, config.ignoreUnauthorized)
    }

    return {
        blob: await response.blob(),
        filename: parseContentDispositionFilename(response.headers.get("Content-Disposition")),
    }
}

/**
 * API Client 实例
 */
export const apiClient = {
    get<T>(endpoint: string, config?: RequestConfig) {
        return request<T>(endpoint, { ...config, method: "GET" })
    },

    post<T>(endpoint: string, body?: unknown, config?: RequestConfig) {
        return request<T>(endpoint, { ...config, method: "POST", body })
    },

    put<T>(endpoint: string, body?: unknown, config?: RequestConfig) {
        return request<T>(endpoint, { ...config, method: "PUT", body })
    },

    patch<T>(endpoint: string, body?: unknown, config?: RequestConfig) {
        return request<T>(endpoint, { ...config, method: "PATCH", body })
    },

    delete<T>(endpoint: string, config?: RequestConfig) {
        return request<T>(endpoint, { ...config, method: "DELETE" })
    },

    download(endpoint: string, config?: RequestConfig) {
        return requestBlob(endpoint, config)
    }
}
