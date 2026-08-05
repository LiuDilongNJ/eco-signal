/**
 * 示例 API 端点 - 用户相关接口
 *
 * 使用方式:
 * import { userApi } from "@/api/endpoints/example"
 * const users = await userApi.getUsers({ page: 1, pageSize: 10 })
 */

import { apiClient } from "@/api/client"

// ---------- 类型定义 ----------

export interface User {
    id: string
    name: string
    email: string
    role: "admin" | "user" | "viewer"
    status: "active" | "inactive"
    createdAt: string
    updatedAt: string
}

export interface PaginatedResponse<T> {
    data: T[]
    total: number
    page: number
    pageSize: number
    totalPages: number
}

export interface GetUsersParams {
    page?: number
    pageSize?: number
    search?: string
    role?: User["role"]
    status?: User["status"]
}

export interface CreateUserPayload {
    name: string
    email: string
    role: User["role"]
}

export interface UpdateUserPayload {
    name?: string
    email?: string
    role?: User["role"]
    status?: User["status"]
}

// ---------- API 方法 ----------

export const userApi = {
    /** 获取用户列表（分页） */
    getUsers(params?: GetUsersParams) {
        return apiClient.get<PaginatedResponse<User>>("/users", { params: params ? { ...params } : undefined })
    },

    /** 获取单个用户 */
    getUser(id: string) {
        return apiClient.get<User>(`/users/${id}`)
    },

    /** 创建用户 */
    createUser(payload: CreateUserPayload) {
        return apiClient.post<User>("/users", payload)
    },

    /** 更新用户 */
    updateUser(id: string, payload: UpdateUserPayload) {
        return apiClient.patch<User>(`/users/${id}`, payload)
    },

    /** 删除用户 */
    deleteUser(id: string) {
        return apiClient.delete<void>(`/users/${id}`)
    },
}
