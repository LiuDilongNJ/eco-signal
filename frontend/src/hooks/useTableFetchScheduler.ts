/**
 * Scheduler for server-side table fetches.
 *
 * Historically every table state change (initial load, pagination, sorting,
 * nav switch, filter typing) was funneled through a fixed 400ms debounce,
 * which made even <100ms API responses feel sluggish. This hook keeps the
 * debounce only for text-driven changes (`filters` / `searchQuery`) and runs
 * every other trigger immediately.
 */

import { useCallback, useEffect, useRef } from "react"

interface DebouncedTableState {
    searchQuery?: string
    filters?: Record<string, string>
}

/** Compare filter records treating missing keys and empty strings as equal. */
function filtersEqual(a?: Record<string, string>, b?: Record<string, string>): boolean {
    const keys = new Set([...Object.keys(a ?? {}), ...Object.keys(b ?? {})])
    for (const key of keys) {
        if ((a?.[key] ?? "") !== (b?.[key] ?? "")) return false
    }
    return true
}

function contextFilterChanged(a?: Record<string, string>, b?: Record<string, string>): boolean {
    return (a?.project_id ?? "") !== (b?.project_id ?? "") ||
        (a?.collection_id ?? "") !== (b?.collection_id ?? "")
}

export function useTableFetchScheduler<S extends DebouncedTableState>(
    fetcher: (state: S) => void | Promise<void>,
    debounceMs = 400,
): (state: S) => void {
    // Keep the latest fetcher without invalidating the returned callback,
    // so pages can pass an inline/useCallback fetch with changing deps.
    const fetcherRef = useRef(fetcher)
    fetcherRef.current = fetcher

    const prevStateRef = useRef<S | null>(null)
    const timeoutRef = useRef<number | null>(null)

    useEffect(() => {
        return () => {
            if (timeoutRef.current !== null) window.clearTimeout(timeoutRef.current)
        }
    }, [])

    return useCallback(
        (state: S) => {
            const prev = prevStateRef.current
            prevStateRef.current = state

            // Only filter/search edits are typing-driven and need debouncing;
            // note filter changes also reset `page`, so filters take precedence.
            const textDriven =
                prev !== null &&
                !contextFilterChanged(prev.filters, state.filters) &&
                (!filtersEqual(prev.filters, state.filters) ||
                    (prev.searchQuery ?? "") !== (state.searchQuery ?? ""))

            if (timeoutRef.current !== null) {
                window.clearTimeout(timeoutRef.current)
                timeoutRef.current = null
            }

            if (textDriven) {
                timeoutRef.current = window.setTimeout(() => {
                    timeoutRef.current = null
                    void fetcherRef.current(state)
                }, debounceMs)
            } else {
                void fetcherRef.current(state)
            }
        },
        [debounceMs],
    )
}
