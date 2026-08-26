import { apiClient } from "../client"
import { getApiData } from "../utils"
import type { FilterOptionLabel, FilterOptionUser } from "../utils"

export interface MediaPublic {
    media_id?: number
    uuid?: string
    media_type: string
    is_metadata?: boolean
    name?: string | null
    filename?: string | null
    site_id?: number | null
    site_name?: string | null
    sensor_id?: number | null
    sensor_name?: string | null
    medium?: string | null
    bit_depth?: string | number
    size_b?: number | null
    license_id?: number | null
    license_name?: string | null
    doi?: string | null
    note?: string | null
    uploader_id?: number | null
    uploader_name?: string | null
    creator_id?: number | null
    creator_name?: string | null
    /** browse/list 接口返回 date_time */
    date_time?: string
    duty_cycle_recording?: number | null
    duty_cycle_period?: number | null
    label?: string | null
    labels?: string[]
    hierarchy?: string[]
    preview_url?: string | null
    spectrogram?: string | null
    sphere?: string | null
    realm_name?: string | null
    site_realm_name?: string | null
    theme_value?: string | null
    theme_source?: string | null
    topography_m?: number | null
    freshwater_depth_m?: number | null
    audio_setting?: MediaAudioSetting | null
    photo_setting?: MediaPhotoSetting | null
    media_url?: string | null
    image_width?: number | null
    image_height?: number | null
    [key: string]: any
}

export interface MediaListItem extends MediaPublic {
    media_id: number
    labels: string[]
}

export interface GetMediaParams {
    page?: number
    page_size?: number
    order_by?: string
    order_dir?: "asc" | "desc"
    project_id?: number
    collection_id?: number
    [key: string]: any
}

export interface PagedMediaResponse<T = MediaPublic> {
    code: number
    message: string
    data: T[]
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    }
}


interface CreateMediaPayloadBase {
    collection_id: number
    file_upload_ids: number[]
    filename_prefix?: string
    date_time?: string
    date_from_filename?: boolean
    site_id?: number
    sensor_id?: number
    creator_id?: number | null
    license_id?: number
    medium?: string
    note?: string
    doi?: string
}

export interface CreateAudioMediaPayload extends CreateMediaPayloadBase {
    media_type: "audio"
    recording_gain_db?: number
    duty_cycle_recording?: number
    duty_cycle_period?: number
}

export interface CreatePhotoMediaPayload extends CreateMediaPayloadBase {
    media_type: "photo"
    recording_gain_db?: never
    duty_cycle_recording?: never
    duty_cycle_period?: never
}

/** Creation fields are deliberately discriminated so a photo cannot carry audio settings. */
export type CreateMediaPayload = CreateAudioMediaPayload | CreatePhotoMediaPayload

export interface UpdateMediaPayload {
    name?: string | null
    date_time?: string | null
    site_id?: number | null
    sensor_id?: number | null
    medium?: string | null
    license_id?: number | null
    creator_id?: number | null
    doi?: string | null
    note?: string | null
    recording_gain_db?: number | null
    sampling_rate_hz?: number | null
    bit_depth?: number | null
    channel_num?: number | null
    duration_s?: number | null
    duty_cycle_recording?: number | null
    duty_cycle_period?: number | null
}

export interface CreateMediaParams {
    project_id?: number
    [key: string]: string | number | boolean | undefined
}

export interface MediaCreateFailedItem {
    file_upload_id: number
    reason: string
}

/** Response body of `POST /v1/media`. */
export interface MediaCreateResponse {
    queue_id?: number | null
    queued: number[]
    failed: MediaCreateFailedItem[]
}

export interface BrowseMediaParams {
    project_id: number
    view_type: "gallery" | "list"
    page?: number
    page_size?: number
    collection_id?: number | null
    name?: string | null
    media_type?: "audio" | "photo" | null
    order_by?: string | null
    order_dir?: "asc" | "desc" | null
}

