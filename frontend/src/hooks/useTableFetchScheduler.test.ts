import { renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useTableFetchScheduler } from "./useTableFetchScheduler"

interface TestState {
    page: number
    pageSize: number
    searchQuery: string
    filters: Record<string, string>
    sortKey: string | null
    sortDir: "asc" | "desc" | null
}

function makeState(overrides: Partial<TestState> = {}): TestState {
    return {
        page: 1,
        pageSize: 10,
        searchQuery: "",
        filters: {},
        sortKey: null,
        sortDir: null,
        ...overrides,
    }
}

describe("useTableFetchScheduler", () => {
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it("runs the initial fetch immediately", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        expect(fetcher).toHaveBeenCalledTimes(1)
    })

    it("runs pagination and sorting changes immediately", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        result.current(makeState({ page: 2 }))
        result.current(makeState({ page: 2, sortKey: "name", sortDir: "desc" }))
        expect(fetcher).toHaveBeenCalledTimes(3)
    })

    it("runs project and collection context changes immediately", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState({ filters: { project_id: "1", collection_id: "10" } }))
        result.current(makeState({ filters: { project_id: "1", collection_id: "11" } }))
        result.current(makeState({ filters: { project_id: "2", collection_id: "20" } }))

        expect(fetcher).toHaveBeenCalledTimes(3)
        expect(fetcher).toHaveBeenLastCalledWith(
            makeState({ filters: { project_id: "2", collection_id: "20" } }),
        )
    })

    it("debounces filter changes by 400ms", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        expect(fetcher).toHaveBeenCalledTimes(1)

        result.current(makeState({ filters: { name: "a" } }))
        result.current(makeState({ filters: { name: "ab" } }))
        expect(fetcher).toHaveBeenCalledTimes(1)

        vi.advanceTimersByTime(400)
        expect(fetcher).toHaveBeenCalledTimes(2)
        expect(fetcher).toHaveBeenLastCalledWith(makeState({ filters: { name: "ab" } }))
    })

    it("debounces even when a filter change also resets the page", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState({ page: 3 }))
        expect(fetcher).toHaveBeenCalledTimes(1)

        // Typing a filter resets page to 1 in the same state update.
        result.current(makeState({ page: 1, filters: { name: "a" } }))
        expect(fetcher).toHaveBeenCalledTimes(1)

        vi.advanceTimersByTime(400)
        expect(fetcher).toHaveBeenCalledTimes(2)
    })

    it("debounces search query changes", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        result.current(makeState({ searchQuery: "abc" }))
        expect(fetcher).toHaveBeenCalledTimes(1)

        vi.advanceTimersByTime(400)
        expect(fetcher).toHaveBeenCalledTimes(2)
    })

    it("treats cleared filter values and missing keys as equal", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState({ filters: { name: "" } }))
        // Same effective filters, page changed -> immediate.
        result.current(makeState({ page: 2, filters: {} }))
        expect(fetcher).toHaveBeenCalledTimes(2)
    })

    it("re-running with an identical state fetches immediately (refresh)", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        const state = makeState({ filters: { name: "x" } })
        result.current(state)
        expect(fetcher).toHaveBeenCalledTimes(1)

        result.current(state)
        expect(fetcher).toHaveBeenCalledTimes(2)
    })

    it("an immediate trigger cancels a pending debounced fetch", () => {
        const fetcher = vi.fn()
        const { result } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        result.current(makeState({ filters: { name: "a" } }))
        // Pagination fires before the debounce elapses; only the latest state should fetch.
        result.current(makeState({ page: 2, filters: { name: "a" } }))
        expect(fetcher).toHaveBeenCalledTimes(2)

        vi.advanceTimersByTime(400)
        expect(fetcher).toHaveBeenCalledTimes(2)
    })

    it("cancels a pending debounced fetch on unmount", () => {
        const fetcher = vi.fn()
        const { result, unmount } = renderHook(() => useTableFetchScheduler(fetcher))

        result.current(makeState())
        result.current(makeState({ filters: { name: "a" } }))
        unmount()

        vi.advanceTimersByTime(400)
        expect(fetcher).toHaveBeenCalledTimes(1)
    })

    it("always uses the latest fetcher instance", () => {
        const first = vi.fn()
        const second = vi.fn()
        const { result, rerender } = renderHook(({ fn }) => useTableFetchScheduler(fn), {
            initialProps: { fn: first },
        })

        result.current(makeState())
        expect(first).toHaveBeenCalledTimes(1)

        rerender({ fn: second })
        result.current(makeState({ page: 2 }))
        expect(second).toHaveBeenCalledTimes(1)
        expect(first).toHaveBeenCalledTimes(1)
    })
})
