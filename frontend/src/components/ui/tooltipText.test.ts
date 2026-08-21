import { describe, expect, it } from "vitest"
import { getTooltipText } from "./tooltipText"

describe("getTooltipText", () => {
    it("expands common action labels into useful hover hints", () => {
        expect(getTooltipText("Delete")).toBe("Delete the selected records")
        expect(getTooltipText("Reset table")).toBe("Clear filters, sorting, and selected rows")
        expect(getTooltipText("Taxa")).toBe("Associate the collection with one or several taxa")
    })

    it("preserves custom descriptive text", () => {
        expect(getTooltipText("Only audio files can be assigned")).toBe("Only audio files can be assigned")
        expect(getTooltipText(undefined)).toBeUndefined()
    })
})
