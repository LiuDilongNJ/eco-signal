import { apiClient } from "../client"

export interface OperationLogRead {
    log_id: number
    user_id?: number
    username?: string
    action: string
    resource_type: string
    resource_id?: string
    description?: string
    req_ip?: string
    req_endpoint?: string
    payload?: unknown
    status_code: number
    creation_date: string
}

export interface PageInfo {
    total: number
    page: number
    page_size: number
    total_pages: number
}

export interface PagedOperationLogResponse {
    code: number
    message: string
    data: OperationLogRead[]
    page_info: PageInfo
}

export interface GetOperationLogsParams {
    page?: number
    page_size?: number
    log_id?: number
    user_id?: number
    username?: string
    action?: string
    resource_type?: string
    description?: string
    status_code?: number | string
    search?: string
    date_from?: string
    date_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export type StorageHealth = "healthy" | "warning" | "critical" | "unavailable"

export interface FilesystemStatus {
    scope: "container_root" | "media"
    path: string
    available: boolean
    total_bytes: number | null
    used_bytes: number | null
    free_bytes: number | null
    used_percent: number | null
    status: StorageHealth
}

export interface StorageStatus {
    checked_at: string
    status: StorageHealth
    warning_percent: number
    critical_percent: number
    filesystems: FilesystemStatus[]
}

export interface StorageStatusResponse {
    code: number
    message: string
    data: StorageStatus
}

export const systemApi = {
    /** 获取系统操作日志 */
    getOperationLogs(params?: GetOperationLogsParams) {
        const cleanParams = params
            ? Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ""))
            : undefined
        return apiClient.get<PagedOperationLogResponse>("/v1/system/operation-logs", { params: cleanParams })
    },

    /** 获取文件系统容量；仅管理员可访问。 */
    getStorageStatus(signal?: AbortSignal) {
        return apiClient.get<StorageStatusResponse>("/v1/system/storage", { signal })
    },
}
