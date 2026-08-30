import { apiClient } from "../client"
import type { FilterOptionUser } from "../utils"
import type { ApiResponse } from "../../types"
import type { Contributor, ProjectStats } from "../../features/project/types"
import type { RowCapabilities } from "../capabilities"

// ---------- 类型定义 ----------

export interface ProjectPublic {
    project_id?: number
    uuid: string
    name: string
    url?: string
    doi?: string
    creator_id?: number
    creator_name?: string
    creation_date: string
    public: boolean
    active: boolean
    capabilities?: RowCapabilities
    // allow extra fields
    [key: string]: any
}

export interface ProjectOption {
    id: number
    name: string
}

export interface PageInfo {
    total: number
    page: number
    page_size: number
    total_pages: number
}

export interface PagedProjectResponse {
    code: number
    message: string
    data: ProjectPublic[]
    page_info: PageInfo
}

export interface ProjectOptionsResponse {
    code: number
    message: string
    data: ProjectOption[]
}

export interface GetProjectsParams {
    page?: number
    page_size?: number
    name?: string
    url?: string
    project_id?: number
    uuid?: string
    doi?: string
    creator_id?: number
    creator_name?: string
    creation_date_from?: string
    creation_date_to?: string
    public?: boolean
    active?: boolean
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface CreateProjectPayload {
    name: string
    url?: string
    description?: string
    description_short?: string
    doi?: string
    public: boolean
    active: boolean
}

export interface CreateProjectResponse {
    code: number
    message: string
    data: { project_id: number }
}

export interface ProjectOverviewParams {
    project_id: number | string
    collection_id?: number | string
}

export interface ProjectOverviewData {
    stats: ProjectStats
    contributors: Contributor[]
}

// ---------- API 方法 ----------

export const projectsApi = {
    /** 获取项目列表（分页与搜索） */
    getProjects(params?: GetProjectsParams) {
        // filter out undefined or empty string params to clean the URL
        const cleanParams = params ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== '')) : undefined
        return apiClient.get<PagedProjectResponse>("/v1/projects", { params: cleanParams as any })
    },

    /** 获取项目选项（简化的项目列表） */
    getProjectOptions(ignoreUnauthorized?: boolean) {
        return apiClient.get<ProjectOptionsResponse>("/v1/project-options", { ignoreUnauthorized })
    },

    /** 创建项目 */
    createProject(payload: CreateProjectPayload) {
        return apiClient.post<CreateProjectResponse>("/v1/projects", payload)
    },

    /** 获取项目详情 */
    getProject(project_id: number, ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: ProjectPublic }>(
            `/v1/projects/${project_id}`,
            { ignoreUnauthorized },
        )
    },

    /** 更新项目 */
    updateProject(project_id: number, payload: Partial<CreateProjectPayload>) {
        return apiClient.patch<{ code: number; message: string; data: any }>(`/v1/projects/${project_id}`, payload)
    },

    /** 删除项目 */
    deleteProject(project_id: number) {
        return apiClient.delete<{ code: number; message: string; data: any }>(`/v1/projects/${project_id}`)
    },

    /** 导出项目数据 */
    exportCsv(params?: GetProjectsParams) {
        const cleanParams = params ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== '')) : undefined
        return apiClient.download("/v1/projects/exports", { params: cleanParams as any })
    },

    /** 获取项目与集合的树形结构 */
    getProjectCollectionsTree() {
        return apiClient.get<{ code: number; message: string; data: any[] }>("/v1/project-hierarchies")
    },

    /** 获取项目关联集合弹窗数据 */
    getCollectionLinkOptions(projectId: number) {
        return apiClient.get<{ code: number; message: string; data: any }>(`/v1/projects/${projectId}/collection-options`)
    },

    /** 更新项目的集合关联关系 */
    updateProjectCollections(projectId: number, collectionIds: number[]) {
        // 假设后端接受这种格式，或者根据需要调整
        return apiClient.put<{ code: number; message: string; data: any }>(`/v1/projects/${projectId}/collections`, { collection_ids: collectionIds })
    },

    /** 获取项目/集合统计信息 */
    getSummary(
        params: ProjectOverviewParams,
        ignoreUnauthorized?: boolean,
    ) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([, value]) => value !== undefined && value !== ""),
        )
        return apiClient.get<ApiResponse<ProjectOverviewData>>("/v1/project-overviews", {
            params: cleanParams,
            ignoreUnauthorized,
        })
    },

    /** 获取项目卡片列表 (HomePage Slide 2) */
    getProjectCards(ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: any[] }>(
            "/v1/project-directory-items",
            { ignoreUnauthorized },
        )
    },

    /** Data > Projects：Creator 列筛选下拉（project_id / collection_id 可选） */
    getFilterOptions(params?: { project_id?: number; collection_id?: number }) {
        const cleanParams = params
            ? (Object.fromEntries(
                  Object.entries(params).filter(
                      ([_, v]) => v !== undefined && v !== null && (typeof v !== "string" || v !== ""),
                  ),
              ) as Record<string, number>)
            : undefined
        return apiClient.get<{ code: number; message: string; data: { creator: FilterOptionUser[] } }>(
            "/v1/projects/filter-options",
            { params: cleanParams as any },
        )
    },
}
