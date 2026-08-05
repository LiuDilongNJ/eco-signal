export const COOKIE_CONSENT_KEY = "cookieConsent"
export const COOKIE_PREFERENCES_KEY = "cookiePreferences"
export const COOKIE_RETENTION_DAYS = 180

export type CookieConsent = "accepted" | "rejected" | "customized"

export type CookiePreferences = {
    functional: boolean
}

export const FUNCTIONAL_COOKIE_NAMES = [
    "ecoSignal_spec_zoom_percent",
    "ecoSignal_spec_zoom_percent_draft_in",
    "ecoSignal_spec_zoom_percent_draft_out",
    "ecoSignal_photo_zoom_percent_draft_in",
    "ecoSignal_photo_zoom_percent_draft_out",
    "ecoSignal_spec_px_per_sec",
    "ecoSignal_annot_save_mode",
] as const

export const FUNCTIONAL_LOCAL_STORAGE_KEYS = [
    "eco-app-store",
] as const

const COOKIE_PREFERENCES_CHANGE_EVENT = "eco-cookie-preferences-change"
export const COOKIE_PREFERENCES_OPEN_EVENT = "eco-cookie-preferences-open"

export function openCookiePreferences(): void {
    if (typeof window === "undefined") return
    window.dispatchEvent(new Event(COOKIE_PREFERENCES_OPEN_EVENT))
}

export function readCookiePreferences(): CookiePreferences {
    if (typeof window === "undefined") return { functional: false }
    const consent = window.localStorage.getItem(COOKIE_CONSENT_KEY)
    if (consent === "accepted") return { functional: true }
    if (consent === "rejected") return { functional: false }
    try {
        const raw = window.localStorage.getItem(COOKIE_PREFERENCES_KEY)
        if (!raw) return { functional: false }
        const parsed = JSON.parse(raw) as { functional?: unknown }
        return { functional: parsed.functional === true }
    } catch (err) {
        console.warn("Failed to parse cookie preferences:", err)
        return { functional: false }
    }
}

export function isFunctionalCookiesAllowed(): boolean {
    if (typeof window === "undefined") return false
    const consent = window.localStorage.getItem(COOKIE_CONSENT_KEY)
    if (consent === "accepted") return true
    if (consent === "customized") {
        try {
            const raw = window.localStorage.getItem(COOKIE_PREFERENCES_KEY)
            if (!raw) return false
            const parsed = JSON.parse(raw) as { functional?: unknown }
            return parsed.functional === true
        } catch (err) {
            console.warn("Failed to parse cookie preferences:", err)
            return false
        }
    }
    return false
}

export function clearBrowserCookie(name: string): void {
    if (typeof document === "undefined") return
    document.cookie = `${encodeURIComponent(name)}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; samesite=lax`
}

export function clearFunctionalCookies(): void {
    FUNCTIONAL_COOKIE_NAMES.forEach(clearBrowserCookie)
    if (typeof window !== "undefined") {
        FUNCTIONAL_LOCAL_STORAGE_KEYS.forEach((key) => window.localStorage.removeItem(key))
    }
}

export function saveCookieSettings(functional: boolean, consent: CookieConsent): void {
    if (typeof window === "undefined") return
    window.localStorage.setItem(COOKIE_PREFERENCES_KEY, JSON.stringify({ functional }))
    window.localStorage.setItem(COOKIE_CONSENT_KEY, consent)
    if (!functional) clearFunctionalCookies()
    window.dispatchEvent(new Event(COOKIE_PREFERENCES_CHANGE_EVENT))
}

export function subscribeCookiePreferencesChange(listener: () => void): () => void {
    if (typeof window === "undefined") return () => {}
    window.addEventListener(COOKIE_PREFERENCES_CHANGE_EVENT, listener)
    window.addEventListener("storage", listener)
    return () => {
        window.removeEventListener(COOKIE_PREFERENCES_CHANGE_EVENT, listener)
        window.removeEventListener("storage", listener)
    }
}
