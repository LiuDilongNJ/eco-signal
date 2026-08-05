import { apiClient } from "../client"

export interface UploadImageResponse {
    code: number
    message: string
    data: {
        filename: string
        path: string
    }
}

export interface BatchInitResponse {
    code: number
    message: string
    data: {
        batch_id: string
        [key: string]: unknown
    }
}

export interface UploadChunkResponse {
    code: number
    message: string
    data: {
        filename: string
        uploaded_chunks: number
        total_chunks: number
        is_complete: boolean
        file_upload_id?: number
        [key: string]: unknown
    }
}

export const filesApi = {
    uploadImage(category: string, file: File) {
        const formData = new FormData()
        formData.append("file", file)
        return apiClient.post<UploadImageResponse>(`/v1/file-images/${category}`, formData)
    },

    /** 初始化一个上传批次 */
    batchInit(collection_id?: number) {
        return apiClient.post<BatchInitResponse>("/v1/file-upload-batches", undefined, { params: { collection_id } })
    },

    /** 上传文件分块 (multipart/form-data) */
    uploadChunk(params: {
        filename: string
        chunk_index: number
        total_chunks: number
        batch_id: string
        file: Blob
        collection_id?: number
        media_type: "audio" | "photo"
    }) {
        const formData = new FormData()
        formData.append("filename", params.filename)
        formData.append("chunk_index", String(params.chunk_index))
        formData.append("total_chunks", String(params.total_chunks))
        formData.append("media_type", params.media_type)
        if (params.collection_id) formData.append("collection_id", String(params.collection_id))
        formData.append("file", params.file)
        return apiClient.post<UploadChunkResponse>(`/v1/file-upload-batches/${params.batch_id}/chunks`, formData)
    }
}
