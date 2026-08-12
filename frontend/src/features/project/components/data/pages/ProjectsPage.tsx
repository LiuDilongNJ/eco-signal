import { Button as ESButton } from "@/components/ui"
/**
 * ProjectsPage - Projects 数据页面
 */

import { useState, useCallback, useRef, useEffect } from "react"
import type { Key } from "react"
import { DataPageLayout } from "../DataPageLayout"
import { AddProjectDrawer } from "../../modals/AddProjectDrawer"
import { LinkCollectionsDrawer } from "../../modals/LinkCollectionsDrawer"
import { projectsApi } from "../../../../../api/endpoints/projects"
import { filesApi } from "../../../../../api/endpoints/files"
import { usersApi } from "../../../../../api/endpoints/users"

import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { FolderKanban, Link2 } from "lucide-react"
import { message } from "@/components/ui"
import { useProjectStore } from "../../../stores/useProjectStore"
import { useTabStore } from "../../../stores/useTabStore"
import { downloadFile } from "@/utils/download"
import { useNavigate } from "react-router-dom"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

const COLUMNS: ColumnDef[] = [
    { key: "project_id", label: "ID", type: "number", width: "120px", sortable: true, filterable: true },
    { key: "uuid", label: "UUID", type: "text", width: "300px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "url", label: "URL", type: "text", width: "240px", sortable: true, filterable: true },
    { key: "doi", label: "DOI", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creator_name", label: "Creator", type: "text", width: "140px", sortable: true, filterable: true },
    { key: "creation_date", label: "Created", type: "date", width: "240px", sortable: true, filterable: true, filterType: "dateRange" },
    { key: "public", label: "Public", type: "badge", width: "140px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
    { key: "active", label: "Active", type: "badge", width: "140px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
]

const FORM_FIELDS: FormFieldDef[] = [
    { key: "name", label: "Name", type: "text", required: true },
    { key: "url", label: "URL", type: "text" },
    { key: "doi", label: "DOI", type: "text" },
    { key: "creator_name", label: "Creator", type: "text" },
    { key: "created", label: "Created", type: "date" },
    { key: "public", label: "Public", type: "select", options: ["True", "False"] },
    { key: "active", label: "Active", type: "select", options: ["True", "False"] },
]

export function ProjectsPage() {
    const selectProject = useProjectStore((s) => s.selectProject)
    const currentProjectId = useProjectStore((s) => s.currentProjectId)
    const currentProjectIdRef = useRef(currentProjectId)
    useEffect(() => { currentProjectIdRef.current = currentProjectId }, [currentProjectId])
    const upsertProjectOption = useProjectStore((s) => s.upsertProjectOption)
    const setProjectSearch = useProjectStore((s) => s.setProjectSearch)
    const fetchProjectOptions = useProjectStore((s) => s.fetchProjectOptions)
    const fetchCollectionOptions = useProjectStore((s) => s.fetchCollectionOptions)
    const setActiveTab = useTabStore((s) => s.setActiveTab)
    const navigate = useNavigate()

    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [addDrawerOpen, setAddDrawerOpen] = useState(false)
    const [linkDrawerOpen, setLinkDrawerOpen] = useState(false)
    const [editProjectId, setEditProjectId] = useState<number | null>(null)
    const [linkProjectId, setLinkProjectId] = useState<number | null>(null)
    const [meIsAdmin, setMeIsAdmin] = useState(false)

    const [tableState, setTableState] = useState<TableState | null>(null)
    const navFilter = useProjectStore((s) => s.dataPageNavFilters.project ?? "current")
    const setDataPageNavFilter = useProjectStore((s) => s.setDataPageNavFilter)

    useEffect(() => {
        let cancelled = false
            ; (async () => {
                try {
                    const res = await usersApi.getMe({ ignoreUnauthorized: true })
                    if (!cancelled && (res.code === 0 || res.code === 200) && res.data) {
                        setMeIsAdmin(!!res.data.is_admin)
                    }
                } catch (error) {
                    console.error("Failed to fetch current user:", error)
                }
            })()
        return () => {
            cancelled = true
        }
    }, [])

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
        // Current 模式下，用户手动输入的 project_id 与当前项目不符时，直接展示空结果
        const userFilterPid = state.filters?.project_id
        if (
            state.navFilter === "current" &&
            userFilterPid !== undefined &&
            userFilterPid !== null &&
            String(userFilterPid).trim() !== ""
        ) {
            const currentPid = currentProjectIdRef.current
            if (currentPid != null && String(userFilterPid) !== String(currentPid)) {
                setRows([])
                setTotalRows(0)
                setLoading(false)
                return
            }
        }

        try {
            const params: any = {
                page: state.page,
                page_size: state.pageSize,
            }

            if (state.sortKey) {
                params.order_by = state.sortKey
                params.order_dir = state.sortDir || "asc"
            }

            // Append all column filters
            Object.entries(state.filters).forEach(([k, v]) => {
                if (v !== "" && v !== null && v !== undefined) {
                    if (k === "public" || k === "active") {
                        params[k] = String(v).toLowerCase() === "true"
                    } else if (k === "project_id") {
                        params.project_id = Number(v)
                    } else if (k === "creation_date") {
                        const [start, end] = String(v).split(",")
                        if (start) params.creation_date_from = start
                        if (end) params.creation_date_to = end
                    } else {
                        params[k] = String(v).trim()
                    }
                }
            })

            const res = await projectsApi.getProjects(params)
            if (res && res.data) {
                const formattedRows = res.data.map(p => ({
                    ...p,
                    public: p.public ? "True" : "False",
                    active: p.active ? "True" : "False",
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : 0)
            }
        } catch (error) {
            console.error("Failed to fetch projects:", error)
        } finally {
            setLoading(false)
        }
    }, [])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleAddSubmit = useCallback(async (values: Record<string, any>) => {
        try {
            setLoading(true)
            const payload = {
                name: values.name,
                url: values.url,
                description: values.description,
                description_short: values.description_short,
                doi: values.doi,
                public: Boolean(values.public),
                active: Boolean(values.active),
            }

            const isEdit = editProjectId !== null

            const res = isEdit
                ? await projectsApi.updateProject(editProjectId, payload)
                : await projectsApi.createProject(payload)

            if (res.code === 0 || res.code === 200) {
                if (!isEdit && values.picture_file instanceof File) {
                    try {
                        const uploadResult = await filesApi.uploadProjectPicture(
                            res.data.project_id,
                            values.picture_file,
                        )
                        if (uploadResult.code !== 0 && uploadResult.code !== 200) {
                            message.error(uploadResult.message || "Project created, but picture upload failed")
                        }
                    } catch (uploadError: any) {
                        console.error("Upload project picture error:", uploadError)
                        message.error(uploadError?.message || "Project created, but picture upload failed")
                    }
                }
                message.success(`Project ${isEdit ? 'updated' : 'created'} successfully`)
                setAddDrawerOpen(false)
                setEditProjectId(null)
                void fetchProjectOptions(true)
                // Refresh table
                if (tableState) {
                    handleTableChange(tableState)
                }
            } else {
                message.error(res.message || `Failed to ${isEdit ? 'update' : 'create'} project`)
            }
        } catch (error: any) {
            console.error("Save project error:", error)
            message.error(error?.message || "An error occurred while saving project")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange, editProjectId, fetchProjectOptions])

    const handleDeleteSubmit = useCallback(async (selectedKeys: any[]) => {
        try {
            setLoading(true)

            // For now, assuming only single selection deletion is fully supported by the UI structure. 
            // If bulk delete is possible, this needs to be a Promise.all or a separate bulk delete endpoint.
            for (const key of selectedKeys) {
                const res = await projectsApi.deleteProject(key)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || `Failed to delete project ${key}`)
                    break; // Stop on first error
                }
            }

            message.success("Project deleted successfully")

            void fetchProjectOptions(true)

            // Refresh table
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (error: any) {
            console.error("Delete project error:", error)
            message.error(error?.message || "An error occurred while deleting project")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange, fetchProjectOptions])

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
                        if (k === "public" || k === "active") {
                            params[k] = String(v).toLowerCase() === "true"
                        } else if (k === "project_id") {
                            params.project_id = Number(v)
                        } else if (k === "collection_id") {
                            params.collection_id = Number(v)
                        } else if (k === "creation_date") {
                            const [start, end] = String(v).split(",")
                            if (start) params.creation_date_from = start
                            if (end) params.creation_date_to = end
                        } else {
                            params[k] = String(v).trim()
                        }
                    }
                })
            }
            const download = await projectsApi.exportCsv(params)
            downloadFile(download)
        } catch (error: any) {
            console.error("Export projects error:", error)
            message.error(error?.message || "An error occurred while exporting projects")
        } finally {
            setLoading(false)
        }
    }, [tableState])

    const handleViewProject = useCallback(
        (keys: Key[]) => {
            if (keys.length !== 1) return
            const raw = keys[0]
            const row = rows.find((r) => String(r.project_id) === String(raw))
            const projectId = Number(row?.project_id ?? raw)
            if (!Number.isFinite(projectId)) return
            setProjectSearch("")
            if (row?.name != null) {
                upsertProjectOption({
                    id: projectId,
                    name: String(row.name),
                })
            }
            setActiveTab("desc")
            void selectProject(projectId)
            navigate(`/dashboard/${projectId}?tab=desc`)
        },
        [navigate, rows, selectProject, setActiveTab, setProjectSearch, upsertProjectOption]
    )

    return (
        <>
            <DataPageLayout
                title="Projects"
                columns={COLUMNS}
                rows={rows as RowData[]}
                formFields={FORM_FIELDS}
                showNavFilter={true}
                defaultNavFilter="current"
                navFilterValue={navFilter}
                onNavFilterChange={(value) => setDataPageNavFilter("project", value)}
                icon={FolderKanban}
                loading={loading}
                rowKey="project_id"
                serverSide={true}
                totalRows={totalRows}
                currentRowHighlight={{ idField: "project_id", currentId: loading ? null : currentProjectId }}
                onTableStateChange={handleTableChange}
                defaultSortKey="project_id"
                defaultSortDir="asc"
                onAddCustom={() => {
                    setEditProjectId(null)
                    setAddDrawerOpen(true)
                }}
                onEditCustom={(selectedKeys) => {
                    if (selectedKeys.length === 1) {
                        setEditProjectId(selectedKeys[0])
                        setAddDrawerOpen(true)
                    }
                }}
                onDeleteCustom={handleDeleteSubmit}
                deleteConfirmation={{ entityLabel: "project", nameField: "name" }}
                onExportCustom={handleExport}
                onViewCustom={handleViewProject}
                hideAdd={!meIsAdmin}
                hideDelete={!meIsAdmin}
                renderCustomActions={(selectedRows) => (
                    <>
                        {(
                            <ESButton appearance="unstyled" className="data-btn" title="Link" disabled={selectedRows.size !== 1} onClick={() => {
                                const projectId = Array.from(selectedRows)[0] as number
                                setLinkProjectId(projectId)
                                setLinkDrawerOpen(true)
                            }}>
                                <Link2 size={14} /> Link
                            </ESButton>
                        )}
                    </>
                )}
            />
            <AddProjectDrawer
                open={addDrawerOpen}
                editId={editProjectId}
                onClose={() => {
                    setAddDrawerOpen(false)
                    setEditProjectId(null)
                }}
                onSubmit={handleAddSubmit}
            />
            <LinkCollectionsDrawer
                open={linkDrawerOpen}
                projectId={linkProjectId}
                onClose={() => {
                    setLinkDrawerOpen(false)
                    setLinkProjectId(null)
                }}
                onSuccess={() => {
                    if (linkProjectId != null) {
                        void fetchCollectionOptions(linkProjectId)
                    }
                    void fetchProjectOptions(true)
                    if (tableState) handleTableChange(tableState)
                }}
            />
        </>
    )
}
