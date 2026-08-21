/**
 * AddCollectionDrawer - 添加集合抽屉组件
 *
 * 使用 Ant Design Drawer + Form 实现，支持深色/浅色主题切换
 */

import { useEffect, useState } from "react"
import { Form, Input, Select, Switch, Button, ConfigProvider, Space } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { EditorModal } from "./EditorModal"
import { SetTaxonsDrawer, type CollectionTaxonDraft } from "./SetTaxonsDrawer"
import { CustomScrollArea } from "@/components/ui"
import { collectionsApi } from "../../../../api/endpoints/collections"
import { useAppStore } from "@/store/useAppStore"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { EmptyState } from "@/components/ui"
import { parseRichText } from "@/utils/string"
import { httpUrlRule } from "../../utils/urlValidation"
import "./styles/FormDrawer.css"

interface AddCollectionDrawerProps {
    open: boolean
    editId?: number | null // If provided, drawer operates in edit mode
    projectId?: number | null
    onClose: () => void
    onSubmit: (values: Record<string, any>, taxons: CollectionTaxonDraft[]) => void
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
                    imageUploadCategory="collections"
                    onSave={(html) => {
                        if (onChange) onChange(html)
                        setEditorOpen(false)
                    }}
                />
            )}
        </>
    )
}

export function AddCollectionDrawer({ open, editId, projectId, onClose, onSubmit }: AddCollectionDrawerProps) {
    const [form] = Form.useForm()
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [loadingData, setLoadingData] = useState(false)
    const [spheres, setSpheres] = useState<{ label: string, value: string }[]>([])
    const [fetchingSpheres, setFetchingSpheres] = useState(false)
    const [taxons, setTaxons] = useState<CollectionTaxonDraft[]>([])

    useEffect(() => {
        if (open) {
            form.resetFields()
            setTaxons([])

            // Fetch spheres
            setFetchingSpheres(true)
            collectionsApi.getSpheres().then(res => {
                if (res.code === 0 || res.code === 200) {
                    // Assuming the response is an array of strings or similar. User will provide format later.
                    // If it's an array of objects we'll map differently, but for now map blindly
                    const data = Array.isArray(res.data) ? res.data : []
                    setSpheres(data.map((s: any) => {
                        if (typeof s === 'string') return { label: s, value: s }
                        if (s.name) return { label: s.name, value: s.name }
                        if (s.id) return { label: String(s.id), value: String(s.id) }
                        return { label: String(s), value: String(s) }
                    }))
                }
            }).catch(console.error).finally(() => setFetchingSpheres(false))

            if (editId) {
                setLoadingData(true)
                collectionsApi.getCollection(editId).then(res => {
                    if (res.code === 0 || res.code === 200) {
                        const data = res.data
                        form.setFieldsValue({
                            ...data,
                            creator: data.creator?.name || data.creator_name || (typeof data.creator === "string" ? data.creator : ""),
                        })
                    }
                }).catch(err => {
                    console.error("Failed to fetch collection details:", err)
                }).finally(() => {
                    setLoadingData(false)
                })
            }
        }
    }, [open, editId, projectId, form])

    const handleFinish = (values: Record<string, any>) => {
        // Format DatePicker value to ISO string if any are used, though mostly string returned from DB
        if (values.creation_date && typeof values.creation_date.toISOString === 'function') {
            values.creation_date = values.creation_date.toISOString()
        }

        onSubmit(values, taxons)
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={editId ? "Edit Collection" : "New Collection"}
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
                        initialValues={{ public_access: false, public_tags: false }}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        <div className="form-drawer-layout">
                            <div className="form-drawer-main-col">
                                <Form.Item name="name" label="Name" rules={[{ required: true, message: "Please enter a collection name" }]}>
                                    <Input />
                                </Form.Item>

                                <Form.Item
                                    name="sphere"
                                    label="Sphere"
                                >
                                    <Select
                                        className="form-drawer-select"
                                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                                        showSearch
                                        allowClear
                                        loading={fetchingSpheres}
                                        options={spheres}
                                        notFoundContent={
                                            <EmptyState className="form-drawer-select-empty" title="No Data" />
                                        }
                                        filterOption={(input, option) =>
                                            (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
                                        }
                                    />
                                </Form.Item>

                                <Form.Item
                                    name="project_url"
                                    label="External project URL"
                                    tooltip="link to an external project website for further contextual info"
                                    rules={[httpUrlRule("External project URL")]}
                                >
                                    <Input type="url" inputMode="url" autoComplete="off" />
                                </Form.Item>

                                <Form.Item
                                    name="external_media_url"
                                    label="External Media URL"
                                    tooltip="link to an external data repository where recordings of this collection are also stored"
                                    rules={[httpUrlRule("External Media URL")]}
                                >
                                    <Input type="url" inputMode="url" autoComplete="off" />
                                </Form.Item>

                                <Form.Item name="doi" label="DOI">
                                    <Input />
                                </Form.Item>

                                <Form.Item name="description" label="Description">
                                    <RichTextInput title="Edit Description" />
                                </Form.Item>

                                <Form.Item
                                    className="form-drawer-switch-row"
                                    label="Public Access"
                                >
                                    <Form.Item name="public_access" valuePropName="checked" noStyle>
                                        <Switch />
                                    </Form.Item>
                                </Form.Item>

                                <Form.Item
                                    className="form-drawer-switch-row"
                                    label="Public Annotations"
                                    colon={false}
                                    required={false}
                                >
                                    <Form.Item name="public_tags" valuePropName="checked" noStyle>
                                        <Switch />
                                    </Form.Item>
                                </Form.Item>

                                {editId ? (
                                    <Form.Item
                                        label="Taxa"
                                        tooltip="Associate the collection with one or several taxa (species or higher-order) that it targets. BY and AT show the current user and time immediately after adding, then are finalized when you save."
                                    >
                                        <SetTaxonsDrawer
                                            embedded
                                            open
                                            collectionId={editId}
                                            projectId={projectId ?? null}
                                            onDraftChange={setTaxons}
                                        />
                                    </Form.Item>
                                ) : null}
                            </div>

                            {editId && (
                                <div className="form-drawer-side-col">
                                    <Form.Item name="collection_id" label="ID" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="uuid" label="UUID" required={false}>
                                        <Input readOnly />
                                    </Form.Item>

                                    <Form.Item name="creator" label="Creator" required={false}>
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
