import { Input as ESInput } from "@/components/ui"
/**
 * AddUserDrawer - 添加用户抽屉组件
 *
 * 使用 Ant Design Drawer + Form 实现，支持深色/浅色主题切换
 */

import { useEffect, useState } from "react"
import { Form, Input, Switch, Button, ConfigProvider, Space } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { usersApi } from "../../../../api/endpoints/users"
import { validateHexColor, optionalOrcidRule } from "../../../settings/utils/formValidation"
import "./styles/FormDrawer.css"

interface AddUserDrawerProps {
    open: boolean
    editId?: number | null // If provided, drawer operates in edit mode
    onClose: () => void
    onSubmit: (values: Record<string, any>) => void
}

export function AddUserDrawer({ open, editId, onClose, onSubmit }: AddUserDrawerProps) {
    const [form] = Form.useForm()
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loadingData, setLoadingData] = useState(false)
    const colorValue = Form.useWatch("color", form)

    useEffect(() => {
        if (open) {
            form.resetFields()
            if (editId) {
                // Fetch and populate data for edit
                setLoadingData(true)
                usersApi.getUser(editId).then(res => {
                    if (res.code === 0 || res.code === 200) {
                        form.setFieldsValue(res.data)
                    }
                }).catch(err => {
                    console.error("Failed to fetch user details:", err)
                }).finally(() => {
                    setLoadingData(false)
                })
            }
        }
    }, [open, editId, form])

    const handleFinish = (values: Record<string, any>) => {
        onSubmit(values)
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={editId ? "Edit User" : "New User"}
                placement="right"
                open={open}
                onClose={onClose}
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={loadingData}>Cancel</Button>
                        <Button
                            type="primary"
                            loading={loadingData}
                            onClick={() => form.submit()}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            Save
                        </Button>
                    </Space>
                }
                styles={{
                    wrapper: {
                        width: editId ? 800 : 480,
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
                        requiredMark={renderRequiredMark}
                        initialValues={{ active: true, color: "#FFFFFF" }}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        {/* ... (rest of form content) */}
                        <div className="form-drawer-layout">
                            <div className="form-drawer-main-col">
                                {/* In create mode, show username and passwords on the left */}
                                {!editId && (
                                    <>
                                        <Form.Item
                                            name="username"
                                            label="Username"
                                            rules={[
                                                { required: true, message: "Please enter a username" },
                                                { min: 3, max: 20, message: "Username must be 3–20 characters" },
                                            ]}
                                        >
                                            <Input />
                                        </Form.Item>

                                        <Form.Item
                                            name="password"
                                            label="Password"
                                            rules={[
                                                { required: true, message: "Please enter a password" },
                                                { min: 8, max: 128, message: "Password must be 8–128 characters" },
                                            ]}
                                        >
                                            <Input.Password />
                                        </Form.Item>

                                        <Form.Item
                                            name="confirm_password"
                                            label="Confirm Password"
                                            dependencies={['password']}
                                            rules={[
                                                { required: true, message: "Please confirm your password" },
                                                ({ getFieldValue }) => ({
                                                    validator(_, value) {
                                                        if (!value || getFieldValue('password') === value) {
                                                            return Promise.resolve();
                                                        }
                                                        return Promise.reject(new Error('Passwords do not match!'));
                                                    },
                                                }),
                                            ]}
                                        >
                                            <Input.Password />
                                        </Form.Item>
                                    </>
                                )}

                                <Form.Item name="name" label="Name" rules={[{ required: true, message: "Please enter a name" }]}>
                                    <Input />
                                </Form.Item>

                                <Form.Item name="email" label="Email" rules={[{ required: true, type: 'email', message: "Please enter a valid email" }]}>
                                    <Input />
                                </Form.Item>

                                <Form.Item name="orcid" label="ORCID" rules={[optionalOrcidRule()]}>
                                    <Input  maxLength={100} />
                                </Form.Item>

                                <Form.Item
                                    name="color"
                                    label="Color"
                                    rules={[
                                        {
                                            validator: async (_, value) => {
                                                const error = validateHexColor(String(value ?? ""))
                                                if (error) throw new Error(error)
                                            },
                                        },
                                    ]}
                                >
                                    <Input
                                        maxLength={7}
                                        prefix={
                                            <ESInput appearance="unstyled"
                                                type="color"
                                                aria-label="User color"
                                                value={
                                                    typeof colorValue === "string" && /^#[0-9A-Fa-f]{6}$/.test(colorValue)
                                                        ? colorValue
                                                        : "#FFFFFF"
                                                }
                                                onChange={(e) => form.setFieldValue("color", e.target.value.toUpperCase())}
                                                style={{
                                                    width: 32,
                                                    height: 24,
                                                    padding: 0,
                                                    border: "none",
                                                    background: "transparent",
                                                    cursor: "pointer",
                                                }}
                                            />
                                        }
                                    />
                                </Form.Item>

                                <Form.Item
                                    className="form-drawer-switch-row"
                                    label="Active"
                                    colon={false}
                                    required={false}
                                >
                                    <Form.Item name="active" valuePropName="checked" noStyle>
                                        <Switch />
                                    </Form.Item>
                                </Form.Item>
                            </div>

                            {editId && (
                                <div className="form-drawer-side-col">
                                    <Form.Item name="user_id" label="ID" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="username" label="Username" required={false}>
                                        <Input readOnly />
                                    </Form.Item>
                                </div>
                            )}
                        </div>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
