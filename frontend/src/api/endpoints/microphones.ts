import { apiClient } from "../client"
import type { CsvImportResult } from "../csvImport"

export interface MicrophoneOption {
    microphone_id: number
    name: string
}

export interface MicrophoneRecorderInfo {
    recorder_id: number
    name?: string | null
    is_default?: boolean | null
    notes?: string | null
}

export interface MicrophonePublic {
    microphone_id: number
    uuid: string
    name?: string
    microphone_element?: string
    sensitivity?: number
    signal_to_noise_ratio?: number
    recorders: MicrophoneRecorderInfo[]
}

export type MicrophoneListItem = Omit<MicrophonePublic, "recorders"> & {
    recorder_count: number
}

export interface MicrophoneCreateBody {
    name?: string | null
    microphone_element?: string | null
    sensitivity?: number | null
    signal_to_noise_ratio?: number | null
}

export interface MicrophoneUpdateBody {
    name?: string | null
    microphone_element?: string | null
    sensitivity?: number | null
    signal_to_noise_ratio?: number | null
}
export type ImportResult = CsvImportResult

export interface ListMicrophonesParams {
    page?: number
    page_size?: number
    microphone_id?: number | string
    uuid?: string
    name?: string
    microphone_element?: string
    sensitivity?: string
    signal_to_noise_ratio?: string
    recorder_id?: number | string
    recorder_count?: number | string
    order_by?: string
    order_dir?: "asc" | "desc"
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const microphonesApi = {
    getOptions(params?: { recorder_id?: number }) {
        return apiClient.get<{ code: number; message: string; data: MicrophoneOption[] }>("/v1/microphone-options", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    list(params?: ListMicrophonesParams) {
        return apiClient.get<{
            code: number
            message: string
            data: MicrophoneListItem[]
            page_info: { total: number; page: number; page_size: number }
        }>("/v1/microphones", { params: cleanParams(params as Record<string, unknown>) })
    },

    create(body: MicrophoneCreateBody) {
        return apiClient.post<{ code: number; message: string }>("/v1/microphones", body)
    },

    get(id: number) {
        return apiClient.get<{ code: number; message: string; data: MicrophonePublic }>(`/v1/microphones/${id}`)
    },

    update(id: number, body: MicrophoneUpdateBody) {
        return apiClient.put<{ code: number; message: string }>(`/v1/microphones/${id}`, body)
    },

    delete(id: number) {
        return apiClient.delete<{ code: number; message: string }>(`/v1/microphones/${id}`)
    },
    importCsv(file: File) {
        const formData = new FormData()
        formData.append("file", file)
        return apiClient.post<{ code: number; message: string; data: ImportResult }>("/v1/microphones/imports", formData)
    },

    exportCsv(params?: Omit<ListMicrophonesParams, "page" | "page_size">) {
        return apiClient.download("/v1/microphones/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
