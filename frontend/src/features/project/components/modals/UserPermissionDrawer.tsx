import { Button as ESButton } from "@/components/ui"
import { useState, useEffect, useMemo, useCallback } from "react"
import { Button, Switch, message, ConfigProvider, Select, Tooltip, Space } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { X, AudioLines, MapPin, ScanLine, ClipboardCheck, Check, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { permissionsApi } from "../../../../api/endpoints/permissions"
import type { AccessRoleCode, AccessRolePublic, CollectionPermissionConfig, ProjectPermissionConfig, UserPermissionConfig } from "../../../../api/endpoints/permissions"
import { CustomScrollArea } from "@/components/ui"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/UserPermissionDrawer.css"
interface UserPermissionDrawerProps {
    open: boolean
    userId: number | null
    userIds?: number[]
    currentUserId?: number | null
    onClose: () => void
    onSuccess?: () => void
}

const MODULE_ICONS = [
    { key: "media", icon: AudioLines, label: "Media" },
    { key: "site", icon: MapPin, label: "Site" },
    { key: "annotation", icon: ScanLine, label: "Annotation" },
    { key: "review", icon: ClipboardCheck, label: "Review" },
]

type PermissionAction = "none" | "read" | "write"

const MODULE_KEYS = MODULE_ICONS.map(m => m.key)

const DEFAULT_ACCESS_ROLES: AccessRolePublic[] = [
    {
        code: "viewer",
        name: "Viewer",
        kind: "access",
        display_order: 10,
        project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read"],
        collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read"],
    },
    {
        code: "annotator",
        name: "Annotator",
        kind: "access",
        display_order: 20,
        project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "annotation:write_own", "review:read"],
        collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "annotation:write_own", "review:read"],
    },
    {
        code: "reviewer",
        name: "Reviewer",
        kind: "access",
        display_order: 30,
        project_permissions: ["project:read", "media:read", "site:read", "annotation:read", "review:read", "review:write_own", "site:read"],
        collection_permissions: ["collection:read", "media:read", "site:read", "annotation:read", "review:read", "review:write_own", "site:read"],
    },
    {
        code: "manager",
        name: "Manager",
        kind: "access",
        display_order: 40,
        project_permissions: ["project:write"],
        collection_permissions: ["collection:write"],
    },
    {
        code: "custom",
        name: "Custom",
        kind: "access",
        display_order: 50,
        project_permissions: [],
        collection_permissions: [],
    },
]

