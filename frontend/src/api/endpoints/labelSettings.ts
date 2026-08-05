/**
 * 标签设置 / Label settings（`GET/POST/PUT/DELETE /api/v1/label-settings`，Redoc tag: label-settings）
 */
import { apiClient } from "../client"

export type LabelType = "private" | "public"

export interface LabelAdminPublic {
    label_id: number
    name: string
    type: LabelType | string
    creator_id?: number | null
    creator_name?: string | null
    creation_date: string
}

export interface LabelCreatorOption {
    user_id: number
    name: string
}

export interface LabelFilterOptions {
    creator: LabelCreatorOption[]
}

export interface PagedLabelSettingsResponse {
    code: number
    message: string
    data: LabelAdminPublic[] | null
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    } | null
}

export interface ListLabelSettingsParams {
    page?: number
    page_size?: number
    label_id?: number | string
    name?: string
    type?: LabelType | string
    creator_id?: number | string
    creator_name?: string
    creation_date_from?: string
    creation_date_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface LabelAdminCreateBody {
    name: string
    type?: LabelType
}

export interface LabelAdminUpdateBody {
    name?: string
    type?: LabelType
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const labelSettingsApi = {
    list(params?: ListLabelSettingsParams) {
        return apiClient.get<PagedLabelSettingsResponse>("/v1/label-settings", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    getFilterOptions() {
        return apiClient.get<{ code: number; message: string; data: LabelFilterOptions }>(
            "/v1/label-settings/filter-options",
        )
    },

    get(labelId: number) {
        return apiClient.get<{ code: number; message: string; data: LabelAdminPublic }>(
            `/v1/label-settings/${labelId}`,
        )
    },

    create(body: LabelAdminCreateBody) {
        return apiClient.post<{ code: number; message: string; data: LabelAdminPublic }>(
            "/v1/label-settings",
            body,
        )
    },

    update(labelId: number, body: LabelAdminUpdateBody) {
        return apiClient.put<{ code: number; message: string; data: LabelAdminPublic }>(
            `/v1/label-settings/${labelId}`,
            body,
        )
    },

    delete(labelId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/label-settings/${labelId}`)
    },

    exportCsv(params?: Omit<ListLabelSettingsParams, "page" | "page_size">) {
        return apiClient.download("/v1/label-settings/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
