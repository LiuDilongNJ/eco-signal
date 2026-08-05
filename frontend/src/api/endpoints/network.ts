import { apiClient } from "../client"

/** GET /v1/network-nodes — `stats` 与后端 NodeStats 一致 */
export interface NodeStats {
    users: number
    projects: number
    collections: number
    audios: number
    photos: number
    videos: number
    annotations: number
    sites: number
}

/**
 * GET /v1/network-nodes 列表项。
 * 本地实例节点可能使用 `id: 0`；请以 `is_local` / `id` 判断，勿用 `if (id)` 这类会把 0 判假的写法。
 */
export interface NetworkNodePublic {
    id: number
    name: string
    app_url: string
    latitude: number | null
    longitude: number | null
    /** 当前实例目录节点为 true（首页地图橙色）；联邦种子节点为 false（绿色） */
    is_local: boolean
    stats: NodeStats
    last_synced_at: string | null
}

/** GET /v1/network-settings — 后端为管理员接口；无权限时请求会失败，前端需降级 */
export interface NetworkSettings {
    server_name: string
    app_url: string
    host_url: string
    latitude: number | null
    longitude: number | null
    shared: boolean
    federation_secret: string
}

/** PUT /v1/network-settings — 字段均为可选，与后端 NetworkSettingsUpdate 一致 */
export interface NetworkSettingsUpdate {
    server_name?: string
    app_url?: string
    host_url?: string
    latitude?: number | null
    longitude?: number | null
    shared?: boolean
    federation_secret?: string | null
}

export const networkApi = {
    /** 获取网络节点列表（地图标记 + 统计） */
    getNodes() {
        return apiClient.get<{ code: number; message: string; data: NetworkNodePublic[] }>("/v1/network-nodes")
    },

    /** 获取本实例联邦配置（含地图锚点经纬度）；需管理员，公开首页调用失败属正常 */
    getSettings() {
        return apiClient.get<{ code: number; message: string; data: NetworkSettings }>("/v1/network-settings")
    },

    /** 更新联邦配置；需管理员 */
    updateSettings(body: NetworkSettingsUpdate) {
        return apiClient.put<{ code: number; message: string; data: NetworkSettings }>("/v1/network-settings", body)
    },

    /** 生成新的联邦密钥并保存；需管理员 */
    generateFederationSecret() {
        return apiClient.post<{ code: number; message: string; data: NetworkSettings }>(
            "/v1/network-secret-rotations",
        )
    },
}
