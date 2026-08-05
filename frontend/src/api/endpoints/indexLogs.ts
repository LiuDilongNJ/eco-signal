import dayjs from "dayjs"
import { apiClient } from "../client"

export interface IndexLogDeleteItem {
    log_id: number
    media_id: number
    index_id: number
}

export interface IndexLogCreateRequest {
    project_id: number
    media_id: number
    index_id: number
    version: string
    min_time?: string | null
    max_time?: string | null
    min_frequency?: string | null
    max_frequency?: string | null
    params: Record<string, unknown>
    results: Record<string, unknown>
}

export interface IndexLogCreateResponse {
    log_id: number
    stored_count: number
}

export interface IndexLogFilterOption {
    label: string
    value: string
}

export interface IndexLogFilterOptions {
    user: IndexLogFilterOption[]
    index_type: IndexLogFilterOption[]
    var_type: IndexLogFilterOption[]
}

function formatDisplayDate(iso: string | null | undefined): string {
    if (!iso) return ""
    const d = dayjs(iso)
    return d.isValid() ? d.format("YYYY-MM-DD HH:mm:ss") : iso
}

/** GET /v1/index-logs item (IndexLogRead) */
export interface IndexLogPublic {
    log_id: number
    media_id: number
    user_id: number
    index_id: number
    version: string | null
    min_time: string | null
    max_time: string | null
    min_frequency: string | null
    max_frequency: string | null
    variable_type: string | null
    variable_order: number
    variable_name: string | null
    variable_value: string | null
    creation_date: string
    media_name?: string | null
    user_name?: string | null
    index_name?: string | null
}

export interface PagedIndexLogsResponse {
    code: number
    message: string
    data: IndexLogPublic[] | null
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    } | null
}

export interface ListIndexLogsParams {
    page?: number
    page_size?: number
    project_id?: number
    collection_id?: number
    media_id?: number | string
    log_id?: number | string
    version?: string
    min_t_min?: number | string
    min_t_max?: number | string
    max_t_min?: number | string
    max_t_max?: number | string
    min_f_min?: number | string
    min_f_max?: number | string
    max_f_min?: number | string
    max_f_max?: number | string
    var_type?: string
    var_order_min?: number | string
    var_order_max?: number | string
    var_name?: string
    var_value_min?: number | string
    var_value_max?: number | string
    media_name?: string
    user?: string
    index_type?: string
    creation_date_from?: string
    creation_date_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface IndexLogExportParams {
    project_id?: number
    collection_id?: number
    order_by?: string
    order_dir?: "asc" | "desc"
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

/** Map current GET /v1/index-logs response to DataPageLayout table row. */
export function formatIndexLogRow(r: IndexLogPublic, idx: number): Record<string, unknown> {
    return {
        __key: `${r.log_id}_${r.variable_name ?? ""}_${r.variable_order}_${idx}`,
        log_id: r.log_id,
        media_id: r.media_id,
        index_id: r.index_id,
        media_name: r.media_name ?? "",
        user_name: r.user_name ?? "",
        index_name: r.index_name ?? "",
        version: r.version ?? "",
        min_time: r.min_time ?? "",
        max_time: r.max_time ?? "",
        min_frequency: r.min_frequency ?? "",
        max_frequency: r.max_frequency ?? "",
        variable_type: r.variable_type ?? "",
        variable_order: r.variable_order,
        variable_name: r.variable_name ?? "",
        variable_value: r.variable_value ?? "",
        creation_date: formatDisplayDate(r.creation_date),
    }
}

export const indexLogsApi = {
    create(payload: IndexLogCreateRequest) {
        return apiClient.post<{ code: number; message: string; data: IndexLogCreateResponse }>("/v1/index-logs", payload)
    },

    getList(params?: ListIndexLogsParams) {
        return apiClient.get<PagedIndexLogsResponse>("/v1/index-logs", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    getFilterOptions(params?: { project_id?: number; collection_id?: number }) {
        return apiClient.get<{ code: number; message: string; data: IndexLogFilterOptions }>(
            "/v1/index-logs/filter-options",
            { params: cleanParams(params as Record<string, unknown>) },
        )
    },

    exportCsv(params?: IndexLogExportParams) {
        return apiClient.download("/v1/index-logs/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    deleteGroups(items: IndexLogDeleteItem[]) {
        return apiClient.delete<any>("/v1/index-logs", { body: items })
    },
}
