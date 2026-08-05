import { useCallback, useEffect } from "react"

import { geoApi, type GenericGeoOption } from "../../../../api/endpoints/geo"
import { usePagedSelectOptions } from "../../../../hooks/usePagedSelectOptions"

export type GeoOptionType = "iho" | "realm" | "biome" | "functionalType"

export type GeoOptionsFilter = {
    parentRealmId?: number | null
    parentBiomeId?: number | null
}

const GEO_PAGE_SIZE = 100

function geoOptionKey(option: GenericGeoOption): string | number {
    return option.id ?? option.gid ?? option.name
}

export function useGeoOptions(type: GeoOptionType, filter?: GeoOptionsFilter) {
    const parentRealmId = filter?.parentRealmId
    const parentBiomeId = filter?.parentBiomeId
    const enabled =
        (type !== "biome" || filter === undefined || parentRealmId != null)
        && (type !== "functionalType" || filter === undefined || parentBiomeId != null)

    const fetchPage = useCallback(
        async (query: string, page: number, pageSize: number) => {
            if (!enabled) return { items: [], hasMore: false }
            const pageParams = {
                search: query || undefined,
                page,
                page_size: pageSize,
            }
            const response =
                type === "iho"
                    ? await geoApi.getIhoOptions(pageParams, true)
                    : type === "realm"
                      ? await geoApi.getIucnRealms(pageParams, true)
                      : type === "biome"
                        ? await geoApi.getIucnBiomes(
                              { ...pageParams, realm_id: parentRealmId ?? undefined },
                              true,
                          )
                        : await geoApi.getIucnFunctionalTypes(
                              { ...pageParams, biome_id: parentBiomeId ?? undefined },
                              true,
                          )
            return {
                items: response.data ?? [],
                hasMore: page < (response.page_info?.total_pages ?? 1),
            }
        },
        [enabled, parentBiomeId, parentRealmId, type],
    )

    const paged = usePagedSelectOptions<GenericGeoOption>({
        pageSize: GEO_PAGE_SIZE,
        getKey: geoOptionKey,
        fetchPage,
    })

    useEffect(() => {
        paged.reset()
        if (enabled) void paged.loadFirst()
        // Parent IDs define a new cascade context and must replace prior pages.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled, parentBiomeId, parentRealmId, type])

    return paged
}
