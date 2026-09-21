import { beforeEach, describe, expect, it, vi } from "vitest"
import { isFunctionalCookiesAllowed } from "../../../../home/cookieConsent"
import {
    ANNOT_LAST_SOUND_COOKIE_KEY,
    ANNOT_LAST_SOUND_SESSION_KEY,
    parseLastAnnotationSoundValue,
    readLastAnnotationSound,
    resetLastAnnotationSoundMemoryForTests,
    resolveLastAnnotationSound,
    writeLastAnnotationSound,
} from "./lastAnnotationSoundPreference"

vi.mock("../../../../home/cookieConsent", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../../../../home/cookieConsent")>()
    return {
        ...actual,
        isFunctionalCookiesAllowed: vi.fn(() => true),
    }
})

describe("lastAnnotationSoundPreference", () => {
    beforeEach(() => {
        resetLastAnnotationSoundMemoryForTests()
        window.sessionStorage.clear()
        document.cookie = `${ANNOT_LAST_SOUND_COOKIE_KEY}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`
        vi.mocked(isFunctionalCookiesAllowed).mockReturnValue(true)
    })

    it("parses soundscape and sound id", () => {
        expect(parseLastAnnotationSoundValue('{"soundscape":"biophony","soundId":12}')).toEqual({
            soundscape: "biophony",
            soundId: 12,
        })
        expect(parseLastAnnotationSoundValue('{"soundscape":"geophony","soundId":null}')).toEqual({
            soundscape: "geophony",
            soundId: null,
        })
        expect(parseLastAnnotationSoundValue("not-json")).toBeNull()
    })

    it("resolves a stored sound id against current classifications", () => {
        writeLastAnnotationSound({ soundscape: "biophony", soundId: 12 })
        expect(
            resolveLastAnnotationSound([
                { sound_id: 9, soundscape_component: "anthropophony" },
                { sound_id: 12, soundscape_component: "biophony" },
            ]),
        ).toEqual({ soundscape: "biophony", soundId: 12 })
    })

    it("keeps soundscape when the stored sound id no longer exists", () => {
        writeLastAnnotationSound({ soundscape: "biophony", soundId: 99 })
        expect(
            resolveLastAnnotationSound([{ sound_id: 12, soundscape_component: "biophony" }]),
        ).toEqual({ soundscape: "biophony", soundId: null })
    })

    it("falls back to session storage when functional cookies are not allowed", () => {
        vi.mocked(isFunctionalCookiesAllowed).mockReturnValue(false)
        writeLastAnnotationSound({ soundscape: "geophony", soundId: 4 })
        resetLastAnnotationSoundMemoryForTests()
        expect(window.sessionStorage.getItem(ANNOT_LAST_SOUND_SESSION_KEY)).toContain("geophony")
        expect(readLastAnnotationSound()).toEqual({ soundscape: "geophony", soundId: 4 })
    })
})
