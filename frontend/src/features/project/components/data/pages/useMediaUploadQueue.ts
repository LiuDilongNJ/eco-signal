import { useCallback, useState } from "react"
import { message } from "@/components/ui"
import { filesApi } from "../../../../../api/endpoints/files"
import type { QueueFile } from "../../modals/UploadAudioDrawer"

const CHUNK_SIZE = 5 * 1024 * 1024
function createUploadQueueId(): string {
    const cryptoApi = globalThis.crypto
    if (typeof cryptoApi?.randomUUID === "function") {
        return cryptoApi.randomUUID()
    }

    const bytes = new Uint8Array(16)
    if (typeof cryptoApi?.getRandomValues === "function") {
        cryptoApi.getRandomValues(bytes)
    } else {
        for (let index = 0; index < bytes.length; index += 1) {
            bytes[index] = Math.floor(Math.random() * 256)
        }
    }
    bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40
    bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function uploadErrorText(error: unknown): string | undefined {
    if (!error) return undefined
    if (typeof error === "string") return error.trim() || undefined
    if (error instanceof Error) return error.message || undefined

    const value = error as {
        data?: { detail?: { message?: unknown }; message?: unknown }
        response?: { data?: { detail?: { message?: unknown }; message?: unknown } }
        detail?: unknown
        message?: unknown
    }
    const nested =
        value.data?.detail?.message ??
        value.data?.message ??
        value.response?.data?.detail?.message ??
        value.response?.data?.message ??
        value.detail ??
        value.message
    if (typeof nested === "string" && nested.trim()) return nested.trim()

    try {
        const serialized = JSON.stringify(error)
        return serialized && serialized !== "{}" ? serialized : undefined
    } catch {
        return undefined
    }
}

export function useMediaUploadQueue(
    mediaType: "audio" | "photo",
    collectionId: string | number | null | undefined,
) {
    const [queueFiles, setQueueFiles] = useState<QueueFile[]>([])
    const [batchId, setBatchId] = useState<string | null>(null)
    const [drawerOpen, setDrawerOpen] = useState(false)

    const uploadFile = useCallback(async (queueFile: QueueFile, currentBatchId: string) => {
        const updateFile = (patch: Partial<QueueFile>) => {
            setQueueFiles((previous) => previous.map((file) => (
                file.id === queueFile.id ? { ...file, ...patch } : file
            )))
        }

        const totalChunks = Math.ceil(queueFile.file.size / CHUNK_SIZE)
        updateFile({ status: "uploading", progress: 0 })
        try {
            for (let index = 0; index < totalChunks; index += 1) {
                const chunk = queueFile.file.slice(
                    index * CHUNK_SIZE,
                    (index + 1) * CHUNK_SIZE,
                )
                const response = await filesApi.uploadChunk({
                    filename: queueFile.name,
                    chunk_index: index,
                    total_chunks: totalChunks,
                    batch_id: currentBatchId,
                    file: chunk,
                    media_type: mediaType,
                    collection_id:
                        collectionId && collectionId !== "all"
                            ? Number(collectionId)
                            : undefined,
                })
                const progress = Math.round(((index + 1) / totalChunks) * 100)
                if (response?.data?.is_complete && response.data.file_upload_id) {
                    updateFile({
                        file_upload_id: response.data.file_upload_id,
                    })
                }
                updateFile({ progress })
            }
            updateFile({ status: "done", progress: 100 })
        } catch (error) {
            console.error(`Failed to upload ${queueFile.name}:`, error)
            updateFile({
                status: "error",
                error,
                errorMessage: uploadErrorText(error),
            })
        }
    }, [collectionId, mediaType])

    const startUploads = useCallback(async (files: File[]) => {
        if (files.length === 0) return

        const newFiles: QueueFile[] = files.map((file) => ({
            id: createUploadQueueId(),
            name: file.name,
            file,
            status: "pending",
            progress: 0,
        }))
        setQueueFiles((previous) => [...previous, ...newFiles])
        setDrawerOpen(true)

        let currentBatchId = batchId
        if (!currentBatchId) {
            try {
                const response = await filesApi.batchInit(
                    collectionId && collectionId !== "all"
                        ? Number(collectionId)
                        : undefined,
                )
                currentBatchId = response.data?.batch_id ?? null
                if (!currentBatchId) {
                    message.error(response.message || "Failed to start upload batch")
                    return
                }
                setBatchId(currentBatchId)
            } catch (error) {
                console.error("Failed to initialize upload batch:", error)
                message.error("Failed to start upload batch")
                return
            }
        }

        for (const queueFile of newFiles) {
            await uploadFile(queueFile, currentBatchId)
        }
    }, [batchId, collectionId, uploadFile])

    const reset = useCallback(() => {
        setDrawerOpen(false)
        setQueueFiles([])
        setBatchId(null)
    }, [])

    return {
        queueFiles,
        batchId,
        drawerOpen,
        startUploads,
        retryUpload: batchId ? (file: QueueFile) => uploadFile(file, batchId) : undefined,
        reset,
    }
}
