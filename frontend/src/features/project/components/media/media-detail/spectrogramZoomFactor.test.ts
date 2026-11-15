import { describe, expect, it } from "vitest"

import {
    commitSpectrogramZoomFactorDraft,
    nextWindowByZoomFactor,
    parseSpectrogramZoomFactor,
    SPECTROGRAM_ZOOM_FACTOR_DEFAULT,
    SPECTROGRAM_ZOOM_FACTOR_MAX,
    SPECTROGRAM_ZOOM_FACTOR_MIN,
} from "./mediaDetailSupport"

describe("spectrogram zoom factor", () => {
    it("defaults and clamps the user-supplied increment", () => {
        expect(parseSpectrogramZoomFactor(null)).toBe(SPECTROGRAM_ZOOM_FACTOR_DEFAULT)
        expect(parseSpectrogramZoomFactor("1")).toBe(SPECTROGRAM_ZOOM_FACTOR_MIN)
        expect(parseSpectrogramZoomFactor("99")).toBe(SPECTROGRAM_ZOOM_FACTOR_MAX)
        expect(parseSpectrogramZoomFactor("2.5")).toBe(2.5)
    })

    it("rejects a zoom factor below 1 instead of applying it", () => {
        expect(commitSpectrogramZoomFactorDraft("0.5")).toBeNull()
        expect(commitSpectrogramZoomFactorDraft("1")).toBe(1)
        expect(commitSpectrogramZoomFactorDraft("2")).toBe(2)
    })

    it("zooms in by dividing width and out by multiplying width", () => {
        expect(nextWindowByZoomFactor(20, 2, "in")).toBe(10)
        expect(nextWindowByZoomFactor(20, 2, "out")).toBe(40)
    })

    it("returns to the original width after zooming in then out", () => {
        const original = 16
        const factor = 1.6
        const zoomedIn = nextWindowByZoomFactor(original, factor, "in")
        expect(nextWindowByZoomFactor(zoomedIn, factor, "out")).toBeCloseTo(original)
    })
})
