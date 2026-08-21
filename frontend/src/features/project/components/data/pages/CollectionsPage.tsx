import { Button as ESButton } from "@/components/ui"
/**
 * CollectionsPage - Collections 数据页面
 */

import { useState, useCallback, useMemo, useEffect, useRef } from "react"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { FileArchive, Library, PackageOpen } from "lucide-react"
import { collectionsApi } from "../../../../../api/endpoints/collections"
import { usersApi } from "../../../../../api/endpoints/users"
import { AddCollectionDrawer } from "../../modals/AddCollectionDrawer"
import type { CollectionTaxonDraft } from "../../modals/SetTaxonsDrawer"
import {
    ExportBundleDrawer,
    ImportBundleDrawer,
} from "../../modals/CollectionBundleDrawers"
import { message } from "@/components/ui"

import { useProjectStore } from "../../../stores/useProjectStore"
import { useTabStore } from "../../../stores/useTabStore"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

function renderTaxonPills(_value: unknown, record: RowData) {
    const taxons = Array.isArray((record as any).taxons) ? (record as any).taxons : []
    const names = taxons
        .map((taxon: any) => String(taxon?.cached_name ?? taxon?.name ?? taxon?.id ?? "").trim())
        .filter(Boolean)

    if (names.length === 0) return null

    return (
        <span className="collection-taxon-pills collection-taxon-pills--scroll" title={names.join(", ")}>
            {names.map((name: string, index: number) => (
                <span className="collection-taxon-pill" key={`${name}-${index}`} title={name}>
                    {name}
                </span>
            ))}
        </span>
    )
}

