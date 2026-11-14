import { expect, it } from "vitest"

import { resolveViewportFreqHz } from "./mediaDetailSupport"

const full = { specMinHz: 1, specMaxHz: 24000 }
const annotation = { lo: 1200, hi: 3400 }

it("uses the open annotation band while bandpass is on", () => {
    expect(
        resolveViewportFreqHz({
            ...full,
            bandFilter: true,
            pendingBand: null,
            annotationBand: annotation,
            keepVisibleFrequency: false,
        }),
    ).toEqual({ freqMinHz: 1200, freqMaxHz: 3400 })
})

it("keeps the visible full band after reset even if an annotation stays selected", () => {
    expect(
        resolveViewportFreqHz({
            ...full,
            bandFilter: true,
            pendingBand: null,
            annotationBand: annotation,
            keepVisibleFrequency: true,
        }),
    ).toEqual({ freqMinHz: 1, freqMaxHz: 24000 })
})

it("still applies a newly requested annotation band after reset is cleared", () => {
    expect(
        resolveViewportFreqHz({
            ...full,
            bandFilter: true,
            pendingBand: annotation,
            annotationBand: null,
            keepVisibleFrequency: false,
        }),
    ).toEqual({ freqMinHz: 1200, freqMaxHz: 3400 })
})
