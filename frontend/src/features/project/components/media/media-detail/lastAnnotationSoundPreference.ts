import { isFunctionalCookiesAllowed } from "../../../../home/cookieConsent"
import { getCookieValue, setCookieValue } from "./mediaDetailSupport"

export const ANNOT_LAST_SOUND_COOKIE_KEY = "ecoSignal_annot_last_sound"
export const ANNOT_LAST_SOUND_SESSION_KEY = "ecoSignal_annot_last_sound"

export type LastAnnotationSoundSelection = {
    soundscape: string
    soundId: number | null
}

let lastAnnotationSoundMemory: LastAnnotationSoundSelection | null = null

export function parseLastAnnotationSoundValue(raw: string | null | undefined): LastAnnotationSoundSelection | null {
    if (raw == null || raw.trim() === "") return null
    try {
        const parsed = JSON.parse(raw) as { soundscape?: unknown; soundId?: unknown }
        if (typeof parsed.soundscape !== "string") return null
        if (parsed.soundId == null || parsed.soundId === "") {
            return { soundscape: parsed.soundscape, soundId: null }
        }
        const n = typeof parsed.soundId === "number" ? parsed.soundId : Number(parsed.soundId)
        if (!Number.isFinite(n) || n <= 0) return null
        return { soundscape: parsed.soundscape, soundId: Math.trunc(n) }
    } catch {
        return null
    }
}

function readSessionSelection(): LastAnnotationSoundSelection | null {
    if (typeof window === "undefined") return null
    try {
        return parseLastAnnotationSoundValue(window.sessionStorage.getItem(ANNOT_LAST_SOUND_SESSION_KEY))
    } catch {
        return null
    }
}

export function readLastAnnotationSound(): LastAnnotationSoundSelection | null {
    if (lastAnnotationSoundMemory) return lastAnnotationSoundMemory
    const fromCookie = parseLastAnnotationSoundValue(getCookieValue(ANNOT_LAST_SOUND_COOKIE_KEY))
    if (fromCookie) {
        lastAnnotationSoundMemory = fromCookie
        return fromCookie
    }
    const fromSession = readSessionSelection()
    if (fromSession) lastAnnotationSoundMemory = fromSession
    return fromSession
}

export function writeLastAnnotationSound(selection: LastAnnotationSoundSelection): void {
    lastAnnotationSoundMemory = selection
    const raw = JSON.stringify(selection)
    setCookieValue(ANNOT_LAST_SOUND_COOKIE_KEY, raw)
    if (typeof window === "undefined") return
    try {
        if (isFunctionalCookiesAllowed()) {
            window.sessionStorage.removeItem(ANNOT_LAST_SOUND_SESSION_KEY)
        } else {
            window.sessionStorage.setItem(ANNOT_LAST_SOUND_SESSION_KEY, raw)
        }
    } catch {
        /* ignore quota / private-mode failures; in-memory still applies */
    }
}

export function resolveLastAnnotationSound(
    classifications: Array<{ sound_id: number; soundscape_component?: string | null }>,
): LastAnnotationSoundSelection | null {
    const last = readLastAnnotationSound()
    if (!last) return null
    if (classifications.length === 0) return last
    if (last.soundId != null) {
        const match = classifications.find((row) => row.sound_id === last.soundId)
        if (match) {
            return {
                soundscape: match.soundscape_component ?? "",
                soundId: match.sound_id,
            }
        }
    }
    const soundscapeExists = classifications.some(
        (row) => (row.soundscape_component ?? "") === last.soundscape,
    )
    if (!soundscapeExists) return null
    return { soundscape: last.soundscape, soundId: null }
}

export function resetLastAnnotationSoundMemoryForTests(): void {
    lastAnnotationSoundMemory = null
}
