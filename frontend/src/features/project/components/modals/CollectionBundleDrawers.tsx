import { Input as ESInput } from "@/components/ui"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
    Alert,
    Button,
    ConfigProvider,
    Descriptions,
    Divider,
    Progress,
    Space,
    Tag,
    Typography,
    message,
} from "@/components/ui"
import { Download, FileArchive, Upload } from "lucide-react"

import {
    collectionBundleExportsApi,
    type CollectionBundleExport,
} from "@/api/endpoints/collectionBundleExports"
import {
    dataImportsApi,
    type DataImportStatus,
} from "@/api/endpoints/dataImports"
import { CustomScrollArea } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { useAntdBrandConfig } from "@/features/project/hooks/useAntdBrandConfig"
import { useAppStore } from "@/store/useAppStore"
import { downloadFile } from "@/utils/download"
import "./styles/CollectionBundleDrawers.css"

const CHUNK_SIZE = 5 * 1024 * 1024
const COLLECTION_BUNDLE_DRAWER_WIDTH = 480
const TERMINAL_IMPORT_STATUSES = new Set(["completed", "failed", "cancelled"])
const TERMINAL_EXPORT_STATUSES = new Set(["completed", "failed", "cancelled", "expired"])
const COUNT_LABELS: Record<string, string> = {
    collections: "Collections",
    project_links: "Project links",
    sites: "Sites",
    site_links: "Site links",
    media: "Media",
    audio: "Audio",
    photos: "Photos",
    media_files: "Media files",
    media_links: "Media links",
    previews: "Previews",
    annotations: "Annotations",
    reviews: "Reviews",
    labels: "Labels",
    label_links: "Label links",
}

function countLabel(key: string): string {
    return COUNT_LABELS[key] ?? key.replace(/_/g, " ")
}

function bundleDrawerStyles() {
    return {
        wrapper: {
            width: COLLECTION_BUNDLE_DRAWER_WIDTH,
        },
        header: {
            borderBottom: "none",
            color: "var(--text-main)",
        },
        body: {
            padding: 0,
            overflow: "hidden",
        },
        mask: {
            backdropFilter: "blur(4px)",
        },
    }
}

