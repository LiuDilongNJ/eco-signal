import { useEffect } from "react"
import { userPreferenceApi } from "@/api/endpoints/users"
import { normalizeTheme, useAppStore } from "@/store/useAppStore"
import { authUtils } from "@/utils/auth"
import { startSessionActivityMonitor, stopSessionActivityMonitor } from "@/utils/sessionActivityMonitor"

export function AuthSessionWatcher() {
    useEffect(() => {
        let requestGeneration = 0

        const syncAccountTheme = async () => {
            const generation = ++requestGeneration
            const token = authUtils.getToken()
            if (!token) return

            try {
                const preference = await userPreferenceApi.get({ ignoreUnauthorized: true })
                if (generation !== requestGeneration || authUtils.getToken() !== token) return
                useAppStore.getState().applyAccountTheme(normalizeTheme(preference.theme))
            } catch {
                // Keep the current theme when account preferences cannot be loaded.
            }
        }

        startSessionActivityMonitor()
        void syncAccountTheme()
        window.addEventListener("eco-auth-change", syncAccountTheme)

        return () => {
            requestGeneration += 1
            window.removeEventListener("eco-auth-change", syncAccountTheme)
            stopSessionActivityMonitor()
        }
    }, [])

    return null
}
