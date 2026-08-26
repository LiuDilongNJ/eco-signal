import { apiClient } from "../client"
import type { PagedApiResponse } from "../../types"
import type { ImportResult } from "../tabularImport"

export interface SoundClassificationRecord {
    sound_id: number
    soundscape_component: string | null
    sound_type: string | null
}

export interface ListSoundClassificationParams {
    page?: number
    page_size?: number
    sound_id?: number
    soundscape_component?: string
    sound_type?: string
    order_by?: "sound_id" | "soundscape_component" | "sound_type"
    order_dir?: "asc" | "desc"
}

export interface SoundClassificationWriteBody {
    soundscape_component: string
    sound_type: string | null
}

export type SoundClassificationImportResult = ImportResult

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, value]) => (
            value !== undefined && value !== null && String(value).trim() !== ""
        )),
    ) as Record<string, string | number>
}

const BASE = "/v1/sound-classification-records"

export const soundClassificationsApi = {
    list(params?: ListSoundClassificationParams) {
        return apiClient.get<PagedApiResponse<SoundClassificationRecord[]>>(BASE, {
            params: cleanParams(params as Record<string, unknown>),
            ignoreUnauthorized: true,
        })
    },

    get(soundId: number) {
        return apiClient.get<{ code: number; message: string; data: SoundClassificationRecord }>(
            `${BASE}/${soundId}`,
        )
    },

    create(body: SoundClassificationWriteBody) {
        return apiClient.post<{ code: number; message: string; data: SoundClassificationRecord }>(BASE, body)
    },

    update(soundId: number, body: SoundClassificationWriteBody) {
        return apiClient.put<{ code: number; message: string; data: SoundClassificationRecord }>(
            `${BASE}/${soundId}`,
            body,
        )
    },

    delete(soundId: number) {
        return apiClient.delete<{ code: number; message: string; data: null }>(`${BASE}/${soundId}`)
    },

    importCsv(file: File, dryRun = true) {
        const formData = new FormData()
        formData.append("file", file)
        formData.append("dry_run", String(dryRun))
        return apiClient.post<{
            code: number
            message: string
            data: SoundClassificationImportResult
        }>(`${BASE}/imports`, formData)
    },

    exportCsv(params?: Pick<ListSoundClassificationParams, "order_by" | "order_dir">) {
        return apiClient.download(`${BASE}/exports`, {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
