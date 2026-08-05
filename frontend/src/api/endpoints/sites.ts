import { apiClient } from "../client"
import type { FilterOptionUser } from "../utils"
import type { GetMediaParams } from "./media"

/** POST /v1/sites — matches backend SiteCreate */
export interface SiteCreatePayload {
    name: string
    longitude?: number | null
    latitude?: number | null
    topography_m?: number | null
    freshwater_depth_m?: number | null
    realm_id?: number | null
    biome_id?: number | null
    functional_type_id?: number | null
    iho_id?: number | null
    gadm0_gid?: string | null
    gadm1_gid?: string | null
    gadm2_gid?: string | null
    collection_id?: number | null
    project_id?: number | null
}

/** PATCH /v1/sites/{id} — matches backend SiteUpdate */
export type SiteUpdatePayload = Omit<SiteCreatePayload, "collection_id" | "project_id">

export interface SiteOption {
    site_id: number
    name: string
    [key: string]: any
}

/** GET /v1/site-map-items — matches backend SiteMapMarker / SiteMapResponse */
export interface SiteMapMarker {
    site_id: number
    name?: string | null
    geometry?: {
        point?: {
            latitude: number
            longitude: number
        } | null
    } | null
    media_count?: number
    realm_id?: number | null
    realm_name?: string | null
    biome_id?: number | null
    functional_type_id?: number | null
}

/** GET /v1/site-map-items 返回的地图中心点（纬度 / 经度） */
export interface SiteMapCenter {
    latitude: number
    longitude: number
}

export interface SiteMapResponse {
    markers: SiteMapMarker[]
    center?: SiteMapCenter | null
    count: number
}

export interface SiteMapQueryParams {
    project_id: number
    collection_id?: number
    media_type?: "audio" | "photo"
    // `0` is reserved for the map-only "No selected" filter sentinel.
    realm_id?: number
    biome_id?: number
    functional_type_id?: number
}

export interface SiteMapGeometriesQueryParams {
    project_id: number
    site_ids: number[]
    collection_id?: number
}

export interface SiteMapGeometryItem {
    site_id: number
    geometry: Record<string, unknown>
}

export interface SiteMapGeometryResponse {
    items: SiteMapGeometryItem[]
    count: number
}

export interface IucnOption {
    id: number
    name: string
    children: IucnOption[]
}

export interface IucnOptionsResponse {
    realms: IucnOption[]
}

export interface IucnOptionsQueryParams {
    project_id?: number
    collection_id?: number
}

export type SiteOptionsParams = Partial<GetMediaParams>

export const sitesApi = {
    /** 获取 Site 下拉选项 */
    getOptions(params?: SiteOptionsParams) {
        return apiClient.get<{ code: number; message: string; data: SiteOption[] }>("/v1/site-options", { params })
    },

    /** Data > Sites：Creator 列筛选下拉（project_id 必填） */
    getFilterOptions(params: { project_id: number; collection_id?: number }) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
        ) as { project_id: number; collection_id?: number }
        return apiClient.get<{ code: number; message: string; data: { creator: FilterOptionUser[] } }>(
            "/v1/sites/filter-options",
            { params: cleanParams as any },
        )
    },

    /** 导出站点 CSV */
    exportCsv(params: any) {
        return apiClient.download("/v1/sites/exports", { params })
    },
    
    /** 获取站点分页列表 */
    getList(params: any) {
        return apiClient.get<any>("/v1/sites", { params })
    },

    /** 获取项目地图站点标记 */
    getMap(params: SiteMapQueryParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: SiteMapResponse }>(
            "/v1/site-map-items",
            {
                params: {
                    project_id: params.project_id,
                    collection_id: params.collection_id,
                    media_type: params.media_type,
                    realm_id: params.realm_id,
                    biome_id: params.biome_id,
                    functional_type_id: params.functional_type_id,
                },
                ignoreUnauthorized,
            },
        )
    },

    /** 获取 IUCN 三级筛选树 */
    getIucnOptions(params?: IucnOptionsQueryParams) {
        const cleanParams = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== undefined && v !== null),
              ) as IucnOptionsQueryParams)
            : undefined
        return apiClient.get<{ code: number; message: string; data: IucnOptionsResponse }>(
            "/v1/iucn-typology-options",
            { params: cleanParams as any },
        )
    },

    /** 按需获取站点地图几何 */
    getMapGeometries(params: SiteMapGeometriesQueryParams, ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: SiteMapGeometryResponse }>(
            "/v1/site-map-items/geometries",
            {
                params: {
                    project_id: params.project_id,
                    site_ids: params.site_ids.join(","),
                    collection_id: params.collection_id,
                },
                ignoreUnauthorized,
            },
        )
    },

    /** 获取单个站点详情 */
    getSite(id: number, projectId?: number | null) {
        return apiClient.get<any>(`/v1/sites/${id}`, {
            params: projectId ? { project_id: projectId } : undefined,
        })
    },

    /** 创建站点 */
    createSite(data: SiteCreatePayload) {
        return apiClient.post<any>("/v1/sites", data)
    },

    /** 更新站点 */
    updateSite(id: number, data: SiteUpdatePayload, projectId?: number | null) {
        return apiClient.patch<any>(`/v1/sites/${id}`, data, {
            params: projectId ? { project_id: projectId } : undefined,
        })
    },

    /** 删除站点 */
    deleteSite(id: number) {
        return apiClient.delete<any>(`/v1/sites/${id}`)
    },

    /** 更新站点的集合 / 项目关联（集合与项目勾选相互独立） */
    updateSiteCollections(
        siteId: number,
        payload: { collection_ids: number[]; project_ids: number[] },
    ) {
        return apiClient.put<{ code: number; message: string; data: any }>(`/v1/sites/${siteId}/collections`, payload)
    },

    /** 获取站点关联弹窗的选项及当前关联状态 */
    getLinkOptions(siteId: number, params: { project_id: number; name?: string; other_project_name?: string }) {
        return apiClient.get<{ code: number; message: string; data: any }>(`/v1/sites/${siteId}/collection-options`, {
            params,
        })
    }
}