/** Detail payload returned by GET /v1/media/{id}. */
export interface MediaPreviewItem {
    preview_id: number
    media_id: number
    type: string
    url: string
}

export interface MediaAudioSetting {
    recording_gain_db?: number
    sampling_rate_hz?: number
    bit_depth?: number
    channel_num?: number
    duration_s?: number
}

export interface MediaPhotoSetting {
    exposure_ms?: number | null
    aperture?: number | null
    iso?: number | null
}

export interface RecordingDetail extends Record<string, unknown> {
    media_id?: number
    id?: number
    is_metadata?: boolean
    filename?: string
    name?: string
    audio_url?: string
    media_url?: string
    audio_setting?: MediaAudioSetting
    photo_setting?: MediaPhotoSetting
    image_width?: number
    image_height?: number
    previews?: MediaPreviewItem[]
    collection_id?: number
    project_id?: number
    labels?: unknown[]
    label?: string
    uuid?: string
    note?: string
    creation_date?: string
    site_name?: string
    sensor_name?: string
    medium?: string
    license_name?: string
    doi?: string
    creator_id?: number
    creator_name?: string
    uploader_id?: number
    uploader_name?: string
    spectrogram?: string
    duration_s?: number
    sampling_rate_hz?: number
    theme_value?: string | null
    theme_source?: string | null
    channels?: string
    bit_depth?: string
    size_b?: number
    gain?: string
    download_url?: string
    date_time?: string
}

export const RECORDING_FFT_SIZES = [128, 256, 512, 1024, 2048, 4096] as const

export type SpectrogramQueryParams = {
    start_time?: number
    end_time?: number
    min_freq?: number
    max_freq?: number
    fft_size?: number
    window?: string
    channel?: number
    width?: number
    height?: number
    filter?: boolean
}

export type MediaAudioQueryParams = {
    start_time?: number
    end_time?: number
    min_freq?: number
    max_freq?: number
    fft_size?: number
    filter?: boolean
    /** 前端 reload token，避免浏览器 disk cache 命中错误频段 */
    reload_key?: number
}

/** GET /v1/media-options — 下拉用（media_id + 显示名） */
export interface MediaOption {
    media_id: number
    name?: string | null
    media_type?: string | null
    is_metadata?: boolean
    filename?: string | null
}

