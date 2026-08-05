import type { GetMediaParams } from "../../../../../api/endpoints/media"
import type { TableState } from "../DataPageLayout"

type MediaQueryState = Pick<
    TableState,
    "page" | "pageSize" | "filters" | "sortKey" | "sortDir"
>

export interface BuildMediaQueryParamsOptions {
    includePagination?: boolean
    includeSorting?: boolean
    includeSiteFilter?: boolean
}

export function resolveMetadataTypeFilter(value: unknown): string | undefined {
    const normalized = String(value).toLowerCase().trim()
    if (!normalized) return undefined
    if (
        normalized.includes("meta") ||
        normalized === "true" ||
        normalized === "1" ||
        normalized === "yes"
    ) {
        return "metadata"
    }
    if (
        normalized.includes("file") ||
        normalized === "false" ||
        normalized === "0" ||
        normalized === "no"
    ) {
        return "file"
    }
    return normalized
}

export function buildMediaQueryParams(
    mediaType: "audio" | "photo",
    state: MediaQueryState | null,
    scope: {
        projectId?: string | number | null
        collectionId?: string | number | null
    },
    options: BuildMediaQueryParamsOptions = {},
): GetMediaParams {
    const {
        includePagination = true,
        includeSorting = true,
        includeSiteFilter = true,
    } = options
    const params: GetMediaParams = { media_type: mediaType }

    if (state) {
        if (includePagination) {
            params.page = state.page
            params.page_size = state.pageSize
        }

        if (includeSorting) {
            if (state.sortKey) {
                params.order_by = state.sortKey
                params.order_dir = state.sortDir || "asc"
            }
        }

        Object.entries(state.filters).forEach(([key, value]) => {
            if (value === "" || value === null || value === undefined) return

            if (key === "media_id") {
                params.media_id = Number(value)
            } else if (key === "labels") {
                params.label_name = String(value).trim()
            } else if (key === "site_name") {
                if (includeSiteFilter) {
                    params.site_name = String(value).trim()
                }
            } else if (key === "date_time") {
                const [start, end] = String(value).split(",")
                if (start) params.date_time_from = start
                if (end) params.date_time_to = end
            } else if (key === "is_metadata") {
                const typeFilter = resolveMetadataTypeFilter(value)
                if (typeFilter) params.type = typeFilter
            } else if (
                key !== "project_id" &&
                key !== "collection_id" &&
                key !== "media_type"
            ) {
                params[key] = String(value)
            }
        })
    }

    if (scope.projectId !== undefined && scope.projectId !== null && scope.projectId !== "") {
        params.project_id = Number(scope.projectId)
    }
    if (
        scope.collectionId !== undefined &&
        scope.collectionId !== null &&
        scope.collectionId !== "" &&
        scope.collectionId !== "all"
    ) {
        params.collection_id = Number(scope.collectionId)
    }

    return params
}
