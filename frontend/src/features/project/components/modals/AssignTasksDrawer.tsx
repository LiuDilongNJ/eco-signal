import { useEffect, useMemo, useState } from "react"
import { Button, Checkbox, message, ConfigProvider, Input, Space, Typography } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { tasksApi, type AssignableUserPublic, type BatchTaskAssignmentRequest } from "../../../../api/endpoints/tasks"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import { dispatchTasksChanged } from "../../data/taskEvents"
import "./styles/AssignTasksDrawer.css"

const { Title } = Typography

interface AssignTasksDrawerProps {
    open: boolean
    mediaId: number | null
    mediaIds?: number[]
    projectId?: number | null
    /** 传入则只对这些标注分配 annotation 任务；不传则按 media 分配 media 任务 */
    annotationIds?: number[]
    onClose: () => void
    onSuccess?: () => void
}

export function AssignTasksDrawer({ open, mediaId, mediaIds, projectId, annotationIds, onClose, onSuccess }: AssignTasksDrawerProps) {
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [assignableUsers, setAssignableUsers] = useState<AssignableUserPublic[]>([])
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
    const [comments, setComments] = useState<Record<number, string>>({})
    const targetMediaIds = useMemo(
        () =>
            Array.from(
                new Set(
                    (Array.isArray(mediaIds) && mediaIds.length > 0
                        ? mediaIds
                        : mediaId != null
                            ? [mediaId]
                            : []
                    ).filter((id) => Number.isFinite(id) && id > 0),
                ),
            ),
        [mediaId, mediaIds],
    )
    const isAnnotationMode = annotationIds !== undefined
    const targetAnnotationIds = useMemo(
        () =>
            Array.from(
                new Set(
                    (annotationIds ?? []).filter((id) => Number.isFinite(id) && id > 0),
                ),
            ),
        [annotationIds],
    )

    useEffect(() => {
        if (open && targetMediaIds.length > 0) {
            void fetchData()
        }
        if (!open) {
            setAssignableUsers([])
            setSelectedIds(new Set())
            setComments({})
        }
    }, [open, projectId, targetMediaIds])

    const fetchData = async () => {
        if (!projectId) return
        setLoading(true)
        try {
            setComments({})

            if (targetMediaIds.length === 1) {
                const res = await tasksApi.getAssignableUsers(projectId, targetMediaIds[0]!)
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Failed to fetch users")
                    return
                }
                const users = res.data || []
                setAssignableUsers(users)

                // Pre-select users who already have tasks for this media
                const currentlyAssigned = new Set<number>()
                users.forEach((u) => {
                    if (u.task_count > 0) {
                        currentlyAssigned.add(u.user_id)
                    }
                })
                setSelectedIds(currentlyAssigned)
                return
            }

            const res = await tasksApi.getBatchAssignableUsers(projectId, targetMediaIds)
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to fetch users")
                return
            }
            setAssignableUsers(res.data || [])
            setSelectedIds(new Set())
        } catch (error) {
            console.error(error)
            message.error("Failed to fetch assignable users")
        } finally {
            setLoading(false)
        }
    }

    const handleSave = async () => {
        if (!projectId || targetMediaIds.length === 0 || selectedIds.size === 0) return
        if (isAnnotationMode && targetAnnotationIds.length === 0) {
            message.error("No target annotations to assign.")
            return
        }
        setSaving(true)
        try {
            const assignments = Array.from(selectedIds).map((userId) => ({
                user_id: userId,
                comment: comments[userId] || "",
            }))

            const payload: BatchTaskAssignmentRequest = isAnnotationMode
                ? {
                      type: "annotation",
                      annotation_ids: targetAnnotationIds,
                      assignments,
                  }
                : {
                      type: "media",
                      media_ids: targetMediaIds,
                      assignments,
                  }

            const res = await tasksApi.assignTasksBatch(projectId, payload)
            if (isSuccessfulDrawerResponse(res.code, res.message)) {
                const successMessage = isAnnotationMode
                    ? targetAnnotationIds.length > 1
                        ? `Tasks assigned for ${targetAnnotationIds.length} annotations`
                        : "Tasks assigned successfully"
                    : targetMediaIds.length > 1
                        ? `Tasks assigned for ${targetMediaIds.length} items`
                        : "Tasks assigned successfully"
                message.success(successMessage)
                dispatchTasksChanged(projectId)
                onSuccess?.()
                onClose()
            } else {
                message.error(res.message || "Failed to assign tasks")
            }
        } catch (err) {
            message.error(err instanceof Error && err.message ? err.message : "Failed to assign tasks")
        } finally {
            setSaving(false)
        }
    }

    const drawerTitle = isAnnotationMode
        ? targetAnnotationIds.length > 1
            ? `Assign Tasks (${targetAnnotationIds.length} annotations)`
            : "Assign Tasks"
        : targetMediaIds.length > 1
            ? `Assign Tasks (${targetMediaIds.length} items)`
            : "Assign Tasks"

    const toggleUser = (id: number, checked: boolean) => {
        setSelectedIds(prev => {
            const next = new Set(prev)
            if (checked) {
                next.add(id)
            } else {
                next.delete(id)
            }
            return next
        })
    }

    const handleCommentChange = (id: number, value: string) => {
        setComments(prev => ({ ...prev, [id]: value }))
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={
                    <Title level={4} style={{ margin: 0 }}>
                        {drawerTitle}
                    </Title>
                }
                placement="right"
                open={open}
                onClose={onClose}
                styles={{
                    wrapper: {
                        width: 480,
                    },
                    header: {
                        borderBottom: "none",
                        color: "var(--text-main)",
                    },
                    body: {
                        padding: 0,
                        overflow: "hidden",
                    },
                    mask: {
                        backdropFilter: "blur(4px)",
                    },
                }}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={saving}>
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            loading={saving}
                            disabled={loading || selectedIds.size === 0}
                            onClick={handleSave}
                        >
                            Save
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <div style={{ padding: "24px" }}>
                        {loading ? (
                            <LoadingState label="Loading users..." variant="inline" />
                        ) : (
                            <div className="assign-tasks-content" style={{ background: 'var(--bg-surface-secondary)', borderRadius: '8px', border: `1px solid ${isDark ? 'var(--border-color)' : 'var(--border-color)'}`, overflow: 'hidden' }}>
                                <div className="assign-tasks-list">
                                    {assignableUsers.map((user, index) => {
                                        const isChecked = selectedIds.has(user.user_id)
                                        return (
                                            <div className="assign-tasks-item" key={user.user_id} style={{ 
                                                padding: '12px 16px', 
                                                borderBottom: index < assignableUsers.length - 1 ? `1px dashed ${isDark ? 'var(--border-color)' : 'var(--border-color)'}` : 'none',
                                                background: isChecked ? (isDark ? 'var(--bg-capsule)' : 'var(--bg-surface-secondary)') : 'transparent',
                                            }}>
                                                <Checkbox
                                                    checked={isChecked}
                                                    onChange={(e) => toggleUser(user.user_id, e.target.checked)}
                                                    style={{ fontWeight: 500, color: isDark ? 'var(--text-main)' : 'var(--text-secondary)' }}
                                                >
                                                    {user.name || user.username}
                                                </Checkbox>
                                                
                                                {isChecked && (
                                                    <div className="assign-tasks-note">
                                                        <Input 
                                                            value={comments[user.user_id] || ''}
                                                            onChange={(e) => handleCommentChange(user.user_id, e.target.value)}
                                                            placeholder="Notes"
                                                            maxLength={1000}
                                                            aria-label={`Notes for ${user.name || user.username}`}
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        )
                                    })}
                                    {assignableUsers.length === 0 && (
                                        <EmptyState className="assign-tasks-empty" title="No assignable users found." />
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
