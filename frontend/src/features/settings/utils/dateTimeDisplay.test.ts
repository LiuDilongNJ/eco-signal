import { describe, expect, it } from "vitest"

import { displayApiDateTime } from "./dateTimeDisplay"

describe("displayApiDateTime", () => {
    it("preserves the complete API datetime string", () => {
        expect(displayApiDateTime("2026-07-16 13:37:48")).toBe("2026-07-16 13:37:48")
    })

    it("does not normalize an API datetime value", () => {
        expect(displayApiDateTime("2026-07-16T13:37:48.123Z")).toBe("2026-07-16T13:37:48.123Z")
    })

    it.each([null, undefined])("returns an empty string for %s", (value) => {
        expect(displayApiDateTime(value)).toBe("")
    })
})
