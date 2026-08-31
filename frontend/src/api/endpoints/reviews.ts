import { apiClient } from "../client"
import type { FilterOptionReviewStatus, FilterOptionTaxon, FilterOptionUser } from "../utils"
import type { RowCapabilities } from "../capabilities"

/** 与 GET 标注详情内嵌 reviews、POST/PUT 响应一致 */
export interface AnnotationReviewRead {
    annotation_id: number
    reviewer_id: number
    annotation_review_status_id: number
    taxon_id?: number | null
    note?: string | null
    creation_date: string
    media_name?: string | null
    media_type?: string | null
    reviewer_name: string
    status_name: string
    taxon_name?: string | null
    capabilities?: RowCapabilities
}

export interface ReviewCreatePayload {
    project_id: number
    annotation_id: number
    annotation_review_status_id: number
    taxon_id?: number | null
    note?: string | null
}

export interface ReviewUpdatePayload {
    annotation_review_status_id: number
    taxon_id?: number | null
    note?: string | null
}

/** GET /v1/reviews 查询参数，与当前后端路由一致。 */
export interface ReviewsListParams {
    project_id?: number | null
    collection_id?: number | null
    page?: number
    page_size?: number
    annotation_id?: number | null
    media_name?: string | null
    media_type?: string | null
    reviewer_id?: number | null
    reviewer_name?: string | null
    status_id?: number | null
    status_name?: string | null
    taxon_id?: number | null
    taxon_name?: string | null
    note?: string | null
    creation_date_from?: string | null
    creation_date_to?: string | null
    order_by?: string
    order_dir?: "asc" | "desc" | string
}

export interface ReviewsExportParams {
    project_id?: number | null
    collection_id?: number | null
    annotation_id?: number | null
    media_name?: string | null
    media_type?: string | null
    reviewer_id?: number | null
    reviewer_name?: string | null
    status_id?: number | null
    status_name?: string | null
    taxon_id?: number | null
    taxon_name?: string | null
    note?: string | null
    creation_date_from?: string | null
    creation_date_to?: string | null
    order_by?: string
    order_dir?: "asc" | "desc" | string
}

export interface ReviewsPageInfo {
    total: number
    page: number
    page_size: number
    total_pages?: number
}

type ReviewsPagedBody = {
    code: number
    message: string
    data: AnnotationReviewRead[] | null
    page_info: ReviewsPageInfo | null
}

function cleanParams(params: Record<string, unknown>): Record<string, string | number | boolean | undefined> {
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number | boolean | undefined>
}

export const reviewsApi = {
    /** Data > Reviews：筛选下拉（project_id 必填） */
    getFilterOptions(params: { project_id: number; collection_id?: number }) {
        return apiClient.get<{
            code: number
            message: string
            data: { reviewer: FilterOptionUser[]; status: FilterOptionReviewStatus[]; taxon: FilterOptionTaxon[] }
        }>("/v1/reviews/filter-options", { params: cleanParams(params) })
    },

    /** 获取 Reviews 分页列表（原始响应） */
    getList(params: ReviewsListParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<ReviewsPagedBody>("/v1/reviews", {
            params: cleanParams(params as Record<string, unknown>),
            ignoreUnauthorized,
        })
    },

    /** GET /v1/reviews — 解析 code / data / page_info */
    async listPaged(params: ReviewsListParams, ignoreUnauthorized?: boolean): Promise<{
        items: AnnotationReviewRead[]
        pageInfo: ReviewsPageInfo
    }> {
        const res = await apiClient.get<ReviewsPagedBody>("/v1/reviews", {
            params: cleanParams(params as Record<string, unknown>),
            ignoreUnauthorized,
        })
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

    /**
     * 创建评审。后端成功时可能返回 `data: null`，需再 GET 列表刷新。
     */
    async create(payload: ReviewCreatePayload): Promise<AnnotationReviewRead | null> {
        const res = await apiClient.post<{
            code: number
            message: string
            data: AnnotationReviewRead | null
        }>("/v1/reviews", payload)
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
        return res.data ?? null
    },

    /**
     * 更新评审。后端成功时可能返回 `data: null`，需再 GET 列表刷新。
     */
    async update(
        annotationId: number,
        reviewerId: number,
        projectId: number,
        payload: ReviewUpdatePayload,
    ): Promise<AnnotationReviewRead | null> {
        const res = await apiClient.put<{
            code: number
            message: string
            data: AnnotationReviewRead | null
        }>(
            `/v1/annotations/${annotationId}/reviews/${reviewerId}`,
            payload,
            { params: { project_id: projectId } },
        )
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
        return res.data ?? null
    },

    /**
     * 删除评审。
     */
    async delete(annotationId: number, reviewerId: number, projectId: number): Promise<void> {
        const res = await apiClient.delete<{ code: number; message: string }>(
            `/v1/annotations/${annotationId}/reviews/${reviewerId}`,
            { params: { project_id: projectId } },
        )
        if (res.code !== 0) {
            throw new Error(res.message || `Request failed (code ${String(res.code)})`)
        }
    },

    exportCsv(params: ReviewsExportParams) {
        return apiClient.download("/v1/reviews/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
