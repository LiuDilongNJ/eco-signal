import { apiClient } from "../client"
import { getApiData } from "../utils"

export interface UserPublic {
    user_id: number
    username?: string
    name?: string
    email?: string
    orcid?: string
    color?: string
    contrib?: string
    active: boolean
    is_project_admin?: boolean
    preference?: UserPreference | null
    [key: string]: any
}

export interface CurrentUserPublic extends UserPublic {
    can_write_audio: boolean
}

export interface UserOption {
    user_id: number
    name: string
    username?: string
}

export interface CreatorOption extends UserOption {
    username?: string
    is_admin: boolean
}

export interface PageInfo {
    total: number
    page: number
    page_size: number
    total_pages: number
}

export interface PagedUserResponse {
    code: number
    message: string
    data: UserPublic[]
    page_info: PageInfo
}

export interface GetUsersParams {
    page?: number
    page_size?: number
    user_id?: number
    username?: string
    name?: string
    email?: string
    orcid?: string
    active?: boolean
    project_id?: number
    collection_id?: number
    scope?: "current" | "all"
    contrib?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

export const usersApi = {
    getUsers(params?: GetUsersParams) {
        const cleanParams = params
            ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== ""))
            : undefined
        return apiClient.get<PagedUserResponse>("/v1/users", { params: cleanParams as any })
    },
    getCreatorOptions(params: Pick<GetUsersParams, "project_id" | "collection_id">) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([_, value]) => value !== undefined && value !== null),
        )
        return apiClient.get<{ code: number; message: string; data: CreatorOption[] }>("/v1/users/creators", { params: cleanParams as any })
    },
    getContributorRoles() {
        return apiClient.get<{ project_roles: string[]; collection_roles: string[] }>(
            "/v1/contributor-roles",
        )
    },
    getUser(user_id: number) {
        return apiClient.get<{ code: number; message: string; data: UserPublic }>(`/v1/users/${user_id}`)
    },
    createUser(payload: any, params: { project_id: number; collection_id?: number | null }) {
        const cleanParams = Object.fromEntries(
            Object.entries(params).filter(([_, v]) => v !== undefined && v !== null && (v as any) !== ""),
        )
        return apiClient.post<{ code: number; message: string; data: any }>("/v1/users", payload, {
            params: cleanParams as any,
        })
    },
    updateUser(user_id: number, payload: any) {
        return apiClient.patch<{ code: number; message: string; data: any }>(`/v1/users/${user_id}`, payload)
    },
    resetUserPassword(user_id: number, payload: { new_password: string }) {
        return apiClient.put<{ code: number; message: string; data: any }>(
            `/v1/users/${user_id}/password-credential`,
            payload,
        )
    },
    deleteUser(user_id: number) {
        return apiClient.delete<{ code: number; message: string; data: any }>(`/v1/users/${user_id}`)
    },
    getMe(config?: { ignoreUnauthorized?: boolean; project_id?: number; collection_id?: number }) {
        const { project_id, collection_id, ...requestConfig } = config ?? {}
        const params =
            project_id !== undefined && project_id !== null
                ? {
                    project_id,
                    ...(collection_id !== undefined && collection_id !== null ? { collection_id } : {}),
                }
                : undefined
        return apiClient.get<{ code: number; message: string; data: CurrentUserPublic }>("/v1/current-user", {
            ...requestConfig,
            params,
        })
    },
    updateMe(
        payload: {
            name?: string | null
            email?: string | null
            orcid?: string | null
            color?: string | null
        } & Partial<UserPreference>,
    ) {
        return apiClient.patch<{ code: number; message: string; data: any }>("/v1/current-user", payload)
    },
    updateMyPassword(payload: { current_password: string; new_password: string }) {
        return apiClient.put<{ code: number; message: string; data: any }>(
            "/v1/current-user/password-credential",
            payload,
        )
    },
    setContributorRole(
        user_id: number,
        payload: { project_id: number; collection_id?: number | null; contribution_role?: string | null },
    ) {
        return apiClient.put<{ code: number; message: string; data: any }>(
            `/v1/users/${user_id}/contributors`,
            payload,
        )
    },
    exportCsv(params?: GetUsersParams) {
        const cleanParams = params
            ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== ""))
            : undefined
        return apiClient.download("/v1/users/exports", { params: cleanParams as any })
    },
    getMenuItems(params?: { project_id?: number; collection_id?: number }) {
        const cleanParams = params
            ? Object.fromEntries(
                  Object.entries(params).filter(([_, v]) => v !== undefined && v !== null),
              )
            : undefined
        return apiClient.get<{ code: number; message: string; data: { name: string; visible: boolean }[] }>(
            "/v1/current-user/menu-items",
            { params: cleanParams as { project_id?: number; collection_id?: number } | undefined },
        )
    },
    /** 获取用户选项列表，用于 Creator 筛选下拉框 */
    getUserOptions(params?: { project_id?: number; collection_id?: number }) {
        const cleanParams = params
            ? Object.fromEntries(Object.entries(params).filter(([_, v]) => v !== undefined && v !== null))
            : undefined
        return apiClient.get<{ code: number; message: string; data: { user_id: number; name: string; username?: string }[] }>(
            "/v1/user-options",
            { params: cleanParams as any },
        )
    },
}

/** 用户偏好（FFT / 主题等），与 GET/PATCH /v1/current-user 的 data 字段一致 */
export interface UserPreference {
    fft?: number
    theme?: "light" | "dark" | "auto"
    language?: string
    timezone?: string
    notifications_enabled?: boolean
}

function preferenceFromUserData(data: UserPublic | null | undefined): UserPreference {
    if (!data || typeof data !== "object") return {}
    const source = typeof data.preference === "object" && data.preference != null ? data.preference : data
    const p: UserPreference = {}
    if (typeof source.fft === "number") p.fft = source.fft
    if (source.theme === "light" || source.theme === "dark" || source.theme === "auto") {
        p.theme = source.theme
    }
    if (typeof source.language === "string") p.language = source.language
    if (typeof source.timezone === "string") p.timezone = source.timezone
    if (typeof source.notifications_enabled === "boolean") p.notifications_enabled = source.notifications_enabled
    return p
}

export const userPreferenceApi = {
    async get(config?: { ignoreUnauthorized?: boolean }): Promise<UserPreference> {
        const res = await apiClient.get<{ code: number; message: string; data: UserPublic }>(
            "/v1/current-user",
            config,
        )
        const data = getApiData(res)
        return preferenceFromUserData(data)
    },

    async patch(body: Partial<UserPreference>): Promise<void> {
        await apiClient.patch<{ code: number; message: string; data: null }>(
            "/v1/current-user/preferences",
            body,
        )
    },
}
