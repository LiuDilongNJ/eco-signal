import { describe, expect, it } from "vitest"

import {
    buildMediaViewportParams,
    toAudioQueryParams,
} from "./mediaViewportParams"
import { parseAudioBandpassCookie } from "./media-detail/mediaDetailSupport"

describe("media bandpass preference", () => {
    it("defaults to enabled when no valid preference exists", () => {
        expect(parseAudioBandpassCookie(null)).toBe(true)
        expect(parseAudioBandpassCookie(undefined)).toBe(true)
        expect(parseAudioBandpassCookie("invalid")).toBe(true)
    })

    it("restores both persisted toggle positions", () => {
        expect(parseAudioBandpassCookie("1")).toBe(true)
        expect(parseAudioBandpassCookie("true")).toBe(true)
        expect(parseAudioBandpassCookie("0")).toBe(false)
        expect(parseAudioBandpassCookie("false")).toBe(false)
    })

    it("includes the visible frequency range when bandpass is enabled", () => {
        const viewport = buildMediaViewportParams({
            durationS: 60,
            samplingRateHz: 48_000,
            viewStart: 10,
            windowSec: 5,
            freqMinHz: 1_000,
            freqMaxHz: 8_000,
            fftSize: 1024,
            stereo: false,
            audioChannel: 1,
            bandFilter: true,
        })

        expect(toAudioQueryParams(viewport)).toMatchObject({
            start_time: 10,
            end_time: 15,
            filter: true,
            min_freq: 1_000,
            max_freq: 8_000,
            fft_size: 1024,
        })
    })

    it("omits frequency parameters when bandpass is disabled", () => {
        const viewport = buildMediaViewportParams({
            durationS: 60,
            samplingRateHz: 48_000,
            viewStart: 10,
            windowSec: 5,
            freqMinHz: 1_000,
            freqMaxHz: 8_000,
            fftSize: 1024,
            stereo: false,
            audioChannel: 1,
            bandFilter: false,
        })

        expect(toAudioQueryParams(viewport)).toEqual({
            start_time: 10,
            end_time: 15,
            filter: false,
        })
    })
})
