/**
 * LinkSiteToCollectionsDrawer - 将站点关联到「项目」和/或「具体集合」。
 * - 勾选项目：同时勾选该项目下全部集合；项目级关联（site_project）覆盖未来新建集合。
 * - 勾选/取消集合：若某项目下全部集合已勾选则勾选项目；若取消任一集合则取消项目勾选。
 * - 取消项目：同时取消该项目下全部集合勾选。
 */

import { useEffect, useState } from "react"
import { Button, ConfigProvider, Space, Checkbox, Collapse, message } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { ChevronDown, Folder } from "lucide-react"

import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { sitesApi } from "../../../../api/endpoints/sites"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/LinkCollectionsDrawer.css"

const { Panel } = Collapse
interface ProjectTreeItem {
    id: number
    name: string
    collections: { id: number; name: string }[]
}

function syncProjectCollectionSelection(
    tree: ProjectTreeItem[],
    collectionIds: number[],
    projectIds: number[],
): { collectionIds: number[]; projectIds: number[] } {
    const collectionSet = new Set(collectionIds)
    const projectSet = new Set(projectIds)

    for (const project of tree) {
        if (project.id <= 0 || project.collections.length === 0) continue
        const collectionIdList = project.collections.map((c) => c.id)
        if (projectSet.has(project.id)) {
            for (const id of collectionIdList) collectionSet.add(id)
            continue
        }
        if (collectionIdList.every((id) => collectionSet.has(id))) {
            projectSet.add(project.id)
        }
    }

    return {
        collectionIds: Array.from(collectionSet),
        projectIds: Array.from(projectSet),
    }
}

interface LinkSiteToCollectionsDrawerProps {
    open: boolean
    siteIds: number[]
    projectId: number | null
    onClose: () => void
    onSuccess?: () => void
}

