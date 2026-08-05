import { Button as ESButton } from "@/components/ui"
/**
 * UsersPage - Users 数据页面
 */

import { useState, useCallback, useEffect, useMemo } from "react"
import { Users, Key } from "lucide-react"
import { message } from "@/components/ui"
import { DataPageLayout } from "../DataPageLayout"
import type { ColumnDef, FormFieldDef, RowData, TableState } from "../DataPageLayout"
import { usersApi } from "../../../../../api/endpoints/users"
import { AddUserDrawer } from "../../modals/AddUserDrawer"
import { ResetPasswordDrawer } from "../../modals/ResetPasswordDrawer"
import { SetContributorDrawer } from "../../modals/SetContributorDrawer"
import { UserPermissionDrawer } from "../../modals/UserPermissionDrawer"


import { UserPlus, Shield } from "lucide-react"
import { useProjectStore } from "../../../stores/useProjectStore"
import { downloadFile } from "@/utils/download"
import { useTableFetchScheduler } from "@/hooks/useTableFetchScheduler"

function normalizeHexColor(raw: unknown): string | null {
    const value = String(raw ?? "").trim()
    return /^#[0-9A-Fa-f]{6}$/.test(value) ? value.toUpperCase() : null
}

const COLUMNS: ColumnDef[] = [
    { key: "user_id", label: "ID", type: "number", width: "120px", sortable: true, filterable: true },
    { key: "username", label: "Username", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "name", label: "Name", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "email", label: "Email", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "orcid", label: "ORCID", type: "text", width: "220px", sortable: true, filterable: true },
    {
        key: "color",
        label: "Color",
        type: "text",
        width: "180px",
        sortable: false,
        filterable: true,
        renderCell: (value) => {
            const hex = normalizeHexColor(value) ?? "#FFFFFF"
            return (
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                    <span
                        aria-hidden
                        style={{
                            width: 14,
                            height: 14,
                            borderRadius: 999,
                            background: hex,
                            border: "1px solid var(--border-color)",
                            boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.18)",
                            flexShrink: 0,
                        }}
                    />
                    <span className="dpl-cell-text" title={hex}>
                        {hex}
                    </span>
                </span>
            )
        },
    },
    { key: "contrib", label: "Project Contrib.", type: "text", width: "220px", sortable: true, filterable: true },
    { key: "active", label: "Active", type: "badge", width: "220px", sortable: true, filterable: true, filterOptions: ["True", "False"] },
]

/** Aligns with backend `UserCreate`: username, name, email, password required; orcid/active optional. */
const FORM_FIELDS: FormFieldDef[] = [
    { key: "username", label: "Username", type: "text", required: true },
    { key: "password", label: "Password", type: "text", required: true },
    { key: "name", label: "Name", type: "text", required: true },
    { key: "email", label: "Email", type: "text", required: true },
    { key: "orcid", label: "ORCID", type: "text" },
    { key: "active", label: "Active", type: "select", options: ["True", "False"] },
]

const PROJECT_CONTRIBUTOR_ROLES = ["PI", "Researcher", "Field Technician", "Data Analyst"]
const COLLECTION_CONTRIBUTOR_ROLES = ["Field Recorder", "Annotator", "Reviewer", "Data Curator"]

