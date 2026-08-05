import { apiClient } from "../client"

export interface CollectionBundleExport {
    export_id: string
    project_id: number
    collection_id: number
    queue_id: number
    status: "queued" | "running" | "completed" | "failed" | "cancelled" | "expired"
    filename: string | null
    size_b: number | null
    counts: Record<string, number> | null
    warnings: string[] | null
    error: string | null
    creation_date: string
    completion_date: string | null
    expires_at: string | null
}

type ExportResponse = {
    code: number
    message: string
    data: CollectionBundleExport
}

export const collectionBundleExportsApi = {
    create(projectId: number, collectionId: number) {
        return apiClient.post<ExportResponse>("/v1/collection-bundle-exports", {
            project_id: projectId,
            collection_id: collectionId,
        })
    },

    list(projectId: number) {
        return apiClient.get<{
            code: number
            message: string
            data: CollectionBundleExport[]
        }>("/v1/collection-bundle-exports", { params: { project_id: projectId } })
    },

    get(exportId: string, signal?: AbortSignal) {
        return apiClient.get<ExportResponse>(
            `/v1/collection-bundle-exports/${exportId}`,
            { signal },
        )
    },

    download(exportId: string) {
        return apiClient.download(`/v1/collection-bundle-exports/${exportId}/file`)
    },
}
