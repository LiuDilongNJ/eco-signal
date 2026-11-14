import { expect, it } from "vitest"

import { resizeDraftPixelRectFromHandle } from "./mediaDetailSupport"

const start = { left: 100, top: 80, width: 80, height: 40 }

it("resizes a corner without keeping the original proportions", () => {
    const next = resizeDraftPixelRectFromHandle(start, "se", 40, 10, 800, 400)
    expect(next).toEqual({ left: 100, top: 80, width: 120, height: 50 })
})

it("moves only the dragged edges and keeps the opposite corner fixed", () => {
    const next = resizeDraftPixelRectFromHandle(start, "nw", -20, -15, 800, 400)
    expect(next).toEqual({ left: 80, top: 65, width: 100, height: 55 })
})

it("stops a corner at the viewport and the minimum size", () => {
    const next = resizeDraftPixelRectFromHandle(start, "se", 5000, -5000, 200, 200, 12)
    expect(next.left).toBe(100)
    expect(next.top).toBe(80)
    expect(next.width).toBe(100)
    expect(next.height).toBe(12)
})
