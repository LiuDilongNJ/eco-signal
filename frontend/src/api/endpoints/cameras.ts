import { apiClient } from "../client"
import type { CsvImportResult } from "../csvImport"

export interface CameraLensInfo {
    lens_id: number
    name?: string | null
    is_default?: boolean | null
    notes?: string | null
}

export interface CameraPublic {
    camera_id: number
    uuid: string
    name?: string | null
    version?: string | null
    brand?: string | null
    lenses: CameraLensInfo[]
}

export interface CameraListItem {
    camera_id: number
    uuid: string
    name?: string | null
    version?: string | null
    brand?: string | null
    lens_count: number
}

export interface PagedCamerasResponse {
    code: number
    message: string
    data: CameraListItem[]
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    }
}

export interface CameraCreateBody {
    name: string
    version?: string | null
    brand?: string | null
}

export interface CameraUpdateBody {
    name?: string
    version?: string | null
    brand?: string | null
}

export interface CameraLensCreateBody {
    lens_id: number
    is_default?: boolean
    notes?: string | null
}
export type ImportResult = CsvImportResult

export interface ListCamerasParams {
    page?: number
    page_size?: number
    camera_id?: number | string
    uuid?: string
    name?: string
    version?: string
    brand?: string
    lens_count?: number | string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export const camerasApi = {
    list(params?: ListCamerasParams) {
        const clean = params
            ? Object.fromEntries(
                  Object.entries(params).filter(
                      ([, v]) => v !== undefined && v !== null && String(v).trim() !== "",
                  ),
              )
            : undefined
        return apiClient.get<PagedCamerasResponse>("/v1/cameras", { params: clean as Record<string, string | number> })
    },

    get(cameraId: number) {
        return apiClient.get<{ code: number; message: string; data: CameraPublic }>(`/v1/cameras/${cameraId}`)
    },

    create(body: CameraCreateBody) {
        return apiClient.post<{ code: number; message: string; data: CameraPublic }>("/v1/cameras", body)
    },

    update(cameraId: number, body: CameraUpdateBody) {
        return apiClient.put<{ code: number; message: string; data: CameraPublic }>(`/v1/cameras/${cameraId}`, body)
    },

    delete(cameraId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/cameras/${cameraId}`)
    },
    importCsv(file: File) {
        const formData = new FormData()
        formData.append("file", file)
        return apiClient.post<{ code: number; message: string; data: ImportResult }>("/v1/cameras/imports", formData)
    },

    addLens(cameraId: number, body: CameraLensCreateBody) {
        return apiClient.post<{ code: number; message: string; data: null }>(
            `/v1/cameras/${cameraId}/lenses`,
            body,
        )
    },

    removeLens(cameraId: number, lensId: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/cameras/${cameraId}/lenses/${lensId}`)
    },

    exportCsv(params?: Omit<ListCamerasParams, "page" | "page_size">) {
        const clean = params
            ? Object.fromEntries(
                  Object.entries(params).filter(
                      ([, v]) => v !== undefined && v !== null && String(v).trim() !== "",
                  ),
              )
            : undefined
        return apiClient.download("/v1/cameras/exports", {
            params: clean as Record<string, string | number>,
        })
    },
}
