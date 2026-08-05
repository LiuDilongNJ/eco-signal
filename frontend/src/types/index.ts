/**
 * 全局类型定义
 */

/** 通用分页参数 */
export interface PaginationParams {
    page: number
    pageSize: number
}

export interface ApiResponse<T> {
    code: number
    message: string
    data: T
    meta?: Record<string, string>
}

export interface PaginationMeta {
    total: number
    page: number
    page_size: number
    total_pages?: number
}

export interface PagedApiResponse<T> extends ApiResponse<T> {
    page_info: PaginationMeta
}

/** 通用分页响应 */
export interface PaginatedResponse<T> {
    data: T[]
    total: number
    page: number
    pageSize: number
    totalPages: number
}

/** 通用 API 错误 */
export interface ApiErrorResponse {
    code: string
    message: string
    details?: Record<string, string[]>
}

/** 排序方向 */
export type SortDirection = "asc" | "desc"

/** 排序参数 */
export interface SortParams {
    field: string
    direction: SortDirection
}
