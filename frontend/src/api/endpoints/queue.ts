import { apiClient } from "../client"
import type { ApiResponse, PagedApiResponse } from "../../types"

export interface QueueQueryParams {
    page?: number
    page_size?: number
    queue_id?: number
    type?: string
    status?: string
    user_id?: number
    username?: string
    completed?: string
    total?: string
    start_time_from?: string
    start_time_to?: string
    stop_time_from?: string
    stop_time_to?: string
    error?: string
    warning?: string
    search?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface QueueDetail {
    queue_id: number
    status: "pending" | "running" | "completed" | "error" | "warning" | "unknown"
    progress: number
    completed: number
    total: number
    error?: string | null
    warning?: string | null
    type: string
    message?: string | null
    start_time?: string | null
    stop_time?: string | null
}

export interface QueueListItem extends QueueDetail {
    user_id: number
    username: string
}

export interface QueueExportParams {
    order_by?: string
    order_dir?: "asc" | "desc"
}

export const queueApi = {
    /** 获取 Queue 分页列表 */
    getList(params: QueueQueryParams) {
        return apiClient.get<PagedApiResponse<QueueListItem[]>>("/v1/queues", { params })
    },

    /** 获取单个 Queue 状态 */
    getDetail(queueId: number, signal?: AbortSignal) {
        return apiClient.get<ApiResponse<QueueDetail>>(
            `/v1/queues/${queueId}`,
            signal ? { signal } : undefined,
        )
    },

    /** 批量删除队列任务 */
    deleteItems(queueIds: number[]) {
        return apiClient.delete<ApiResponse<null>>("/v1/queues", { body: { queue_ids: queueIds } })
    },

    exportCsv(params: QueueExportParams) {
        return apiClient.download("/v1/queues/exports", { params })
    },
}
