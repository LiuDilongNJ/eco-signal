import { apiClient } from "../client"
import type { IndexLogCreateRequest } from "./indexLogs"

export type BirdNETLocale = "af" | "ar" | "cs" | "da" | "de" | "en_uk" | "en_us" | "es" | "fi" | "fr" | "hu" | "it" | "ja" | "ko" | "nl" | "no" | "pl" | "pt" | "ro" | "ru" | "sk" | "sl" | "sv" | "th" | "tr" | "uk" | "zh"

export interface BirdNETParams {
    sensitivity?: number
    min_conf?: number
    overlap?: number
    sf_thresh?: number
    min_freq?: number
    max_freq?: number
    locale?: BirdNETLocale
    top_n?: number | null
}

export interface BatDetectParams {
    detection_threshold?: number
    chunk_size?: number
}

export interface InsectParams {
    window_size?: number
    stride_length?: number
    max_freq?: number
}

export interface MergeParams {
    is_merged?: boolean
    max_gap?: number
    keep_merged?: boolean
}

export interface AnalysisQueueStatus {
    queue_id: number
    status: string
    message: string
    progress: number
    completed: number
    total: number
    type: string
}

export interface AnalysisJobResponse {
    queued: AnalysisQueueStatus[]
    failed: Array<Record<string, string | number>>
}

export interface RunAnalysisRequest {
    project_id: number
    media_ids: number[]
    birdnet?: BirdNETParams | null
    batdetect?: BatDetectParams | null
    insects?: InsectParams | null
    merge?: MergeParams
}

export interface AcousticIndexParameter {
    key: string
    default?: string | number | boolean | null
    value_type: "string" | "number" | "boolean"
}

export interface IndexType {
    index_id: number
    name?: string | null
    description?: string | null
    param?: unknown
    url?: string | null
    parameters: AcousticIndexParameter[]
}

export interface AcousticIndexJob {
    index_id?: number
    analysis_type?: "template_matching" | "max_frequency"
    params: Record<string, string | number | boolean | null>
}

export interface AcousticIndexSelection {
    min_time: number
    max_time: number
    min_frequency: number
    max_frequency: number
    filter_enabled?: boolean
}

export interface RunAcousticIndicesRequest {
    project_id: number
    media_ids: number[]
    selection?: AcousticIndexSelection
    channel?: "mono" | "left" | "right"
    indices: AcousticIndexJob[]
}

export interface AcousticIndexPreviewRequest {
    project_id: number
    media_id: number
    selection: AcousticIndexSelection
    channel?: "mono" | "left" | "right"
    index_id: number
    params: Record<string, string | number | boolean | null>
}

export interface AcousticIndexPreviewResponse {
    media_id: number
    index_id: number
    index_name: string
    version: string
    params: Record<string, unknown>
    results: Record<string, unknown>
    save_payload: IndexLogCreateRequest
}

export const analysisApi = {
    /** 运行AI模型分析 */
    runAnalysis(payload: RunAnalysisRequest) {
        return apiClient.post<{ code: number; message: string; data: AnalysisJobResponse }>("/v1/analysis-jobs", payload)
    },

    /** 获取声学指数目录 */
    getIndexTypes() {
        return apiClient.get<{ code: number; message: string; data: IndexType[] }>("/v1/index-types")
    },

    /** 计算声学指数 */
    runAcousticIndices(payload: RunAcousticIndicesRequest) {
        return apiClient.post<{ code: number; message: string; data: AnalysisJobResponse }>("/v1/acoustic-index-jobs", payload)
    },

    /** 预览声学指数结果 */
    previewAcousticIndex(payload: AcousticIndexPreviewRequest) {
        return apiClient.post<{ code: number; message: string; data: AcousticIndexPreviewResponse }>("/v1/acoustic-index-previews", payload)
    }
}
