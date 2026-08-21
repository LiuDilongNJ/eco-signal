import { apiClient } from "../client"
import { getApiData, type FilterOptionUser } from "../utils"
import type { AnnotationReviewRead } from "./reviews"

/** 当前用户在该标注上被分配的 tag 任务（仅当有对应 Task 时返回） */
export interface AnnotationTaskSummary {
    task_id: number
    type: string
    status: string
    comment?: string | null
}

/** GET /v1/annotations 列表项 — 与后端 AnnotationPublic 对齐（节选） */
export interface AnnotationPublic {
    annotation_id: number
    uuid: string
    media_id: number
    media_name?: string | null
    media_type?: string | null
    min_x: number
    max_x: number
    min_y: number
    max_y: number
    sound_id?: number | null
    object_type?: "organism" | "other" | null
    soundscape_component?: string | null
    sound_type?: string | null
    reference?: boolean
    comments?: string | null
    taxon_id?: number | null
    taxon_scientific_name?: string | null
    taxon_common_name?: string | null
    uncertain?: boolean | null
    sound_distance_m?: number | null
    distance_not_estimable?: boolean | null
    individual_num?: number | null
    animal_sound_type?: string | null
    creator_id: number
    creator_name?: string | null
    creator_color?: string | null
    creator_type?: string | null
    confidence?: number | null
    creation_date?: string | null
    /** 分配给当前用户的任务摘要；有声谱图斜线待办提示，提交 review 后通常不再展示 */
    task?: AnnotationTaskSummary | null
    /** 列表接口也会批量附带（见 annotation_service.get_annotation_list） */
    reviews?: AnnotationReviewRead[]
}

/** GET /v1/annotations/{annotation_id} §4.5 标注详情（含审阅列表） */
export type AnnotationWithReviews = AnnotationPublic

export interface AnnotationPageInfo {
    total: number
    page: number
    page_size: number
    total_pages: number
}

/** GET /v1/annotations 查询参数（含筛选与分页） */
export type AnnotationListParams = Record<string, string | number | boolean | undefined>

/** POST /v1/annotations — 与后端 AnnotationCreate 对齐 */
export interface CreateAnnotationPayload {
    project_id: number
    media_id: number
    min_x: number
    max_x: number
    min_y: number
    max_y: number
    sound_id?: number | null
    object_type?: "organism" | "other" | null
    reference?: boolean
    comments?: string | null
    taxon_id?: number | null
    uncertain?: boolean | null
    sound_distance_m?: number | null
    distance_not_estimable?: boolean | null
    individual_num?: number | null
    animal_sound_type?: string | null
    creator_type?: string
    confidence?: number | null
}

type AnnotationsPagedBody = {
    code: number
    message: string
    data: AnnotationPublic[] | null
    page_info: AnnotationPageInfo | null
}

/** PATCH body — 与后端 AnnotationUpdate 对齐 */
export interface UpdateAnnotationPayload {
    min_x?: number
    max_x?: number
    min_y?: number
    max_y?: number
    sound_id?: number | null
    object_type?: "organism" | "other" | null
    reference?: boolean
    comments?: string | null
    taxon_id?: number | null
    uncertain?: boolean | null
    sound_distance_m?: number | null
    distance_not_estimable?: boolean | null
    individual_num?: number | null
    confidence?: number | null
    animal_sound_type?: string | null
}

export interface AnnotationFilterOptionSound {
    sound_id: number
    soundscape_component?: string | null
    sound_type: string
}

export interface AnnotationFilterOptionTaxon {
    taxon_id: number
    name: string
}

export interface AnnotationFilterOptionsResponse {
    creator: FilterOptionUser[]
    soundscape: string[]
    sound: AnnotationFilterOptionSound[]
    taxon: AnnotationFilterOptionTaxon[]
    animal_sound: string[]
}