export const mediaApi = {
    /** 获取 Media 列表 */
    getMedia(params?: GetMediaParams) {
        const cleanParams = params ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== '')) : undefined
        return apiClient.get<PagedMediaResponse<MediaListItem>>("/v1/media", { params: cleanParams as any })
    },

    /** 浏览 Media 列表（支持画廊/列表视图） */
    browseMedia(params: BrowseMediaParams, ignoreUnauthorized?: boolean) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([_, v]) => v !== undefined && v !== null && v !== ""),
        )
        return apiClient.get<PagedMediaResponse>("/v1/media-browse-items", {
            params: cleanParams as any,
            ignoreUnauthorized,
        })
    },

    /** 批量创建媒体记录 */
    createMedia(payload: CreateMediaPayload, params?: CreateMediaParams) {
        return apiClient.post<{ code: number; message: string; data: MediaCreateResponse }>("/v1/media", payload, { params })
    },

    /** 获取媒体记录详情 */
    getMediaDetail(id: number, projectId: number, ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: MediaPublic }>(
            `/v1/media/${id}`,
            { params: { project_id: projectId }, ignoreUnauthorized },
        )
    },

    /** 详情页：校验 code===0 并返回 data */
    async getRecordingDetail(mediaId: number, projectId: number, ignoreUnauthorized?: boolean): Promise<RecordingDetail> {
        const res = await apiClient.get<{ code: number; message: string; data: RecordingDetail }>(
            `/v1/media/${mediaId}`,
            { params: { project_id: projectId }, ignoreUnauthorized },
        )
        return getApiData(res)
    },

    getMediaContent(mediaId: number, projectId: number) {
        return apiClient.download(`/v1/media/${mediaId}/content`, { params: { project_id: projectId } })
    },

    /** GET /v1/media-options — 顶栏录音切换等 */
    async getMediaOptions(
        params: {
            project_id: number
            collection_id?: number
            name?: string
        },
        ignoreUnauthorized?: boolean,
    ): Promise<MediaOption[]> {
        const clean = Object.fromEntries(
            Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
        ) as Record<string, string | number>
        const res = await apiClient.get<{ code: number; message: string; data: MediaOption[] }>(
            "/v1/media-options",
            { params: clean, ignoreUnauthorized },
        )
        return getApiData(res)
    },

    /** 实时声谱图 PNG（需 Bearer，用 blob + object URL 展示） */
    fetchSpectrogramBlob(mediaId: number, projectId: number, params?: SpectrogramQueryParams, ignoreUnauthorized?: boolean) {
        const clean = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
              ) as Record<string, string | number | boolean | undefined>)
            : undefined
        return apiClient.download(`/v1/media/${mediaId}/spectrogram`, {
            params: { ...(clean ?? {}), project_id: projectId },
            ignoreUnauthorized,
        })
    },

    /** 音频流（整段拉取为 blob，便于带 Authorization；大文件注意内存） */
    fetchAudioBlob(mediaId: number, projectId: number, params?: MediaAudioQueryParams, ignoreUnauthorized?: boolean) {
        const clean = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
              ) as Record<string, string | number | boolean | undefined>)
            : undefined
        return apiClient.download(`/v1/media/${mediaId}/audio`, {
            params: { ...(clean ?? {}), project_id: projectId },
            ignoreUnauthorized,
        })
    },

    /** 更新媒体记录 */
    updateMedia(id: number, projectId: number, payload: UpdateMediaPayload) {
        return apiClient.patch<{ code: number; message: string; data: MediaPublic }>(
            `/v1/media/${id}`,
            payload,
            { params: { project_id: projectId } },
        )
    },

    /** 删除媒体记录 */
    deleteMedia(id: number) {
        return apiClient.delete<{ code: number; message: string; data: any }>(`/v1/media/${id}`)
    },

    /** 获取媒体关联集合弹窗数据 */
    getCollectionLinkOptions(mediaId: number, params: { project_id: number; name?: string; other_project_name?: string }) {
        return apiClient.get<{ code: number; message: string; data: any }>(`/v1/media/${mediaId}/collection-options`, {
            params,
        })
    },

    /** 批量更新媒体的集合关联关系 */
    updateMediaCollectionLinks(mediaIds: number[], projectId: number, collectionIds: number[]) {
        return apiClient.put<{ code: number; message: string; data: any }>(
            "/v1/media-collection-links",
            { media_ids: mediaIds, collection_ids: collectionIds },
            { params: { project_id: projectId } },
        )
    },

    exportAudioCsv(params: GetMediaParams) {
        const { project_id, collection_id, order_by, order_dir } = params
        return apiClient.download("/v1/audios/exports", {
            params: { project_id, collection_id, order_by, order_dir },
        })
    },

    exportPhotoCsv(params: GetMediaParams) {
        const { project_id, collection_id, order_by, order_dir } = params
        return apiClient.download("/v1/photos/exports", {
            params: { project_id, collection_id, order_by, order_dir },
        })
    },

    /** Data > Audios：Uploader / Creator 列筛选下拉（project_id 必填） */
    getFilterOptions(params: { project_id: number; collection_id?: number }) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([_, v]) => v !== undefined && v !== null),
        ) as { project_id: number; collection_id?: number }
        return apiClient.get<{
            code: number
            message: string
            data: { uploader: FilterOptionUser[]; creator: FilterOptionUser[]; labels: FilterOptionLabel[] }
        }>("/v1/media/filter-options", { params: cleanParams as any })
    },
}
