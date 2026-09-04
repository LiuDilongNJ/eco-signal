import { describe, expect, it } from "vitest"
import { canParseFilenameDateTime, getUnparseableFilenameDateTimes } from "./filenameDatetime"

describe("filename datetime parsing", () => {
    it.each([
        "recording_20260825_125959.wav",
        "recording_2026-08-25T12:59:59.wav",
        "recording_20260825T125959.wav",
        "recording_2026_08_25-125959.wav",
    ])("accepts %s", (filename) => {
        expect(canParseFilenameDateTime(filename)).toBe(true)
    })

    it.each([
        "KrA3_102229322T991000",
        "recording_20260230_125959.wav",
        "recording_20261301_125959.wav",
        "recording_20260825_246000.wav",
        "recording_20260825_1260000.wav",
    ])("rejects %s", (filename) => {
        expect(canParseFilenameDateTime(filename)).toBe(false)
    })

    it("returns only filenames without a valid datetime", () => {
        expect(getUnparseableFilenameDateTimes([
            "valid_20260825_125959.wav",
            "plain_recording.wav",
            "invalid_20260230_125959.wav",
        ])).toEqual([
            "plain_recording.wav",
            "invalid_20260230_125959.wav",
        ])
    })
})
