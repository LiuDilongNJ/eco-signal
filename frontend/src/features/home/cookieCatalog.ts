import { COOKIE_RETENTION_DAYS } from "./cookieConsent"

export type CookieCategory = "Strictly Necessary Cookies" | "Functional Cookies"

export type CookieCatalogEntry = {
    name: string
    duration: string
    category: CookieCategory
    description: string
}

/** First-party browser storage disclosed in the preference center. */
const COOKIE_RETENTION = `${COOKIE_RETENTION_DAYS} Days`

export const COOKIE_CATALOG: CookieCatalogEntry[] = [
    {
        name: "cookieConsent",
        duration: COOKIE_RETENTION,
        category: "Strictly Necessary Cookies",
        description: "Stores your cookie consent choice for this site",
    },
    {
        name: "cookiePreferences",
        duration: COOKIE_RETENTION,
        category: "Strictly Necessary Cookies",
        description: "Stores your customized cookie category preferences",
    },
    {
        name: "accessToken",
        duration: "Session",
        category: "Strictly Necessary Cookies",
        description: "Keeps you signed in while you use the application",
    },
    {
        name: "loggedInUser",
        duration: "Session",
        category: "Strictly Necessary Cookies",
        description: "Remembers your display name after login",
    },
    {
        name: "refresh_token",
        duration: "Session",
        category: "Strictly Necessary Cookies",
        description: "HTTP-only cookie used by the API to refresh your login session",
    },
    {
        name: "eco-app-store",
        duration: "Persistent",
        category: "Functional Cookies",
        description: "Remembers interface preferences such as theme and sidebar state",
    },
    {
        name: "ecoSignal_spec_zoom_percent",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the audio spectrogram zoom percentage",
    },
    {
        name: "ecoSignal_spec_zoom_percent_draft_in",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the audio spectrogram zoom-in input value",
    },
    {
        name: "ecoSignal_spec_zoom_percent_draft_out",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the audio spectrogram zoom-out input value",
    },
    {
        name: "ecoSignal_photo_zoom_percent_draft_in",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the photo viewer zoom-in input value",
    },
    {
        name: "ecoSignal_photo_zoom_percent_draft_out",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the photo viewer zoom-out input value",
    },
    {
        name: "ecoSignal_spec_px_per_sec",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the audio spectrogram pixels-per-second preference",
    },
    {
        name: "ecoSignal_annot_save_mode",
        duration: COOKIE_RETENTION,
        category: "Functional Cookies",
        description: "Remembers the default annotation save action",
    },
]

export function cookiesForCategory(category: CookieCategory): CookieCatalogEntry[] {
    return COOKIE_CATALOG.filter((c) => c.category === category)
}
