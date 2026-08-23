import { apiClient } from "../client"
import type { ImportResult as TabularImportResult } from "../tabularImport"

export interface RecorderOption {
    recorder_id: number
    name: string
}

export interface RecorderMicrophoneInfo {
    microphone_id: number
    name?: string
    is_default?: boolean
    notes?: string
}

export interface RecorderListItem {
    recorder_id: number
    uuid: string
    name?: string
    version?: string
    brand?: string
    microphone_count: number
}

export interface RecorderPublic {
    recorder_id: number
    uuid: string
    name?: string
    version?: string
    brand?: string
    microphones: RecorderMicrophoneInfo[]
}

export interface RecorderCreateBody {
    name?: string | null
    version?: string | null
    brand?: string | null
}

export interface RecorderUpdateBody {
    name?: string | null
    version?: string | null
    brand?: string | null
}
export type ImportResult = TabularImportResult

export interface ListRecordersParams {
    page?: number
    page_size?: number
    recorder_id?: number | string
    uuid?: string
    name?: string
    version?: string
    brand?: string
    microphone_count?: number | string
    order_by?: string
    order_dir?: "asc" | "desc"
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const recordersApi = {
    getOptions() {
        return apiClient.get<{ code: number; message: string; data: RecorderOption[] }>("/v1/recorder-options")
    },

    list(params?: ListRecordersParams) {
        return apiClient.get<{
            code: number
            message: string
            data: RecorderListItem[]
            page_info: { total: number; page: number; page_size: number }
        }>("/v1/recorders", { params: cleanParams(params as Record<string, unknown>) })
    },

    create(body: RecorderCreateBody) {
        return apiClient.post<{ code: number; message: string }>("/v1/recorders", body)
    },

    get(id: number) {
        return apiClient.get<{ code: number; message: string; data: RecorderPublic }>(`/v1/recorders/${id}`)
    },

    update(id: number, body: RecorderUpdateBody) {
        return apiClient.put<{ code: number; message: string }>(`/v1/recorders/${id}`, body)
    },

    delete(id: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/recorders/${id}`)
    },
    importCsv(file: File, dryRun = true) {
        const formData = new FormData()
        formData.append("file", file)
        formData.append("dry_run", String(dryRun))
        return apiClient.post<{ code: number; message: string; data: ImportResult }>("/v1/recorders/imports", formData)
    },

    exportCsv(params?: Omit<ListRecordersParams, "page" | "page_size">) {
        return apiClient.download("/v1/recorders/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
