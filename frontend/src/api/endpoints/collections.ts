import { apiClient } from "../client"
import type { FilterOptionUser } from "../utils"

export interface CollectionPublic {
    collection_id: number;
    uuid: string;
    name: string;
    doi: string;
    description: string;
    sphere: string | null;
    external_media_url: string;
    project_url: string;
    public_access: boolean;
    public_tags: boolean;
    creator_id: number;
    creation_date: string;
    creator?: {
        user_id: number;
        name: string;
    };
    taxons?: any[];
    [key: string]: any;
}

export interface GetCollectionsParams {
    page?: number;
    page_size?: number;
    order_by?: string;
    order_dir?: "asc" | "desc";
    collection_id?: number;
    uuid?: string;
    name?: string;
    sphere?: string;
    project_url?: string;
    external_media_url?: string;
    doi?: string;
    creator_id?: number;
    creation_date_from?: string;
    creation_date_to?: string;
    public_access?: boolean;
    public_tags?: boolean;
    [key: string]: any;
}

export interface PagedCollectionResponse {
    code: number;
    message: string;
    data: CollectionPublic[];
    page_info: {
        total: number;
        page: number;
        page_size: number;
        total_pages: number;
    };
}

/** GET /v1/media-timeline-items */
export interface CollectionTimelineItem {
    media_id: number
    media_type: string
    name: string
    start_date: string
    end_date: string
    duration_s?: number | null
    site_id?: number | null
    site_key?: string
    site_name: string
    duty_cycle_recording?: number | null
    duty_cycle_period?: number | null
    is_metadata: boolean
    creator_name?: string
    realm?: string | null
    item_count?: number
}

export interface CollectionTimelineRange {
    min: string | null
    max: string | null
}

export interface CollectionTimelineResponse {
    project_id: number
    collection_id?: number | null
    items: CollectionTimelineItem[]
    time_range: CollectionTimelineRange
    has_more?: boolean
}

export const collectionsApi = {
    /** 获取 Collections 列表 */
    getCollections(params?: GetCollectionsParams) {
        const cleanParams = params ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== '')) : undefined
        return apiClient.get<PagedCollectionResponse>("/v1/collections", { params: cleanParams as any })
    },

    /** 获取 Spheres 列表 */
    getSpheres() {
        return apiClient.get<any>("/v1/collection-sphere-options")
    },

    /** 获取 Collection 选项 */
    getCollectionOptions(project_id: number | string, ignoreUnauthorized?: boolean) {
        return apiClient.get<any>("/v1/collection-options", {
            params: { project_id },
            ignoreUnauthorized,
        })
    },

    /** 创建 Collection */
    createCollection(payload: Partial<CollectionPublic>, project_id?: number) {
        return apiClient.post<{ code: number; message: string; data: any }>("/v1/collections", payload, {
            params: project_id ? { project_id } : undefined
        })
    },

    /** 获取 Collection 详情 */
    getCollection(id: number | string) {
        return apiClient.get<{ code: number; message: string; data: CollectionPublic }>(
            `/v1/collections/${id}`,
        )
    },

    /** 获取 Collection 视图页数据 */
    getCollectionView(
        project_id: number | string,
        collection_id: number | string,
        ignoreUnauthorized?: boolean,
    ) {
        return apiClient.get<{ code: number; message: string; data: CollectionPublic }>(
            "/v1/collection-overviews",
            { params: { project_id, collection_id }, ignoreUnauthorized },
        )
    },

    /** 更新 Collection */
    updateCollection(id: number | string, payload: Partial<CollectionPublic>) {
        return apiClient.patch<{ code: number; message: string; data: any }>(
            `/v1/collections/${id}`,
            payload,
        )
    },

    /** 删除 Collection */
    deleteCollection(id: number | string) {
        return apiClient.delete<{ code: number; message: string; data: any }>(
            `/v1/collections/${id}`,
        )
    },

    /** 导出 Collection 数据 */
    exportCsv(params?: GetCollectionsParams) {
        const cleanParams = params ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== '')) : undefined
        return apiClient.download("/v1/collections/exports", { params: cleanParams as any })
    },

    /** 获取集合关联的 Taxons */
    getCollectionTaxons(id: number | string, projectId: number | string) {
        return apiClient.get<{ code: number; message: string; data: any[] }>(
            `/v1/collections/${id}/taxons`,
            { params: { project_id: projectId } },
        )
    },

    /** 批量设置集合的 Taxons */
    setCollectionTaxons(id: number | string, projectId: number | string, payload: { taxons: any[] }) {
        return apiClient.put<{ code: number; message: string; data: any }>(
            `/v1/collections/${id}/taxons`,
            payload,
            { params: { project_id: projectId } },
        )
    },

    /** Data > Collections：Creator 列筛选下拉（project_id / collection_id 可选） */
    getFilterOptions(params?: { project_id?: number; collection_id?: number }) {
        const cleanParams = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(
                      ([_, v]) => v !== undefined && v !== null && (typeof v !== "string" || v !== ""),
                  ),
              ) as Record<string, number>)
            : undefined
        return apiClient.get<{ code: number; message: string; data: { creator: FilterOptionUser[] } }>(
            "/v1/collections/filter-options",
            { params: cleanParams as any },
        )
    },

    /** 集合时间线（站点 × 时间，音频条） */
    getTimeline(
        params: {
            project_id: number
            collection_id?: number
            site_ids?: string
            include_metadata?: boolean
            response_mode?: "overview" | "detail"
            site_key?: string
            start_date?: string
            end_date?: string
            media_type?: "audio" | "photo"
            order_dir?: "asc" | "desc"
        },
        ignoreUnauthorized?: boolean,
    ) {
        const clean = Object.fromEntries(
            Object.entries(params).filter(([, v]) => v !== undefined && v !== ""),
        )
        return apiClient.get<{ code: number; message: string; data: CollectionTimelineResponse }>(
            "/v1/media-timeline-items",
            { params: clean as any, ignoreUnauthorized },
        )
    },
}
