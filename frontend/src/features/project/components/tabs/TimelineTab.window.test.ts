import { expect, it } from "vitest"

import { clampTimelineViewWindow } from "./TimelineTab"

const bounds = {
    dataMin: 0,
    dataMax: 1_000_000,
    dataSpan: 1_000_000,
    chartTrackPx: 1000,
}

it("lets a zoomed timeline pan past the last recording so its label fits", () => {
    const span = 100_000
    const window = clampTimelineViewWindow(1_000_000, 1_000_000 + span, bounds)
    expect(window.end).toBeGreaterThan(bounds.dataMax)
    expect(window.end - window.start).toBe(span)
    const rightmostRatio = (bounds.dataMax - window.start) / span
    expect(rightmostRatio).toBeGreaterThan(0.2)
    expect(rightmostRatio).toBeLessThan(0.5)
})

it("does not pan a zoomed timeline before the first recording", () => {
    const window = clampTimelineViewWindow(-50_000, 50_000, bounds)
    expect(window.start).toBe(bounds.dataMin)
})

it("keeps a wide timeline from scrolling the data off the left", () => {
    const span = 3_000_000
    const window = clampTimelineViewWindow(500_000, 500_000 + span, bounds)
    expect(window.start).toBe(bounds.dataMin)
})
