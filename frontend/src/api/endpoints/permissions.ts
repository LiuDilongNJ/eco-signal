import { apiClient } from "../client"

export interface PermissionPublic {
    permission_id: number
    name: string
    resource_type: string
    action: string
}

export interface CollectionPermissionConfig {
    project_id: number
    collection_id: number
    collection_name: string
    stored_permissions: string[]
    effective_permissions: string[]
}

export interface ProjectPermissionConfig {
    project_id: number
    project_name: string
    can_manage_project: boolean
    stored_permissions: string[]
    effective_permissions: string[]
    collections: CollectionPermissionConfig[]
}

export interface UserPermissionConfig {
    is_admin: boolean | null
    can_manage_admin_role: boolean
    projects: ProjectPermissionConfig[]
}

export interface CollectionPermissionAssignment {
    project_id: number
    collection_id: number
    stored_permissions: string[]
}

export interface ProjectPermissionAssignment {
    project_id: number
    stored_permissions: string[]
    collections: CollectionPermissionAssignment[]
}

export interface UserPermissionSyncRequest {
    is_admin?: boolean | null
    projects?: ProjectPermissionAssignment[]
}

export const permissionsApi = {
    /** 获取所有权限定义 */
    listPermissions() {
        return apiClient.get<{ code: number; message: string; data: PermissionPublic[] }>("/v1/permissions")
    },
    
    /** 获取用户权限配置快照 */
    getUserPermissionConfig(userId: number) {
        return apiClient.get<{ code: number; message: string; data: UserPermissionConfig }>(`/v1/users/${userId}/permission-configuration`)
    },
    
    /** 同步用户权限 */
    syncUserPermissions(userId: number, payload: UserPermissionSyncRequest) {
        return apiClient.put<{ code: number; message: string; data: any }>(`/v1/users/${userId}/permissions`, payload)
    }
}
