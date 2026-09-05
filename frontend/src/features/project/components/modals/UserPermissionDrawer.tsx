import { Button as ESButton } from "@/components/ui"
import { useState, useEffect, useMemo, useCallback } from "react"
import { Button, Switch, message, ConfigProvider, Tooltip, Space } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { X, Mic, MapPin, ScanLine, ClipboardCheck, Check, ChevronDown, ChevronRight } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { permissionsApi } from "../../../../api/endpoints/permissions"
import type { CollectionPermissionConfig, ProjectPermissionConfig, UserPermissionConfig } from "../../../../api/endpoints/permissions"
import { CustomScrollArea } from "@/components/ui"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/UserPermissionDrawer.css"
interface UserPermissionDrawerProps {
    open: boolean
    userId: number | null
    userIds?: number[]
    onClose: () => void
    onSuccess?: () => void
}

const MODULE_ICONS = [
    { key: "audio", icon: Mic, label: "Audio" },
    { key: "site", icon: MapPin, label: "Site" },
    { key: "annotation", icon: ScanLine, label: "Annotation" },
    { key: "review", icon: ClipboardCheck, label: "Review" },
]

type PermissionAction = "none" | "read" | "write"

const MODULE_KEYS = MODULE_ICONS.map(m => m.key)

export function UserPermissionDrawer({ open, userId, userIds, onClose, onSuccess }: UserPermissionDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [config, setConfig] = useState<UserPermissionConfig | null>(null)
    const [expandedProjects, setExpandedProjects] = useState<number[]>([])
    const targetUserIds = useMemo(
        () => Array.from(new Set((userIds?.length ? userIds : userId != null ? [userId] : [])
            .map((id) => Number(id))
            .filter((id) => Number.isFinite(id) && id > 0))),
        [userId, userIds],
    )
    const primaryUserId = targetUserIds[0] ?? null
    const isBatch = targetUserIds.length > 1

    const projectHasStoredAccess = (project: ProjectPermissionConfig) =>
        project.stored_permissions.length > 0 || project.collections.some(collection => collection.stored_permissions.length > 0)

    const collectionHasStoredAccess = (collection: CollectionPermissionConfig) => collection.stored_permissions.length > 0

    const fetchConfig = useCallback(async (id: number) => {
        setLoading(true)
        try {
            const res = await permissionsApi.getUserPermissionConfig(id)
            if (res.data) {
                const nextConfig = isBatch
                    ? {
                        ...res.data,
                        is_admin: false,
                        projects: res.data.projects.map((project) => ({
                            ...project,
                            stored_permissions: [],
                            effective_permissions: [],
                            collections: project.collections.map((collection) => ({
                                ...collection,
                                stored_permissions: [],
                                effective_permissions: [],
                            })),
                        })),
                    }
                    : res.data
                setConfig(nextConfig)
                // Initialize expanded projects based on explicit or inherited permission rows.
                const expanded = nextConfig.projects
                    .filter(p =>
                        p.effective_permissions.length > 0
                        || p.collections.some(
                            c => c.stored_permissions.length > 0 || c.effective_permissions.length > 0,
                        )
                    )
                    .map(p => p.project_id)
                setExpandedProjects(expanded)
            }
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "Failed to fetch permission config")
        } finally {
            setLoading(false)
        }
    }, [isBatch])

    useEffect(() => {
        if (open && primaryUserId) {
            void fetchConfig(primaryUserId)
        } else if (!open) {
            setConfig(null)
            setExpandedProjects([])
        }
    }, [open, primaryUserId, fetchConfig])

    const handleSave = async () => {
        if (targetUserIds.length === 0 || !config) return
        setSaving(true)
        try {
            const projects = config.projects
                .map(p => {
                    const collections = p.collections
                        .filter(c => c.stored_permissions.length > 0)
                        .map(c => ({
                            project_id: p.project_id,
                            collection_id: c.collection_id,
                            stored_permissions: c.stored_permissions,
                        }))
                    const storedPermissions = p.can_manage_project ? p.stored_permissions : []

                    return {
                        project_id: p.project_id,
                        stored_permissions: storedPermissions,
                        collections,
                    }
                })
                .filter(p => p.stored_permissions.length > 0 || p.collections.length > 0)

            const payload = {
                is_admin: !isBatch && config.can_manage_admin_role ? config.is_admin : undefined,
                projects,
            }
            const failures: string[] = []
            let successCount = 0
            for (const targetUserId of targetUserIds) {
                try {
                    const res = await permissionsApi.syncUserPermissions(targetUserId, payload)
                    if (isSuccessfulDrawerResponse(res.code, res.message)) {
                        successCount += 1
                    } else {
                        failures.push(res.message || `Failed to update user ${targetUserId}`)
                    }
                } catch (error: unknown) {
                    failures.push(error instanceof Error ? error.message : `Failed to update user ${targetUserId}`)
                }
            }

            if (failures.length > 0) {
                if (successCount > 0) onSuccess?.()
                message.error(
                    isBatch
                        ? `${failures.length} of ${targetUserIds.length} users failed to update`
                        : failures[0],
                )
                return
            }

            message.success(isBatch ? `Permissions updated for ${successCount} users` : "Permissions updated successfully")
            onSuccess?.()
            onClose()
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "Failed to sync permissions")
        } finally {
            setSaving(false)
        }
    }

    const toggleProjectExpanded = (projectId: number) => {
        setExpandedProjects(prev =>
            prev.includes(projectId) ? prev.filter(v => v !== projectId) : [...prev, projectId]
        )
    }

    const toggleProjectEnabled = (projectId: number) => {
        if (config?.is_admin) return
        const project = config?.projects.find(p => p.project_id === projectId)
        if (!project) return
        if (!project.can_manage_project) {
            return
        }
        const isEnabled = projectHasStoredAccess(project)
        setConfig(conf => {
            if (!conf) return null
            return {
                ...conf,
                projects: conf.projects.map(p => {
                    if (p.project_id !== projectId) return p
                    if (isEnabled) {
                        return {
                            ...p,
                            stored_permissions: [],
                            collections: p.collections.map(c => ({ ...c, stored_permissions: [] })),
                        }
                    }
                    return p.stored_permissions.length === 0
                        ? { ...p, stored_permissions: ["project:read"] }
                        : p
                }),
            }
        })
        if (!isEnabled) {
            setExpandedProjects(prev => (prev.includes(projectId) ? prev : [...prev, projectId]))
        } else {
            setExpandedProjects(prev => prev.filter(v => v !== projectId))
        }
    }

    const getIconState = (permissions: string[], resource: string): PermissionAction => {
        if (permissions.includes(`${resource}:write`)) return "write"
        if (permissions.includes(`${resource}:read`)) return "read"
        return "none"
    }

    const getProjectIconState = (project: ProjectPermissionConfig, resource: string): PermissionAction => {
        if (project.stored_permissions.includes("project:write")) return "write"
        return getIconState(project.stored_permissions, resource)
    }

    const updateCollectionPerms = (
        perms: string[],
        resource: string,
        inheritedState: PermissionAction,
    ): string[] => {
        const currentStoredState = getIconState(perms, resource)
        const basePerms = perms.filter(p => !p.startsWith(`${resource}:`))

        if (currentStoredState === "write") return basePerms
        if (currentStoredState === "read") return [...basePerms, `${resource}:write`]
        if (inheritedState === "read") return [...basePerms, `${resource}:write`]
        if (inheritedState === "write") return basePerms
        return [...basePerms, `${resource}:read`]
    }

    const toggleIconPerm = (
        scope: "project" | "collection",
        id: number,
        resource: string,
        projectId?: number,
    ) => {
        if (!config || config.is_admin) return
        setConfig(prev => {
            if (!prev) return null
            const newConfig = { ...prev }
            const updatePerms = (perms: string[]): string[] => {
                const currentState = getIconState(perms, resource)
                const basePerms = perms.filter(p => !p.startsWith(`${resource}:`))
                if (currentState === "none") return [...basePerms, `${resource}:read`]
                if (currentState === "read") return [...basePerms, `${resource}:write`]
                return basePerms
            }
            if (scope === "project") {
                newConfig.projects = newConfig.projects.map(p => {
                    if (p.project_id === id && p.can_manage_project) {
                        const nextPerms = updatePerms(p.stored_permissions)
                        return {
                            ...p,
                            stored_permissions: nextPerms,
                        }
                    }
                    return p
                })
            } else {
                newConfig.projects = newConfig.projects.map(p => ({
                    ...p,
                    collections: p.collections.map(c =>
                        c.collection_id === id && p.project_id === projectId && p.can_manage_project
                            ? {
                                ...c,
                                stored_permissions: updateCollectionPerms(
                                    c.stored_permissions,
                                    resource,
                                    getProjectIconState(p, resource),
                                ),
                            }
                            : c
                    )
                }))
            }
            return newConfig
        })
    }

    const toggleCollectionEnabled = (projectId: number, collectionId: number) => {
        if (config?.is_admin) return
        const project = config?.projects.find(p => p.project_id === projectId)
        if (!project?.can_manage_project) return
        const collection = project.collections.find(c => c.collection_id === collectionId)
        if (!collection) return
        const isEnabled = collectionHasStoredAccess(collection)
        setConfig(conf => {
            if (!conf) return null
            return {
                ...conf,
                projects: conf.projects.map(p => p.project_id === projectId ? {
                    ...p,
                    collections: p.collections.map(c => {
                        if (c.collection_id !== collectionId) return c
                        if (isEnabled) return { ...c, stored_permissions: [] }
                        return c.stored_permissions.length === 0
                            ? { ...c, stored_permissions: ["collection:read"] }
                            : c
                    }),
                } : p),
            }
        })
    }

    const toggleRole = (scope: "project" | "collection", id: number, projectId?: number) => {
        if (config?.is_admin) return
        setConfig(prev => {
            if (!prev) return null
            const newConfig = { ...prev }

            if (scope === "project") {
                newConfig.projects = newConfig.projects.map(p => {
                    if (p.project_id === id && p.can_manage_project) {
                        const isFullAdmin = p.stored_permissions.includes("project:write")
                        if (!isFullAdmin) {
                            // Switching TO Manage
                            setExpandedProjects(ex => ex.filter(pid => pid !== id))
                            return {
                                ...p, stored_permissions: ["project:write"],
                            }
                        } else {
                            // Switching TO User should downgrade instead of clearing the whole subtree.
                            return {
                                ...p, stored_permissions: ["project:read"],
                            }
                        }
                    }
                    return p
                })
            } else {
                newConfig.projects = newConfig.projects.map(p => ({
                    ...p,
                    collections: p.collections.map(c => {
                        if (c.collection_id === id && p.project_id === projectId && p.can_manage_project) {
                            const isColFullAdmin = c.stored_permissions.includes("collection:write")
                            if (!isColFullAdmin) {
                                return { ...c, stored_permissions: ["collection:write"] }
                            } else {
                                return { ...c, stored_permissions: ["collection:read"] }
                            }
                        }
                        return c
                    })
                }))
            }
            return newConfig
        })
    }

    const mergePermissionState = (base: string[], incoming: string[]) => {
        const merged = [...base]
        for (const permission of incoming) {
            if (!permission.includes(":")) continue
            const [resource, action] = permission.split(":", 2)
            if (!resource || !action) continue
            const existing = getIconState(merged, resource)
            if (existing === "write") continue
            if (action === "write") {
                const withoutResource = merged.filter(p => !p.startsWith(`${resource}:`))
                merged.splice(0, merged.length, ...withoutResource, `${resource}:write`)
            } else if (action === "read" && existing === "none") {
                merged.push(`${resource}:read`)
            }
        }
        return merged
    }

    const getProjectInheritedPermissions = (project: ProjectPermissionConfig) => {
        if (project.stored_permissions.includes("project:write")) {
            return MODULE_KEYS.map(resource => `${resource}:write`)
        }
        return project.stored_permissions.filter(permission =>
            MODULE_KEYS.some(resource => permission.startsWith(`${resource}:`))
        )
    }

    const getCollectionDisplayPermissions = (
        project: ProjectPermissionConfig,
        collection: CollectionPermissionConfig,
    ) => {
        let displayPermissions = [...collection.stored_permissions]
        displayPermissions = mergePermissionState(displayPermissions, getProjectInheritedPermissions(project))
        if (collection.stored_permissions.includes("collection:write")) {
            displayPermissions = mergePermissionState(
                displayPermissions,
                MODULE_KEYS.map(resource => `${resource}:write`),
            )
        }
        return displayPermissions
    }

    const isInheritedIcon = (
        project: ProjectPermissionConfig,
        collection: CollectionPermissionConfig,
        resource: string,
    ) => {
        const storedState = getIconState(collection.stored_permissions, resource)
        const displayState = getIconState(getCollectionDisplayPermissions(project, collection), resource)
        return displayState !== "none" && storedState === "none"
    }

    const renderIcons = (
        scope: "project" | "collection",
        id: number,
        permissions: string[],
        disabled?: boolean,
        projectId?: number,
        inheritedResources: Set<string> = new Set(),
    ) => {
        return (
            <div className="upd-icons-container">
                {MODULE_ICONS.map(m => {
                    const state = getIconState(permissions, m.key)
                    const inherited = inheritedResources.has(m.key)
                    const emptyColor = isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.15)"
                    const borderColor = state === "none"
                        ? (isDark ? "rgba(255,255,255,0.1)" : "var(--border-light)")
                        : "var(--brand)"
                    const itemColor = state === "write"
                        ? "#fff"
                        : state === "read"
                            ? "var(--brand)"
                            : emptyColor
                    const itemBackground = state === "write" ? "var(--brand)" : "transparent"
                    const stateLabel = state.charAt(0).toUpperCase() + state.slice(1)
                    return (
                        <Tooltip key={m.key} title={`${m.label}: ${inherited ? "Inherited " : ""}${stateLabel}`}>
                            <div
                                className={`upd-icon-item${inherited ? " upd-icon-item--inherited" : ""}`}
                                onClick={(e) => { e.stopPropagation(); if (!disabled) toggleIconPerm(scope, id, m.key, projectId); }}
                                style={{
                                    cursor: config?.is_admin || disabled ? "not-allowed" : "pointer",
                                    color: itemColor,
                                    border: `1px solid ${borderColor}`,
                                    background: itemBackground,
                                    opacity: config?.is_admin || disabled ? 0.6 : inherited ? 0.75 : 1,
                                }}
                            >
                                <m.icon size={18} strokeWidth={state === "none" ? 2 : 2.5} />
                            </div>
                        </Tooltip>
                    )
                })}
            </div>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={
                    <div className="upd-drawer-title-container">
                        <span className="upd-drawer-title-text">
                            {isBatch ? `Permission Configuration (${targetUserIds.length} Users)` : "Permission Configuration"}
                        </span>
                        {!isBatch ? (
                            <div className="upd-drawer-admin-container">
                                <span className="upd-drawer-admin-text">Administrator</span>
                                <Switch
                                    checked={!!config?.is_admin}
                                    disabled={!config?.can_manage_admin_role || saving || loading}
                                    onChange={v => setConfig(p => p ? { ...p, is_admin: v } : null)}
                                    style={{ backgroundColor: config?.is_admin ? "var(--brand)" : undefined }}
                                />
                            </div>
                        ) : null}
                    </div>
                }
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={saving || loading}>
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            loading={saving}
                            disabled={loading}
                            onClick={() => void handleSave()}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
                placement="right"
                onClose={onClose}
                open={open}
                closeIcon={<X size={20} style={{ color: "var(--text-muted)" }} />}
                styles={{
                    wrapper: {
                        width: 800,
                    },
                    header: {
                        padding: "20px 24px",
                        borderBottom: "1px solid var(--border-light)",
                        background: isDark ? "var(--bg-surface)" : undefined,
                        borderBottomColor: isDark ? "var(--border-color)" : undefined,
                        color: "var(--text-main)",
                    },
                    mask: { backdropFilter: "blur(4px)" },
                    body: {
                        padding: 0,
                        overflow: "hidden",
                    },
                }}
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: "0 0 24px 0" }}>
                        {loading ? <LoadingState label="Loading permissions..." variant="inline" className="upd-drawer-loading" /> : (
                            config?.is_admin ? (
                                <div className="upd-drawer-admin-view">
                                    <div className="upd-drawer-admin-icon">
                                        <Check size={24} strokeWidth={3} />
                                    </div>
                                    <div className="upd-drawer-admin-title">Full Administrator Access</div>
                                    <div className="upd-drawer-admin-desc">This user has full administrative privileges across the entire platform.</div>
                                </div>
                            ) : (
                                <div className="upd-drawer-list-container">
                                    {config?.projects.map(project => {
                                        const isFullAdmin = project.stored_permissions.includes("project:write");
                                        const projectChecked = projectHasStoredAccess(project);
                                        const isProjectExpanded = expandedProjects.includes(project.project_id);
                                        const role = isFullAdmin ? 'Manage' : (projectChecked ? 'User' : null);
                                        const canEditProject = project.can_manage_project && !config.is_admin;
                                        const canExpandProject = projectChecked && !isFullAdmin;
                                        return (
                                            <div key={project.project_id} className="upd-card">
                                                <div className="upd-row  upd-project-row">
                                                    <div className="upd-project-info">
                                                        <div
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                if (canEditProject) toggleProjectEnabled(project.project_id)
                                                            }}
                                                            style={{ cursor: canEditProject ? 'pointer' : 'not-allowed' }}
                                                        >
                                                            {projectChecked ? (
                                                                <div className="upd-checkbox-checked"><Check size={12} strokeWidth={4} /></div>
                                                            ) : (
                                                                <div className="upd-checkbox-unchecked" />
                                                            )}
                                                        </div>
                                                        {canExpandProject ? (
                                                            <ESButton appearance="unstyled"
                                                                type="button"
                                                                className="upd-tree-toggle"
                                                                onClick={() => toggleProjectExpanded(project.project_id)}
                                                            >
                                                                {isProjectExpanded ? (
                                                                    <ChevronDown size={16} className="upd-tree-toggle-icon" />
                                                                ) : (
                                                                    <ChevronRight size={16} className="upd-tree-toggle-icon" />
                                                                )}
                                                                <span className="upd-project-name">{project.project_name}</span>
                                                            </ESButton>
                                                        ) : (
                                                            <span className="upd-project-name">{project.project_name}</span>
                                                        )}
                                                    </div>
                                                    <div className="upd-divider" />
                                                    <div className="upd-role-container">
                                                        {role && (
                                                            <span
                                                                className={`upd-badge ${role === "Manage" ? "upd-badge--manager" : "upd-badge--user"}`}
                                                                role="button"
                                                                tabIndex={canEditProject ? 0 : -1}
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    if (canEditProject) toggleRole("project", project.project_id)
                                                                }}
                                                                onKeyDown={(e) => {
                                                                    if (canEditProject && (e.key === "Enter" || e.key === " ")) {
                                                                        e.preventDefault()
                                                                        e.stopPropagation()
                                                                        toggleRole("project", project.project_id)
                                                                    }
                                                                }}
                                                            >
                                                                {role}
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="upd-actions-container">
                                                        {isFullAdmin ? <div className="upd-full-access-text">Full Project Access</div> : renderIcons("project", project.project_id, project.stored_permissions, !canEditProject)}
                                                    </div>
                                                </div>
                                                {canExpandProject && isProjectExpanded && project.collections.map(col => {
                                                    const isColFullAdmin = col.stored_permissions.includes("collection:write");
                                                    const displayPermissions = getCollectionDisplayPermissions(project, col);
                                                    const inheritedResources = new Set(
                                                        MODULE_KEYS.filter(resource => isInheritedIcon(project, col, resource))
                                                    );
                                                    const isUnlocked = collectionHasStoredAccess(col);
                                                    const colRole = isColFullAdmin ? 'Manage' : (isUnlocked ? 'User' : null);
                                                    const canEditCollection = project.can_manage_project && !config.is_admin;
                                                    return (
                                                        <div key={col.collection_id} className="upd-row  upd-collection-row">
                                                            <div className="upd-collection-info">
                                                                <div
                                                                    onClick={(e) => { e.stopPropagation(); if (!isColFullAdmin && canEditCollection) toggleCollectionEnabled(project.project_id, col.collection_id); }}
                                                                    style={{ cursor: isColFullAdmin || !canEditCollection ? 'not-allowed' : 'pointer' }}
                                                                >
                                                                    {isUnlocked ? (
                                                                        <div className="upd-checkbox-checked"><Check size={12} strokeWidth={4} /></div>
                                                                    ) : (
                                                                        <div className="upd-checkbox-unchecked" />
                                                                    )}
                                                                </div>
                                                                <span className="upd-collection-name">{col.collection_name}</span>
                                                            </div>
                                                            <div className="upd-divider" />
                                                            <div className="upd-role-container">
                                                                {colRole && (
                                                                    <span
                                                                        className={`upd-badge ${colRole === "Manage" ? "upd-badge--manager" : "upd-badge--user"}`}
                                                                        role="button"
                                                                        tabIndex={canEditCollection ? 0 : -1}
                                                                        onClick={(e) => {
                                                                            e.stopPropagation()
                                                                            if (canEditCollection) toggleRole("collection", col.collection_id, project.project_id)
                                                                        }}
                                                                        onKeyDown={(e) => {
                                                                            if (canEditCollection && (e.key === "Enter" || e.key === " ")) {
                                                                                e.preventDefault()
                                                                                e.stopPropagation()
                                                                                toggleRole("collection", col.collection_id, project.project_id)
                                                                            }
                                                                        }}
                                                                    >
                                                                        {colRole}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <div className="upd-actions-container">
                                                                {isColFullAdmin ? <div className="upd-full-access-text">Full Collection Access</div> : renderIcons("collection", col.collection_id, displayPermissions, !isUnlocked || !canEditCollection, project.project_id, inheritedResources)}
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        );
                                    })}
                                </div>
                            )
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