export const annotationsApi = {
    /** 获取标注分页列表（原始响应，供 Data 页等使用） */
    getList(params: AnnotationListParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<AnnotationsPagedBody>("/v1/annotations", { params, ignoreUnauthorized })
    },

    /**
     * GET /v1/annotations — 解析 code / data / page_info（§4.1 标注列表）
     */
    async listPaged(params: AnnotationListParams, ignoreUnauthorized?: boolean): Promise<{
        items: AnnotationPublic[]
        pageInfo: AnnotationPageInfo
    }> {
        const res = await apiClient.get<AnnotationsPagedBody>("/v1/annotations", { params, ignoreUnauthorized })
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
        const page = typeof params.page === "number" ? params.page : 1
        const pageSize = typeof params.page_size === "number" ? params.page_size : 20
        return {
            items: res.data ?? [],
            pageInfo:
                res.page_info ?? {
                    total: 0,
                    page,
                    page_size: pageSize,
                    total_pages: 0,
                },
        }
    },

    /** GET /v1/annotations/all — 不分页列表，供媒体详情页使用 */
    async listAll(params: AnnotationListParams, ignoreUnauthorized?: boolean): Promise<AnnotationPublic[]> {
        const res = await apiClient.get<{ code: number; message: string; data: AnnotationPublic[] | null }>(
            "/v1/annotations/all",
            { params, ignoreUnauthorized },
        )
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
        return res.data ?? []
    },

    /** 分页拉取某媒体下全部标注 ID（用于分配 tag 任务等） */
    async listAllIdsForMedia(mediaId: number, projectId: number): Promise<number[]> {
        const ids: number[] = []
        let page = 1
        let totalPages = 1
        do {
            const { items, pageInfo } = await this.listPaged({
                media_id: mediaId,
                project_id: projectId,
                page,
                page_size: 100,
                order_by: "annotation_id",
                order_dir: "asc",
            })
            for (const a of items) ids.push(a.annotation_id)
            totalPages = Math.max(1, pageInfo.total_pages)
            page++
        } while (page <= totalPages)
        return ids
    },

    /** 创建标注 POST /v1/annotations */
    async create(payload: CreateAnnotationPayload): Promise<unknown> {
        const res = await apiClient.post<{ code: number; message: string; data: unknown }>(
            "/v1/annotations",
            payload,
        )
        return getApiData(res)
    },

    /** PATCH /v1/annotations/{id} — 与后端 AnnotationUpdate 对齐（字段均为可选） */
    async update(annotationId: number, projectId: number, payload: UpdateAnnotationPayload): Promise<AnnotationPublic> {
        const res = await apiClient.patch<{ code: number; message: string; data: AnnotationPublic }>(
            `/v1/annotations/${annotationId}`,
            payload,
            { params: { project_id: projectId } },
        )
        return getApiData(res) as AnnotationPublic
    },

    /** §4.5 标注详情（含审阅列表）GET /v1/annotations/{annotation_id} */
    async getById(annotationId: number, projectId: number, ignoreUnauthorized?: boolean): Promise<AnnotationWithReviews> {
        const res = await apiClient.get<{ code: number; message: string; data: AnnotationWithReviews }>(
            `/v1/annotations/${annotationId}`,
            { params: { project_id: projectId }, ignoreUnauthorized },
        )
        return getApiData(res) as AnnotationWithReviews
    },

    /** §4.4 DELETE /v1/annotations/{annotation_id} */
    async delete(annotationId: number, projectId: number): Promise<void> {
        const res = await apiClient.delete<{ code: number; message: string }>(
            `/v1/annotations/${annotationId}`,
            { params: { project_id: projectId } },
        )
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
    },

    /**
     * §4.7 GET /v1/annotations/exports — 流式 CSV；可按媒体 + 当前声谱视窗（时间与频率重叠）过滤。
     */
    exportViewportCsv(params: {
        media_id: number
        project_id?: number
        view_time_start: number
        view_time_end: number
        view_freq_min: number
        view_freq_max: number
    }) {
        return apiClient.download("/v1/annotations/exports", {
            params: {
                media_id: params.media_id,
                project_id: params.project_id,
                view_time_start: params.view_time_start,
                view_time_end: params.view_time_end,
                view_freq_min: params.view_freq_min,
                view_freq_max: params.view_freq_max,
            },
        })
    },

    exportCsv(params: any) {
        return apiClient.download("/v1/annotations/exports", { params })
    },

    /** Data > Annotations：列表筛选下拉（project_id 必填） */
    getFilterOptions(params: { project_id: number; collection_id?: number }) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([_, v]) => v !== undefined && v !== null),
        ) as { project_id: number; collection_id?: number }
        return apiClient.get<{ code: number; message: string; data: AnnotationFilterOptionsResponse }>(
            "/v1/annotations/filter-options",
            { params: cleanParams as any },
        )
    },
}
