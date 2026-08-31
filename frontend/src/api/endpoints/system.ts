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

export type StorageHealth = "healthy" | "warning" | "critical"

/** GET /v1/system/storage — backend container root filesystem status. */
export interface StorageStatus {
    path: string
    total_bytes: number
    used_bytes: number
    free_bytes: number
    used_percent: number
    status: StorageHealth
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

    /** 获取后端容器根目录的磁盘状态；仅管理员可访问。 */
    getStorageStatus() {
        return apiClient.get<StorageStatusResponse>("/v1/system/storage")
    },
}
