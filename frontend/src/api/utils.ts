/**
 * 统一解析 { code, message, data } 业务封装响应；成功以 code === 0 为准。
 */
export function getApiData<T>(res: { code?: number; message?: string; data?: T }): T {
    if (res == null || typeof res !== "object") {
        throw new Error("Invalid response")
    }
    if (res.code !== 0) {
        throw new Error(res.message || `Request failed (code ${String(res.code)})`)
    }
    if (res.data === undefined) {
        throw new Error(res.message || "No data in response")
    }
    return res.data
}

/** Shared shapes for GET /v1/.../filter-options (Data module column filter dropdowns). */
export interface FilterOptionUser {
    user_id: number
    name: string
}

export interface FilterOptionLabel {
    label_id: number
    name: string
}

export interface FilterOptionReviewStatus {
    annotation_review_status_id: number
    name: string
}

export interface FilterOptionTaxon {
    taxon_id: number
    name: string
}

export function mapFilterUsersToSelectOptions(
    users: FilterOptionUser[] | undefined | null,
): { label: string; value: number }[] {
    if (!users?.length) return []
    return users.map((u) => ({ label: u.name, value: u.user_id }))
}

export function mapFilterLabelsToSelectOptions(
    labels: FilterOptionLabel[] | undefined | null,
): { label: string; value: number }[] {
    if (!labels?.length) return []
    return labels.map((label) => ({ label: label.name, value: label.label_id }))
}

export function mapFilterReviewStatusesToSelectOptions(
    statuses: FilterOptionReviewStatus[] | undefined | null,
): { label: string; value: number }[] {
    if (!statuses?.length) return []
    return statuses.map((s) => ({ label: s.name, value: s.annotation_review_status_id }))
}

export function mapFilterTaxaToSelectOptions(
    taxa: FilterOptionTaxon[] | undefined | null,
): { label: string; value: number }[] {
    if (!taxa?.length) return []
    return taxa.map((t) => ({ label: t.name, value: t.taxon_id }))
}
