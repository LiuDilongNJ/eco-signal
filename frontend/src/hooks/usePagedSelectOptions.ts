import { useCallback, useEffect, useRef, useState } from "react"

export type PagedSelectResult<T> = {
    items: T[]
    hasMore: boolean
}

export type PagedSelectState<T> = {
    options: T[]
    page: number
    query: string
    loading: boolean
    hasMore: boolean
}

type UsePagedSelectOptionsParams<T> = {
    pageSize: number
    getKey: (option: T) => string | number
    fetchPage: (query: string, page: number, pageSize: number) => Promise<PagedSelectResult<T>>
    requireQuery?: boolean
    debounceMs?: number
}

const EMPTY_QUERY_DELAY_MS = 300

function mergeOptions<T>(
    getKey: (option: T) => string | number,
    ...groups: Array<Array<T | null | undefined>>
): T[] {
    const result: T[] = []
    const seen = new Set<string | number>()
    for (const group of groups) {
        for (const option of group) {
            if (option == null) continue
            const key = getKey(option)
            if (seen.has(key)) continue
            seen.add(key)
            result.push(option)
        }
    }
    return result
}

export function usePagedSelectOptions<T>({
    pageSize,
    getKey,
    fetchPage,
    requireQuery = false,
    debounceMs = EMPTY_QUERY_DELAY_MS,
}: UsePagedSelectOptionsParams<T>) {
    const [state, setState] = useState<PagedSelectState<T>>({
        options: [],
        page: 0,
        query: "",
        loading: false,
        hasMore: false,
    })
    const stateRef = useRef(state)
    const currentRef = useRef<T | null>(null)
    const requestVersionRef = useRef(0)
    const loadingRef = useRef(false)
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const fetchPageRef = useRef(fetchPage)
    const getKeyRef = useRef(getKey)

    fetchPageRef.current = fetchPage
    getKeyRef.current = getKey

    const updateState = useCallback((next: PagedSelectState<T>) => {
        stateRef.current = next
        setState(next)
    }, [])

    const cancelPending = useCallback(() => {
        requestVersionRef.current += 1
        loadingRef.current = false
        if (searchTimerRef.current) {
            clearTimeout(searchTimerRef.current)
            searchTimerRef.current = null
        }
    }, [])

    const loadPage = useCallback(
        async (query: string, page: number, replace: boolean) => {
            const normalizedQuery = query.trim()
            if (requireQuery && normalizedQuery === "") {
                cancelPending()
                updateState({
                    options: currentRef.current ? [currentRef.current] : [],
                    page: 0,
                    query: "",
                    loading: false,
                    hasMore: false,
                })
                return
            }
            if (!replace && loadingRef.current) return

            const requestVersion = replace
                ? ++requestVersionRef.current
                : requestVersionRef.current
            loadingRef.current = true
            const existing = stateRef.current
            updateState({
                options: replace
                    ? currentRef.current
                        ? [currentRef.current]
                        : []
                    : existing.options,
                page: replace ? 0 : existing.page,
                query: normalizedQuery,
                loading: true,
                hasMore: replace ? false : existing.hasMore,
            })

            try {
                const result = await fetchPageRef.current(normalizedQuery, page, pageSize)
                if (requestVersion !== requestVersionRef.current) return
                const current = currentRef.current
                updateState({
                    options: replace
                        ? mergeOptions(getKeyRef.current, current ? [current] : [], result.items)
                        : mergeOptions(getKeyRef.current, stateRef.current.options, result.items),
                    page,
                    query: normalizedQuery,
                    loading: false,
                    hasMore: result.hasMore,
                })
            } catch {
                if (requestVersion !== requestVersionRef.current) return
                updateState({
                    ...stateRef.current,
                    loading: false,
                    hasMore: false,
                })
            } finally {
                if (requestVersion === requestVersionRef.current) {
                    loadingRef.current = false
                }
            }
        },
        [cancelPending, pageSize, requireQuery, updateState],
    )

    const loadFirst = useCallback(
        (query = "") => loadPage(query, 1, true),
        [loadPage],
    )

    const loadNext = useCallback(() => {
        const current = stateRef.current
        if (current.loading || !current.hasMore || current.page === 0) return
        void loadPage(current.query, current.page + 1, false)
    }, [loadPage])

    const search = useCallback(
        (query: string) => {
            cancelPending()
            const normalizedQuery = query.trim()
            updateState({
                options: currentRef.current ? [currentRef.current] : [],
                page: 0,
                query: normalizedQuery,
                loading: false,
                hasMore: false,
            })
            if (requireQuery && normalizedQuery === "") return
            searchTimerRef.current = setTimeout(() => {
                searchTimerRef.current = null
                void loadPage(normalizedQuery, 1, true)
            }, debounceMs)
        },
        [cancelPending, debounceMs, loadPage, requireQuery, updateState],
    )

    const reset = useCallback(
        (current: T | null = null) => {
            cancelPending()
            currentRef.current = current
            updateState({
                options: current ? [current] : [],
                page: 0,
                query: "",
                loading: false,
                hasMore: false,
            })
        },
        [cancelPending, updateState],
    )

    const setCurrentOption = useCallback((current: T | null) => {
        currentRef.current = current
        if (!current) return
        const next = {
            ...stateRef.current,
            options: mergeOptions(getKeyRef.current, [current], stateRef.current.options),
        }
        stateRef.current = next
        setState(next)
    }, [])

    useEffect(() => cancelPending, [cancelPending])

    return {
        ...state,
        loadFirst,
        loadNext,
        reset,
        search,
        setCurrentOption,
    }
}

export function isSelectScrollNearBottom(target: EventTarget | null, threshold = 24): boolean {
    if (!(target instanceof HTMLElement)) return false
    return target.scrollTop + target.clientHeight >= target.scrollHeight - threshold
}