const COLUMNS: ColumnDef[] = [
    { key: "collection_id", label: "ID", type: "number", width: "120px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "300px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "200px", sortable: true, filterable: true },
    { key: "sphere", label: "Sphere", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "project_url", label: "External project URL", type: "text", width: "240px", sortable: true, filterable: true },
    { key: "external_media_url", label: "External Media URL", type: "text", width: "260px", sortable: true, filterable: true },
    { key: "doi", label: "DOI", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creation_date", label: "Created", type: "date", width: "240px", sortable: true, filterable: true, filterType: "dateRange" },
    { key: "public_access", label: "Public Access", type: "badge", width: "140px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
    { key: "public_tags", label: "Public Annotations", type: "badge", width: "160px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
    { key: "taxon_name", label: "Taxa", type: "text", width: "360px", sortable: true, filterable: true, renderCell: renderTaxonPills },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text", required: true },
    { key: "description", label: "Description", type: "textarea" },
    { key: "sphere", label: "Sphere", type: "text" },
    { key: "project_url", label: "External project URL", type: "text" },
    { key: "external_media_url", label: "External Media URL", type: "text" },
    { key: "doi", label: "DOI", type: "text" },
    { key: "public_access", label: "Public Access", type: "select", options: ["True", "False"] },
    { key: "public_tags", label: "Public Annotations", type: "select", options: ["True", "False"] },
]

export function CollectionsPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [tableState, setTableState] = useState<TableState | null>(null)

    const [addDrawerOpen, setAddDrawerOpen] = useState(false)
    const [editCollectionId, setEditCollectionId] = useState<number | null>(null)
    const [meIsProjectAdmin, setMeIsProjectAdmin] = useState(false)
    const [importBundleOpen, setImportBundleOpen] = useState(false)
    const [exportBundleOpen, setExportBundleOpen] = useState(false)
    const [exportBundleCollection, setExportBundleCollection] = useState<{
        collection_id: number
        name?: string
    } | null>(null)
    const tableRequestIdRef = useRef(0)
    const currentProjectId = useProjectStore(s => s.currentProjectId)
    const currentCollectionId = useProjectStore(s => s.currentCollectionId)
    const selectCollection = useProjectStore(s => s.selectCollection)
    const setActiveTab = useTabStore(s => s.setActiveTab)
    const collectionOptions = useProjectStore(s => s.collectionOptions)
    const fetchCollectionOptions = useProjectStore((s) => s.fetchCollectionOptions)
    const requestDataMenuRefresh = useProjectStore((s) => s.requestDataMenuRefresh)
    const navFilter = useProjectStore((s) => s.dataPageNavFilters.collection ?? "current")
    const setDataPageNavFilter = useProjectStore((s) => s.setDataPageNavFilter)

    /**
     * 顶栏选「ALL Collections」时 store 里 currentCollectionId 为 ""，无法与 collection_id 比对。
     * 用选项里第一个真实集合 id 作为「当前」标签的参照（与默认加载顺序一致）。
     */
    const highlightCollectionId = useMemo(() => {
        const cid = currentCollectionId
        if (cid !== null && cid !== undefined && String(cid).trim() !== "") {
            return cid
        }
        const firstReal = collectionOptions.find(
            (o: { id?: string | number | null }) =>
                o != null && o.id !== "" && o.id !== undefined && o.id !== null,
        )
        return firstReal?.id ?? null
    }, [currentCollectionId, collectionOptions])

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const projectIdNum =
                    currentProjectId != null && String(currentProjectId).trim() !== ""
                        ? Number(currentProjectId)
                        : NaN
                const res = await usersApi.getMe({
                    ignoreUnauthorized: true,
                    ...(Number.isFinite(projectIdNum) ? { project_id: projectIdNum } : {}),
                })
                if (!cancelled && (res.code === 0 || res.code === 200) && res.data) {
                    setMeIsProjectAdmin(!!res.data.is_project_admin)
                }
            } catch (error) {
                console.error("Failed to fetch current user:", error)
                if (!cancelled) {
                    setMeIsProjectAdmin(false)
                }
            }
        })()
        return () => {
            cancelled = true
        }
    }, [currentProjectId])

    const fetchTableData = useCallback(async (state: TableState) => {
        const requestId = ++tableRequestIdRef.current
        setLoading(true)
        try {
            const params: any = {
                page: state.page,
                page_size: state.pageSize,
                ...state.filters // project_id and collection_id will come through this
            }

            if (state.sortKey) {
                params.order_by = state.sortKey
                params.order_dir = state.sortDir || "asc"
            }

            Object.entries(state.filters).forEach(([k, v]) => {
                if (v !== "" && v !== null && v !== undefined) {
                    if (k === "public_access" || k === "public_tags") {
                        params[k] = String(v).toLowerCase() === "true"
                    } else if (k === "collection_id") {
                        params.collection_id = Number(v)
                    } else if (k === "creation_date") {
                        const [start, end] = String(v).split(",")
                        if (start) params.creation_date_from = start
                        if (end) params.creation_date_to = end
                    } else {
                        params[k] = String(v).trim()
                    }
                } else if (k === "collection_id" || k === "project_id") {
                    // Inherited from DataPageLayout via state.filters spread earlier
                    // if they are undefined or empty, delete them so they don't get sent verbatim
                    delete params[k]
                }
            })

            const res = await collectionsApi.getCollections(params)
            if (requestId !== tableRequestIdRef.current) return
            if (res && res.data) {
                const formattedRows = res.data.map((p: any) => ({
                    ...p,
                    creator_name: p.creator_name || String(p.creator_id || ""),
                    public_access: p.public_access ? "True" : "False",
                    public_tags: p.public_tags ? "True" : "False",
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : (res.data.length || 0))
            }
        } catch (error) {
            console.error("Failed to fetch collections:", error)
        } finally {
            if (requestId === tableRequestIdRef.current) setLoading(false)
        }
    }, [])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleAddSubmit = useCallback(async (values: Record<string, any>, taxons: CollectionTaxonDraft[]) => {
        try {
            setLoading(true)
            const payload = {
                name: values.name,
                description: values.description,
                sphere: values.sphere ?? null,
                external_media_url: values.external_media_url,
                project_url: values.project_url,
                doi: values.doi,
                public_access: Boolean(values.public_access),
                public_tags: Boolean(values.public_tags),
            }

            const isEdit = editCollectionId !== null

            if (!isEdit && !currentProjectId) {
                message.error("Please select a project first")
                setLoading(false)
                return
            }

            const res = isEdit
                ? await collectionsApi.updateCollection(editCollectionId, payload)
                : await collectionsApi.createCollection(payload, Number(currentProjectId!))

            if (res.code === 0 || res.code === 200) {
                const savedCollectionId = isEdit
                    ? editCollectionId
                    : Number(res.data?.collection_id ?? res.data?.id ?? 0) || null
                if (savedCollectionId && currentProjectId && (isEdit || taxons.length > 0)) {
                    const taxaRes = await collectionsApi.setCollectionTaxons(
                        savedCollectionId,
                        currentProjectId,
                        { taxons },
                    )
                    if (taxaRes.code !== 0 && taxaRes.code !== 200) {
                        throw new Error(taxaRes.message || "Failed to update collection taxa")
                    }
                }
                message.success(`Collection ${isEdit ? 'updated' : 'created'} successfully`)
                setAddDrawerOpen(false)
                setEditCollectionId(null)
                if (currentProjectId != null && String(currentProjectId).trim() !== "") {
                    await fetchCollectionOptions(currentProjectId)
                    requestDataMenuRefresh()
                }
                if (tableState) {
                    handleTableChange(tableState)
                }
            } else {
                message.error(res.message || `Failed to ${isEdit ? 'update' : 'create'} collection`)
            }
        } catch (error: any) {
            console.error("Save collection error:", error)
            message.error(error?.message || "An error occurred while saving collection")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange, editCollectionId, currentProjectId, fetchCollectionOptions, requestDataMenuRefresh])

    const handleDeleteSubmit = useCallback(async (selectedKeys: any[]) => {
        try {
            setLoading(true)
            for (const key of selectedKeys) {
                const res = await collectionsApi.deleteCollection(key)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || `Failed to delete collection ${key}`)
                    break;
                }
            }
            message.success("Collection deleted successfully")
            if (currentProjectId != null && String(currentProjectId).trim() !== "") {
                await fetchCollectionOptions(currentProjectId)
                requestDataMenuRefresh()
            }
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (error: any) {
            console.error("Delete collection error:", error)
            message.error(error?.message || "An error occurred while deleting collection")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange, currentProjectId, fetchCollectionOptions, requestDataMenuRefresh])

    const handleExport = useCallback(async () => {
        try {
            setLoading(true)
            const params: any = {}
            if (tableState) {
                if (tableState.sortKey) {
                    params.order_by = tableState.sortKey
                    params.order_dir = tableState.sortDir || "asc"
                }

                Object.entries(tableState.filters).forEach(([k, v]) => {
                    if (v !== "" && v !== null && v !== undefined) {
                        if (k === "public_access" || k === "public_tags") {
                            params[k] = String(v).toLowerCase() === "true"
                        } else if (k === "collection_id") {
                            params.collection_id = Number(v)
                        } else if (k === "creation_date") {
                            const [start, end] = String(v).split(",")
                            if (start) params.creation_date_from = start
                            if (end) params.creation_date_to = end
                        } else {
                            params[k] = String(v).trim()
                        }
                    } else if (k === "collection_id" || k === "project_id") {
                        delete params[k]
                    }
                })
            }

            // Always pass the current project_id if we are filtering by current project
            if (currentProjectId) {
                params.project_id = Number(currentProjectId);
            }

            const download = await collectionsApi.exportCsv(params)
            downloadFile(download)
        } catch (error: any) {
            console.error("Export collections error:", error)
            message.error(error?.message || "An error occurred while exporting collections")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId])

    const refreshAfterBundleImport = useCallback(async () => {
        if (currentProjectId != null && String(currentProjectId).trim() !== "") {
            await fetchCollectionOptions(currentProjectId)
            requestDataMenuRefresh()
        }
        if (tableState) {
            handleTableChange(tableState)
        }
    }, [
        currentProjectId,
        fetchCollectionOptions,
        handleTableChange,
        requestDataMenuRefresh,
        tableState,
    ])

    return (
        <>
            <DataPageLayout
                title="Collections"
                columns={COLUMNS}
                rows={rows}
                formFields={FORM_FIELDS}
                showNavFilter
                defaultNavFilter="current"
                navFilterValue={navFilter}
                onNavFilterChange={(value) => setDataPageNavFilter("collection", value)}
                icon={Library}
                loading={loading}
                serverSide={true}
                totalRows={totalRows}
                rowKey="collection_id"
                currentRowHighlight={{ idField: "collection_id", currentId: highlightCollectionId }}

                onTableStateChange={handleTableChange}
                defaultSortKey="collection_id"
                defaultSortDir="asc"
                addDisabled={!meIsProjectAdmin}
                onViewCustom={(selectedKeys) => {
                    if (selectedKeys.length === 1) {
                        selectCollection(selectedKeys[0] as number)
                        setActiveTab("desc")
                    }
                }}
                onAddCustom={() => {
                    setEditCollectionId(null)
                    setAddDrawerOpen(true)
                }}
                onEditCustom={(selectedKeys) => {
                    if (selectedKeys.length === 1) {
                        setEditCollectionId(selectedKeys[0])
                        setAddDrawerOpen(true)
                    }
                }}
                onDeleteCustom={handleDeleteSubmit}
                deleteConfirmation={{ entityLabel: "collection", nameField: "name" }}
                onExportCustom={handleExport}
                renderAfterExportActions={(selectedRows) => (
                    <ESButton appearance="unstyled"
                        className="data-btn"
                        title="Export Bundle"
                        disabled={
                            selectedRows.size !== 1 ||
                            !currentProjectId ||
                            !meIsProjectAdmin
                        }
                        onClick={() => {
                            const collectionId = Number(Array.from(selectedRows)[0])
                            const selected = rows.find(
                                (row) => Number(row.collection_id) === collectionId,
                            )
                            setExportBundleCollection({
                                collection_id: collectionId,
                                name: selected?.name ? String(selected.name) : undefined,
                            })
                            setExportBundleOpen(true)
                        }}
                    >
                        <FileArchive size={14} /> Export Bundle
                    </ESButton>
                )}
                extraToolbar={
                    <ESButton appearance="unstyled"
                        className="data-btn"
                        title="Import Bundle"
                        disabled={!currentProjectId || !meIsProjectAdmin}
                        onClick={() => setImportBundleOpen(true)}
                    >
                        <PackageOpen size={14} /> Import Bundle
                    </ESButton>
                }

            />
            <AddCollectionDrawer
                open={addDrawerOpen}
                editId={editCollectionId}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => {
                    setAddDrawerOpen(false)
                    setEditCollectionId(null)
                }}
                onSubmit={handleAddSubmit}
            />
            <ImportBundleDrawer
                open={importBundleOpen}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                onClose={() => setImportBundleOpen(false)}
                onImported={refreshAfterBundleImport}
            />
            <ExportBundleDrawer
                open={exportBundleOpen}
                projectId={currentProjectId ? Number(currentProjectId) : null}
                collection={exportBundleCollection}
                onClose={() => setExportBundleOpen(false)}
            />
        </>
    )
}
