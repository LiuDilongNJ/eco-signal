import { beforeEach, describe, expect, it, vi } from "vitest"
import {
    TASK_MODE_TIP_STORAGE_KEY,
    isTaskModeTipDismissed,
    setTaskModeTipDismissed,
} from "./taskModeTipPreference"

vi.mock("../../../home/cookieConsent", () => ({
    isFunctionalCookiesAllowed: vi.fn(() => true),
}))

import { isFunctionalCookiesAllowed } from "../../../home/cookieConsent"

describe("taskModeTipPreference", () => {
    beforeEach(() => {
        window.localStorage.clear()
        window.sessionStorage.clear()
        vi.mocked(isFunctionalCookiesAllowed).mockReturnValue(true)
    })

    it("defaults to not dismissed", () => {
        expect(isTaskModeTipDismissed()).toBe(false)
    })

    it("persists dismissal in localStorage when functional cookies are allowed", () => {
        setTaskModeTipDismissed(true)
        expect(window.localStorage.getItem(TASK_MODE_TIP_STORAGE_KEY)).toBe("1")
        expect(isTaskModeTipDismissed()).toBe(true)
    })

    it("falls back to sessionStorage when functional cookies are not allowed", () => {
        vi.mocked(isFunctionalCookiesAllowed).mockReturnValue(false)
        setTaskModeTipDismissed(true)
        expect(window.localStorage.getItem(TASK_MODE_TIP_STORAGE_KEY)).toBeNull()
        expect(window.sessionStorage.getItem(TASK_MODE_TIP_STORAGE_KEY)).toBe("1")
        expect(isTaskModeTipDismissed()).toBe(true)
    })
})
