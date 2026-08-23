import { apiClient } from "../client"
import type { ImportResult as TabularImportResult } from "../tabularImport"

export interface LensCameraInfo {
    camera_id: number
    name?: string | null
    is_default?: boolean | null
    notes?: string | null
}

export interface LensPublic {
    lens_id: number
    uuid: string
    name?: string | null
    focal_length?: string | null
    max_aperture?: string | null
    brand?: string | null
    cameras: LensCameraInfo[]
}

export type LensListItem = Omit<LensPublic, "cameras"> & {
    camera_count: number
}

export interface PagedLensesResponse {
    code: number
    message: string
    data: LensListItem[]
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    }
}

export interface ListLensesParams {
    page?: number
    page_size?: number
    lens_id?: number | string
    uuid?: string
    name?: string
    focal_length?: string
    max_aperture?: string
    brand?: string
    camera_count?: number | string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface LensCreateBody {
    name: string
    focal_length?: string | null
    max_aperture?: string | null
    brand?: string | null
}

export interface LensUpdateBody {
    name?: string
    focal_length?: string | null
    max_aperture?: string | null
    brand?: string | null
}
export type ImportResult = TabularImportResult

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const lensesApi = {
    list(params?: ListLensesParams) {
        return apiClient.get<PagedLensesResponse>("/v1/lenses", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    get(lensId: number) {
        return apiClient.get<{ code: number; message: string; data: LensPublic }>(`/v1/lenses/${lensId}`)
    },

    create(body: LensCreateBody) {
        return apiClient.post<{ code: number; message: string; data: LensPublic }>("/v1/lenses", body)
    },

    update(lensId: number, body: LensUpdateBody) {
        return apiClient.put<{ code: number; message: string; data: LensPublic }>(`/v1/lenses/${lensId}`, body)
    },

    delete(lensId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/lenses/${lensId}`)
    },
    importCsv(file: File, dryRun = true) {
        const formData = new FormData()
        formData.append("file", file)
        formData.append("dry_run", String(dryRun))
        return apiClient.post<{ code: number; message: string; data: ImportResult }>("/v1/lenses/imports", formData)
    },

    exportCsv(params?: Omit<ListLensesParams, "page" | "page_size">) {
        const clean = params
            ? Object.fromEntries(
                  Object.entries(params).filter(
                      ([, v]) => v !== undefined && v !== null && String(v).trim() !== "",
                  ),
              )
            : undefined
        return apiClient.download("/v1/lenses/exports", {
            params: clean as Record<string, string | number>,
        })
    },
}

export type FetchLensListAllParams = Omit<ListLensesParams, "page" | "page_size">

/**
 * Loads all lenses via paginated GET `/v1/lenses` (server caps `page_size` at 100).
 */
export async function fetchLensListAll(params?: FetchLensListAllParams): Promise<{
    data: LensListItem[]
    errorMessage?: string
}> {
    const all: LensListItem[] = []
    let page = 1
    const page_size = 100
    const order_by = params?.order_by ?? "name"
    const order_dir = params?.order_dir ?? "asc"
    for (;;) {
        const res = await lensesApi.list({
            ...params,
            page,
            page_size,
            order_by,
            order_dir,
        })
        if (res.code !== 0 && res.code !== 200) {
            return { data: [], errorMessage: res.message || "Failed to load lenses" }
        }
        const chunk = res.data ?? []
        all.push(...chunk)
        if (chunk.length < page_size) break
        page += 1
        if (page > 200) break
    }
    return { data: all }
}
