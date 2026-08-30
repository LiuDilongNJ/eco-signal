import { Button as ESButton } from "@/components/ui"
/**
 * SitesPage - Sites 数据页面
 */

import { useState, useCallback } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { message } from "@/components/ui"
import { sitesApi, type SiteCreatePayload, type SiteUpdatePayload } from "../../../../../api/endpoints/sites"
import { useProjectStore } from "../../../stores/useProjectStore"
import { SiteFormDrawer } from "../../modals/SiteFormDrawer"
import { LinkSiteToCollectionsDrawer } from "../../modals/LinkSiteToCollectionsDrawer"
import { MapPin, Link as LinkIcon } from "lucide-react"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"
import { usePermissions } from "@/hooks/usePermissions"
import { rowCan, selectionCan } from "../rowCapabilities"

const COLUMNS: ColumnDef[] = [
    { key: "site_id", label: "ID", type: "number", width: "80px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "300px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "latitude", label: "Latitude", type: "number", width: "150px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "longitude", label: "Longitude", type: "number", width: "150px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "topography_m", label: "Topography (m)", type: "number", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "freshwater_depth_m", label: "Water Depth (m)", type: "number", width: "180px", sortable: true, filterable: true, filterType: "numberRange" },
    { key: "gadm0", label: "GADM0", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "gadm1", label: "GADM1", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "gadm2", label: "GADM2", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "iho", label: "IHO", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "realm_name", label: "Realm", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "biome_name", label: "Biome", type: "text", width: "160px", sortable: true, filterable: true },
    { key: "functional_type_name", label: "Functional Type", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creation_date", label: "Created", type: "date", width: "160px", sortable: true, filterable: true, filterType: "dateRange" },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text", required: true },
    { key: "latitude", label: "Latitude", type: "number" },
    { key: "longitude", label: "Longitude", type: "number" },
    { key: "topography_m", label: "Topography (m)", type: "number" },
    { key: "freshwater_depth_m", label: "Water Depth (m)", type: "number" },
    { key: "gadm0_gid", label: "GADM0", type: "select" },
    { key: "gadm1_gid", label: "GADM1", type: "select" },
    { key: "gadm2_gid", label: "GADM2", type: "select" },
    { key: "iho_id", label: "IHO", type: "select" },
    { key: "realm_id", label: "Realm", type: "select" },
    { key: "biome_id", label: "Biome", type: "select" },
    { key: "functional_type_id", label: "Functional Type", type: "select" },
]

function buildSiteListParams(
    state: TableState,
    scope: { projectId?: string | number | null; collectionId?: string | number | null },
): Record<string, unknown> {
    const params: Record<string, unknown> = {
        page: state.page,
        page_size: state.pageSize,
    }

    const sortKey = state.sortKey
    if (sortKey) {
        params.order_by = sortKey
        params.order_dir = state.sortDir || "asc"
    }

    for (const [key, rawValue] of Object.entries(state.filters)) {
        if (rawValue === "" || rawValue == null) continue
        const value = String(rawValue).trim()
        if (!value) continue

        if (key === "site_id") {
            params.site_id = Number(rawValue)
        } else if (key === "creation_date") {
            const [start, end] = value.split(",")
            if (start) params.creation_date_from = start
            if (end) params.creation_date_to = end
        } else if (key === "gadm0" || key === "gadm1" || key === "gadm2") {
            params[key] = value
        } else if (key === "iho" || key === "iho_id") {
            const ihoId = Number(value)
            if (Number.isFinite(ihoId) && String(ihoId) === value) {
                params.iho_id = ihoId
            } else {
                params.iho = value
            }
        } else if (key === "realm_name" || key === "realm" || key === "realm_id") {
            const realmId = Number(value)
            if (Number.isFinite(realmId) && String(realmId) === value) {
                params.realm_id = realmId
            } else {
                params.realm_name = value
            }
        } else if (key === "biome_name" || key === "biome" || key === "biome_id") {
            const biomeId = Number(value)
            if (Number.isFinite(biomeId) && String(biomeId) === value) {
                params.biome_id = biomeId
            } else {
                params.biome_name = value
            }
        } else if (key === "functional_type_name" || key === "functional_type" || key === "functional_type_id") {
            const functionalTypeId = Number(value)
            if (Number.isFinite(functionalTypeId) && String(functionalTypeId) === value) {
                params.functional_type_id = functionalTypeId
            } else {
                params.functional_type_name = value
            }
        } else if (key !== "project_id" && key !== "collection_id") {
            params[key] = value
        }
    }

    if (scope.projectId != null && String(scope.projectId).trim() !== "") {
        params.project_id = Number(scope.projectId)
    }
    if (
        scope.collectionId != null &&
        String(scope.collectionId).trim() !== "" &&
        scope.collectionId !== "all"
    ) {
        params.collection_id = Number(scope.collectionId)
    }

    return params
}

