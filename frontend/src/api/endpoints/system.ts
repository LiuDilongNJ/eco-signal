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
    payload?: any
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

export const systemApi = {
    /** 获取系统操作日志 */
    getOperationLogs(params?: GetOperationLogsParams) {
        const cleanParams = params
            ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== ""))
            : undefined
        return apiClient.get<PagedOperationLogResponse>("/v1/system/operation-logs", { params: cleanParams as any })
    },
}
