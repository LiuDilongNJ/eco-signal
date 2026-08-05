/**
 * 许可证 / Copyright（与后端 `GET/POST/PUT/DELETE /api/v1/licenses` 一致，Redoc tag: licenses）
 */
import { apiClient } from "../client"

export interface LicenseOption {
    license_id: number
    name: string
}

export interface LicensePublic {
    license_id: number
    name: string
    link: string
}

export interface PagedLicensesResponse {
    code: number
    message: string
    data: LicensePublic[] | null
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    } | null
}

export interface ListLicensesParams {
    page?: number
    page_size?: number
    license_id?: number | string
    name?: string
    link?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface LicenseCreateBody {
    name: string
    link: string
}

export interface LicenseUpdateBody {
    name?: string | null
    link?: string | null
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const licensesApi = {
    /** 下拉选项（公开） */
    getOptions(params?: { project_id?: number; collection_id?: number }) {
        return apiClient.get<{ code: number; message: string; data: LicenseOption[] }>("/v1/license-options", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    list(params?: ListLicensesParams) {
        return apiClient.get<PagedLicensesResponse>("/v1/licenses", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    get(licenseId: number) {
        return apiClient.get<{ code: number; message: string; data: LicensePublic }>(`/v1/licenses/${licenseId}`)
    },

    create(body: LicenseCreateBody) {
        return apiClient.post<{ code: number; message: string; data: LicensePublic }>("/v1/licenses", body)
    },

    update(licenseId: number, body: LicenseUpdateBody) {
        return apiClient.put<{ code: number; message: string; data: LicensePublic }>(`/v1/licenses/${licenseId}`, body)
    },

    delete(licenseId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/licenses/${licenseId}`)
    },

    exportCsv(params?: Omit<ListLicensesParams, "page" | "page_size">) {
        return apiClient.download("/v1/licenses/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
