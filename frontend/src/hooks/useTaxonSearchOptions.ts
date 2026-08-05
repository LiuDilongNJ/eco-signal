import { useCallback } from "react"

import { taxonsApi, type TaxonPublic } from "../api/endpoints/taxons"
import { usePagedSelectOptions } from "./usePagedSelectOptions"

export type TaxonSearchOption<TValue extends string | number = number> = {
    value: TValue
    label: string
    taxon: TaxonPublic
}

export function formatTaxonOptionLabel(taxon: TaxonPublic): string {
    const scientificName = (taxon.cached_scientific_name ?? "").trim()
    const commonName = (taxon.cached_common_name ?? "").trim()
    if (scientificName && commonName) return `${commonName} - ${scientificName}`
    return scientificName || commonName || `Taxon ${taxon.taxon_id}`
}

export function useTaxonSearchOptions<TValue extends string | number = number>({
    toValue = ((taxonId: number) => taxonId) as (taxonId: number) => TValue,
    pageSize = 50,
}: {
    toValue?: (taxonId: number) => TValue
    pageSize?: number
} = {}) {
    const fetchPage = useCallback(
        async (query: string, page: number, size: number) => {
            const rows = await taxonsApi.listSuggestionsData(
                query,
                size,
                undefined,
                (page - 1) * size,
            )
            return {
                items: rows.map((taxon) => ({
                    value: toValue(taxon.taxon_id),
                    label: formatTaxonOptionLabel(taxon),
                    taxon,
                })),
                hasMore: rows.length === size,
            }
        },
        [toValue],
    )

    return usePagedSelectOptions<TaxonSearchOption<TValue>>({
        pageSize,
        getKey: (option) => option.value,
        fetchPage,
        requireQuery: true,
    })
}
