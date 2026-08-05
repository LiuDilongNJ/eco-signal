/**
 * AddProjectDrawer - 添加项目抽屉组件
 *
 * 使用 Ant Design Drawer + Form 实现，支持深色/浅色主题切换
 */

import { useEffect, useState } from "react"
import { Form, Input, Switch, Button, ConfigProvider, Space, UploadField } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { Upload as UploadIcon } from "lucide-react"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { EditorModal } from "./EditorModal"
import { CustomScrollArea } from "@/components/ui"
import { filesApi } from "../../../../api/endpoints/files"
import { projectsApi } from "../../../../api/endpoints/projects"
import { parseRichText } from "@/utils/string"
import { httpUrlRule } from "../../utils/urlValidation"
import "./styles/FormDrawer.css"

interface AddProjectDrawerProps {
    open: boolean
    editId?: number | null // If provided, drawer operates in edit mode
    onClose: () => void
    onSubmit: (values: Record<string, any>) => void
}

const RichTextInput = ({ value, onChange, title }: any) => {

    const [editorOpen, setEditorOpen] = useState(false)

    // Strip HTML tags for preview in Input
    const getPreviewText = (html: any) => {
        if (!html) return ""
        const decoded = parseRichText(html)
        return decoded.replace(/<[^>]*>?/gm, '').replace(/&nbsp;/g, ' ')
    }

    return (
        <>
            <Input
                value={getPreviewText(value)}
                readOnly
                onClick={() => setEditorOpen(true)}
                style={{ cursor: "pointer" }}
            />
            {editorOpen && (
                <EditorModal
                    open={editorOpen}
                    onClose={() => setEditorOpen(false)}
                    title={title || "Edit"}
                    initialContent={value || ""}
                    imageUploadCategory="projects"
                    onSave={(html) => {
                        if (onChange) onChange(html)
                        setEditorOpen(false)
                    }}
                />
            )}
        </>
    )
}

export function AddProjectDrawer({ open, editId, onClose, onSubmit }: AddProjectDrawerProps) {
    const [form] = Form.useForm()
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const [loadingData, setLoadingData] = useState(false)
    const drawerTheme = useAntdBrandConfig(isDark)

    useEffect(() => {
        if (open) {
            form.resetFields()
            if (editId) {
                // Fetch and populate data for edit
                setLoadingData(true)
                projectsApi.getProject(editId).then(res => {
                    if (res.code === 0 || res.code === 200) {
                        const data = res.data
                        form.setFieldsValue({
                            ...data,
                            // Convert picture_id (string) to fileList array format expected by Antd Upload
                            picture_id: data.picture_id ? [
                                {
                                    uid: '-1',
                                    name: data.picture_id,
                                    status: 'done',
                                    url: `/sounds/projects/${data.picture_id}`, // Construct preview url assuming this is the path format
                                    response: { filename: data.picture_id }
                                }
                            ] : undefined
                        })
                    }
                }).catch(err => {
                    console.error("Failed to fetch project details:", err)
                }).finally(() => {
                    setLoadingData(false)
                })
            }
        }
    }, [open, editId, form])

    const handleFinish = (values: Record<string, any>) => {
        // Format DatePicker value to ISO string
        if (values.creation_date && typeof values.creation_date.toISOString === 'function') {
            values.creation_date = values.creation_date.toISOString()
        }

        // Extract filename for picture_id
        if (values.picture_id && values.picture_id.length > 0) {
            const file = values.picture_id[0]
            values.picture_id = file.response?.filename || file.name
        } else {
            values.picture_id = undefined
        }

        onSubmit(values)
    }

    const normFile = (e: any) => {
        if (Array.isArray(e)) {
            return e
        }
        return e?.fileList
    }

    const customUpload = async (options: any) => {
        const { file, onSuccess, onError, onProgress } = options
        try {
            // Optional: fake progress for UX
            onProgress({ percent: 50 })

            const res = await filesApi.uploadImage("projects", file as File)

            if (res.code === 0 || res.code === 200) {
                onProgress({ percent: 100 })
                onSuccess(res.data)

                // Form.Item "valuePropName" is "fileList", we need to update the file in the "fileList" to indicate it's complete
                const currentFiles = form.getFieldValue("picture_id") || []

                // Generate a local preview URL from the file object to ensure it is immediately visible
                const previewUrl = URL.createObjectURL(file as unknown as Blob)

                const updatedFiles = currentFiles.map((f: any) => {
                    if (f.uid === file.uid) {
                        return { ...f, status: 'done', url: previewUrl, response: res.data }
                    }
                    return f
                })
                form.setFieldValue("picture_id", updatedFiles)
            } else {
                onError(new Error(res.message || "Upload failed"))
            }
        } catch (error) {
            console.error("Upload error:", error)
            onError(error)
        }
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={editId ? "Edit Project" : "New Project"}
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
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={handleFinish}
                        requiredMark={renderRequiredMark}
                        initialValues={{ public: false, active: true }}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        <div className="form-drawer-layout">
                            <div className="form-drawer-main-col">
                                <Form.Item name="name" label="Name" rules={[{ required: true, message: "Please enter a project name" }]}>
                                    <Input />
                                </Form.Item>

                                <Form.Item
                                    name="url"
                                    label="URL"
                                    rules={[httpUrlRule("URL")]}
                                >
                                    <Input type="text" inputMode="url" autoComplete="off" />
                                </Form.Item>

                                <Form.Item name="doi" label="DOI">
                                    <Input />
                                </Form.Item>

                                <Form.Item name="description_short" label="Short Description">
                                    <RichTextInput title="Edit Short Description" />
                                </Form.Item>

                                <Form.Item name="description" label="Description">
                                    <RichTextInput title="Edit Description" />
                                </Form.Item>

                                <Form.Item
                                    className="form-drawer-inline-row"
                                    label="Picture"
                                >
                                    <Form.Item
                                        name="picture_id"
                                        valuePropName="fileList"
                                        getValueFromEvent={normFile}
                                        noStyle
                                    >
                                        <UploadField
                                            name="file"
                                            customRequest={customUpload}
                                            maxCount={1}
                                            accept="image/*"
                                            className="form-drawer-picture-upload"
                                        >
                                            <Button
                                                className="form-drawer-picture-upload-btn"
                                                icon={<UploadIcon size={16} />}
                                            >
                                                Upload
                                            </Button>
                                        </UploadField>
                                    </Form.Item>
                                </Form.Item>

                                <Form.Item
                                    className="form-drawer-switch-row"
                                    label="Public"
                                    colon={false}
                                    required={false}
                                >
                                    <Form.Item name="public" valuePropName="checked" noStyle>
                                        <Switch />
                                    </Form.Item>
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
                                    <Form.Item name="project_id" label="ID" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="uuid" label="UUID" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="creator_name" label="Creator" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="creation_date" label="Created" required={false}>
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
