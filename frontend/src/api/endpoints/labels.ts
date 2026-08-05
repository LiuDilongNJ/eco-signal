import { apiClient } from "../client"

export interface LabelPublic {
    label_id: number
    name: string
    creator_id?: number
    creation_date: string
}

/** Normalize GET /v1/labels data. */
export function normalizeLabelList(data: unknown): LabelPublic[] {
    if (!Array.isArray(data)) return []
    const out: LabelPublic[] = []
    for (const item of data) {
        if (item == null || typeof item !== "object") continue
        const r = item as Record<string, unknown>
        const lid = typeof r.label_id === "number" ? r.label_id : Number(r.label_id)
        const name = typeof r.name === "string" ? r.name.trim() : String(r.name ?? "").trim()
        if (!Number.isFinite(lid) || lid <= 0 || !name) continue
        const creator = r.creator_id
        out.push({
            label_id: Math.trunc(lid),
            name,
            creator_id: typeof creator === "number" && Number.isFinite(creator) ? creator : undefined,
            creation_date: typeof r.creation_date === "string" ? r.creation_date : "",
        })
    }
    return out
}

export const labelsApi = {
    /** 获取标签列表 */
    getLabels(ignoreUnauthorized?: boolean) {
        return apiClient.get<{ code: number; message: string; data: LabelPublic[] }>("/v1/labels", { ignoreUnauthorized })
    },

    /** 创建新标签 */
    createLabel(name: string) {
        return apiClient.post<{ code: number; message: string; data: LabelPublic }>("/v1/labels", { name })
    },

    /** 删除标签 */
    deleteLabel(labelId: number) {
        return apiClient.delete<{ code: number; message: string; data: Record<string, unknown> }>(
            `/v1/labels/${labelId}`,
        )
    },

    /** 批量设置媒体的单个标签（传 null 清空） */
    setMediaLabels(mediaIds: number[], projectId: number, labelId: number | null) {
        return apiClient.put<{ code: number; message: string; data: { succeeded: number[]; failed: Array<{ media_id: number; status_code: number; message: string }> } }>(
            "/v1/media-labels",
            { media_ids: mediaIds, label_id: labelId },
            { params: { project_id: projectId } },
        )
    },
}

/** GET /v1/labels，业务成功时返回规范化列表 */
export async function fetchLabelsCatalog(ignoreUnauthorized?: boolean): Promise<LabelPublic[]> {
    const labelsRes = await labelsApi.getLabels(ignoreUnauthorized)
    const c = labelsRes.code
    if (c != null && c !== 0 && c !== 200) {
        throw new Error(labelsRes.message || "Failed to load labels")
    }
    return normalizeLabelList(labelsRes.data)
}
