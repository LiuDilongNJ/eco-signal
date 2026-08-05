import { useEffect } from "react"
import type { ReactNode } from "react"
import type { RuleObject } from "@/components/ui"
import { Button, Form, Input, LoadingState, Select, ConfigProvider, Space } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import type { FormFieldDef } from "../data/DataPageLayout"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { isSelectScrollNearBottom } from "@/hooks/usePagedSelectOptions"
import { useTaxonSearchOptions } from "@/hooks/useTaxonSearchOptions"
import "./styles/FormDrawer.css"

export interface ReviewFormDrawerProps {
    open: boolean
    mode: "add" | "edit"
    fields: FormFieldDef[]
    initialData?: Record<string, unknown>
    onClose: () => void
    onSubmit: (values: Record<string, unknown>) => void
    submitting?: boolean
}

const STATUS_OPTIONS = [
    { label: "Accepted", value: "Accepted" },
    { label: "Corrected", value: "Corrected" },
    { label: "Rejected", value: "Rejected" },
    { label: "Uncertain", value: "Uncertain" },
]

function isCorrectedStatus(value: unknown): boolean {
    return String(value ?? "").toLowerCase().includes("correct")
}

export function ReviewFormDrawer({
    open,
    mode,
    fields,
    initialData,
    onClose,
    onSubmit,
    submitting = false
}: ReviewFormDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [form] = Form.useForm()
    const selectedStatus = Form.useWatch("status", form)
    const taxonEnabled = isCorrectedStatus(selectedStatus)

    const taxonSearch = useTaxonSearchOptions()

    const getInitialTaxonOption = () => {
        const rawId = initialData?.taxon ?? initialData?.taxon_id
        if (rawId == null || rawId === "") return null
        const id = Number(rawId)
        if (!Number.isFinite(id)) return null
        const rawLabel = initialData?.taxon_name ?? initialData?.taxon_label
        const label = typeof rawLabel === "string" && rawLabel.trim() ? rawLabel.trim() : `Taxon ${id}`
        return {
            value: id,
            label,
            taxon: { taxon_id: id },
        }
    }

    useEffect(() => {
        if (!open) return
        if (mode === "add") {
            form.resetFields()
            taxonSearch.reset()
        } else if (mode === "edit" && initialData) {
            form.setFieldsValue(initialData)
            taxonSearch.reset(getInitialTaxonOption())
        }
        // Pagination state methods are stable and initialData is the drawer reset boundary.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, mode, initialData, form])

    useEffect(() => {
        if (!open || selectedStatus == null || selectedStatus === "" || isCorrectedStatus(selectedStatus)) return
        form.setFieldValue("taxon", undefined)
    }, [open, selectedStatus, form])

    const renderFieldItem = (field: FormFieldDef): ReactNode => {
        let innerElement: ReactNode = <Input />

        if (field.key === "status") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={STATUS_OPTIONS}
                    allowClear
                />
            )
        } else if (field.key === "taxon") {
            return (
                <Form.Item
                    key={field.key}
                    name={field.key}
                    label={field.label}
                    rules={field.required ? [{ required: true, message: `Please enter ${field.label}` }] : []}
                >
                    <Select
                        className="form-drawer-select"
                        classNames={{ popup: { root: "form-drawer-select-popup" } }}
                        showSearch
                        allowClear
                        disabled={!taxonEnabled}
                        filterOption={false}
                        loading={taxonSearch.loading}
                        options={taxonSearch.options}
                        onSearch={taxonSearch.search}
                        onPopupScroll={(event) => {
                            if (isSelectScrollNearBottom(event.currentTarget)) {
                                taxonSearch.loadNext()
                            }
                        }}
                        notFoundContent={taxonSearch.query ? undefined : "Type a taxon name to search"}
                        popupRender={(menu) => (
                            <>
                                {menu}
                                {taxonSearch.loading ? (
                                    <div style={{ display: "flex", justifyContent: "center", padding: 8 }}>
                                        <LoadingState size="sm" showLabel={false} />
                                    </div>
                                ) : null}
                            </>
                        )}
                        onChange={(value: number | undefined) => {
                            taxonSearch.setCurrentOption(
                                value == null
                                    ? null
                                    : taxonSearch.options.find((option) => option.value === value) ?? null,
                            )
                        }}
                    />
                </Form.Item>
            )
        } else if (field.type === "textarea") {
            const maxLength = field.key === "note" ? 200 : undefined
            innerElement = <Input.TextArea rows={4} maxLength={maxLength} />
        }

        const rules: RuleObject[] = field.required
            ? [{ required: true, message: `Please enter ${field.label}` }]
            : []
        if (field.key === "note") {
            rules.push({ max: 200, message: "Note must be at most 200 characters" })
        }

        // Handle readonly fields from FORM_FIELDS if any (though we handle them in info column)
        const isReadonly = (field as FormFieldDef & { readonly?: boolean }).readonly

        return (
            <Form.Item
                key={field.key}
                name={field.key}
                label={field.label}
                rules={rules}
            >
                {isReadonly ? <Input disabled /> : innerElement}
            </Form.Item>
        )
    }

    // Filter fields to only show editable ones in the first column
    const editableFields = fields.filter(
        (field) => !(field as FormFieldDef & { readonly?: boolean }).readonly,
    )

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={<span className="form-drawer-title">{mode === "edit" ? "Edit Review" : "New Review"}</span>}
                placement="right"
                onClose={onClose}
                open={open}
                styles={{
                    wrapper: {
                        width: 800,
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
                extra={
                    <Space>
                        <Button onClick={onClose} disabled={submitting}>
                            Cancel
                        </Button>
                        <Button
                            type="primary"
                            onClick={() => form.submit()}
                            loading={submitting}
                            style={{ background: "var(--brand)", borderColor: "var(--brand)" }}
                        >
                            {mode === "edit" ? "Save" : "Create"}
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={onSubmit}
                        requiredMark
                        disabled={submitting}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        {/* Hidden fields to ensure IDs are passed in values object */}
                        <Form.Item name="annotation_id" hidden><Input /></Form.Item>
                        <Form.Item name="reviewer_id" hidden><Input /></Form.Item>
                        
                        <div className="form-drawer-layout">
                            <div className="form-drawer-main-col">
                                {editableFields.map(f => renderFieldItem(f))}
                            </div>
                            <div className="form-drawer-side-col">
                                {initialData && (
                                    <>
                                        <Form.Item 
                                            label="Annotation ID" 
                                            required={false}
                                            name="annotation_id" // Ensure name is present for value collection
                                        >
                                            <Input readOnly />
                                        </Form.Item>
                                        <Form.Item label="Media Name" required={false}>
                                            <Input readOnly value={String(initialData.media_name ?? "")} />
                                        </Form.Item>
                                        <Form.Item label="Reviewer" required={false}>
                                            <Input readOnly value={String(initialData.reviewer ?? "")} />
                                        </Form.Item>
                                        <Form.Item label="Created" required={false}>
                                            <Input readOnly value={String(initialData.creation_date ?? "")} />
                                        </Form.Item>
                                        {initialData.review_id && (
                                            <Form.Item label="Review ID" required={false}>
                                                <Input readOnly value={String(initialData.review_id)} />
                                            </Form.Item>
                                        )}
                                    </>
                                )}
                            </div>
                        </div>
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
