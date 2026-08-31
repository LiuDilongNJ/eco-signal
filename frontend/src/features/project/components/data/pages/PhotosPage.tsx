import { Input as ESInput, Button as ESButton } from "@/components/ui"
import { useCallback, useEffect, useRef, useState } from "react"
import { message } from "@/components/ui"
import { ClipboardList as ClipboardListIcon, Image, Link as LinkIcon, Tag as TagIcon } from "lucide-react"
import { mediaApi } from "../../../../../api/endpoints/media"
import { downloadFile } from "@/utils/download"
import { useProjectStore } from "../../../stores/useProjectStore"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef } from "../DataPageLayout"
import { PhotoMediaDrawer } from "../../modals/UploadPhotoDrawer"
import { LinkItemToCollectionsDrawer } from "../../modals/LinkItemToCollectionsDrawer"
import { SetLabelsDrawer } from "../../modals/SetLabelsDrawer"
import { AssignTasksDrawer } from "../../modals/AssignTasksDrawer"
import { buildMediaQueryParams } from "./mediaQueryParams"
import {
    openMediaDetailTab,
    renderLabelPills,
    selectedMediaIds,
} from "./mediaTablePresentation"
import { useMediaTableData } from "./useMediaTableData"
import { useMediaUploadQueue } from "./useMediaUploadQueue"
import { isAbortError, pollAnalysisQueues } from "../../modals/utils/analysisQueuePolling"
import { useCreatorOptions } from "./useCreatorOptions"
import { usePermissions } from "@/hooks/usePermissions"
import { rowCan, selectionCan } from "../rowCapabilities"

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
    { key: "exposure_ms", label: "Exposure (ms)", type: "number", width: "160px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "aperture", label: "Aperture", type: "number", width: "140px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "iso", label: "ISO", type: "number", width: "120px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "size_b", label: "Size (Bytes)", type: "number", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "license_name", label: "License", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "doi", label: "DOI", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "note", label: "Note", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "uploader_name", label: "Uploader", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "date_time", label: "Date Time", type: "date", width: "160px", sortable: true, filterable: true, filterType: "dateRange" },
    { key: "labels", label: "Labels", type: "text", width: "200px", sortable: false, filterable: true, filterSearch: true, renderCell: renderLabelPills },
]

const FORM_FIELDS: FormFieldDef[] = []

function formatIsMetadataDisplay(isMetadata: unknown): string {
    return isMetadata === true ? "metadata" : "file"
}

function isMetadataValue(value: unknown): boolean {
    return value === true || value === "true" || value === 1 || value === "1"
}

