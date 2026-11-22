import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { ApiError } from "@/api/client"
import { systemApi, type StorageStatus } from "@/api/endpoints/system"
import { usersApi } from "@/api/endpoints/users"
import { AUTH_SESSION_VERSION_KEY, authUtils } from "@/utils/auth"
import { formatStorageBytes } from "@/features/settings/utils/storageStatus"
import "./storage-monitor.css"

const AUTH_STORAGE_KEYS = new Set(["accessToken", AUTH_SESSION_VERSION_KEY])

type StorageMonitorState = {
    storage: StorageStatus | null
    loading: boolean
    error: string | null
    isAdmin: boolean
    refresh: () => void
}
const Context = createContext<StorageMonitorState>({ storage: null, loading: false, error: null, isAdmin: false, refresh: () => {} })

export function StorageMonitorProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState(0)
    const activeRequest = useRef<AbortController | null>(null)
    const [generation, setGeneration] = useState(0)
    const [state, setState] = useState<Omit<StorageMonitorState, "refresh">>({ storage: null, loading: false, error: null, isAdmin: false })
    const refresh = useCallback(() => setGeneration(value => value + 1), [])
    useEffect(() => {
        const sync = () => {
            activeRequest.current?.abort()
            setState({ storage: null, loading: false, error: null, isAdmin: false })
            setSession(value => value + 1)
        }
        const onStorage = (event: StorageEvent) => {
            // Ignore non-auth keys (e.g. idle activity timestamps) updated by other tabs.
            if (event.key !== null && !AUTH_STORAGE_KEYS.has(event.key)) return
            sync()
        }
        window.addEventListener("eco-auth-change", sync)
        window.addEventListener("storage", onStorage)
        return () => {
            window.removeEventListener("eco-auth-change", sync)
            window.removeEventListener("storage", onStorage)
        }
    }, [])
    useEffect(() => {
        const controller = new AbortController()
        activeRequest.current = controller
        let timer: ReturnType<typeof setTimeout> | undefined
        let verifiedAdmin: boolean | null = null
        let loading = false
        const scheduleNext = (task: () => void) => {
            if (timer) clearTimeout(timer)
            if (!controller.signal.aborted && !document.hidden) timer = setTimeout(task, 60000)
        }
        const poll = async () => {
            if (verifiedAdmin !== true || loading || document.hidden || controller.signal.aborted) return
            loading = true
            setState(value => ({ ...value, loading: true }))
            try {
                const response = await systemApi.getStorageStatus(controller.signal)
                if (controller.signal.aborted) return
                if ((response.code !== 0 && response.code !== 200) || !response.data || !Array.isArray(response.data.filesystems)) {
                    throw new Error(`Unexpected storage status response (code=${String(response.code)})`)
                }
                setState({ storage: response.data, loading: false, error: null, isAdmin: true })
            } catch (err) {
                if (!controller.signal.aborted) {
                    console.warn("[StorageMonitor] Failed to fetch storage status", err)
                    setState({ storage: null, loading: false, error: "Storage status is unavailable", isAdmin: true })
                }
            } finally {
                loading = false
                scheduleNext(() => void poll())
            }
        }
        const start = async () => {
            if (!authUtils.hasToken() || loading || controller.signal.aborted) return
            loading = true
            setState(value => ({ ...value, loading: true }))
            try {
                const me = await usersApi.getMe({ ignoreUnauthorized: true, signal: controller.signal })
                if (controller.signal.aborted) return
                verifiedAdmin = Boolean(me.data?.is_admin)
                loading = false
                if (!verifiedAdmin) {
                    setState({ storage: null, loading: false, error: null, isAdmin: false })
                    return
                }
                if (document.hidden) {
                    setState(value => ({ ...value, loading: false, isAdmin: true }))
                    return
                }
                setState(value => ({ ...value, isAdmin: true }))
                await poll()
            } catch (err) {
                loading = false
                if (controller.signal.aborted) return
                console.warn("[StorageMonitor] Failed to verify administrator status for storage monitor", err)
                setState(value => ({
                    ...value,
                    loading: false,
                    error: value.isAdmin ? "Storage status is unavailable" : value.error,
                }))
                const isAuthFailure = err instanceof ApiError && (err.status === 401 || err.status === 403)
                if (!isAuthFailure && authUtils.hasToken()) {
                    scheduleNext(() => void start())
                }
            }
        }
        const onVisibility = () => {
            if (timer) clearTimeout(timer)
            if (document.hidden) return
            if (verifiedAdmin === true) {
                void poll()
            } else if (verifiedAdmin === null) {
                void start()
            }
        }
        void start()
        document.addEventListener("visibilitychange", onVisibility)
        return () => {
            controller.abort()
            if (timer) clearTimeout(timer)
            document.removeEventListener("visibilitychange", onVisibility)
        }
    }, [session, generation])
    return <Context.Provider value={{ ...state, refresh }}>{children}</Context.Provider>
}

export const useStorageMonitor = () => useContext(Context)

export function StorageWarningBanner() {
    const { storage, error, isAdmin } = useStorageMonitor()
    if (!isAdmin || (!error && (!storage || storage.status === "healthy"))) return null
    const affected = storage?.filesystems.filter(item => item.status !== "healthy") ?? []
    return (
        <div className={`storage-warning storage-warning--${storage?.status ?? "unavailable"}`} role="alert">
            <strong>{error || (storage?.status === "unavailable" ? "Storage status is unavailable" : "Storage space is running low")}</strong>
            {affected.map(item => (
                <span key={item.scope}>
                    {item.scope === "media" ? "Media storage" : "Container storage"}: {item.available
                        ? `${item.used_percent?.toFixed(1)}% used, ${formatStorageBytes(item.free_bytes ?? 0)} free.`
                        : "Status unavailable."}
                </span>
            ))}
            {!error && storage?.status !== "unavailable" && <span>Review storage usage and remove unnecessary files.</span>}
        </div>
    )
}
