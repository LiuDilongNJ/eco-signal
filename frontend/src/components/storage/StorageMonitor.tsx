import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { systemApi, type StorageStatus } from "@/api/endpoints/system"
import { usersApi } from "@/api/endpoints/users"
import { authUtils } from "@/utils/auth"
import { formatStorageBytes } from "@/features/settings/utils/storageStatus"
import "./storage-monitor.css"

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
        window.addEventListener("eco-auth-change", sync)
        window.addEventListener("storage", sync)
        return () => {
            window.removeEventListener("eco-auth-change", sync)
            window.removeEventListener("storage", sync)
        }
    }, [])
    useEffect(() => {
        const controller = new AbortController()
        activeRequest.current = controller
        let timer: ReturnType<typeof setTimeout> | undefined
        let admin = false
        let loading = false
        const poll = async () => {
            if (!admin || loading || document.hidden || controller.signal.aborted) return
            loading = true
            setState(value => ({ ...value, loading: true }))
            try {
                const response = await systemApi.getStorageStatus(controller.signal)
                if (controller.signal.aborted) return
                if (response.code !== 0 && response.code !== 200) throw new Error("Storage status is unavailable")
                setState({ storage: response.data, loading: false, error: null, isAdmin: true })
            } catch {
                if (!controller.signal.aborted) setState({ storage: null, loading: false, error: "Storage status is unavailable", isAdmin: true })
            } finally {
                loading = false
                if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 60000)
            }
        }
        const onVisibility = () => {
            if (timer) clearTimeout(timer)
            if (!document.hidden) void poll()
        }
        const start = async () => {
            if (!authUtils.hasToken()) return
            try {
                const me = await usersApi.getMe({ ignoreUnauthorized: true, signal: controller.signal })
                if (controller.signal.aborted) return
                admin = Boolean(me.data?.is_admin)
                setState(value => ({ ...value, isAdmin: admin }))
                await poll()
            } catch {
                // Authorization is checked before requesting filesystem information.
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
