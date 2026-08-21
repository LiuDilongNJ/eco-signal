import { Input as ESInput, Button as ESButton } from "@/components/ui"
/**
 * AudiosPage - Audios 数据页面
 */

import { useState, useCallback, useRef, useEffect } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef } from "../DataPageLayout"
import { mediaApi } from "../../../../../api/endpoints/media"
import { emptyCsvImportResult, type CsvImportResult } from "../../../../../api/csvImport"
import { useProjectStore } from "../../../stores/useProjectStore"
import { message } from "@/components/ui"
import { Mic, FileText, Info, Link as LinkIcon, Tag as TagIcon, ClipboardList as ClipboardListIcon, Bot as BotIcon, Activity as ActivityIcon } from "lucide-react"
import { UploadAudioDrawer } from "../../modals/UploadAudioDrawer"
import { EditMediaDrawer } from "../../modals/EditMediaDrawer"
import { LinkItemToCollectionsDrawer } from "../../modals/LinkItemToCollectionsDrawer"
import { SetLabelsDrawer } from "../../modals/SetLabelsDrawer"
import { AssignTasksDrawer } from "../../modals/AssignTasksDrawer"
import { RunAIModelsDrawer } from "../../modals/RunAIModelsDrawer"
import { AcousticIndicesDrawer } from "../../modals/AcousticIndicesDrawer"
import { MetadataInstructionsDrawer } from "../../modals/MetadataInstructionsDrawer"
import { CsvImportResultModal } from "../../../../settings/components/CsvImportResultModal"
import { downloadFile } from "@/utils/download"
import { buildMediaQueryParams } from "./mediaQueryParams"
import { useMediaTableData } from "./useMediaTableData"
import { useMediaUploadQueue } from "./useMediaUploadQueue"
import {
    openMediaDetailTab,
    renderLabelPills,
    selectedMediaIds,
} from "./mediaTablePresentation"

function formatIsMetadataDisplay(isMetadata: unknown): string {
    return isMetadata === true ? "metadata" : "file"
}

function isMetadataValue(value: unknown): boolean {
    return value === true || value === "true" || value === 1 || value === "1"
}

const COLUMNS: ColumnDef[] = [
    { key: "media_id", label: "ID", type: "number", width: "80px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "300px", sortable: true, filterable: true },
    {
        key: "media_type",
        label: "Media Type",
        type: "text",
        width: "150px",
        sortable: true,
        filterable: true,
    },
    {
        key: "is_metadata",
        label: "Type",
        type: "text",
        width: "150px",
        sortable: true,
        filterable: true,
        renderCell: (value) => formatIsMetadataDisplay(value),
    },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "filename", label: "Filename", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "site_name", label: "Site", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "sensor_name", label: "Sensor", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "medium", label: "Medium", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "sampling_rate_hz", label: "Sample Rate (Hz)", type: "text", width: "200px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "bit_depth", label: "Bit Depth", type: "text", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "channel_num", label: "Channels", type: "text", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "duration_s", label: "Duration (s)", type: "text", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "size_b", label: "Size (Bytes)", type: "text", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "recording_gain_db", label: "Gain (dB)", type: "text", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "duty_cycle_recording", label: "Duty Rec (s)", type: "text", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "duty_cycle_period", label: "Duty Period (s)", type: "text", width: "200px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "license_name", label: "License", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "doi", label: "DOI", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "note", label: "Note", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "uploader_name", label: "Uploader", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "date_time", label: "Date Time", type: "date", width: "160px", sortable: true, filterable: true, filterType: "dateRange" },
    { key: "labels", label: "Labels", type: "text", width: "200px", sortable: false, filterable: true, filterSearch: true, renderCell: renderLabelPills },
]

const FORM_FIELDS: FormFieldDef[] = [] // Read only for now

