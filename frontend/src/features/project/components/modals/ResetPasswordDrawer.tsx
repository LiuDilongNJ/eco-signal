/**
 * ResetPasswordDrawer - 重置用户密码的抽屉 (Admin Reset)
 */

import { useState, useEffect } from "react"
import { Form, Input, Button, message, ConfigProvider, Space } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { usersApi } from "../../../../api/endpoints/users"
import { isSuccessfulDrawerResponse } from "./utils/isSuccessfulDrawerResponse"
import "./styles/FormDrawer.css"

interface ResetPasswordDrawerProps {
    open: boolean
    userId: number | null
    onClose: () => void
}

export function ResetPasswordDrawer({ open, userId, onClose }: ResetPasswordDrawerProps) {
    const [form] = Form.useForm()
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loading, setLoading] = useState(false)

    // Reset form when drawer opens or closes
    useEffect(() => {
        if (!open) {
            form.resetFields()
        }
    }, [open, form])

    const handleFinish = async (values: any) => {
        if (!userId) return;

        try {
            setLoading(true)
            const payload = {
                new_password: values.new_password,
            }

            const res = await usersApi.resetUserPassword(userId, payload)
            if (isSuccessfulDrawerResponse(res.code, res.message)) {
                message.success('Password updated successfully')
                form.resetFields()
                onClose()
            } else {
                message.error(res.message || 'Failed to update password')
            }
        } catch (error: any) {
            console.error("Update password error:", error)
            message.error(error?.message || "An error occurred while updating password")
        } finally {
            setLoading(false)
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title="Reset Password"
                placement="right"
                forceRender
                open={open}
                onClose={onClose}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={loading}>Cancel</Button>
                        <Button
                            type="primary"
                            loading={loading}
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
                        requiredMark={renderRequiredMark}
                    >
                        <Form.Item
                            name="new_password"
                            label="New Password"
                            rules={[
                                { required: true, message: "Please enter a new password" },
                                { min: 8, message: "Password must be at least 8 characters long" }
                            ]}
                        >
                            <Input.Password />
                        </Form.Item>

                        <Form.Item
                            name="confirm_password"
                            label="Confirm Password"
                            dependencies={['new_password']}
                            rules={[
                                { required: true, message: "Please confirm your new password" },
                                ({ getFieldValue }) => ({
                                    validator(_, value) {
                                        if (!value || getFieldValue('new_password') === value) {
                                            return Promise.resolve();
                                        }
                                        return Promise.reject(new Error('Passwords do not match!'));
                                    },
                                }),
                            ]}
                        >
                            <Input.Password />
                        </Form.Item>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