export function UserPermissionDrawer({ open, userId, userIds, currentUserId, onClose, onSuccess }: UserPermissionDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [config, setConfig] = useState<UserPermissionConfig | null>(null)
    const [accessRoles, setAccessRoles] = useState<AccessRolePublic[]>([])
    const [expandedProjects, setExpandedProjects] = useState<number[]>([])
    const targetUserIds = useMemo(
        () => Array.from(new Set((userIds?.length ? userIds : userId != null ? [userId] : [])
            .map((id) => Number(id))
            .filter((id) => Number.isFinite(id) && id > 0))),
        [userId, userIds],
    )
    const primaryUserId = targetUserIds[0] ?? null
    const isBatch = targetUserIds.length > 1
    const isCurrentAdministratorTarget = !isBatch && primaryUserId === currentUserId && config?.is_admin === true
    const projectRoleOptions = useMemo(() => {
        const roles = accessRoles.length > 0 ? accessRoles : DEFAULT_ACCESS_ROLES
        return roles.map((accessRole) => ({
            value: accessRole.code,
            label: accessRole.name,
            disabled: accessRole.code === "manager" && !config?.can_manage_admin_role,
        }))
    }, [accessRoles, config?.can_manage_admin_role])
    const collectionRoleOptions = useMemo(() => {
        const roles = accessRoles.length > 0 ? accessRoles : DEFAULT_ACCESS_ROLES
        return roles.map((accessRole) => ({
            value: accessRole.code,
            label: accessRole.name,
            disabled: accessRole.code === "manager" && !config?.can_manage_admin_role,
        }))
    }, [accessRoles, config?.can_manage_admin_role])

    const projectHasStoredAccess = (project: ProjectPermissionConfig) =>
        project.assigned_role !== null || project.stored_permissions.length > 0 || project.collections.some(collection => collection.assigned_role !== null || collection.stored_permissions.length > 0)

    const collectionHasStoredAccess = (collection: CollectionPermissionConfig) => collection.assigned_role !== null || collection.stored_permissions.length > 0

    const fetchConfig = useCallback(async (id: number) => {
        setLoading(true)
        try {
            const [res, roles] = await Promise.all([
                permissionsApi.getUserPermissionConfig(id),
                permissionsApi.listAccessRoles(),
            ])
            setAccessRoles(roles.data ?? [])
            if (res.data) {
                const nextConfig = isBatch
                    ? {
                        ...res.data,
                        is_admin: false,
                        projects: res.data.projects.map((project) => ({
                            ...project,
                            stored_permissions: [],
                            assigned_role: null,
                            effective_permissions: [],
                            collections: project.collections.map((collection) => ({
                                ...collection,
                                stored_permissions: [],
                                assigned_role: null,
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
                    const isNamedProjectRole = p.assigned_role !== null && p.assigned_role !== "custom"
                    const collections = isNamedProjectRole
                        ? []
                        : p.collections
                            .filter(c => c.assigned_role !== null || c.stored_permissions.length > 0)
                            .map(c => ({
                                project_id: p.project_id,
                                collection_id: c.collection_id,
                                stored_permissions: c.stored_permissions,
                                role: c.assigned_role,
                            }))
                    const storedPermissions = p.can_manage_project && p.assigned_role === "custom" ? p.stored_permissions : []

                    return {
                        project_id: p.project_id,
                        stored_permissions: storedPermissions,
                        role: p.can_manage_project ? p.assigned_role : null,
                        collections,
                    }
                })
                .filter(p => p.role !== null || p.stored_permissions.length > 0 || p.collections.length > 0)

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
                            stored_permissions: [], assigned_role: null,
                            collections: p.collections.map(c => ({ ...c, stored_permissions: [], assigned_role: null })),
                        }
                    }
                    return p.assigned_role === null
                        ? {
                            ...p,
                            assigned_role: "viewer",
                            stored_permissions: [],
                            collections: p.collections.map(c => ({
                                ...c,
                                assigned_role: "viewer",
                                stored_permissions: [],
                            })),
                        }
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
        if (permissions.includes("project:write") || permissions.includes("collection:write")) return "write"
        if (permissions.includes(`${resource}:write`)) return "write"
        if (permissions.includes(`${resource}:write_own`)) return "write"
        if (permissions.includes(`${resource}:read`)) return "read"
        if (permissions.includes(`${resource}:read_own`)) return "read"
        return "none"
    }

    const getPermissionScopeLabel = (permissions: string[], resource: string) => {
        if (permissions.includes("project:write") || permissions.includes("collection:write")) return "Write all"
        if (permissions.includes(`${resource}:write`)) return "Write all"
        if (permissions.includes(`${resource}:read`) && permissions.includes(`${resource}:write_own`)) return "Read all, write own"
        if (permissions.includes(`${resource}:write_own`)) return "Write own"
        if (permissions.includes(`${resource}:read`)) return "Read all"
        if (permissions.includes(`${resource}:read_own`)) return "Read own"
        return "None"
    }

    const getPermissionScopeMarker = (permissions: string[], resource: string) => {
        if (resource !== "annotation" && resource !== "review") return null
        if (permissions.includes("project:write") || permissions.includes("collection:write")) return { label: "ALL", kind: "all" }
        if (permissions.includes(`${resource}:write`)) return { label: "ALL", kind: "all" }
        if (permissions.includes(`${resource}:read`) && permissions.includes(`${resource}:write_own`)) {
            return { label: "ALL/OWN", kind: "all-own" }
        }
        if (permissions.includes(`${resource}:write_own`) || permissions.includes(`${resource}:read_own`)) {
            return { label: "OWN", kind: "own" }
        }
        if (permissions.includes(`${resource}:read`)) return { label: "ALL", kind: "all" }
        return null
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
                if (resource === "annotation" || resource === "review") {
                    const basePerms = perms.filter(p => !p.startsWith(`${resource}:`))
                    const has = (action: string) => perms.includes(`${resource}:${action}`)
                    if (has("write")) return basePerms
                    if (has("read") && has("write_own")) return [...basePerms, `${resource}:write`]
                    if (has("read")) return [...basePerms, `${resource}:read`, `${resource}:write_own`]
                    if (has("write_own")) return [...basePerms, `${resource}:read`]
                    if (has("read_own")) return [...basePerms, `${resource}:write_own`]
                    return [...basePerms, `${resource}:read_own`]
                }
                const currentState = getIconState(perms, resource)
                const basePerms = perms.filter(p => !p.startsWith(`${resource}:`))
                if (currentState === "none") return [...basePerms, `${resource}:read`]
                if (currentState === "read") return [...basePerms, `${resource}:write`]
                return basePerms
            }
            if (scope === "project") {
                newConfig.projects = newConfig.projects.map(p => {
                    if (p.project_id === id && p.can_manage_project && p.assigned_role === "custom") {
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
                        c.collection_id === id && p.project_id === projectId && c.can_manage_collection && c.assigned_role === "custom"
                            ? {
                                ...c,
                                stored_permissions: resource === "annotation" || resource === "review"
                                    ? updatePerms(c.stored_permissions)
                                    : updateCollectionPerms(
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
        if (!project) return
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
                        if (!c.can_manage_collection) return c
                        if (isEnabled) return { ...c, stored_permissions: [], assigned_role: null }
                        return c.assigned_role === null
                            ? { ...c, assigned_role: "viewer", stored_permissions: [] }
                            : c
                    }),
                } : p),
            }
        })
    }

    const setScopeRole = (
        scope: "project" | "collection", role: AccessRoleCode | null, id: number, projectId?: number,
    ) => {
        if (!config || config.is_admin) return
        setConfig(prev => {
            if (!prev) return null
            if (scope === "project") {
                return {
                    ...prev,
                    projects: prev.projects.map(project => {
                        if (project.project_id !== id || !project.can_manage_project) return project
                        if (role === "custom") {
                            return {
                                ...project,
                                assigned_role: "custom",
                                stored_permissions: [],
                                collections: project.collections.map(col => ({
                                    ...col,
                                    assigned_role: "custom",
                                    stored_permissions: [],
                                })),
                            }
                        }
                        return {
                            ...project,
                            assigned_role: role,
                            stored_permissions: [],
                            collections: project.collections.map(col => ({
                                ...col,
                                assigned_role: role,
                                stored_permissions: [],
                            })),
                        }
                    }),
                }
            }
            return {
                ...prev,
                projects: prev.projects.map(project => {
                    if (project.project_id !== projectId) return project
                    return {
                        ...project,
                        collections: project.collections.map(collection => {
                            if (collection.collection_id !== id || !collection.can_manage_collection) return collection
                            return {
                                ...collection,
                                assigned_role: role,
                                stored_permissions: role === "custom" ? collection.stored_permissions : [],
                            }
                        }),
                    }
                }),
            }
        })
    }

    const mergePermissionState = (base: string[], incoming: string[]) => {
        const merged = [...base]
        for (const permission of incoming) {
            if (!permission.includes(":")) continue
            const [resource, action] = permission.split(":", 2)
            if (!resource || !action) continue
            const withoutResource = merged.filter(p => !p.startsWith(`${resource}:`))
            const actions = new Set(
                merged
                    .filter(p => p.startsWith(`${resource}:`))
                    .map(p => p.slice(resource.length + 1)),
            )

            if (action === "write") {
                actions.clear()
                actions.add("write")
            } else if (!actions.has("write")) {
                if (action === "read") {
                    actions.add("read")
                    actions.delete("read_own")
                } else if (action === "write_own") {
                    actions.add("write_own")
                    actions.delete("read_own")
                } else if (action === "read_own" && !actions.has("read") && !actions.has("write_own")) {
                    actions.add("read_own")
                }
            }

            merged.splice(
                0,
                merged.length,
                ...withoutResource,
                ...[...actions].map((mergedAction) => `${resource}:${mergedAction}`),
            )
        }
        return merged
    }

    const getRolePermissions = useCallback((roleCode: AccessRoleCode | null, scope: "project" | "collection"): string[] => {
        if (!roleCode || roleCode === "custom") return []
        const roleDef = accessRoles.find(r => r.code === roleCode) ?? DEFAULT_ACCESS_ROLES.find(r => r.code === roleCode)
        if (roleDef) {
            return scope === "project" ? roleDef.project_permissions : roleDef.collection_permissions
        }
        return []
    }, [accessRoles])

    const getProjectInheritedPermissions = useCallback((project: ProjectPermissionConfig) => {
        if (project.assigned_role === "manager" || project.stored_permissions.includes("project:write")) {
            return MODULE_KEYS.map(resource => `${resource}:write`)
        }
        if (project.assigned_role && project.assigned_role !== "custom") {
            return getRolePermissions(project.assigned_role, "project").filter(permission =>
                MODULE_KEYS.some(resource => permission.startsWith(`${resource}:`))
            )
        }
        return project.stored_permissions.filter(permission =>
            MODULE_KEYS.some(resource => permission.startsWith(`${resource}:`))
        )
    }, [getRolePermissions])

    const getProjectDisplayPermissions = useCallback((project: ProjectPermissionConfig): string[] => {
        if (project.assigned_role && project.assigned_role !== "custom") {
            return getRolePermissions(project.assigned_role, "project")
        }
        return project.stored_permissions
    }, [getRolePermissions])

    const getCollectionDisplayPermissions = useCallback((
        project: ProjectPermissionConfig,
        collection: CollectionPermissionConfig,
    ): string[] => {
        if (project.assigned_role && project.assigned_role !== "custom") {
            return getRolePermissions(project.assigned_role, "collection")
        }
        if (collection.assigned_role && collection.assigned_role !== "custom") {
            return getRolePermissions(collection.assigned_role, "collection")
        }
        let displayPermissions = [...collection.stored_permissions]
        displayPermissions = mergePermissionState(displayPermissions, getProjectInheritedPermissions(project))
        if (collection.stored_permissions.includes("collection:write")) {
            displayPermissions = mergePermissionState(
                displayPermissions,
                MODULE_KEYS.map(resource => `${resource}:write`),
            )
        }
        return displayPermissions
    }, [getRolePermissions, getProjectInheritedPermissions])

    const isInheritedIcon = (
        project: ProjectPermissionConfig,
        collection: CollectionPermissionConfig,
        resource: string,
    ) => {
        if (project.assigned_role && project.assigned_role !== "custom") {
            return true
        }
        if (collection.assigned_role && collection.assigned_role !== "custom") {
            return false
        }
        const storedState = getIconState(collection.stored_permissions, resource)
        const displayState = getIconState(getCollectionDisplayPermissions(project, collection), resource)
        return displayState !== "none" && storedState === "none"
    }

    const getResourceSignature = (perms: string[], resource: string): string => {
        if (perms.includes("project:write") || perms.includes("collection:write")) {
            return "write"
        }
        const matching = perms.filter(p => p.startsWith(`${resource}:`)).sort().join(",")
        return matching || "none"
    }

    const getDivergentResources = (
        project: ProjectPermissionConfig,
        collection?: CollectionPermissionConfig,
    ): Set<string> => {
        if (project.assigned_role !== "custom") {
            return new Set()
        }
        const projectDisplay = getProjectDisplayPermissions(project)

        if (collection) {
            if (!collectionHasStoredAccess(collection)) return new Set()
            const colDisplay = getCollectionDisplayPermissions(project, collection)
            const divergent = new Set<string>()
            for (const resource of MODULE_KEYS) {
                if (getResourceSignature(colDisplay, resource) !== getResourceSignature(projectDisplay, resource)) {
                    divergent.add(resource)
                }
            }
            return divergent
        }

        const projectDivergent = new Set<string>()
        for (const col of project.collections) {
            if (!collectionHasStoredAccess(col)) continue
            const colDisplay = getCollectionDisplayPermissions(project, col)
            for (const resource of MODULE_KEYS) {
                if (getResourceSignature(colDisplay, resource) !== getResourceSignature(projectDisplay, resource)) {
                    projectDivergent.add(resource)
                }
            }
        }
        return projectDivergent
    }

    const renderIcons = (
        scope: "project" | "collection",
        id: number,
        permissions: string[],
        disabled?: boolean,
        projectId?: number,
        inheritedResources: Set<string> = new Set(),
        divergentResources: Set<string> = new Set(),
    ) => {
        return (
            <div className="upd-icons-container">
                {MODULE_ICONS.map(m => {
                    const state = getIconState(permissions, m.key)
                    const inherited = inheritedResources.has(m.key)
                    const divergent = divergentResources.has(m.key)
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
                    const stateLabel = getPermissionScopeLabel(permissions, m.key)
                    const scopeMarker = getPermissionScopeMarker(permissions, m.key)
                    const tooltipPrefix = divergent ? "[Customized] " : inherited ? "[Inherited] " : ""
                    const moduleLabel = m.key === "media" ? "Media (Audios, Photos)" : m.label
                    return (
                        <Tooltip key={m.key} title={`${tooltipPrefix}${moduleLabel}: ${stateLabel}`}>
                            <div
                                className={`upd-icon-item${state === "write" ? " upd-icon-item--write" : ""}${inherited ? " upd-icon-item--inherited" : ""}${divergent ? " upd-icon-item--divergent" : ""}${scopeMarker ? ` upd-icon-item--scope-${scopeMarker.kind}` : ""}`}
                                onClick={(e) => { e.stopPropagation(); if (!disabled) toggleIconPerm(scope, id, m.key, projectId); }}
                                style={{
                                    cursor: config?.is_admin || disabled ? "not-allowed" : "pointer",
                                    color: itemColor,
                                    border: `1px solid ${borderColor}`,
                                    background: itemBackground,
                                    opacity: config?.is_admin || disabled ? 0.6 : inherited ? 0.75 : 1,
                                }}
                            >
                                {divergent && <span className="upd-icon-divergence-marker" aria-hidden="true">C</span>}
                                <m.icon size={18} strokeWidth={state === "none" ? 2 : 2.5} />
                                {scopeMarker && <span className="upd-icon-scope-marker" aria-hidden="true">{scopeMarker.label}</span>}
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
                                <Tooltip title={isCurrentAdministratorTarget ? "Administrators cannot revoke their own administrator role" : undefined}>
                                    <span>
                                        <Switch
                                            checked={!!config?.is_admin}
                                            disabled={!config?.can_manage_admin_role || isCurrentAdministratorTarget || saving || loading}
                                            onChange={v => setConfig(p => p ? { ...p, is_admin: v } : null)}
                                            style={{ backgroundColor: config?.is_admin ? "var(--brand)" : undefined }}
                                        />
                                    </span>
                                </Tooltip>
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
                                        const isProjectNamedRole = project.assigned_role !== null && project.assigned_role !== "custom";
                                        const projectChecked = projectHasStoredAccess(project);
                                        const isProjectExpanded = expandedProjects.includes(project.project_id);
                                        const role = project.assigned_role;
                                        const canEditProject = project.can_manage_project && !config.is_admin;
                                        const canExpandProject = projectChecked && project.collections.length > 0;
                                        const projectDisplayPermissions = getProjectDisplayPermissions(project);
                                        const projectDivergentResources = getDivergentResources(project);
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
                                                        {projectChecked && (
                                                            <>
                                                                <Select
                                                                    className="upd-role-select"
                                                                    classNames={{ popup: { root: "upd-role-select-popup" } }}
                                                                    aria-label={`Project role for ${project.project_name}`}
                                                                    disabled={!canEditProject}
                                                                    allowClear={false}
                                                                    placeholder="Custom"
                                                                    value={role ?? undefined}
                                                                    options={projectRoleOptions}
                                                                    onChange={(value) => setScopeRole("project", (value ?? null) as AccessRoleCode | null, project.project_id)}
                                                                />
                                                                {role === "custom" && (
                                                                    <Tooltip title="Some permission combinations may not be useful">
                                                                        <span className="upd-role-warning" aria-label="Custom role warning">
                                                                            <AlertTriangle size={15} className="upd-role-warning-icon" />
                                                                        </span>
                                                                    </Tooltip>
                                                                )}
                                                            </>
                                                        )}
                                                    </div>
                                                    <div className="upd-actions-container">
                                                        {renderIcons(
                                                            "project",
                                                            project.project_id,
                                                            projectDisplayPermissions,
                                                            !canEditProject || role !== "custom",
                                                            undefined,
                                                            undefined,
                                                            projectDivergentResources,
                                                        )}
                                                    </div>
                                                </div>
                                                {canExpandProject && isProjectExpanded && project.collections.map(col => {
                                                    const isColUnlocked = isProjectNamedRole || collectionHasStoredAccess(col);
                                                    const effectiveColRole = isProjectNamedRole ? project.assigned_role : col.assigned_role;
                                                    const displayPermissions = getCollectionDisplayPermissions(project, col);
                                                    const inheritedResources = new Set(
                                                        MODULE_KEYS.filter(resource => isInheritedIcon(project, col, resource))
                                                    );
                                                    const collectionDivergentResources = getDivergentResources(project, col);
                                                    const canEditCollection = col.can_manage_collection && !config.is_admin;
                                                    return (
                                                        <div key={col.collection_id} className="upd-row  upd-collection-row">
                                                            <div className="upd-collection-info">
                                                                <div
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        if (!isProjectNamedRole && canEditCollection) {
                                                                            toggleCollectionEnabled(project.project_id, col.collection_id);
                                                                        }
                                                                    }}
                                                                    style={{ cursor: isProjectNamedRole || !canEditCollection ? 'not-allowed' : 'pointer' }}
                                                                >
                                                                    {isColUnlocked ? (
                                                                        <div className={`upd-checkbox-checked${isProjectNamedRole ? " upd-checkbox--disabled" : ""}`}>
                                                                            <Check size={12} strokeWidth={4} />
                                                                        </div>
                                                                    ) : (
                                                                        <div className="upd-checkbox-unchecked" />
                                                                    )}
                                                                </div>
                                                                <span className="upd-collection-name">{col.collection_name}</span>
                                                            </div>
                                                            <div className="upd-divider" />
                                                            <div className="upd-role-container">
                                                                {isColUnlocked && (
                                                                    <>
                                                                        {isProjectNamedRole ? (
                                                                            <Tooltip title="Inherited from project setting">
                                                                                <span>
                                                                                    <Select
                                                                                        className="upd-role-select"
                                                                                        classNames={{ popup: { root: "upd-role-select-popup" } }}
                                                                                        aria-label={`Collection role for ${col.collection_name}`}
                                                                                        disabled={true}
                                                                                        value={effectiveColRole ?? undefined}
                                                                                        options={collectionRoleOptions}
                                                                                    />
                                                                                </span>
                                                                            </Tooltip>
                                                                        ) : (
                                                                            <>
                                                                                <Select
                                                                                    className="upd-role-select"
                                                                                    classNames={{ popup: { root: "upd-role-select-popup" } }}
                                                                                    aria-label={`Collection role for ${col.collection_name}`}
                                                                                    disabled={!canEditCollection}
                                                                                    value={col.assigned_role ?? undefined}
                                                                                    options={collectionRoleOptions}
                                                                                    onChange={(value) => setScopeRole("collection", (value || null) as AccessRoleCode | null, col.collection_id, project.project_id)}
                                                                                />
                                                                                {col.assigned_role === "custom" && (
                                                                                    <Tooltip title="Some permission combinations may not be useful">
                                                                                        <span className="upd-role-warning" aria-label="Custom role warning">
                                                                                            <AlertTriangle size={15} className="upd-role-warning-icon" />
                                                                                        </span>
                                                                                    </Tooltip>
                                                                                )}
                                                                            </>
                                                                        )}
                                                                    </>
                                                                )}
                                                            </div>
                                                            <div className="upd-actions-container">
                                                                {renderIcons(
                                                                    "collection",
                                                                    col.collection_id,
                                                                    displayPermissions,
                                                                    isProjectNamedRole || !isColUnlocked || !canEditCollection || col.assigned_role !== "custom",
                                                                    project.project_id,
                                                                    inheritedResources,
                                                                    collectionDivergentResources,
                                                                )}
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
