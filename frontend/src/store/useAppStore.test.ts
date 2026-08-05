import { describe, expect, it } from "vitest"

import { getEffectiveTheme, normalizeTheme } from "./useAppStore"

describe("application theme values", () => {
    it.each(["light", "dark", "auto"] as const)("keeps supported theme %s", (theme) => {
        expect(normalizeTheme(theme)).toBe(theme)
    })

    it.each(["system", "unknown", "", null, undefined])(
        "normalizes unsupported theme %s to auto",
        (theme) => {
            expect(normalizeTheme(theme)).toBe("auto")
        },
    )

    it("keeps explicit themes independent of the operating system", () => {
        expect(getEffectiveTheme("light")).toBe("light")
        expect(getEffectiveTheme("dark")).toBe("dark")
    })
})
