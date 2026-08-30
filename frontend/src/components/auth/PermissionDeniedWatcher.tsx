import { useEffect } from "react"
import { message } from "@/components/ui"
import {
    PERMISSION_DENIED_EVENT,
    type PermissionDeniedDetail,
} from "@/utils/permissionNotice"

/** Shared key so a batch operation that fails per row collapses into one toast. */
const TOAST_KEY = "eco-permission-denied"

export function PermissionDeniedWatcher() {
    useEffect(() => {
        const onDenied = (event: Event) => {
            const detail = (event as CustomEvent<PermissionDeniedDetail>).detail
            if (!detail?.message) return
            message.open({ type: "error", content: detail.message, key: TOAST_KEY, duration: 3 })
        }
        window.addEventListener(PERMISSION_DENIED_EVENT, onDenied)
        return () => window.removeEventListener(PERMISSION_DENIED_EVENT, onDenied)
    }, [])

    return null
}
