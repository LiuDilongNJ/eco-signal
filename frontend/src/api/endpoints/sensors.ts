/**
 * 传感器 API（与后端 FastAPI `GET/POST/PUT/DELETE /api/v1/sensors` 一致，Redoc tag: sensors）
 *
 * - `GET /api/v1/sensor-options` — 下拉选项（公开）
 * - `GET /api/v1/sensors` — 分页列表（管理员）
 * - `POST /api/v1/sensors` — 创建（管理员，响应体 `data` 为 null）
 * - `GET /api/v1/sensors/{id}` — 详情（管理员）
 * - `PUT /api/v1/sensors/{id}` — 更新（管理员，响应体 `data` 为 null）
 * - `DELETE /api/v1/sensors/{id}` — 删除（管理员）
 *
 * 前端通过 `resolveApiBaseUrl()`（默认 `/api`）+ 路径 `/v1/sensors` 请求，即同源 `/api/v1/sensors`，开发环境由 Vite 代理到 `http://localhost:8000`。
 */
import { apiClient } from "../client"

export interface SensorOption {
    sensor_id: number
    name: string
    sensor_type?: string
    [key: string]: unknown
}

export interface SensorPublic {
    sensor_id: number
    uuid: string
    name: string
    sensor_type: string
    recorder_id?: number | null
    recorder_name?: string | null
    microphone_id?: number | null
    microphone_name?: string | null
    camera_id?: number | null
    camera_name?: string | null
    lens_id?: number | null
    lens_name?: string | null
    description?: string | null
    creation_date: string
}

export interface PagedSensorsResponse {
    code: number
    message: string
    data: SensorPublic[] | null
    page_info: {
        total: number
        page: number
        page_size: number
        total_pages: number
    } | null
}

/** 创建/更新成功时后端 `success()` 无业务体，`data` 为 null */
export type SensorMutationResponse = {
    code: number
    message: string
    data: null
}

export type SensorDeleteResponse = {
    code: number
    message: string
}

export interface SensorCreateBody {
    name: string
    sensor_type: "audio" | "photo" | "sensor"
    recorder_id?: number | null
    microphone_id?: number | null
    camera_id?: number | null
    lens_id?: number | null
    description?: string | null
}

export interface SensorUpdateBody {
    name?: string | null
    sensor_type?: "audio" | "photo" | "sensor" | null
    recorder_id?: number | null
    microphone_id?: number | null
    camera_id?: number | null
    lens_id?: number | null
    description?: string | null
}

export interface ListSensorsParams {
    page?: number
    page_size?: number
    sensor_id?: number
    uuid?: string
    name?: string
    sensor_type?: string
    recorder_id?: number
    microphone_id?: number
    camera_id?: number
    lens_id?: number
    recorder_name?: string
    microphone_name?: string
    camera_name?: string
    lens_name?: string
    description?: string
    creation_date_from?: string
    creation_date_to?: string
    order_by?: string
    order_dir?: "asc" | "desc"
}

function cleanParams(params?: Record<string, unknown>) {
    if (!params) return undefined
    return Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== ""),
    ) as Record<string, string | number>
}

export const sensorsApi = {
    /**
     * Public options for dropdowns. Optional query params are ignored by the server; kept for callers such as AudiosPage.
     */
    getOptions(params?: { project_id?: number; collection_id?: number }) {
        return apiClient.get<{ code: number; message: string; data: SensorOption[] }>("/v1/sensor-options", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    list(params?: ListSensorsParams) {
        return apiClient.get<PagedSensorsResponse>("/v1/sensors", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },

    get(sensorId: number) {
        return apiClient.get<{ code: number; message: string; data: SensorPublic }>(`/v1/sensors/${sensorId}`)
    },

    create(body: SensorCreateBody) {
        return apiClient.post<SensorMutationResponse>("/v1/sensors", body)
    },

    update(sensorId: number, body: SensorUpdateBody) {
        return apiClient.put<SensorMutationResponse>(`/v1/sensors/${sensorId}`, body)
    },

    delete(sensorId: number) {
        return apiClient.delete<SensorDeleteResponse>(`/v1/sensors/${sensorId}`)
    },

    exportCsv(params?: Omit<ListSensorsParams, "page" | "page_size">) {
        return apiClient.download("/v1/sensors/exports", {
            params: cleanParams(params as Record<string, unknown>),
        })
    },
}
