import { useEffect } from "react"
import { userPreferenceApi } from "@/api/endpoints/users"
import { appQueryClient } from "@/providers/queryClient"
import { normalizeTheme, useAppStore } from "@/store/useAppStore"
import { AUTH_SESSION_VERSION_KEY, AUTH_LANDING_PATH, authUtils } from "@/utils/auth"
import { startSessionActivityMonitor, stopSessionActivityMonitor } from "@/utils/sessionActivityMonitor"

export function AuthSessionWatcher() {
    useEffect(() => {
        let requestGeneration = 0
        const sessionVersionRef = { current: authUtils.getSessionVersion() }

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

        const onAuthChange = () => {
            sessionVersionRef.current = authUtils.getSessionVersion()
            void syncAccountTheme()
        }

        const onSessionVersionStorage = (event: StorageEvent) => {
            if (event.key !== AUTH_SESSION_VERSION_KEY) return

            const nextVersion = authUtils.getSessionVersion()
            const previousVersion = sessionVersionRef.current
            if (nextVersion === previousVersion) return
            sessionVersionRef.current = nextVersion

            // Remove account-scoped permissions/data before the old page can
            // render actions for the newly active account.
            appQueryClient.clear()
            window.dispatchEvent(new CustomEvent("eco-auth-change"))

            // A logged-in page must not remain under the previous account.
            // The landing page only needs the auth event to update its header.
            if (previousVersion && window.location.pathname !== AUTH_LANDING_PATH) {
                window.location.replace(AUTH_LANDING_PATH)
            }
        }

        startSessionActivityMonitor()
        void syncAccountTheme()
        window.addEventListener("eco-auth-change", onAuthChange)
        window.addEventListener("storage", onSessionVersionStorage)

        return () => {
            requestGeneration += 1
            window.removeEventListener("eco-auth-change", onAuthChange)
            window.removeEventListener("storage", onSessionVersionStorage)
            stopSessionActivityMonitor()
        }
    }, [])

    return null
}
