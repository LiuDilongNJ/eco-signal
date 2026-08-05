import { useCallback, useEffect, useRef, useState } from "react"

import {
    taxonsApi,
    type TaxonOption,
    type TaxonOptionsQueryParams,
} from "../../../api/endpoints/taxons"

export type TaxonHierarchyRank = TaxonOptionsQueryParams["rank"]

type TaxonOptionContext = Pick<
    TaxonOptionsQueryParams,
    "class_id" | "order_id" | "family_id" | "genus_id"
>

export type TaxonHierarchyOptionState = {
    options: TaxonOption[]
    page: number
    totalPages: number
    query: string
    loading: boolean
    context: TaxonOptionContext
}

const TAXON_OPTION_PAGE_SIZE = 100
const TAXON_SEARCH_DELAY_MS = 300
const RANKS: TaxonHierarchyRank[] = ["class", "order", "family", "genus", "species"]

function emptyState(): TaxonHierarchyOptionState {
    return {
        options: [],
        page: 0,
        totalPages: 1,
        query: "",
        loading: false,
        context: {},
    }
}

function initialStates(): Record<TaxonHierarchyRank, TaxonHierarchyOptionState> {
    return {
        class: emptyState(),
        order: emptyState(),
        family: emptyState(),
        genus: emptyState(),
        species: emptyState(),
    }
}

export function mergeTaxonOptions(...groups: Array<Array<TaxonOption | null | undefined>>): TaxonOption[] {
    const result: TaxonOption[] = []
    const seen = new Set<string>()
    for (const group of groups) {
        for (const option of group) {
            if (!option || seen.has(option.id)) continue
            seen.add(option.id)
            result.push(option)
        }
    }
    return result
}