export function UsersPage() {
    const [rows, setRows] = useState<RowData[]>([])
    const [totalRows, setTotalRows] = useState(0)
    const [loading, setLoading] = useState(true)
    const [addDrawerOpen, setAddDrawerOpen] = useState(false)
    const [editUserId, setEditUserId] = useState<number | null>(null)
    const [resetPasswordOpen, setResetPasswordOpen] = useState(false)
    const [resetPwdUserId, setResetPwdUserId] = useState<number | null>(null)
    const [contributorDrawerOpen, setContributorDrawerOpen] = useState(false)
    const [contributorUserIds, setContributorUserIds] = useState<number[]>([])
    const [contributorInitialRole, setContributorInitialRole] = useState<string | undefined>(undefined)
    const [permissionDrawerOpen, setPermissionDrawerOpen] = useState(false)
    const [permissionUserIds, setPermissionUserIds] = useState<number[]>([])
    const [currentUserId, setCurrentUserId] = useState<number | null>(null)

    const [tableState, setTableState] = useState<TableState | null>(null)

    const { currentProjectId, currentCollectionId } = useProjectStore()
    const navFilter = useProjectStore((s) => s.dataPageNavFilters.user ?? "current")
    const setDataPageNavFilter = useProjectStore((s) => s.setDataPageNavFilter)
    const scopedCollectionId = useMemo(() => {
        if (currentCollectionId == null || String(currentCollectionId).trim() === "") {
            return null
        }
        const n = Number(currentCollectionId)
        return Number.isFinite(n) ? n : null
    }, [currentCollectionId])

    useEffect(() => {
        let cancelled = false
        ;(async () => {
            try {
                const res = await usersApi.getMe()
                if (cancelled) return
                if ((res.code === 0 || res.code === 200) && res.data?.user_id != null) {
                    setCurrentUserId(res.data.user_id)
                }
            } catch {
                if (!cancelled) setCurrentUserId(null)
            }
        })()
        return () => {
            cancelled = true
        }
    }, [])

    const contribColumnLabel =
        scopedCollectionId != null ? "Collection Contrib." : "Project Contrib."

    const columns = useMemo(() => {
        return COLUMNS.map(c => {
            if (c.key === "contrib") {
                return {
                    ...c,
                    label: contribColumnLabel,
                }
            }
            return c
        })
    }, [contribColumnLabel])

    const fetchTableData = useCallback(async (state: TableState) => {
        setLoading(true)
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
                    if (k === "active") {
                        params[k] = String(v).toLowerCase() === "true"
                    } else if (k === "user_id") {
                        params.user_id = Number(v)
                    } else if (k === "project_id") {
                        params.project_id = Number(v)
                    } else if (k === "collection_id") {
                        params.collection_id = Number(v)
                    } else if (k === "contrib") {
                        params.contrib = String(v)
                    } else {
                        params[k] = String(v)
                    }
                }
            })

            // Determine scope: if project_id or collection_id was added by filters (Current mode)
            // we use current scope. Otherwise use all scope.
            const hasContext = params.project_id != null || params.collection_id != null
            params.scope = hasContext ? "current" : "all"

            if (params.scope === "current" && scopedCollectionId != null && params.collection_id == null) {
                params.collection_id = scopedCollectionId
            }

            // If in "All" mode, we still pass current project as context for the 'contrib' field
            if (params.scope === "all" && currentProjectId) {
                params.project_id = Number(currentProjectId)
                if (scopedCollectionId != null) {
                    params.collection_id = scopedCollectionId
                }
            }

            const res = await usersApi.getUsers(params)
            if (res && res.data) {
                const formattedRows = res.data.map(u => ({
                    ...u,
                    active: u.active ? "True" : "False",
                }))
                setRows(formattedRows as RowData[])
                setTotalRows(res.page_info ? res.page_info.total : 0)
            }
        } catch (error) {
            console.error("Failed to fetch users:", error)
        } finally {
            setLoading(false)
        }
    }, [currentProjectId, scopedCollectionId])

    const scheduleTableFetch = useTableFetchScheduler(fetchTableData)

    const handleTableChange = useCallback((state: TableState) => {
        setTableState(state)
        scheduleTableFetch(state)
    }, [scheduleTableFetch])

    const handleAddSubmit = useCallback(async (values: Record<string, any>) => {
        try {
            setLoading(true)
            const payload = {
                username: values.username,
                password: values.password,
                name: values.name,
                email: values.email,
                orcid: values.orcid,
                color: String(values.color ?? "").trim().toUpperCase() || undefined,
                active: Boolean(values.active),
            }

            const isEdit = editUserId !== null

            if (isEdit) {
                const res = await usersApi.updateUser(editUserId!, payload)
                if (res.code === 0 || res.code === 200) {
                    message.success('User updated successfully')
                    setAddDrawerOpen(false)
                    setEditUserId(null)
                    if (tableState) handleTableChange(tableState)
                } else {
                    message.error(res.message || 'Failed to update user')
                }
            } else {
                if (!currentProjectId) {
                    message.error("Please select a project first")
                    setLoading(false)
                    return
                }

                usersApi.createUser(payload, {
                    project_id: Number(currentProjectId),
                    collection_id: scopedCollectionId ?? undefined,
                }).then(res => {
                    if (res.code === 0 || res.code === 200 || res.code === 201) {
                        message.success('User created successfully')
                        setAddDrawerOpen(false)
                        setEditUserId(null)
                        if (tableState) handleTableChange(tableState)
                    } else {
                        message.error(res.message || 'Failed to create user')
                    }
                }).catch((error: any) => {
                    console.error("Save user error:", error)
                    message.error(error?.message || "An error occurred while saving user")
                }).finally(() => {
                    setLoading(false)
                })
                return // Loading reset handled in promise chain
            }
        } catch (error: any) {
            console.error("Save user error:", error)
            message.error(error?.message || "An error occurred while saving user")
            setLoading(false)
        }
    }, [tableState, handleTableChange, editUserId, currentProjectId, scopedCollectionId])

    const handleDeleteSubmit = useCallback(async (selectedKeys: any[]) => {
        try {
            setLoading(true)
            for (const key of selectedKeys) {
                const res = await usersApi.deleteUser(key)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || `Failed to delete user ${key}`)
                    break
                }
            }
            message.success("User deleted successfully")
            if (tableState) {
                handleTableChange(tableState)
            }
        } catch (error: any) {
            console.error("Delete user error:", error)
            message.error(error?.message || "An error occurred while deleting user")
        } finally {
            setLoading(false)
        }
    }, [tableState, handleTableChange])

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
                        if (k === "active") {
                            params[k] = String(v).toLowerCase() === "true"
                        } else if (k === "user_id") {
                            params.user_id = Number(v)
                        } else if (k === "project_id") {
                            params.project_id = Number(v)
                        } else if (k === "collection_id") {
                            params.collection_id = Number(v)
                        } else if (k === "contrib") {
                            params.contrib = String(v)
                        } else {
                            params[k] = String(v)
                        }
                    }
                })

                const hasContext = params.project_id != null || params.collection_id != null
                params.scope = hasContext ? "current" : "all"
                if (params.scope === "current" && scopedCollectionId != null && params.collection_id == null) {
                    params.collection_id = scopedCollectionId
                }
                if (params.scope === "all" && currentProjectId) {
                    params.project_id = Number(currentProjectId)
                    if (scopedCollectionId != null) params.collection_id = scopedCollectionId
                }
            }
            const download = await usersApi.exportCsv(params)
            downloadFile(download)
        } catch (error: any) {
            console.error("Export users error:", error)
            message.error(error?.message || "An error occurred while exporting users")
        } finally {
            setLoading(false)
        }
    }, [tableState, currentProjectId, scopedCollectionId])

    return (
        <>
            <DataPageLayout
                title="Users"
                columns={columns}
                rows={rows as RowData[]}
                formFields={FORM_FIELDS}
                showNavFilter={true}
                defaultNavFilter="current"
                navFilterValue={navFilter}
                onNavFilterChange={(value) => setDataPageNavFilter("user", value)}
                icon={Users}
                loading={loading}
                rowKey="user_id"
                serverSide={true}
                totalRows={totalRows}
                hideView={true}
                currentRowHighlight={{ idField: "user_id", currentId: currentUserId }}
                onTableStateChange={handleTableChange}
                defaultSortKey="user_id"
                defaultSortDir="asc"
                onAddCustom={() => {
                    setEditUserId(null)
                    setAddDrawerOpen(true)
                }}
                onEditCustom={(selectedKeys) => {
                    if (selectedKeys.length === 1) {
                        setEditUserId(selectedKeys[0])
                        setAddDrawerOpen(true)
                    }
                }}
                onDeleteCustom={handleDeleteSubmit}
                onExportCustom={handleExport}
                renderCustomActions={(selectedRows) => (
                    <>
                        <ESButton appearance="unstyled" className="data-btn" title="Permission" disabled={selectedRows.size === 0} onClick={() => {
                            const userIds = Array.from(selectedRows)
                                .map((id) => Number(id))
                                .filter((id) => Number.isFinite(id) && id > 0)
                            setPermissionUserIds(userIds)
                            setPermissionDrawerOpen(true)
                        }}>
                            <Shield size={14} /> Permission
                        </ESButton>

                        <ESButton appearance="unstyled" className="data-btn" title="Contributor" disabled={selectedRows.size === 0} onClick={() => {
                            const userIds = Array.from(selectedRows)
                                .map((id) => Number(id))
                                .filter((id) => Number.isFinite(id) && id > 0)
                            const userRow = userIds.length === 1
                                ? rows.find(r => Number(r.user_id) === userIds[0])
                                : undefined
                            setContributorUserIds(userIds)
                            setContributorInitialRole(userRow?.contrib as string | undefined)
                            setContributorDrawerOpen(true)
                        }}>
                            <UserPlus size={14} /> Contributor
                        </ESButton>

                        <ESButton appearance="unstyled" className="data-btn" title="Reset Password" disabled={selectedRows.size !== 1} onClick={() => {
                            const userId = Array.from(selectedRows)[0] as number
                            setResetPwdUserId(userId)
                            setResetPasswordOpen(true)
                        }}>
                            <Key size={14} /> Reset Password
                        </ESButton>
                    </>
                )}
            />
            <AddUserDrawer
                open={addDrawerOpen}
                editId={editUserId}
                onClose={() => {
                    setAddDrawerOpen(false)
                    setEditUserId(null)
                }}
                onSubmit={handleAddSubmit}
            />
            <ResetPasswordDrawer
                open={resetPasswordOpen}
                userId={resetPwdUserId}
                onClose={() => {
                    setResetPasswordOpen(false)
                    setResetPwdUserId(null)
                }}
            />

            <SetContributorDrawer
                open={contributorDrawerOpen}
                userId={contributorUserIds[0] ?? null}
                userIds={contributorUserIds}
                initialRole={contributorInitialRole}
                projectRoles={PROJECT_CONTRIBUTOR_ROLES}
                collectionRoles={COLLECTION_CONTRIBUTOR_ROLES}
                onClose={() => {
                    setContributorDrawerOpen(false)
                    setContributorUserIds([])
                    setContributorInitialRole(undefined)
                }}

                onSuccess={() => {
                    if (tableState) handleTableChange(tableState)
                }}
            />
            <UserPermissionDrawer
                open={permissionDrawerOpen}
                userId={permissionUserIds[0] ?? null}
                userIds={permissionUserIds}
                onClose={() => {
                    setPermissionDrawerOpen(false)
                    setPermissionUserIds([])
                }}
                onSuccess={() => {
                    if (tableState) handleTableChange(tableState)
                }}
            />
        </>

    )
}
