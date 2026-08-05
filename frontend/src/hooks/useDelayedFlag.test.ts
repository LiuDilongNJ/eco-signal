import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useDelayedFlag } from "./useDelayedFlag"

describe("useDelayedFlag", () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it("stays false while active is shorter than the delay", () => {
        const { result, rerender } = renderHook(({ active }) => useDelayedFlag(active, 250), {
            initialProps: { active: true },
        })

        expect(result.current).toBe(false)

        act(() => {
            vi.advanceTimersByTime(200)
        })
        expect(result.current).toBe(false)

        // Request finished before the delay elapsed: flag never turns on.
        rerender({ active: false })
        act(() => {
            vi.advanceTimersByTime(300)
        })
        expect(result.current).toBe(false)
    })

    it("turns true after the delay while still active", () => {
        const { result } = renderHook(() => useDelayedFlag(true, 250))

        act(() => {
            vi.advanceTimersByTime(250)
        })
        expect(result.current).toBe(true)
    })

    it("resets to false immediately when active turns off", () => {
        const { result, rerender } = renderHook(({ active }) => useDelayedFlag(active, 250), {
            initialProps: { active: true },
        })

        act(() => {
            vi.advanceTimersByTime(250)
        })
        expect(result.current).toBe(true)

        rerender({ active: false })
        expect(result.current).toBe(false)
    })
})
