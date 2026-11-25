import { describe, expect, it } from "vitest"

import { spectrogramAnnotationsReady } from "./mediaDetailSupport"

const loaded = {
    showSpectrogramLoading: false,
    spectrogramBlobUrl: "blob:current",
    spectrogramImageReadyUrl: "blob:current",
    viewportKey: "view-a",
    readyParamsKey: "view-a",
    activeParamsKey: "view-a",
}

describe("spectrogramAnnotationsReady", () => {
    it("shows annotations only after the current spectrogram image has loaded", () => {
        expect(spectrogramAnnotationsReady(loaded)).toBe(true)
    })

    it("does not flash the next annotation on the previous spectrogram", () => {
        expect(
            spectrogramAnnotationsReady({
                ...loaded,
                viewportKey: "view-b",
                activeParamsKey: null,
            }),
        ).toBe(false)
    })

    it("stays hidden while the replacement spectrogram is still decoding", () => {
        expect(
            spectrogramAnnotationsReady({
                ...loaded,
                spectrogramBlobUrl: "blob:next",
                viewportKey: "view-b",
                activeParamsKey: "view-b",
            }),
        ).toBe(false)
    })

    it("stays hidden for the whole spectrogram request", () => {
        expect(spectrogramAnnotationsReady({ ...loaded, showSpectrogramLoading: true })).toBe(false)
    })
})