/**
 * LinkItemToCollectionsDrawer - 关联媒体到集合抽屉组件
 */

import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react"
import { Button, ConfigProvider, Space, Checkbox, Collapse, message } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { ChevronDown, Folder } from "lucide-react"

import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { mediaApi } from "../../../../api/endpoints/media"
import "./styles/LinkCollectionsDrawer.css"

const { Panel } = Collapse

interface ProjectTreeItem {
    id: number
    name: string
    collections: {
        id: number
        name: string
    }[]
}

interface LinkItemToCollectionsDrawerProps {
    open: boolean
    mediaId: number | null
    mediaIds?: number[]
    projectId: number | null
    onClose: () => void
    onSuccess?: () => void
}

export function LinkItemToCollectionsDrawer({ open, mediaId, mediaIds, projectId, onClose, onSuccess }: LinkItemToCollectionsDrawerProps) {
    const scrollbarInset = 8
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const antdAppTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [treeData, setTreeData] = useState<ProjectTreeItem[]>([])
    const [selectedIds, setSelectedIds] = useState<number[]>([])
    const [activeKeys, setActiveKeys] = useState<(string | number)[]>([])
    const scrollBodyRef = useRef<HTMLDivElement | null>(null)
    const scrollContentRef = useRef<HTMLDivElement | null>(null)
    const scrollTrackRef = useRef<HTMLDivElement | null>(null)
    const thumbDragRef = useRef<{
        pointerId: number
        startClientY: number
        startScrollTop: number
        maxScroll: number
        maxOffset: number
    } | null>(null)
    const [measuredContentHeight, setMeasuredContentHeight] = useState<number | null>(null)
    const [scrollThumb, setScrollThumb] = useState({ visible: false, height: 0, offset: 0 })
    const [isDraggingThumb, setIsDraggingThumb] = useState(false)
    const targetMediaIds = Array.from(
        new Set(
            (mediaIds?.length ? mediaIds : mediaId != null ? [mediaId] : [])
                .map((id) => Number(id))
                .filter((id) => Number.isFinite(id) && id > 0),
        ),
    )
    const primaryMediaId = targetMediaIds[0] ?? null
    const isBatch = targetMediaIds.length > 1

    // 获取数据
    useEffect(() => {
        if (open && primaryMediaId) {
            fetchData()
        }
    }, [open, primaryMediaId, projectId, isBatch])

    const fetchData = async () => {
        if (!primaryMediaId || !projectId) return
        if (isBatch) {
            setSelectedIds([])
        }
        setLoading(true)
        try {
            const res = await mediaApi.getCollectionLinkOptions(primaryMediaId, { project_id: projectId })

            if (res.code === 0 || res.code === 200) {
                const data = res.data
                const newTreeData: ProjectTreeItem[] = []
                const initialSelectedIds: number[] = []

                const processCollections = (cols: any[]) => {
                    return (cols || []).map((c: any) => {
                        if (c.selected) {
                            initialSelectedIds.push(c.collection_id)
                        }
                        return { id: c.collection_id, name: c.name }
                    })
                }

                if (data.current_project) {
                    newTreeData.push({
                        id: data.current_project.project_id || -1,
                        name: `Current Project: ${data.current_project.project_name}`,
                        collections: processCollections(data.current_project.collections)
                    })
                }

                if (data.other_projects) {
                    data.other_projects.forEach((p: any) => {
                        newTreeData.push({
                            id: p.project_id,
                            name: p.project_name,
                            collections: processCollections(p.collections)
                        })
                    })
                }

                if (data.unassigned_collections && data.unassigned_collections.length > 0) {
                    newTreeData.push({
                        id: -2,
                        name: "Unassigned Collections",
                        collections: processCollections(data.unassigned_collections)
                    })
                }

                const nextSelectedIds = isBatch ? [] : Array.from(new Set(initialSelectedIds))

                setTreeData(newTreeData)
                setSelectedIds(nextSelectedIds)
                setActiveKeys(
                    newTreeData
                        .filter((p) => p.collections.some((c) => nextSelectedIds.includes(c.id)))
                        .map((p) => p.id),
                )
            } else {
                message.error(res.message || "Failed to fetch link data")
            }
        } catch (error) {
            console.error("Failed to fetch link data:", error)
            message.error("Failed to fetch link data")
        } finally {
            setLoading(false)
        }
    }

    const handleToggleCollection = (id: number) => {
        setSelectedIds(prev =>
            prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
        )
    }

    const handleSave = async () => {
        if (targetMediaIds.length === 0 || !projectId) return
        setSaving(true)
        try {
            const res = await mediaApi.updateMediaCollectionLinks(targetMediaIds, projectId, selectedIds)
            const failed = Array.isArray(res.data?.failed) ? res.data.failed : []
            if (failed.length === 0) {
                message.success(
                    isBatch
                        ? `Links updated for ${targetMediaIds.length} items`
                        : res.message || "Links updated successfully",
                )
                if (onSuccess) onSuccess()
                onClose()
            } else {
                message.error(
                    isBatch
                        ? `${failed.length} of ${targetMediaIds.length} items failed to update`
                        : failed[0]?.message || "Update failed",
                )
            }
        } catch (error) {
            console.error("Save link collections error:", error)
            message.error("Update failed")
        } finally {
            setSaving(false)
        }
    }

    const updateScrollTopFromTrackOffset = (nextOffset: number) => {
        const bodyNode = scrollBodyRef.current
        const trackNode = scrollTrackRef.current
        if (!bodyNode || !trackNode) return

        const trackHeight = trackNode.clientHeight
        const maxOffset = Math.max(0, trackHeight - scrollThumb.height)
        const clampedOffset = Math.max(0, Math.min(nextOffset, maxOffset))
        const maxScroll = Math.max(0, bodyNode.scrollHeight - bodyNode.clientHeight)
        const nextScrollTop = maxOffset > 0 ? (clampedOffset / maxOffset) * maxScroll : 0
        bodyNode.scrollTop = nextScrollTop
    }

    const handleThumbPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (event.button !== 0) return
        const bodyNode = scrollBodyRef.current
        const trackNode = scrollTrackRef.current
        if (!bodyNode || !trackNode || !scrollThumb.visible) return

        const maxScroll = Math.max(0, bodyNode.scrollHeight - bodyNode.clientHeight)
        const maxOffset = Math.max(0, trackNode.clientHeight - scrollThumb.height)

        thumbDragRef.current = {
            pointerId: event.pointerId,
            startClientY: event.clientY,
            startScrollTop: bodyNode.scrollTop,
            maxScroll,
            maxOffset,
        }
        setIsDraggingThumb(true)
        event.preventDefault()
        event.stopPropagation()
        event.currentTarget.setPointerCapture(event.pointerId)
    }

    const handleThumbPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
        const dragState = thumbDragRef.current
        const bodyNode = scrollBodyRef.current
        if (!dragState || !bodyNode || event.pointerId !== dragState.pointerId) return

        const deltaY = event.clientY - dragState.startClientY
        const ratio = dragState.maxOffset > 0 ? dragState.maxScroll / dragState.maxOffset : 0
        bodyNode.scrollTop = dragState.startScrollTop + deltaY * ratio
    }

    const finishThumbDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
        const dragState = thumbDragRef.current
        if (!dragState || event.pointerId !== dragState.pointerId) return
        thumbDragRef.current = null
        setIsDraggingThumb(false)
        try {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId)
            }
        } catch {
            /* ignore */
        }
    }

    const handleTrackPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
        if (event.target !== event.currentTarget) return
        const trackNode = scrollTrackRef.current
        if (!trackNode || !scrollThumb.visible) return

        const rect = trackNode.getBoundingClientRect()
        const nextOffset = event.clientY - rect.top - scrollThumb.height / 2
        updateScrollTopFromTrackOffset(nextOffset)
    }

    useLayoutEffect(() => {
        if (!open) {
            setMeasuredContentHeight(null)
            setScrollThumb({ visible: false, height: 0, offset: 0 })
            return
        }

        const bodyNode = scrollBodyRef.current
        const contentNode = scrollContentRef.current
        if (!bodyNode || !contentNode) return

        const measure = () => {
            const nextHeight = Math.ceil(contentNode.scrollHeight)
            setMeasuredContentHeight((prev) => (prev === nextHeight ? prev : nextHeight))

            const clientHeight = bodyNode.clientHeight
            const scrollHeight = bodyNode.scrollHeight
            const scrollTop = bodyNode.scrollTop
            const canScroll = scrollHeight > clientHeight + 1 && clientHeight > 0

            if (!canScroll) {
                setScrollThumb((prev) =>
                    prev.visible ? { visible: false, height: 0, offset: 0 } : prev,
                )
                return
            }

            const trackHeight = Math.max(0, clientHeight - scrollbarInset * 2)
            const thumbHeight = Math.max(36, Math.round((clientHeight / scrollHeight) * trackHeight))
            const maxOffset = Math.max(0, trackHeight - thumbHeight)
            const maxScroll = Math.max(1, scrollHeight - clientHeight)
            const thumbOffset = Math.round((scrollTop / maxScroll) * maxOffset)

            setScrollThumb((prev) => {
                if (prev.visible && prev.height === thumbHeight && prev.offset === thumbOffset) {
                    return prev
                }
                return { visible: true, height: thumbHeight, offset: thumbOffset }
            })
        }

        measure()

        const ro = new ResizeObserver(() => {
            requestAnimationFrame(measure)
        })

        ro.observe(bodyNode)
        ro.observe(contentNode)
        Array.from(contentNode.querySelectorAll(".ant-collapse-content, .ant-collapse-content-box")).forEach((el) => {
            ro.observe(el)
        })

        const mo = new MutationObserver(() => {
            requestAnimationFrame(measure)
        })

        mo.observe(contentNode, {
            childList: true,
            subtree: true,
            attributes: true,
        })

        bodyNode.addEventListener("scroll", measure, { passive: true })

        const timers = [
            window.setTimeout(measure, 0),
            window.setTimeout(measure, 120),
            window.setTimeout(measure, 240),
            window.setTimeout(measure, 360),
        ]

        return () => {
            ro.disconnect()
            mo.disconnect()
            bodyNode.removeEventListener("scroll", measure)
            timers.forEach((timer) => window.clearTimeout(timer))
        }
    }, [open, loading, treeData.length, activeKeys.join(","), scrollbarInset])

    return (
        <ConfigProvider theme={antdAppTheme}>
            <FormDrawer
                rootClassName="link-collections-drawer"
                maskClosable={false}
                closable={false}
                title={<span>{isBatch ? `Link ${targetMediaIds.length} Items to Collections` : "Link Item to Collections"}</span>}
                placement="right"
                open={open}
                onClose={onClose}
                styles={{
                    wrapper: {
                        width: 480,
                    },
                    header: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                        borderBottomColor: isDark ? "var(--border-color)" : undefined,
                        color: "var(--text-main)",
                    },
                    body: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                        padding: 0,
                        overflowY: "scroll",
                        overflowX: "hidden",
                        scrollbarGutter: "stable",
                    },
                    mask: {
                        backdropFilter: "blur(4px)",
                    },
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
                <div className="link-collections-scroll-shell">
                    <div ref={scrollBodyRef} className="link-collections-scroll-body">
                        <div
                            ref={scrollContentRef}
                            className="link-collections-scroll-content"
                            style={measuredContentHeight ? { minHeight: measuredContentHeight } : undefined}
                        >
                            {loading ? (
                                <LoadingState label="Loading collections..." variant="inline" className="link-collections-loading" />
                            ) : (
                                <Collapse
                                    ghost
                                    expandIcon={({ isActive }) => <ChevronDown size={14} style={{ transform: isActive ? "rotate(0deg)" : "rotate(-90deg)", transition: "0.2s" }} />}
                                    className="link-collapse"
                                    activeKey={activeKeys}
                                    onChange={(keys) => setActiveKeys(Array.isArray(keys) ? keys : [keys])}
                                >
                                    {treeData.map(project => (
                                        <Panel
                                            header={
                                                <Space size={8}>
                                                    <Folder size={16} color={antdAppTheme.token?.colorPrimary as string} fill={`${antdAppTheme.token?.colorPrimary}44`} />
                                                    <span>{project.name}</span>
                                                </Space>
                                            }
                                            key={project.id}
                                        >
                                            {project.collections.map(col => (
                                                <div key={col.id} className="collection-item">
                                                    <Checkbox
                                                        checked={selectedIds.includes(col.id)}
                                                        onChange={() => handleToggleCollection(col.id)}
                                                    />
                                                    <span className="collection-name">{col.name}</span>
                                                </div>
                                            ))}
                                        </Panel>
                                    ))}
                                </Collapse>
                            )}
                        </div>
                    </div>
                    {scrollThumb.visible ? (
                        <div
                            ref={scrollTrackRef}
                            className={`link-collections-scrollbar-track${isDraggingThumb ? " is-active" : ""}`}
                            aria-hidden
                            onPointerDown={handleTrackPointerDown}
                        >
                            <div
                                className={`link-collections-scrollbar-thumb${isDraggingThumb ? " is-dragging" : ""}`}
                                style={{
                                    height: scrollThumb.height,
                                    transform: `translateY(${scrollThumb.offset}px)`,
                                }}
                                onPointerDown={handleThumbPointerDown}
                                onPointerMove={handleThumbPointerMove}
                                onPointerUp={finishThumbDrag}
                                onPointerCancel={finishThumbDrag}
                                onLostPointerCapture={() => {
                                    thumbDragRef.current = null
                                    setIsDraggingThumb(false)
                                }}
                            />
                        </div>
                    ) : null}
                </div>
            </FormDrawer>
        </ConfigProvider>
    )
}
