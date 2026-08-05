import { Button as ESButton, Input as ESInput } from "@/components/ui"
/**
 * UploadModal - 文件上传弹窗
 *
 * 拖拽上传 + 文件列表 + 进度条
 */

import { useState, useRef, useCallback } from "react"
import { Modal } from "./Modal"
import { CustomScrollArea } from "@/components/ui"
import {
    Upload,
    FileAudio,
    FileSpreadsheet,
    X,
    CheckCircle2,
    AlertCircle,
} from "lucide-react"

interface UploadFile {
    id: string
    name: string
    size: number
    type: "audio" | "csv" | "other"
    progress: number
    status: "uploading" | "done" | "error"
}

interface UploadModalProps {
    open: boolean
    onClose: () => void
}

function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function getFileType(name: string): "audio" | "csv" | "other" {
    const ext = name.split(".").pop()?.toLowerCase()
    if (["wav", "mp3", "flac", "ogg", "aac", "m4a"].includes(ext ?? "")) return "audio"
    if (ext === "csv") return "csv"
    return "other"
}

export function UploadModal({ open, onClose }: UploadModalProps) {
    const [files, setFiles] = useState<UploadFile[]>([])
    const [isDragOver, setIsDragOver] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)

    const addFiles = useCallback((fileList: FileList) => {
        const newFiles: UploadFile[] = Array.from(fileList).map((f) => ({
            id: `${f.name}-${Date.now()}-${Math.random()}`,
            name: f.name,
            size: f.size,
            type: getFileType(f.name),
            progress: 0,
            status: "uploading" as const,
        }))

        setFiles((prev) => [...prev, ...newFiles])

        // 模拟上传进度
        newFiles.forEach((uf) => {
            const interval = setInterval(() => {
                setFiles((prev) =>
                    prev.map((f) => {
                        if (f.id !== uf.id) return f
                        if (f.progress >= 100) {
                            clearInterval(interval)
                            return { ...f, progress: 100, status: "done" as const }
                        }
                        return { ...f, progress: f.progress + 15 + Math.random() * 20 }
                    })
                )
            }, 300 + Math.random() * 400)
        })
    }, [])

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        setIsDragOver(false)
        if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files)
    }

    const removeFile = (id: string) => {
        setFiles((prev) => prev.filter((f) => f.id !== id))
    }

    const doneCount = files.filter((f) => f.status === "done").length

    const handleClose = () => {
        setFiles([])
        setIsDragOver(false)
        onClose()
    }

    return (
        <Modal
            open={open}
            onClose={handleClose}
            title="Upload Files"
            width="560px"
            footer={
                <div className="app-modal-footer-actions">
                    <div className="upload-summary">
                        {files.length > 0 && (
                            <span className="upload-summary-text">
                                {doneCount} / {files.length} completed
                            </span>
                        )}
                    </div>
                    <ESButton appearance="unstyled" className="app-modal-btn cancel" onClick={handleClose}>
                        {files.length > 0 ? "Close" : "Cancel"}
                    </ESButton>
                </div>
            }
        >
            <CustomScrollArea variant="fill">
                <div style={{ padding: "20px 24px" }}>
                    {/* Drop Zone */}
                    <div
                        className={`upload-drop-zone ${isDragOver ? "drag-over" : ""}`}
                        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true) }}
                        onDragLeave={() => setIsDragOver(false)}
                        onDrop={handleDrop}
                        onClick={() => inputRef.current?.click()}
                    >
                        <ESInput appearance="unstyled"
                            type="file"
                            ref={inputRef}
                            className="upload-hidden-input"
                            multiple
                            accept=".wav,.mp3,.flac,.ogg,.aac,.m4a,.csv"
                            onChange={(e) => e.target.files && addFiles(e.target.files)}
                        />
                        <Upload size={32} className="upload-icon" />
                        <p className="upload-drop-text">
                            Drop audio or CSV files here, or <span className="upload-link">browse</span>
                        </p>
                        <p className="upload-drop-hint">WAV, MP3, FLAC, OGG, AAC, M4A, CSV</p>
                    </div>

                    {/* File List */}
                    {files.length > 0 && (
                        <div className="upload-file-list">
                            {files.map((f) => (
                                <div className="upload-file-item" key={f.id}>
                                    <div className="upload-file-icon">
                                        {f.type === "audio" ? <FileAudio size={18} /> :
                                            f.type === "csv" ? <FileSpreadsheet size={18} /> :
                                                <Upload size={18} />}
                                    </div>
                                    <div className="upload-file-info">
                                        <div className="upload-file-row">
                                            <span className="upload-file-name">{f.name}</span>
                                            <span className="upload-file-size">{formatSize(f.size)}</span>
                                        </div>
                                        <div className="upload-progress-bar">
                                            <div
                                                className={`upload-progress-fill ${f.status}`}
                                                style={{ width: `${Math.min(f.progress, 100)}%` }}
                                            />
                                        </div>
                                    </div>
                                    <div className="upload-file-status">
                                        {f.status === "done" ? (
                                            <CheckCircle2 size={16} className="status-done" />
                                        ) : f.status === "error" ? (
                                            <AlertCircle size={16} className="status-error" />
                                        ) : (
                                            <span className="status-percent">{Math.min(Math.round(f.progress), 100)}%</span>
                                        )}
                                    </div>
                                    <ESButton appearance="unstyled" className="upload-file-remove" onClick={() => removeFile(f.id)}>
                                        <X size={14} />
                                    </ESButton>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </CustomScrollArea>
        </Modal>
    )
}