export function PhotosPage() {
    const currentProjectId = useProjectStore((state) => state.currentProjectId)
    const currentCollectionId = useProjectStore((state) => state.currentCollectionId)
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [editMediaId, setEditMediaId] = useState<number | null>(null)
    const [linkMediaIds, setLinkMediaIds] = useState<number[]>([])
    const [labelMediaIds, setLabelMediaIds] = useState<number[]>([])
    const [assignMediaIds, setAssignMediaIds] = useState<number[]>([])
    const mediaProcessingAbortRef = useRef<AbortController | null>(null)
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
    } = useMediaTableData("photo", currentProjectId, currentCollectionId)
    const uploadQueue = useMediaUploadQueue("photo", currentCollectionId)
    const { creatorOptions, currentUserId } = useCreatorOptions(currentProjectId, currentCollectionId)
    const { can } = usePermissions(currentProjectId, currentCollectionId)
    const canWriteAudio = can("audio:write")

    useEffect(() => () => {
        mediaProcessingAbortRef.current?.abort()
    }, [])

    const refreshAfterMediaProcessing = useCallback(async (queueId: number) => {
        mediaProcessingAbortRef.current?.abort()
        const controller = new AbortController()
        mediaProcessingAbortRef.current = controller
        let timedOut = false
        const timeoutId = window.setTimeout(() => {
            timedOut = true
            controller.abort()
        }, 120_000)

        try {
            const summary = await pollAnalysisQueues([queueId], controller.signal)
            const failedStatus = summary.failed[0]
            if (failedStatus) {
                message.warning(failedStatus.error || failedStatus.warning || "Some photos could not be processed.")
            }
            refresh()
        } catch (error) {
            if (timedOut) {
                message.info("Photo processing is taking longer than expected. Please refresh the table later to see the results.")
                refresh()
            } else if (!isAbortError(error)) {
                console.error("Failed to monitor photo processing queue:", error)
                message.info("Photo upload was submitted. Refresh the table later to see the processed files.")
            }
        } finally {
            window.clearTimeout(timeoutId)
            if (mediaProcessingAbortRef.current === controller) {
                mediaProcessingAbortRef.current = null
            }
        }
    }, [refresh])

    const handleView = useCallback((selectedRowKeys: unknown[]) => {
        if (!currentProjectId) {
            message.warning("Please select a project first")
            return
        }
        const ids = [
            ...new Set(
                selectedRowKeys
                    .map((key) => Number(key))
                    .filter((id) => {
                        if (!Number.isFinite(id) || id <= 0) return false
                        const row = rows.find((r) => Number(r.media_id) === id)
                        return !row || !isMetadataValue(row.is_metadata)
                    }),
            ),
        ]
        if (ids.length === 0) {
            message.warning("No viewable media selected")
            return
        }
        ids.forEach((mediaId) => openMediaDetailTab(Number(currentProjectId), mediaId))
    }, [currentProjectId, rows])

    const selectedRowsContainMetadata = useCallback((selectedRows: Set<unknown>) => {
        const selectedIds = new Set(
            Array.from(selectedRows)
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        )
        return rows.some((row) => selectedIds.has(Number(row.media_id)) && isMetadataValue(row.is_metadata))
    }, [rows])

    const selectedRowsContainNonPhoto = useCallback((selectedRows: Set<unknown>) => {
        const selectedIds = new Set(
            Array.from(selectedRows)
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        )
        return rows.some((row) => (
            selectedIds.has(Number(row.media_id)) &&
            (isMetadataValue(row.is_metadata) || String(row.media_type).toLowerCase() !== "photo")
        ))
    }, [rows])

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params = buildMediaQueryParams(
                "photo",
                tableState,
                { projectId: currentProjectId, collectionId: currentCollectionId },
                { includePagination: false },
            )
            downloadFile(await mediaApi.exportPhotoCsv(params))
        } catch (error) {
            console.error("Photo export failed:", error)
            message.error(error instanceof Error ? error.message : "Failed to export photos")
        } finally {
            setLoading(false)
        }
    }, [currentCollectionId, currentProjectId, setLoading, tableState])

    const addDropdownItems = [
        {
            key: "photos",
            label: (<span style={{ display: "flex", alignItems: "center", gap: 8 }}><Image size={16} /> Photos</span>),
            onClick: () => fileInputRef.current?.click(),
        },
    ]

    return (
        <>
            <ESInput appearance="unstyled"
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/tiff,.tif,.tiff"
                multiple
                hidden
                onChange={async (event) => {
                    const files = Array.from(event.target.files ?? [])
                    event.target.value = ""
                    await uploadQueue.startUploads(files)
                }}
            />
            <DataPageLayout
                title="Photos"
                importConfig={{
                    endpoint: "/v1/media/imports",
                    resourceKey: "photoMetadata",
                    importLabel: "Metadata",
                    instructionsLabel: "Metadata Instructions",
                    fields: { project_id: currentProjectId, collection_id: currentCollectionId, media_type: "photo" },
                    disabled: !canWriteAudio || !currentProjectId || !currentCollectionId || currentCollectionId === "all",
                    disabledReason: canWriteAudio
                        ? "Select a project and collection before importing photo metadata"
                        : "You do not have permission to import photo metadata",
                }}
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                icon={Image}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="media_id"
                onTableStateChange={handleTableChange}
                defaultSortKey="media_id"
                defaultSortDir="asc"
                onEditCustom={(selectedRows) => {
                    if (selectedRows.length !== 1) {
                        message.warning(
                            selectedRows.length === 0
                                ? "Please select a photo to edit"
                                : "Please select only one photo to edit",
                        )
                        return
                    }
                    setEditMediaId(Number(selectedRows[0]))
                }}
                onDeleteCustom={async (selectedRowKeys) => {
                    const hideLoading = message.loading(
                        `Deleting ${selectedRowKeys.length} photos...`,
                        0,
                    )
                    try {
                        for (const id of selectedRowKeys) {
                            await mediaApi.deleteMedia(Number(id))
                        }
                        message.success(`Successfully deleted ${selectedRowKeys.length} photos`)
                        refresh()
                    } catch (error) {
                        console.error("Photo deletion failed:", error)
                        message.error(error instanceof Error ? error.message : "Failed to delete photos")
                    } finally {
                        hideLoading()
                    }
                }}
                renderCustomActions={(selectedRows) => {
                    const ids = selectedMediaIds(selectedRows)
                    const photoActionBlockedByMediaType = selectedRowsContainNonPhoto(selectedRows)
                    const canLinkSelection = selectionCan(selectedRows, rows, "media_id", "link")
                    const canAssignSelection = selectionCan(selectedRows, rows, "media_id", "assign")
                    return (
                        <>
                            <ESButton appearance="unstyled"
                                className="data-btn"
                                title={canLinkSelection
                                    ? "Link the selected photos to collections"
                                    : "You do not have permission to link media"}
                                disabled={!canLinkSelection || ids.length === 0}
                                onClick={() => setLinkMediaIds(ids)}
                            >
                                <LinkIcon size={14} /> Link
                            </ESButton>
                            <ESButton appearance="unstyled"
                                className="data-btn"
                                title="Apply labels to the selected photos"
                                disabled={ids.length === 0}
                                onClick={() => setLabelMediaIds(ids)}
                            >
                                <TagIcon size={14} /> Label
                            </ESButton>
                            <ESButton appearance="unstyled"
                                className="data-btn"
                                title={!canAssignSelection
                                    ? "You do not have permission to assign tasks"
                                    : photoActionBlockedByMediaType ? "Only photo files can be assigned" : "Assign the selected photos to a user"}
                                disabled={!canAssignSelection || ids.length === 0 || photoActionBlockedByMediaType}
                                onClick={() => {
                                    if (photoActionBlockedByMediaType) {
                                        message.warning("Only photo files can be assigned.")
                                        return
                                    }
                                    setAssignMediaIds(ids)
                                }}
                            >
                                <ClipboardListIcon size={14} /> Assignment
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
                addDisabled={!currentCollectionId || currentCollectionId === "all"}
                addDisabledTooltip="Before uploading media, please select a collection."
                canAdd={canWriteAudio}
                canEditRecord={(record) => rowCan(record, "edit")}
                canDeleteRecord={(record) => rowCan(record, "delete")}
            />

            <PhotoMediaDrawer
                mode="add"
                open={uploadQueue.drawerOpen}
                files={uploadQueue.queueFiles}
                sites={siteOptions}
                licenses={licenseOptions}
                sensors={sensorOptions}
                userOptions={creatorOptions}
                currentUserId={currentUserId}
                onClose={uploadQueue.reset}
                onAddFiles={() => fileInputRef.current?.click()}
                onRetry={uploadQueue.retryUpload}
                onSave={async (formData) => {
                    const collectionId =
                        currentCollectionId && currentCollectionId !== "all"
                            ? Number(currentCollectionId)
                            : null
                    if (!collectionId) {
                        message.warning("Please select a specific collection before saving.")
                        return
                    }
                    const fileUploadIds = uploadQueue.queueFiles
                        .filter((file) => file.status === "done" && file.file_upload_id)
                        .map((file) => file.file_upload_id!)
                    if (fileUploadIds.length === 0) {
                        message.warning("No completed photos are ready to save.")
                        return
                    }
                    const response = await mediaApi.createMedia({
                        collection_id: collectionId,
                        file_upload_ids: fileUploadIds,
                        media_type: "photo",
                        date_time: (formData.date_time as { format?: (f: string) => string } | undefined)?.format?.("YYYY-MM-DD HH:mm:ss"),
                        date_from_filename: (formData.date_from_filename as boolean) ?? false,
                        site_id: formData.site_id as number | undefined,
                        sensor_id: formData.sensor_id as number | undefined,
                        creator_id: formData.creator_id as number | undefined,
                        license_id: formData.license_id as number | undefined,
                        medium: formData.medium as string | undefined,
                        note: formData.note as string | undefined,
                        doi: formData.doi as string | undefined,
                    }, currentProjectId ? { project_id: Number(currentProjectId) } : undefined)
                    const queueId = response.data?.queue_id
                    message.success("Photo upload submitted. Processing will continue in the background.")
                    uploadQueue.reset()
                    refresh()
                    if (queueId) {
                        void refreshAfterMediaProcessing(queueId)
                    }
                }}
            />

            <PhotoMediaDrawer
                mode="edit"
                open={editMediaId !== null}
                mediaId={editMediaId}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                sites={siteOptions}
                licenses={licenseOptions}
                sensors={sensorOptions}
                userOptions={creatorOptions}
                onClose={() => setEditMediaId(null)}
                onSuccess={refresh}
            />

            <LinkItemToCollectionsDrawer
                open={linkMediaIds.length > 0}
                mediaId={linkMediaIds[0] ?? null}
                mediaIds={linkMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => setLinkMediaIds([])}
                onSuccess={refresh}
            />

            <SetLabelsDrawer
                open={labelMediaIds.length > 0}
                mediaId={labelMediaIds[0] ?? null}
                mediaIds={labelMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => setLabelMediaIds([])}
                onSuccess={refresh}
            />

            <AssignTasksDrawer
                open={assignMediaIds.length > 0}
                mediaId={assignMediaIds[0] ?? null}
                mediaIds={assignMediaIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => setAssignMediaIds([])}
                onSuccess={refresh}
            />
        </>
    )
}
