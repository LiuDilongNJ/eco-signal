import { useEffect, useMemo, useState } from "react"
import { Form, Select, Button, ConfigProvider, Space, message } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useProjectStore } from "../../stores/useProjectStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { usersApi } from "../../../../api/endpoints/users"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/FormDrawer.css"

interface SetContributorDrawerProps {
    open: boolean
    userId: number | null
    userIds?: number[]
    initialRole?: string
    projectRoles: string[]
    collectionRoles: string[]
    onClose: () => void
    onSuccess: () => void
}

export function SetContributorDrawer({ 
    open, 
    userId, 
    userIds,
    initialRole,
    projectRoles, 
    collectionRoles, 
    onClose, 
    onSuccess 
}: SetContributorDrawerProps) {
    const [form] = Form.useForm()
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const { currentProjectId, currentCollectionId } = useProjectStore()
    const drawerTheme = useAntdBrandConfig(isDark)
    const [saving, setSaving] = useState(false)
    const targetUserIds = useMemo(
        () => Array.from(new Set((userIds?.length ? userIds : userId != null ? [userId] : [])
            .map((id) => Number(id))
            .filter((id) => Number.isFinite(id) && id > 0))),
        [userId, userIds],
    )
    const isBatch = targetUserIds.length > 1

    useEffect(() => {
        if (open) {
            form.setFieldsValue({
                contribution_role: isBatch ? undefined : initialRole,
            })
        } else {
            form.resetFields()
        }
    }, [open, initialRole, isBatch, form])

    const handleFinish = async (values: { contribution_role: string }) => {
        if (targetUserIds.length === 0 || !currentProjectId) return

        try {
            setSaving(true)
            const payload = {
                project_id: Number(currentProjectId),
                collection_id: currentCollectionId ? Number(currentCollectionId) : undefined,
                contribution_role: values.contribution_role
            }

            const failures: string[] = []
            let successCount = 0
            for (const targetUserId of targetUserIds) {
                try {
                    const res = await usersApi.setContributorRole(targetUserId, payload)
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
                if (successCount > 0) onSuccess()
                message.error(
                    isBatch
                        ? `${failures.length} of ${targetUserIds.length} users failed to update`
                        : failures[0],
                )
                return
            }

            message.success(isBatch ? `Contributor role set for ${successCount} users` : "Contributor role set successfully")
            onSuccess()
            onClose()
        } catch (error: unknown) {
            console.error("Set contributor error:", error)
            message.error(error instanceof Error ? error.message : "An error occurred while setting contributor role")
        } finally {
            setSaving(false)
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={isBatch ? `Set Contributor (${targetUserIds.length} Users)` : "Set User Contributor"}
                placement="right"
                forceRender

                open={open}
                onClose={onClose}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={saving}>Cancel</Button>
                        <Button
                            type="primary"
                            loading={saving}
                            onClick={() => form.submit()}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
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
                        overflow: "hidden",
                    },
                    footer: {
                        background: isDark ? "var(--bg-surface)" : undefined,
                    },
                    mask: {
                        backdropFilter: "blur(4px)",
                    },
                }}
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={handleFinish}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        <Form.Item
                            name="contribution_role"
                            label={`Contribution Role (${currentCollectionId ? 'Collection' : 'Project'})`}
                            rules={[{ required: true, message: "Please select a role" }]}
                        >
                            <Select
                                className="form-drawer-select"
                                classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                options={(currentCollectionId ? collectionRoles : projectRoles).map(r => ({ label: r, value: r }))}
                                allowClear
                            />
                        </Form.Item>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