export function AudiosPage() {
    const [editDrawerOpen, setEditDrawerOpen] = useState(false)
    const [editMediaId, setEditMediaId] = useState<number | null>(null)
    const [linkDrawerOpen, setLinkDrawerOpen] = useState(false)
    const [linkMediaIds, setLinkMediaIds] = useState<number[]>([])
    const [labelDrawerOpen, setLabelDrawerOpen] = useState(false)
    const [labelMediaIds, setLabelMediaIds] = useState<number[]>([])
    const [assignDrawerOpen, setAssignDrawerOpen] = useState(false)
    const [assignMediaIds, setAssignMediaIds] = useState<number[]>([])
    const [runAIDrawerOpen, setRunAIDrawerOpen] = useState(false)
    const [runAIMediaIds, setRunAIMediaIds] = useState<number[]>([])
    const [idxDrawerOpen, setIdxDrawerOpen] = useState(false)
    const [idxMediaIds, setIdxMediaIds] = useState<number[]>([])
    const [instructionsOpen, setInstructionsOpen] = useState(false)
    const [metadataImportResultOpen, setMetadataImportResultOpen] = useState(false)
    const [metadataImportResult, setMetadataImportResult] = useState<CsvImportResult | null>(null)
    const audioInputRef = useRef<HTMLInputElement>(null)
    const metadataInputRef = useRef<HTMLInputElement>(null)

    const currentProjectId = useProjectStore(s => s.currentProjectId)
    const currentCollectionId = useProjectStore(s => s.currentCollectionId)
    const pendingAudioDetailMediaId = useProjectStore(s => s.pendingAudioDetailMediaId)
    const clearPendingAudioDetailMediaId = useProjectStore(s => s.clearPendingAudioDetailMediaId)
    const {
        rows,
        totalRows,
        loading,
        setLoading,
        tableState,
        siteOptions,
        licenseOptions,
        sensorOptions,
        handleTableChange,
        refresh,
    } = useMediaTableData("audio", currentProjectId, currentCollectionId)
    const uploadQueue = useMediaUploadQueue("audio", currentCollectionId)

    useEffect(() => {
        if (pendingAudioDetailMediaId == null) return
        setEditMediaId(pendingAudioDetailMediaId)
        setEditDrawerOpen(true)
        clearPendingAudioDetailMediaId()
    }, [pendingAudioDetailMediaId, clearPendingAudioDetailMediaId])

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params = buildMediaQueryParams(
                "audio",
                tableState,
                { projectId: currentProjectId, collectionId: currentCollectionId },
                { includePagination: false },
            )
            const download = await mediaApi.exportAudioCsv(params)
            downloadFile(download)
        } catch (error: unknown) {
            console.error("Export error:", error)
            message.error(error instanceof Error ? error.message : "An error occurred while exporting")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId, currentCollectionId, setLoading])

    const handleView = useCallback((selectedRowKeys: unknown[]) => {
        if (selectedRowKeys.length === 0) {
            message.warning("Please select at least one media item to view")
            return
        }
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        const projectId = Number(currentProjectId)
        const viewableIds = [
            ...new Set(
                selectedRowKeys
                    .map((key) => Number(key))
                    .filter((mediaId) => {
                        if (!Number.isFinite(mediaId) || mediaId <= 0) return false
                        const row = rows.find((r) => Number(r.media_id) === mediaId)
                        return !row || !isMetadataValue(row.is_metadata)
                    }),
            ),
        ]

        if (viewableIds.length === 0) {
            message.warning("No viewable media selected")
            return
        }

        for (const mediaId of viewableIds) {
            openMediaDetailTab(projectId, mediaId)
        }
    }, [currentProjectId, rows])

    const selectedRowsContainMetadata = useCallback((selectedRows: Set<unknown>) => {
        const selectedIds = new Set(
            Array.from(selectedRows)
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        )
        return rows.some((row) => selectedIds.has(Number(row.media_id)) && isMetadataValue(row.is_metadata))
    }, [rows])

    const selectedRowsContainNonAudio = useCallback((selectedRows: Set<unknown>) => {
        const selectedIds = new Set(
            Array.from(selectedRows)
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        )
        return rows.some((row) => (
            selectedIds.has(Number(row.media_id)) &&
            (isMetadataValue(row.is_metadata) || String(row.media_type).toLowerCase() !== "audio")
        ))
    }, [rows])

    const addDropdownItems = [
        {
            key: 'audios',
            label: (<span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Mic size={16} /> Audios</span>),
            onClick: () => audioInputRef.current?.click(),
        },
        {
            key: 'metadata',
            label: (<span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><FileText size={16} /> Metadata</span>),
            onClick: () => metadataInputRef.current?.click(),
        },
        {
            key: 'instructions',
            label: (<span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Info size={16} /> Metadata Instructions</span>),
            onClick: () => setInstructionsOpen(true),
        },
    ]

    return (
        <>
            {/* Hidden file inputs */}
            <ESInput appearance="unstyled" ref={audioInputRef} type="file" accept="audio/*" multiple style={{ display: 'none' }} onChange={async (event) => {
                const files = Array.from(event.target.files ?? [])
                event.target.value = ""
                await uploadQueue.startUploads(files)
            }} />

            <ESInput appearance="unstyled" ref={metadataInputRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={async (e) => {
                const file = e.target.files?.[0]
                if (!file) return

                const collId = currentCollectionId && currentCollectionId !== 'all' ? Number(currentCollectionId) : null
                if (!collId) {
                    message.warning('Please select a specific collection to import metadata.')
                    e.target.value = ''
                    return
                }

                const hideLoading = message.loading('Importing metadata...', 0)
                try {
                    if (!currentProjectId) {
                        message.warning('Please select a project first.')
                        return
                    }
                    const res = await mediaApi.importMetadata(Number(currentProjectId), collId, file, "audio")
                    if (res.code !== 0 && res.code !== 200) {
                        message.error(res.message || 'Failed to import metadata')
                        setMetadataImportResult(emptyCsvImportResult(res.message || "Failed to import metadata"))
                        setMetadataImportResultOpen(true)
                        return
                    }
                    setMetadataImportResult(res.data)
                    setMetadataImportResultOpen(true)
                    if ((res.data?.succeeded ?? 0) > 0) {
                        message.success(`Imported ${res.data.succeeded} of ${res.data.total} row(s)`)
                    } else {
                        message.info(`Import completed: 0 rows written out of ${res.data?.total ?? 0} row(s)`)
                    }
                    refresh()
                } catch (err: unknown) {
                    const detailMessage =
                        typeof err === "object" &&
                        err !== null &&
                        "data" in err &&
                        typeof (err as { data?: unknown }).data === "object" &&
                        (err as { data?: { detail?: unknown } }).data?.detail &&
                        typeof (err as { data?: { detail?: { message?: unknown } } }).data?.detail === "object" &&
                        typeof (err as { data?: { detail?: { message?: unknown } } }).data?.detail?.message === "string"
                            ? (err as { data?: { detail?: { message?: string } } }).data?.detail?.message
                            : null

                    const errorMessage = detailMessage || (err instanceof Error ? err.message : 'Failed to import metadata')
                    message.error(errorMessage)
                    setMetadataImportResult(emptyCsvImportResult(errorMessage))
                    setMetadataImportResultOpen(true)

                } finally {
                    hideLoading()
                    e.target.value = ''
                }
            }} />

            <DataPageLayout
                title="Audios"
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                icon={Mic}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="media_id"
                onTableStateChange={handleTableChange}
                defaultSortKey="media_id"
                defaultSortDir="asc"
                onEditCustom={(selectedRows) => {
                    if (selectedRows.length === 1) {
                        const mediaId = Number(selectedRows[0])
                        setEditMediaId(mediaId)
                        setEditDrawerOpen(true)
                    } else if (selectedRows.length > 1) {
                        message.warning('Please select only one item to edit')
                    } else {
                        message.warning('Please select an item to edit')
                    }
                }}
                onDeleteCustom={async (selectedRowKeys) => {
                    const hideLoading = message.loading(`Deleting ${selectedRowKeys.length} records...`, 0)
                    try {
                        for (const id of selectedRowKeys) {
                            await mediaApi.deleteMedia(id as number)
                        }
                        message.success(`Successfully deleted ${selectedRowKeys.length} records`)
                        refresh()
                    } catch (error: unknown) {
                        console.error('[deleteMedia] failed:', error)
                        message.error(error instanceof Error ? error.message : 'Failed to delete records')

                    } finally {
                        hideLoading()
                    }
                }}
                renderCustomActions={(selectedRows) => {
                    const audioActionBlockedByMediaType = selectedRowsContainNonAudio(selectedRows)
                    const selectedIds = selectedMediaIds(selectedRows)
                    const audioActionDisabled = selectedRows.size === 0 || audioActionBlockedByMediaType
                    return (
                    <>
                        <ESButton appearance="unstyled" className="data-btn" title="Link the selected audio files to collections" disabled={selectedRows.size === 0} onClick={() => {
                            setLinkMediaIds(selectedIds)
                            setLinkDrawerOpen(true)
                        }}>
                            <LinkIcon size={14} /> Link
                        </ESButton>
                        <ESButton appearance="unstyled" className="data-btn" title="Apply labels to the selected audio files" disabled={selectedRows.size === 0} onClick={() => {
                            setLabelMediaIds(selectedIds)
                            setLabelDrawerOpen(true)
                        }}>
                            <TagIcon size={14} /> Label
                        </ESButton>
                        <ESButton appearance="unstyled"
                            className="data-btn"
                            title={audioActionBlockedByMediaType ? "Only audio files can be assigned" : "Assign the selected audio files to a user"}
                            disabled={selectedRows.size === 0 || audioActionBlockedByMediaType}
                            onClick={() => {
                                if (audioActionBlockedByMediaType) {
                                    message.warning("Only audio files can be assigned.")
                                    return
                                }
                            setAssignMediaIds(
                                Array.from(selectedRows)
                                    .map((id) => Number(id))
                                    .filter((id) => Number.isFinite(id) && id > 0),
                            )
                            setAssignDrawerOpen(true)
                        }}>
                            <ClipboardListIcon size={14} /> Assignment
                        </ESButton>
                        <ESButton appearance="unstyled" className="data-btn" title={audioActionBlockedByMediaType ? "AI models are available for audio files only" : "Run an AI model on the selected audio files"} disabled={audioActionDisabled} onClick={() => {
                            if (audioActionBlockedByMediaType) {
                                message.warning("AI models are available for audio files only.")
                                return
                            }
                            setRunAIMediaIds(selectedIds)
                            setRunAIDrawerOpen(true)
                        }}>
                            <BotIcon size={14} /> AI models
                        </ESButton>
                        <ESButton appearance="unstyled" className="data-btn" title={audioActionBlockedByMediaType ? "Acoustic indices are available for audio files only" : "Calculate acoustic indices for the selected audio files"} disabled={audioActionDisabled} onClick={() => {
                            if (audioActionBlockedByMediaType) {
                                message.warning("Acoustic indices are available for audio files only.")
                                return
                            }
                            setIdxMediaIds(selectedIds)
                            setIdxDrawerOpen(true)
                        }}>
                            <ActivityIcon size={14} /> Acoustic Indices
                        </ESButton>
                    </>
                    )
                }}
                onExportCustom={handleExport}
                onViewCustom={handleView}
                viewRequiresSingle={false}
                isViewDisabled={(selectedRows) =>
                    selectedRows.size === 0 || selectedRowsContainMetadata(selectedRows)
                }
                addDropdownItems={addDropdownItems}
                addDisabled={!currentCollectionId || currentCollectionId === 'all'}
                addDisabledTooltip="Please select a Collection before adding data."
            />

            <UploadAudioDrawer
                open={uploadQueue.drawerOpen}
                initialFiles={uploadQueue.queueFiles}
                batchId={uploadQueue.batchId}
                siteOptions={siteOptions}
                licenseOptions={licenseOptions}
                sensorOptions={sensorOptions}
                onClose={uploadQueue.reset}
                onAddMoreFiles={() => audioInputRef.current?.click()}
                onRetry={uploadQueue.retryUpload}
                onSave={async (_files, formData) => {
                    const collId = currentCollectionId && currentCollectionId !== 'all'
                        ? Number(currentCollectionId)
                        : null
                    if (!collId) {
                        message.warning('Please select a specific collection before saving.')
                        return false
                    }
                    const fileUploadIds = _files
                        .filter(f => f.status === 'done' && f.file_upload_id)
                        .map(f => f.file_upload_id!)
                    if (fileUploadIds.length === 0) {
                        message.warning('No validated audio files are ready to save.')
                        return false
                    }
                    try {
                        const createMediaParams = currentProjectId
                            ? { project_id: Number(currentProjectId) }
                            : undefined
                        const filenamePrefixRaw = formData.sound_name_prefix
                        const filenamePrefix = typeof filenamePrefixRaw === "string"
                            ? filenamePrefixRaw.trim()
                            : ""
                        const response = await mediaApi.createMedia({
                            collection_id: collId,
                            file_upload_ids: fileUploadIds,
                            filename_prefix: filenamePrefix || undefined,
                            date_time: formData.date_time,
                            date_from_filename: formData.dateFromFilename ?? false,
                            site_id: formData.site_id,
                            sensor_id: formData.sensor_id,
                            license_id: formData.license_id,
                            medium: formData.medium,
                            media_type: 'audio',
                            recording_gain_db: formData.gain != null && String(formData.gain).trim() !== ""
                                ? Number(formData.gain)
                                : undefined,
                            duty_cycle_recording: formData.duty_cycle_recording ? Number(formData.duty_cycle_recording) : undefined,
                            duty_cycle_period: formData.duty_cycle_period ? Number(formData.duty_cycle_period) : undefined,
                            note: formData.note,
                            doi: formData.doi,
                        }, createMediaParams)
                        message.success(`Upload queue ${response.data?.queue_id ?? ""} submitted.`)
                        // 关闭抽屉并刷新列表
                        uploadQueue.reset()
                        refresh()
                        return true
                    } catch (err) {
                        console.error('[createMedia] failed:', err)
                        return false
                    }
                }}
            />

            <MetadataInstructionsDrawer
                open={instructionsOpen}
                mediaType="audio"
                onClose={() => setInstructionsOpen(false)}
            />
            <CsvImportResultModal
                open={metadataImportResultOpen}
                label="audio metadata"
                result={metadataImportResult}
                onClose={() => setMetadataImportResultOpen(false)}
            />

            <EditMediaDrawer
                open={editDrawerOpen}
                mediaId={editMediaId}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                siteOptions={siteOptions}
                licenseOptions={licenseOptions}
                sensorOptions={sensorOptions}
                onClose={() => { setEditDrawerOpen(false); setEditMediaId(null); }}
                onSuccess={refresh}
            />

            <LinkItemToCollectionsDrawer
                open={linkDrawerOpen}
                mediaId={linkMediaIds[0] ?? null}
                mediaIds={linkMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => { setLinkDrawerOpen(false); setLinkMediaIds([]); }}
                onSuccess={refresh}
            />

            <SetLabelsDrawer
                open={labelDrawerOpen}
                mediaId={labelMediaIds[0] ?? null}
                mediaIds={labelMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => { setLabelDrawerOpen(false); setLabelMediaIds([]); }}
                onSuccess={() => {
                    refresh()
                }}
            />

            <AssignTasksDrawer
                open={assignDrawerOpen}
                mediaId={assignMediaIds[0] ?? null}
                mediaIds={assignMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => { setAssignDrawerOpen(false); setAssignMediaIds([]); }}
                onSuccess={refresh}
            />

            <RunAIModelsDrawer
                open={runAIDrawerOpen}
                mediaId={runAIMediaIds[0] ?? null}
                mediaIds={runAIMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => { setRunAIDrawerOpen(false); setRunAIMediaIds([]); }}
                onSuccess={refresh}
            />

            <AcousticIndicesDrawer
                open={idxDrawerOpen}
                mediaId={idxMediaIds[0] ?? null}
                mediaIds={idxMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => { setIdxDrawerOpen(false); setIdxMediaIds([]); }}
                onSuccess={refresh}
            />
        </>
    )
}