function formatBytes(value: number | null | undefined): string {
    if (value == null) return "—"
    if (value < 1024) return `${value} B`
    const units = ["KB", "MB", "GB", "TB"]
    let amount = value / 1024
    let index = 0
    while (amount >= 1024 && index < units.length - 1) {
        amount /= 1024
        index += 1
    }
    return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${units[index]}`
}

type BundleStatusTone = "default" | "processing" | "success" | "error"

function statusTone(status: string): BundleStatusTone {
    if (status === "completed") return "success"
    if (status === "failed" || status === "expired") return "error"
    if (status === "running" || status === "queued" || status === "uploading") return "processing"
    return "default"
}

function statusTag(status: string) {
    return (
        <Tag className={`collection-bundle-drawer__status collection-bundle-drawer__status--${statusTone(status)}`}>
            {status}
        </Tag>
    )
}

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof Error ? error.message : fallback
}

function isAbortError(error: unknown): boolean {
    return error instanceof Error && error.name === "AbortError"
}

interface ImportBundleDrawerProps {
    open: boolean
    projectId: number | null
    onClose: () => void
    onImported: () => void | Promise<void>
}

export function ImportBundleDrawer({
    open,
    projectId,
    onClose,
    onImported,
}: ImportBundleDrawerProps) {
    const [file, setFile] = useState<File | null>(null)
    const [uploading, setUploading] = useState(false)
    const [uploadProgress, setUploadProgress] = useState(0)
    const [batchId, setBatchId] = useState<string | null>(null)
    const [status, setStatus] = useState<DataImportStatus | null>(null)
    const [error, setError] = useState<string | null>(null)
    const completedBatchRef = useRef<string | null>(null)
    const fileInputRef = useRef<HTMLInputElement | null>(null)
    const openCycleRef = useRef(0)
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)

    const isActive = uploading || (!!status && !TERMINAL_IMPORT_STATUSES.has(status.status))

    useEffect(() => {
        if (!open) return
        openCycleRef.current += 1
        if (fileInputRef.current) fileInputRef.current.value = ""
        setFile(null)
        setUploading(false)
        setUploadProgress(0)
        setBatchId(null)
        setStatus(null)
        setError(null)
        completedBatchRef.current = null
    }, [open])

    useEffect(() => {
        if (!batchId) return
        const controller = new AbortController()
        let timer: ReturnType<typeof setTimeout> | undefined

        const poll = async () => {
            try {
                const response = await dataImportsApi.getStatus(batchId, controller.signal)
                setStatus(response.data)
                if (response.data.status === "completed") {
                    if (completedBatchRef.current !== batchId) {
                        completedBatchRef.current = batchId
                        await onImported()
                        message.success("Collection bundle imported successfully")
                    }
                    return
                }
                if (TERMINAL_IMPORT_STATUSES.has(response.data.status)) return
                timer = setTimeout(poll, 2000)
            } catch (pollError: unknown) {
                if (isAbortError(pollError)) return
                setError(errorMessage(pollError, "Failed to query import status"))
            }
        }

        void poll()
        return () => {
            controller.abort()
            if (timer) clearTimeout(timer)
        }
    }, [batchId, onImported])

    const startImport = useCallback(async () => {
        if (!projectId) {
            message.error("Please select a project first")
            return
        }
        if (!file) {
            message.error("Please select a ZIP bundle")
            return
        }
        if (!file.name.toLowerCase().endsWith(".zip")) {
            message.error("Offline import only accepts ZIP files")
            return
        }

        const openCycle = openCycleRef.current
        const isCurrentCycle = () => openCycleRef.current === openCycle

        setUploading(true)
        setUploadProgress(0)
        setStatus(null)
        setError(null)
        completedBatchRef.current = null
        try {
            const session = await dataImportsApi.create(projectId)
            const nextBatchId = session.data.batch_id
            if (isCurrentCycle()) setBatchId(nextBatchId)
            const totalChunks = Math.max(1, Math.ceil(file.size / CHUNK_SIZE))
            for (let index = 0; index < totalChunks; index += 1) {
                const chunk = file.slice(index * CHUNK_SIZE, (index + 1) * CHUNK_SIZE)
                await dataImportsApi.uploadChunk({
                    batchId: nextBatchId,
                    filename: file.name,
                    chunkIndex: index,
                    totalChunks,
                    file: chunk,
                })
                if (isCurrentCycle()) {
                    setUploadProgress(Math.round(((index + 1) / totalChunks) * 100))
                }
            }
            const response = await dataImportsApi.getStatus(nextBatchId)
            if (isCurrentCycle()) setStatus(response.data)
        } catch (uploadError: unknown) {
            if (isCurrentCycle()) {
                setError(errorMessage(uploadError, "Failed to upload collection bundle"))
            }
        } finally {
            if (isCurrentCycle()) setUploading(false)
        }
    }, [file, projectId])

    const reset = () => {
        if (isActive) return
        if (fileInputRef.current) fileInputRef.current.value = ""
        setFile(null)
        setUploadProgress(0)
        setBatchId(null)
        setStatus(null)
        setError(null)
    }

    const close = () => {
        if (isActive) {
            message.info("Import continues in the background. Check the Queue page for status.")
        }
        onClose()
    }

    const summary = status?.summary_json
    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                rootClassName="collection-bundle-drawer"
                open={open}
                onClose={close}
                title="Import Bundle"
                placement="right"
                closable={false}
                maskClosable={!isActive}
                styles={bundleDrawerStyles()}
                extra={
                    <Space>
                        <Button shape="round" onClick={reset} disabled={isActive}>Reset</Button>
                        <Button shape="round" onClick={close}>Close</Button>
                        <Button
                            type="primary"
                            shape="round"
                            icon={<Upload size={14} />}
                            loading={uploading}
                            disabled={!file || !projectId || isActive}
                            onClick={() => void startImport()}
                        >
                            Import
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <div className="collection-bundle-drawer__content">
                        <Alert
                            type="info"
                            showIcon
                            title="The bundle will be imported into the current project."
                            description="Only one signed ZIP bundle can be uploaded. Processing continues in the background after upload."
                        />
                        <div className="collection-bundle-drawer__file-picker">
                            <ESInput appearance="unstyled"
                                ref={fileInputRef}
                                type="file"
                                accept=".zip,application/zip"
                                disabled={isActive}
                                onChange={(event) => {
                                    const selected = event.target.files?.[0] ?? null
                                    if (selected && !selected.name.toLowerCase().endsWith(".zip")) {
                                        message.error("Please select a ZIP file")
                                        event.target.value = ""
                                        return
                                    }
                                    setFile(selected)
                                    setError(null)
                                }}
                            />
                            <Button
                                shape="round"
                                icon={<FileArchive size={14} />}
                                disabled={isActive}
                                onClick={() => fileInputRef.current?.click()}
                            >
                                Select ZIP Bundle
                            </Button>
                        </div>
                        {file && (
                            <Descriptions size="small" column={1} bordered>
                                <Descriptions.Item label="File">{file.name}</Descriptions.Item>
                                <Descriptions.Item label="Size">{formatBytes(file.size)}</Descriptions.Item>
                            </Descriptions>
                        )}
                        {(uploading || uploadProgress > 0) && (
                            <div className="collection-bundle-drawer__progress">
                                <Typography.Text>Upload progress</Typography.Text>
                                <Progress
                                    percent={uploadProgress}
                                    status={error ? "exception" : undefined}
                                    strokeColor={error ? "var(--danger)" : "var(--brand)"}
                                />
                            </div>
                        )}
                        {status && !uploading && uploadProgress === 100 && (
                            <>
                                <Divider />
                                <Descriptions size="small" column={1} bordered>
                                    <Descriptions.Item label="Status">
                                        {statusTag(status.status)}
                                    </Descriptions.Item>
                                    <Descriptions.Item label="Queue">{status.queue_id ?? "Preparing"}</Descriptions.Item>
                                    <Descriptions.Item label="Updated">{status.update_date}</Descriptions.Item>
                                </Descriptions>
                            </>
                        )}
                        {error || status?.error ? (
                            <Alert type="error" showIcon title={error || status?.error} />
                        ) : null}
                        {summary && (
                            <>
                                <Descriptions title="Created" size="small" column={2} bordered>
                                    {Object.entries(summary.created_counts).map(([key, value]) => (
                                        <Descriptions.Item key={key} label={countLabel(key)}>{value}</Descriptions.Item>
                                    ))}
                                </Descriptions>
                                <Descriptions title="Skipped" size="small" column={2} bordered>
                                    {Object.entries(summary.skipped_counts).map(([key, value]) => (
                                        <Descriptions.Item key={key} label={countLabel(key)}>{value}</Descriptions.Item>
                                    ))}
                                </Descriptions>
                                {summary.conflicts.length > 0 && (
                                    <Alert
                                        type="warning"
                                        showIcon
                                        title={`${summary.conflicts.length} conflict(s)`}
                                        description={summary.conflicts.map((item) =>
                                            `${item.resource_type} ${item.identifier}: ${item.reason}`
                                        ).join("\n")}
                                    />
                                )}
                                {summary.warnings.length > 0 && (
                                    <Alert
                                        type="warning"
                                        showIcon
                                        title={`${summary.warnings.length} warning(s)`}
                                        description={summary.warnings.map((item) =>
                                            `${item.resource_type} ${item.identifier}: ${item.message}`
                                        ).join("\n")}
                                    />
                                )}
                            </>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}

interface ExportBundleDrawerProps {
    open: boolean
    projectId: number | null
    collection: { collection_id: number; name?: string } | null
    onClose: () => void
}

export function ExportBundleDrawer({
    open,
    projectId,
    collection,
    onClose,
}: ExportBundleDrawerProps) {
    const [exports, setExports] = useState<CollectionBundleExport[]>([])
    const [activeId, setActiveId] = useState<string | null>(null)
    const [creating, setCreating] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const openCycleRef = useRef(0)
    const isDark = useAppStore((state) => state.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)

    useEffect(() => {
        openCycleRef.current += 1
        if (!open) return
        setExports([])
        setActiveId(null)
        setCreating(false)
        setError(null)
    }, [collection?.collection_id, open, projectId])

    useEffect(() => {
        if (!open || !activeId) return
        const controller = new AbortController()
        let timer: ReturnType<typeof setTimeout> | undefined
        const poll = async () => {
            try {
                const response = await collectionBundleExportsApi.get(activeId, controller.signal)
                setExports((previous) => {
                    const exists = previous.some((item) => item.export_id === activeId)
                    return exists
                        ? previous.map((item) => item.export_id === activeId ? response.data : item)
                        : [response.data, ...previous]
                })
                if (!TERMINAL_EXPORT_STATUSES.has(response.data.status)) {
                    timer = setTimeout(poll, 2000)
                } else if (response.data.status === "completed") {
                    message.success("Collection bundle is ready to download")
                }
            } catch (pollError: unknown) {
                if (!isAbortError(pollError)) {
                    setError(errorMessage(pollError, "Failed to query export status"))
                }
            }
        }
        void poll()
        return () => {
            controller.abort()
            if (timer) clearTimeout(timer)
        }
    }, [activeId, open])

    const selectedExports = useMemo(
        () => exports.filter((item) => item.collection_id === collection?.collection_id),
        [collection?.collection_id, exports],
    )

    const createExport = async () => {
        if (!projectId || !collection) return
        const openCycle = openCycleRef.current
        setCreating(true)
        setError(null)
        try {
            const response = await collectionBundleExportsApi.create(
                projectId,
                collection.collection_id,
            )
            if (openCycleRef.current !== openCycle) return
            setExports((previous) => [response.data, ...previous])
            setActiveId(response.data.export_id)
            message.success("Collection bundle export queued")
        } catch (createError: unknown) {
            if (openCycleRef.current === openCycle) {
                setError(errorMessage(createError, "Failed to create collection bundle export"))
            }
        } finally {
            if (openCycleRef.current === openCycle) setCreating(false)
        }
    }

    const download = async (item: CollectionBundleExport) => {
        try {
            const response = await collectionBundleExportsApi.download(item.export_id)
            downloadFile(response, item.filename ?? `collection-${item.collection_id}.zip`)
        } catch (downloadError: unknown) {
            message.error(errorMessage(downloadError, "Failed to download collection bundle"))
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                rootClassName="collection-bundle-drawer"
                open={open}
                onClose={onClose}
                title="Export Bundle"
                placement="right"
                closable={false}
                maskClosable={false}
                styles={bundleDrawerStyles()}
                extra={
                    <Space>
                        <Button shape="round" onClick={onClose}>Close</Button>
                        <Button
                            type="primary"
                            shape="round"
                            icon={<FileArchive size={14} />}
                            loading={creating}
                            disabled={!projectId || !collection}
                            onClick={() => void createExport()}
                        >
                            Export Bundle
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <div className="collection-bundle-drawer__content">
                        <Alert
                            type="info"
                            showIcon
                            title="A successful offline bundle includes every audio and photo file."
                            description="Generation fails if a source file is missing or ambiguous. Completed downloads remain available for 24 hours."
                        />
                        {collection && (
                            <Descriptions size="small" column={1} bordered>
                                <Descriptions.Item label="Collection">{collection.name || collection.collection_id}</Descriptions.Item>
                                <Descriptions.Item label="Collection ID">{collection.collection_id}</Descriptions.Item>
                            </Descriptions>
                        )}
                        {error && <Alert type="error" showIcon title={error} />}
                        <Divider />
                        <Typography.Title level={5} className="collection-bundle-drawer__section-title">
                            Recent exports
                        </Typography.Title>
                        {selectedExports.length === 0 ? (
                            <Typography.Text type="secondary">No recent exports for this collection.</Typography.Text>
                        ) : (
                            <div className="collection-bundle-drawer__records">
                                {selectedExports.map((item) => (
                                    <div
                                        className="collection-bundle-drawer__record"
                                        key={item.export_id}
                                    >
                                        <div className="collection-bundle-drawer__record-content">
                                            <Space wrap>
                                                {statusTag(item.status)}
                                                <Typography.Text>{item.filename || `Queue ${item.queue_id}`}</Typography.Text>
                                                <Typography.Text type="secondary">{formatBytes(item.size_b)}</Typography.Text>
                                            </Space>
                                            <Typography.Text type="secondary">
                                                Created: {item.creation_date}
                                                {item.expires_at ? ` · Expires: ${item.expires_at}` : ""}
                                            </Typography.Text>
                                            {item.error && <Alert type="error" showIcon title={item.error} />}
                                            {item.warnings && item.warnings.length > 0 && (
                                                <Alert type="warning" showIcon title={item.warnings.join("; ")} />
                                            )}
                                            {item.counts && (
                                                <Typography.Text type="secondary">
                                                    {Object.entries(item.counts).map(([key, value]) => `${countLabel(key)}: ${value}`).join(" · ")}
                                                </Typography.Text>
                                            )}
                                            {item.status === "completed" && (
                                                <Button
                                                    shape="round"
                                                    icon={<Download size={14} />}
                                                    onClick={() => void download(item)}
                                                >
                                                    Download
                                                </Button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
