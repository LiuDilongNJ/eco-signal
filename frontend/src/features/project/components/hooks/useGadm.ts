import { useCallback, useEffect } from "react"

import { geoApi, type GadmOption } from "../../../../api/endpoints/geo"
import { usePagedSelectOptions } from "../../../../hooks/usePagedSelectOptions"

const GEO_PAGE_SIZE = 100

export function useGadm(level: number, parentGid?: string | null) {
    const enabled = level === 0 || (parentGid != null && parentGid !== "")
    const fetchPage = useCallback(
        async (query: string, page: number, pageSize: number) => {
            if (!enabled) return { items: [], hasMore: false }
            const response = await geoApi.getGadmOptions(
                {
                    level,
                    parent_gid: level > 0 ? parentGid! : undefined,
                    search: query || undefined,
                    page,
                    page_size: pageSize,
                },
                true,
            )
            return {
                items: response.data ?? [],
                hasMore: page < (response.page_info?.total_pages ?? 1),
            }
        },
        [enabled, level, parentGid],
    )
    const paged = usePagedSelectOptions<GadmOption>({
        pageSize: GEO_PAGE_SIZE,
        getKey: (option) => option.gid,
        fetchPage,
    })

    useEffect(() => {
        paged.reset()
        if (enabled) void paged.loadFirst()
        // The scalar hierarchy context is the reset boundary for this option list.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [enabled, level, parentGid])

    return paged
}