export function SitesPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const [modalOpen, setModalOpen] = useState(false)
    const [modalMode, setModalMode] = useState<"add" | "edit">("add")
    const [editData, setEditData] = useState<Record<string, string | number | boolean>>({})
    const [editId, setEditId] = useState<number | null>(null)
    const [modalSubmitting, setModalSubmitting] = useState(false)

    const [linkDrawerOpen, setLinkDrawerOpen] = useState(false)
    const [linkSiteIds, setLinkSiteIds] = useState<number[]>([])

    const currentProjectId = useProjectStore(s => s.currentProjectId)
    const currentCollectionId = useProjectStore(s => s.currentCollectionId)
    const { can } = usePermissions(currentProjectId, currentCollectionId)
    const canWriteSite = can("site:write")

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        try {
            const params = buildSiteListParams(state, {
                projectId: currentProjectId,
                collectionId: currentCollectionId,
            })

            const res = await sitesApi.getList(params)
            if (res && res.data) {
                const formattedRows = res.data.map((p: any) => ({
                    ...p,
                    creator_name: p.creator_name ?? String(p.creator_id ?? ""),
                    realm_name: p.realm_name ?? "",
                    biome_name: p.biome_name ?? "",
                    functional_type_name: p.functional_type_name ?? "",
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data.length || 0))
            }
        } catch (error) {
            console.error("Failed to fetch sites:", error)
            message.error("Failed to load sites")
        } finally {
            setLoading(false)
        }
    }, [currentProjectId, currentCollectionId])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleAdd = () => {
        setModalMode("add")
        setEditData({})
        setEditId(null)
        setModalOpen(true)
    }

    const handleEdit = async (selectedRowKeys: any[]) => {
        if (selectedRowKeys.length === 1) {
            const id = selectedRowKeys[0] as number
            try {
                const res = await sitesApi.getSite(id, currentProjectId ? Number(currentProjectId) : undefined)
                if (res && res.data) {
                    setModalMode("edit")
                    setEditId(id)
                    setEditData(res.data)
                    setModalOpen(true)
                }
            } catch (err: any) {
                console.error("Failed to fetch site details", err)
                message.error("Failed to load site details")
            }
        } else {
            message.warning("Please select exactly one site to edit")
        }
    }

    const handleDelete = async (selectedRowKeys: any[]) => {
        const hideLoading = message.loading(`Deleting ${selectedRowKeys.length} records...`, 0)
        try {
            for (const id of selectedRowKeys) {
                await sitesApi.deleteSite(id as number)
            }
            message.success(`Successfully deleted ${selectedRowKeys.length} records`)
            if (tableState) handleTableChange(tableState)
        } catch (err: any) {
            console.error('[deleteSite] failed:', err)
            message.error(err.message || 'Failed to delete records')

        } finally {
            hideLoading()
        }
    }

    const handleSubmit = async (data: Record<string, string | number | boolean>) => {
        setModalSubmitting(true)
        try {
            const pickNum = (v: unknown): number | undefined => {
                if (v === null || v === undefined || v === "") return undefined
                if (typeof v === "object" && v !== null && "value" in v) {
                    return pickNum((v as { value: unknown }).value)
                }
                const n = Number(v)
                return Number.isFinite(n) ? n : undefined
            }
            const pickStr = (v: unknown): string | undefined => {
                if (v === null || v === undefined || v === "") return undefined
                const s = String(v).trim()
                return s === "" ? undefined : s
            }
            /** GADM Select uses labelInValue → { value, label } */
            const pickGadmGid = (v: unknown): string | undefined => {
                if (v === null || v === undefined || v === "") return undefined
                if (typeof v === "object" && v !== null && "value" in v) {
                    return pickStr((v as { value: unknown }).value)
                }
                return pickStr(v)
            }

            const core: SiteUpdatePayload = {
                name: String(data.name ?? "").trim(),
                longitude: pickNum(data.longitude),
                latitude: pickNum(data.latitude),
                topography_m: pickNum(data.topography_m),
                freshwater_depth_m: pickNum(data.freshwater_depth_m),
                realm_id: pickNum(data.realm_id),
                biome_id: pickNum(data.biome_id),
                functional_type_id: pickNum(data.functional_type_id),
                iho_id: pickNum(data.iho_id),
                gadm0_gid: pickGadmGid(data.gadm0_gid),
                gadm1_gid: pickGadmGid(data.gadm1_gid),
                gadm2_gid: pickGadmGid(data.gadm2_gid),
            }

            if (modalMode === "add") {
                const createPayload: SiteCreatePayload = {
                    ...core,
                    project_id: currentProjectId ? Number(currentProjectId) : undefined,
                    collection_id:
                        currentCollectionId && currentCollectionId !== "all"
                            ? Number(currentCollectionId)
                            : undefined,
                }
                const payload = Object.fromEntries(
                    Object.entries(createPayload).filter(([, v]) => v !== undefined)
                ) as SiteCreatePayload
                await sitesApi.createSite(payload)
                message.success('Site created successfully')
            } else if (editId) {
                const payload = Object.fromEntries(
                    Object.entries(core).map(([k, v]) => [k, v === undefined ? null : v])
                ) as SiteUpdatePayload
                await sitesApi.updateSite(editId, payload, currentProjectId ? Number(currentProjectId) : undefined)
                message.success('Site updated successfully')
            }
            setModalOpen(false)
            if (tableState) handleTableChange(tableState)
        } catch (err: any) {
            console.error('[submitSite] failed:', err)
            message.error(err.message || 'Failed to submit data')

        } finally {
            setModalSubmitting(false)
        }
    }

    const handleExport = async () => {
        if (!tableState) {
            message.warning("Table data is not yet loaded.")
            return
        }
        const hideLoading = message.loading('Exporting sites...', 0)
        try {
            const params = buildSiteListParams(tableState, {
                projectId: currentProjectId,
                collectionId: currentCollectionId,
            })

            const download = await sitesApi.exportCsv(params)
            downloadFile(download)
            message.success('Export successful')
        } catch (err: any) {
            console.error('[exportSites] failed:', err)
            message.error(err.message || 'Failed to export sites')
        } finally {
            hideLoading()
        }
    }

    return (
        <>
            <DataPageLayout
                title="Sites"
                importConfig={{
                    endpoint: "/v1/sites/imports",
                    resourceKey: "sites",
                    addLabel: "Add Site",
                    fields: { project_id: currentProjectId, collection_id: currentCollectionId },
                    disabled: !canWriteSite || !currentProjectId || !currentCollectionId || currentCollectionId === "all",
                    disabledReason: canWriteSite
                        ? "Select a project and collection before importing sites"
                        : "You do not have permission to import sites",
                }}
                icon={MapPin}
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="site_id"
                onTableStateChange={handleTableChange}
                defaultSortKey="site_id"
                defaultSortDir="asc"
                onAddCustom={handleAdd}
                onEditCustom={handleEdit}
                onDeleteCustom={handleDelete}
                onExportCustom={handleExport}
                hideView={true}
                canAdd={canWriteSite}
                canEditRecord={(record) => rowCan(record, "edit")}
                canDeleteRecord={(record) => rowCan(record, "delete")}
                renderCustomActions={(selectedRows) => (
                    <>
                        <ESButton
                            appearance="unstyled"
                            className="data-btn"
                            title={selectionCan(selectedRows, rows, "site_id", "link")
                                ? "Link the selected sites to collections"
                                : "You do not have permission to link sites"}
                            disabled={!selectionCan(selectedRows, rows, "site_id", "link")}
                            onClick={() => {
                                setLinkSiteIds(Array.from(selectedRows) as number[])
                                setLinkDrawerOpen(true)
                            }}
                        >
                            <LinkIcon size={14} /> Link
                        </ESButton>
                    </>
                )}
            />

            {modalOpen ? (
                <SiteFormDrawer
                    key={modalMode === "edit" ? `edit-${editId ?? "none"}` : "add"}
                    open={modalOpen}
                    mode={modalMode}
                    fields={FORM_FIELDS}
                    initialData={editData}
                    onClose={() => setModalOpen(false)}
                    onSubmit={handleSubmit}
                    submitting={modalSubmitting}
                />
            ) : null}

            <LinkSiteToCollectionsDrawer
                open={linkDrawerOpen}
                siteIds={linkSiteIds}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => {
                    setLinkDrawerOpen(false)
                    setLinkSiteIds([])
                }}
                onSuccess={() => {
                    if (tableState) handleTableChange(tableState)
                }}
            />
        </>
    )
}
