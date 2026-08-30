import { useEffect, useMemo, useState } from "react"
import { Button, Checkbox, message, ConfigProvider, Input, Space, Typography } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { tasksApi } from "../../../../api/endpoints/tasks"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
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
    const [assignableUsers, setAssignableUsers] = useState<any[]>([])
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
    const [comments, setComments] = useState<Record<number, string>>({})
    const targetMediaIds = useMemo(
        () => (
            Array.isArray(mediaIds) && mediaIds.length > 0
                ? mediaIds
                : mediaId != null
                    ? [mediaId]
                    : []
        ).filter((id) => Number.isFinite(id) && id > 0),
        [mediaId, mediaIds],
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
    }, [open, targetMediaIds])

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
                users.forEach(u => {
                    if (u.task_count > 0) {
                        currentlyAssigned.add(u.user_id)
                    }
                })
                setSelectedIds(currentlyAssigned)
                return
            }

            const responses = await Promise.all(targetMediaIds.map((id) => tasksApi.getAssignableUsers(projectId, id)))
            const userMap = new Map<number, any>()

            for (const res of responses) {
                if (res.code !== 0 && res.code !== 200) {
                    message.error(res.message || "Failed to fetch users")
                    return
                }
                for (const user of res.data || []) {
                    if (!userMap.has(user.user_id)) {
                        userMap.set(user.user_id, user)
                    }
                }
            }

            setAssignableUsers(Array.from(userMap.values()))
            setSelectedIds(new Set())
        } catch (error) {
            console.error(error)
            message.error("Failed to fetch assignable users")
        } finally {
            setLoading(false)
        }
    }

    const handleSave = async () => {
        if (targetMediaIds.length === 0) return
        setSaving(true)
        try {
            const assignments = Array.from(selectedIds).map(userId => ({
                user_id: userId,
                comment: comments[userId] || ""
            }))

            const succeededMediaIds: number[] = []
            const skippedMediaIds: number[] = []
            const failedMediaIds: number[] = []

            for (const currentMediaId of targetMediaIds) {
                let payload:
                    | {
                          type: "media"
                          assignments: { user_id: number; comment?: string }[]
                      }
                    | {
                          type: "annotation"
                          annotation_ids: number[]
                          assignments: { user_id: number; comment?: string }[]
                      }

                if (annotationIds !== undefined) {
                    const annotation_ids =
                        targetMediaIds.length === 1
                            ? annotationIds
                            : []

                    if (annotation_ids.length === 0) {
                        skippedMediaIds.push(currentMediaId)
                        continue
                    }

                    payload = {
                        type: "annotation",
                        annotation_ids,
                        assignments,
                    }
                } else {
                    payload = {
                        type: "media",
                        assignments,
                    }
                }

                if (!projectId) {
                    failedMediaIds.push(currentMediaId)
                    continue
                }
                const res = await tasksApi.assignTasks(projectId, currentMediaId, payload)
                if (isSuccessfulDrawerResponse(res.code, res.message)) {
                    succeededMediaIds.push(currentMediaId)
                } else {
                    failedMediaIds.push(currentMediaId)
                }
            }

            if (succeededMediaIds.length === 0 && skippedMediaIds.length > 0 && failedMediaIds.length === 0) {
                message.error("No target annotations to assign.")
                return
            }

            if (failedMediaIds.length === 0) {
                const successMessage = targetMediaIds.length === 1
                    ? "Tasks assigned successfully"
                    : skippedMediaIds.length > 0
                        ? `Tasks assigned for ${succeededMediaIds.length} items, skipped ${skippedMediaIds.length}`
                        : `Tasks assigned for ${succeededMediaIds.length} items`
                message.success(successMessage)
                onSuccess?.()
                onClose()
            } else {
                if (succeededMediaIds.length > 0) {
                    onSuccess?.()
                }
                message.warning(
                    `Assigned ${succeededMediaIds.length} items, skipped ${skippedMediaIds.length}, failed ${failedMediaIds.length}`,
                )
            }
        } catch (err) {
            message.error("Failed to assign tasks")
        } finally {
            setSaving(false)
        }
    }

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
                        {targetMediaIds.length > 1 ? `Assign Tasks (${targetMediaIds.length} items)` : "Assign Tasks"}
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
                            onClick={handleSave}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
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
                                                padding: '16px', 
                                                borderBottom: index < assignableUsers.length - 1 ? `1px dashed ${isDark ? 'var(--border-color)' : 'var(--border-color)'}` : 'none',
                                                background: isChecked ? (isDark ? 'var(--bg-capsule)' : 'var(--bg-surface-secondary)') : 'transparent',
                                                height: '50px'
                                            }}>
                                                <Checkbox
                                                    checked={isChecked}
                                                    onChange={(e) => toggleUser(user.user_id, e.target.checked)}
                                                    style={{ fontWeight: 500, color: isDark ? 'var(--text-main)' : 'var(--text-secondary)' }}
                                                >
                                                    {user.name || user.username}
                                                </Checkbox>
                                                
                                                {isChecked && (
                                                    <div style={{paddingLeft: '24px' }}>
                                                        <Input 
                                                            value={comments[user.user_id] || ''}
                                                            onChange={(e) => handleCommentChange(user.user_id, e.target.value)}
                                                            style={{ 
                                                                borderRadius: '6px',
                                                                borderColor: 'var(--brand)'
                                                            }}
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