export function LinkSiteToCollectionsDrawer({
    open,
    siteIds,
    projectId,
    onClose,
    onSuccess,
}: LinkSiteToCollectionsDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [treeData, setTreeData] = useState<ProjectTreeItem[]>([])
    const [selectedCollectionIds, setSelectedCollectionIds] = useState<number[]>([])
    const [selectedProjectIds, setSelectedProjectIds] = useState<number[]>([])
    const [activeKeys, setActiveKeys] = useState<(string | number)[]>([])
    const targetSiteIds = Array.from(new Set(siteIds.filter((siteId) => siteId > 0)))
    const primarySiteId = targetSiteIds[0] ?? null
    const isBatch = targetSiteIds.length > 1

    useEffect(() => {
        if (open && primarySiteId) {
            void fetchData()
        }
    }, [open, primarySiteId, projectId, isBatch])

    const fetchData = async () => {
        if (!primarySiteId || !projectId) return
        setLoading(true)
        try {
            const res = await sitesApi.getLinkOptions(primarySiteId, { project_id: Number(projectId) })
            const r = res as {
                code: number
                data?: {
                    selected_collection_ids?: number[]
                    selected_project_ids?: number[]
                    current_project?: any
                    other_projects?: any[]
                    unassigned_collections?: any[]
                    options?: {
                        current_project?: any
                        other_projects?: any[]
                        unassigned_collections?: any[]
                    }
                }
                message?: string
            }

            if (r.code === 0 || r.code === 200) {
                const data = r.data || {}

                const rawCollectionIds = isBatch ? [] : (data.selected_collection_ids || [])
                const rawProjectIds = isBatch ? [] : (data.selected_project_ids || [])

                const newTreeData: ProjectTreeItem[] = []

                // Determine where options are (nested or flat)
                const options = data.options || data

                const processCollections = (cols: any[]) =>
                    (cols || []).map((c: any) => ({
                        id: (c.collection_id || c.id) as number,
                        name: String(c.name ?? ""),
                    }))

                if (options.current_project) {
                    const cp = options.current_project
                    newTreeData.push({
                        id: cp.project_id || cp.id,
                        name: `Current Project: ${cp.project_name || cp.name}`,
                        collections: processCollections(cp.collections || []),
                    })
                }

                if (options.other_projects) {
                    options.other_projects.forEach((p: any) => {
                        newTreeData.push({
                            id: p.project_id || p.id,
                            name: p.project_name || p.name,
                            collections: processCollections(p.collections || []),
                        })
                    })
                }

                if (options.unassigned_collections && options.unassigned_collections.length > 0) {
                    newTreeData.push({
                        id: -2,
                        name: "Unassigned Collections",
                        collections: processCollections(options.unassigned_collections),
                    })
                }

                const synced = syncProjectCollectionSelection(
                    newTreeData,
                    rawCollectionIds,
                    rawProjectIds,
                )
                setTreeData(newTreeData)
                setSelectedCollectionIds(synced.collectionIds)
                setSelectedProjectIds(synced.projectIds)

                // Only expand items that have something selected
                const keysToExpand = newTreeData
                    .filter((p) => {
                        const isProjChecked = p.id > 0 && synced.projectIds.includes(p.id)
                        const hasSelectedCol = p.collections.some((c) =>
                            synced.collectionIds.includes(c.id),
                        )
                        return (!isBatch && isProjChecked) || hasSelectedCol
                    })
                    .map((p) => p.id)
                setActiveKeys(keysToExpand)
            } else {
                message.error(r.message || "Failed to load link data")
                setTreeData([])
            }
        } catch (error) {
            console.error("Failed to fetch link data:", error)
            message.error("Failed to load link data")
        } finally {
            setLoading(false)
        }
    }

    const toggleCollection = (id: number) => {
        const parentProject = treeData.find(
            (p) => p.id > 0 && p.collections.some((c) => c.id === id),
        )
        const nextCollections = selectedCollectionIds.includes(id)
            ? selectedCollectionIds.filter((i) => i !== id)
            : [...selectedCollectionIds, id]
        setSelectedCollectionIds(nextCollections)

        if (!parentProject) return
        const allChecked = parentProject.collections.every((c) => nextCollections.includes(c.id))
        setSelectedProjectIds((prevProjects) => {
            if (allChecked) {
                return prevProjects.includes(parentProject.id)
                    ? prevProjects
                    : [...prevProjects, parentProject.id]
            }
            return prevProjects.filter((i) => i !== parentProject.id)
        })
    }

    const toggleProject = (projectNumericId: number) => {
        if (projectNumericId < 0) return
        const project = treeData.find((p) => p.id === projectNumericId)
        if (!project) return
        const collectionIds = project.collections.map((c) => c.id)
        const willCheck = !selectedProjectIds.includes(projectNumericId)

        setSelectedProjectIds((prev) =>
            willCheck ? [...prev, projectNumericId] : prev.filter((i) => i !== projectNumericId),
        )
        setSelectedCollectionIds((prev) => {
            if (willCheck) {
                const next = new Set(prev)
                for (const id of collectionIds) next.add(id)
                return Array.from(next)
            }
            return prev.filter((id) => !collectionIds.includes(id))
        })
        if (willCheck) {
            setActiveKeys((prev) =>
                prev.includes(projectNumericId) ? prev : [...prev, projectNumericId],
            )
        }
    }

    const handleSave = async () => {
        if (!primarySiteId || !projectId) return
        setSaving(true)
        try {
            const res = await sitesApi.updateSiteCollections(targetSiteIds, Number(projectId), {
                collection_ids: selectedCollectionIds,
                project_ids: selectedProjectIds,
            })
            if (isSuccessfulDrawerResponse(res.code, res.message)) {
                message.success(isBatch ? `Links updated for ${targetSiteIds.length} sites` : "Links updated")
                onSuccess?.()
                onClose()
            } else {
                message.error(res.message || "Update failed")
            }
        } catch (error) {
            console.error("Save link collections error:", error)
            message.error("Save failed")
        } finally {
            setSaving(false)
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={isBatch ? `Link ${targetSiteIds.length} Sites to Projects & Collections` : "Link Site to Projects & Collections"}
                placement="right"
                open={open}
                onClose={onClose}
                styles={{
                    wrapper: {
                        width: 640,
                    },
                    header: {
                        borderBottom: "none",
                        color: "var(--text-main)",
                    },
                    body: {
                        padding: 0,
                        overflow: "hidden",
                    },
                    mask: { backdropFilter: "blur(4px)" },
                }}
                extra={
                    <Space>
                        <Button onClick={onClose}>Cancel</Button>
                        <Button
                            type="primary"
                            loading={saving}
                            onClick={handleSave}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: "16px" }}>
                        {loading ? (
                            <LoadingState label="Loading collections..." variant="inline" className="link-collections-loading" />
                        ) : (
                            <Collapse
                                ghost
                                expandIcon={({ isActive }) => (
                                    <ChevronDown
                                        size={14}
                                        style={{
                                            transform: isActive ? "rotate(0deg)" : "rotate(-90deg)",
                                            transition: "0.2s",
                                        }}
                                    />
                                )}
                                className="link-collapse"
                                activeKey={activeKeys}
                                onChange={(keys) => setActiveKeys(Array.isArray(keys) ? keys : [keys])}
                            >
                                {treeData.map((project) => {
                                    const hasProjectToggle = project.id > 0
                                    const projectChecked = hasProjectToggle && selectedProjectIds.includes(project.id)

                                    return (
                                        <Panel
                                            header={
                                                <div
                                                    style={{
                                                        display: "flex",
                                                        alignItems: "flex-start",
                                                        gap: 12,
                                                        flexWrap: "wrap",
                                                    }}
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    {hasProjectToggle ? (
                                                        <Checkbox
                                                            checked={projectChecked}
                                                            onChange={() => toggleProject(project.id)}
                                                        />
                                                    ) : (
                                                        <span style={{ width: 16 }} />
                                                    )}
                                                    <Space size={8} style={{ marginLeft: 0 }}>
                                                        <Folder size={16} color="var(--brand)" style={{ opacity: 0.9 }} />
                                                        <span>{project.name}</span>
                                                    </Space>
                                                </div>
                                            }
                                            key={project.id}
                                        >
                                            {project.collections.map((col) => (
                                                <div key={col.id} className="collection-item">
                                                    <Checkbox
                                                        checked={selectedCollectionIds.includes(col.id)}
                                                        onChange={() => toggleCollection(col.id)}
                                                    />
                                                    <span className="collection-name">{col.name}</span>
                                                </div>
                                            ))}
                                        </Panel>
                                    )
                                })}
                            </Collapse>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