export function useTaxonHierarchyOptions() {
    const [states, setStates] = useState(initialStates)
    const statesRef = useRef(states)
    const selectedRef = useRef<Record<TaxonHierarchyRank, TaxonOption | null>>({
        class: null,
        order: null,
        family: null,
        genus: null,
        species: null,
    })
    const requestVersionRef = useRef<Record<TaxonHierarchyRank, number>>({
        class: 0,
        order: 0,
        family: 0,
        genus: 0,
        species: 0,
    })
    const loadingRef = useRef<Record<TaxonHierarchyRank, boolean>>({
        class: false,
        order: false,
        family: false,
        genus: false,
        species: false,
    })
    const searchTimersRef = useRef<Partial<Record<TaxonHierarchyRank, ReturnType<typeof setTimeout>>>>({})

    const updateRank = useCallback(
        (
            rank: TaxonHierarchyRank,
            updater: (current: TaxonHierarchyOptionState) => TaxonHierarchyOptionState,
        ) => {
            setStates((current) => {
                const next = { ...current, [rank]: updater(current[rank]) }
                statesRef.current = next
                return next
            })
        },
        [],
    )

    const cancelRank = useCallback((rank: TaxonHierarchyRank) => {
        requestVersionRef.current[rank] += 1
        loadingRef.current[rank] = false
        const timer = searchTimersRef.current[rank]
        if (timer) {
            clearTimeout(timer)
            delete searchTimersRef.current[rank]
        }
    }, [])

    const resetRank = useCallback(
        (rank: TaxonHierarchyRank, selected: TaxonOption | null = null) => {
            cancelRank(rank)
            selectedRef.current[rank] = selected
            updateRank(rank, () => ({
                ...emptyState(),
                options: selected ? [selected] : [],
            }))
        },
        [cancelRank, updateRank],
    )

    const setSelectedOption = useCallback(
        (rank: TaxonHierarchyRank, selected: TaxonOption | null) => {
            selectedRef.current[rank] = selected
            if (!selected) return
            updateRank(rank, (current) => ({
                ...current,
                options: mergeTaxonOptions([selected], current.options),
            }))
        },
        [updateRank],
    )

    const loadPage = useCallback(
        async (
            rank: TaxonHierarchyRank,
            context: TaxonOptionContext,
            query: string,
            page: number,
            replace: boolean,
            selected?: TaxonOption | null,
        ) => {
            if (!replace && loadingRef.current[rank]) return
            if (selected !== undefined) selectedRef.current[rank] = selected

            const normalizedQuery = query.trim()
            const requestVersion = replace
                ? ++requestVersionRef.current[rank]
                : requestVersionRef.current[rank]
            loadingRef.current[rank] = true
            updateRank(rank, (current) => ({
                ...current,
                context,
                query: normalizedQuery,
                loading: true,
                ...(replace
                    ? {
                        options: selectedRef.current[rank] ? [selectedRef.current[rank]!] : [],
                        page: 0,
                        totalPages: 1,
                    }
                    : {}),
            }))

            try {
                const response = await taxonsApi.listOptions({
                    rank,
                    ...context,
                    q: normalizedQuery || undefined,
                    page,
                    page_size: TAXON_OPTION_PAGE_SIZE,
                })
                if (
                    requestVersion !== requestVersionRef.current[rank]
                    || response.code !== 0
                ) {
                    return
                }

                const incoming = response.data ?? []
                const total = response.page_info?.total ?? incoming.length
                const totalPages = response.page_info?.total_pages
                    ?? Math.max(1, Math.ceil(total / TAXON_OPTION_PAGE_SIZE))
                updateRank(rank, (current) => ({
                    ...current,
                    options: replace
                        ? mergeTaxonOptions(
                            selectedRef.current[rank] ? [selectedRef.current[rank]] : [],
                            incoming,
                        )
                        : mergeTaxonOptions(current.options, incoming),
                    page,
                    totalPages,
                    loading: false,
                    context,
                    query: normalizedQuery,
                }))
            } catch {
                // Keep the current selection available when the remote dictionary cannot be loaded.
            } finally {
                if (requestVersion === requestVersionRef.current[rank]) {
                    loadingRef.current[rank] = false
                    updateRank(rank, (current) => ({ ...current, loading: false }))
                }
            }
        },
        [updateRank],
    )

    const loadFirst = useCallback(
        (
            rank: TaxonHierarchyRank,
            context: TaxonOptionContext = {},
            selected?: TaxonOption | null,
        ) => loadPage(rank, context, "", 1, true, selected),
        [loadPage],
    )

    const loadNext = useCallback(
        (rank: TaxonHierarchyRank) => {
            const current = statesRef.current[rank]
            if (current.loading || current.page === 0 || current.page >= current.totalPages) return
            void loadPage(
                rank,
                current.context,
                current.query,
                current.page + 1,
                false,
            )
        },
        [loadPage],
    )

    const search = useCallback(
        (
            rank: TaxonHierarchyRank,
            context: TaxonOptionContext,
            query: string,
        ) => {
            cancelRank(rank)
            const normalizedQuery = query.trim()
            updateRank(rank, () => ({
                ...emptyState(),
                context,
                query: normalizedQuery,
                options: selectedRef.current[rank] ? [selectedRef.current[rank]!] : [],
            }))
            searchTimersRef.current[rank] = setTimeout(() => {
                delete searchTimersRef.current[rank]
                void loadPage(rank, context, normalizedQuery, 1, true)
            }, TAXON_SEARCH_DELAY_MS)
        },
        [cancelRank, loadPage, updateRank],
    )

    const resetAll = useCallback(() => {
        for (const rank of RANKS) {
            cancelRank(rank)
            selectedRef.current[rank] = null
        }
        const next = initialStates()
        statesRef.current = next
        setStates(next)
    }, [cancelRank])

    useEffect(() => {
        return () => {
            for (const rank of RANKS) cancelRank(rank)
        }
    }, [cancelRank])

    return {
        states,
        loadFirst,
        loadNext,
        resetAll,
        resetRank,
        search,
        setSelectedOption,
    }
}
