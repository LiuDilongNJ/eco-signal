import { describe, expect, it } from "vitest"

import {
    buildCameraWritePayload,
    buildLensWritePayload,
    buildMicrophoneWritePayload,
    buildRecorderWritePayload,
    nullableTrimmedText,
    requiredTrimmedText,
} from "./settingsPayload"

describe("settings payload text conversion", () => {
    it.each([undefined, null, "", "   "])("converts %s to null for optional text", (value) => {
        expect(nullableTrimmedText(value)).toBeNull()
    })

    it("trims optional text without dropping the field value", () => {
        expect(nullableTrimmedText("  value  ")).toBe("value")
    })

    it("trims required text and keeps an empty string for validation", () => {
        expect(requiredTrimmedText("  name  ")).toBe("name")
        expect(requiredTrimmedText("   ")).toBe("")
    })

    it("keeps required recorder and camera names while clearing optional fields", () => {
        expect(buildRecorderWritePayload({ name: "Recorder", version: "", brand: undefined })).toEqual({
            name: "Recorder",
            version: null,
            brand: null,
        })
        expect(buildCameraWritePayload({ name: " Camera ", version: "", brand: "" })).toEqual({
            name: "Camera",
            version: null,
            brand: null,
        })
    })

    it("keeps required microphone and lens names while clearing optional fields", () => {
        expect(buildMicrophoneWritePayload({ name: "Mic" })).toEqual({
            name: "Mic",
            microphone_element: null,
            sensitivity: null,
            signal_to_noise_ratio: null,
        })
        expect(buildLensWritePayload({ name: " Lens " })).toEqual({
            name: "Lens",
            focal_length: null,
            max_aperture: null,
            brand: null,
        })
    })
})
