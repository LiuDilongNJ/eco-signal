import type { ApiResponse, PagedApiResponse } from "../../types"
import { apiClient } from "../client"
import { getApiData } from "../utils"

export interface TaskListItem {
    task_id: number
    type: "media" | "annotation"
    media_id: number | null
    annotation_id: number | null
    assigner_id: number
    assignee_id: number
    assigner_name: string | null
    assignee_name: string | null
    status: string
    comment: string | null
    datetime: string | null
    media_name: string | null
    media_type?: string | null
}

export interface AssignableUserPublic {
    user_id: number
    name?: string | null
    username: string
    task_count: number
}

export interface TaskAssignmentItem {
    user_id: number
    comment?: string
}

export type TaskAssignmentRequest =
    | { type: "annotation"; annotation_ids: number[]; assignments: TaskAssignmentItem[] }
    | { type: "media"; annotation_ids?: null; assignments: TaskAssignmentItem[] }

export interface TaskAssignmentResult {
    assigned_count: number
}

export interface TaskQueryParams {
    page?: number
    page_size?: number
    task_id?: number
    type?: "media" | "annotation"
    media_name?: string
    media_type?: string
    annotation_id?: number
    assigner_id?: number
    assigner_name?: string
    assignee_id?: number
    assignee_name?: string
    project_id?: number
    collection_id?: number
    status?: string
    comment?: string
    datetime_from?: string
    datetime_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export interface TaskExportParams {
    project_id: number
    collection_id?: number
    order_by?: string
    order_dir?: "asc" | "desc"
}

export const tasksApi = {
    getList(params: TaskQueryParams) {
        return apiClient.get<PagedApiResponse<TaskListItem[]>>("/v1/tasks", { params })
    },

    /** 删除单个 Task */
    deleteTask(taskId: number) {
        return apiClient.delete<{ code: number; message: string; data: any }>(`/v1/tasks/${taskId}`)
    },

    getAssignableUsers(mediaId: number) {
        return apiClient.get<ApiResponse<AssignableUserPublic[]>>(`/v1/media/${mediaId}/task-assignee-options`)
    },

    assignTasks(mediaId: number, payload: TaskAssignmentRequest) {
        return apiClient.put<ApiResponse<TaskAssignmentResult>>(`/v1/media/${mediaId}/tasks`, payload)
    },

    async listAssignableUsers(mediaId: number, ignoreUnauthorized?: boolean): Promise<AssignableUserPublic[]> {
        const response = await apiClient.get<ApiResponse<AssignableUserPublic[]>>(
            `/v1/media/${mediaId}/task-assignee-options`,
            { ignoreUnauthorized },
        )
        return getApiData(response)
    },

    async assign(mediaId: number, payload: TaskAssignmentRequest): Promise<TaskAssignmentResult> {
        const response = await apiClient.put<ApiResponse<TaskAssignmentResult>>(`/v1/media/${mediaId}/tasks`, payload)
        return getApiData(response)
    },

    exportCsv(params: TaskExportParams) {
        return apiClient.download("/v1/tasks/exports", { params })
    },
}
