import { apiClient } from "../client"

export interface DataImportCounts {
    collections: number
    project_links: number
    sites: number
    site_links: number
    media: number
    audio: number
    photos: number
    media_files: number
    media_links: number
    previews: number
    annotations: number
    reviews: number
    labels: number
    label_links: number
}

export interface DataImportSummary {
    project_id: number
    collection_id: number
    collection_uuid: string
    signature_verified: boolean
    checksum_verified: boolean
    created_counts: DataImportCounts
    skipped_counts: DataImportCounts
    conflicts: Array<{ resource_type: string; identifier: string; reason: string }>
    warnings: Array<{ resource_type: string; identifier: string; message: string }>
}

export interface DataImportStatus {
    batch_id: string
    project_id: number
    uploader_id: number
    file_upload_id: number | null
    queue_id: number | null
    status: string
    error: string | null
    summary_json: DataImportSummary | null
    cleanup_after: string | null
    creation_date: string
    update_date: string
}

export const dataImportsApi = {
    create(projectId: number) {
        return apiClient.post<{
            code: number
            message: string
            data: { batch_id: string; project_id: number; status: string }
        }>("/v1/data-imports", { project_id: projectId })
    },

    getStatus(batchId: string, signal?: AbortSignal) {
        return apiClient.get<{ code: number; message: string; data: DataImportStatus }>(
            `/v1/data-imports/${batchId}`,
            { signal },
        )
    },

    uploadChunk(params: {
        batchId: string
        filename: string
        chunkIndex: number
        totalChunks: number
        file: Blob
    }) {
        const body = new FormData()
        body.append("filename", params.filename)
        body.append("chunk_index", String(params.chunkIndex))
        body.append("total_chunks", String(params.totalChunks))
        body.append("file", params.file)
        return apiClient.post<{
            code: number
            message: string
            data: {
                filename: string
                uploaded_chunks: number
                total_chunks: number
                is_complete: boolean
                file_upload_id?: number
            }
        }>(`/v1/file-upload-batches/${params.batchId}/chunks`, body)
    },
}
