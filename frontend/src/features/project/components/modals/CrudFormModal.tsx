import { Button as ESButton, Textarea as ESTextarea, Select as ESSelect, Input as ESInput, Label } from "@/components/ui"
/**
 * CrudFormModal - CRUD 表单弹窗
 *
 * 动态生成表单字段，支持 text / number / select / textarea / boolean / date
 */

import { useState, useEffect, useMemo } from "react"
import { Modal } from "./Modal"
import { CustomScrollArea } from "@/components/ui"
import { isUrlLikeField, validateOptionalHttpUrl } from "../../utils/urlValidation"

interface FormField {
    key: string
    label: string
    type: "text" | "number" | "select" | "textarea" | "boolean" | "date" | "file"
    options?: string[] | { label: string; value: string | number }[]
    readonly?: boolean
    required?: boolean
    defaultValue?: string | number | boolean
}

interface CrudFormModalProps {
    open: boolean
    onClose: () => void
    mode: "add" | "edit"
    tableName: string
    fields: FormField[]
    initialData?: Record<string, string | number | boolean>
    onSubmit: (data: Record<string, string | number | boolean>) => void
}

export function CrudFormModal({
    open,
    onClose,
    mode,
    tableName,
    fields = [],
    initialData = {},
    onSubmit,
}: CrudFormModalProps) {
    const [formData, setFormData] = useState<Record<string, string | number | boolean>>({})
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

    // 初始化表单数据
    useEffect(() => {
        if (!open) return
        if (mode === "edit" && initialData) {
            setFormData({ ...initialData })
        } else {
            const defaults: Record<string, string | number | boolean> = {}
            fields.forEach((f) => {
                if (f.defaultValue !== undefined) defaults[f.key] = f.defaultValue
                else if (f.type === "boolean") defaults[f.key] = false
                else if (f.type === "number") defaults[f.key] = 0
                else defaults[f.key] = ""
            })
            setFormData(defaults)
        }
    }, [open, mode])

    const visibleFields = useMemo(() => {
        return fields.filter((f) => !(f.readonly && mode === "add"))
    }, [fields, mode])

    // 左右两列
    const leftFields = visibleFields.filter((_, i) => i % 2 === 0)
    const rightFields = visibleFields.filter((_, i) => i % 2 === 1)

    const updateField = (key: string, value: string | number | boolean) => {
        setFormData((prev) => ({ ...prev, [key]: value }))
        setFieldErrors((prev) => {
            if (!prev[key]) return prev
            const next = { ...prev }
            delete next[key]
            return next
        })
    }

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault()
        const nextErrors: Record<string, string> = {}
        visibleFields.forEach((field) => {
            if (!isUrlLikeField(field.key, field.label)) return
            const error = validateOptionalHttpUrl(formData[field.key], field.label)
            if (error) nextErrors[field.key] = error
        })
        setFieldErrors(nextErrors)
        if (Object.keys(nextErrors).length > 0) return
        onSubmit(formData)
        onClose()
    }

    const singularName = tableName?.endsWith("s") ? tableName.slice(0, -1) : (tableName || "Record")

    return (
        <Modal
            open={open}
            onClose={onClose}
            title={mode === "edit" ? `Edit ${singularName}` : `New ${singularName}`}
            width={mode === "edit" ? "720px" : "480px"}
            footer={
                <div className="app-modal-footer-actions">
                    <ESButton appearance="unstyled" className="app-modal-btn cancel" onClick={onClose}>Cancel</ESButton>
                    <ESButton appearance="unstyled" className="app-modal-btn primary" onClick={handleSubmit}>
                        {mode === "edit" ? "Save Changes" : "Create"}
                    </ESButton>
                </div>
            }
        >
            <CustomScrollArea variant="fill">
                <div style={{ padding: "20px 24px" }}>
                    <form className="crud-form" onSubmit={handleSubmit}>
                        <div className={`form-columns ${mode === "edit" ? "two-col" : "one-col"}`}>
                            <div className="form-column">
                                {(mode === "add" ? visibleFields : leftFields).map((field) => (
                                    <FormGroup
                                        key={field.key}
                                        field={field}
                                        value={formData[field.key] ?? ""}
                                        onChange={(v) => updateField(field.key, v)}
                                        disabled={field.readonly}
                                        error={fieldErrors[field.key]}
                                    />
                                ))}
                            </div>
                            {mode === "edit" && (
                                <div className="form-column">
                                    {rightFields.map((field) => (
                                        <FormGroup
                                            key={field.key}
                                            field={field}
                                            value={formData[field.key] ?? ""}
                                            onChange={(v) => updateField(field.key, v)}
                                            disabled={field.readonly}
                                            error={fieldErrors[field.key]}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    </form>
                </div>
            </CustomScrollArea>
        </Modal>
    )
}

// ---- FormGroup 子组件 ----
function FormGroup({
    field,
    value,
    onChange,
    disabled,
    error,
}: {
    field: FormField
    value: string | number | boolean
    onChange: (v: string | number | boolean) => void
    disabled?: boolean
    error?: string
}) {
    return (
        <div className="form-group">
            <Label className="form-label">
                {field.label}
                {field.required && <span className="form-required">*</span>}
            </Label>

            {field.type === "textarea" ? (
                <ESTextarea appearance="unstyled"
                    className="form-input form-textarea"
                    value={value !== null && value !== undefined ? String(value) : ""}
                    onChange={(e) => onChange(e.target.value)}
                    disabled={disabled}
                    rows={3}
                />
            ) : field.type === "select" ? (
                <ESSelect appearance="unstyled"
                    className="form-input form-select"
                    value={value !== null && value !== undefined ? String(value) : ""}
                    onChange={(e) => onChange(e.target.value)}
                    disabled={disabled}
                >
                    <option value="">Select...</option>
                    {(field.options || []).map((opt) => {
                        if (typeof opt === "string") {
                            return (
                                <option key={opt} value={opt}>
                                    {opt}
                                </option>
                            )
                        }
                        const v = String(opt.value)
                        return (
                            <option key={v} value={v}>
                                {opt.label}
                            </option>
                        )
                    })}
                </ESSelect>
            ) : field.type === "boolean" ? (
                <ESButton appearance="unstyled"
                    type="button"
                    className={`form-toggle ${value ? "on" : ""}`}
                    onClick={() => onChange(!value)}
                    disabled={disabled}
                >
                    <span className="toggle-thumb" />
                </ESButton>
            ) : field.type === "file" ? (
                <div className="form-file-drop">
                    <ESInput appearance="unstyled"
                        type="file"
                        className="form-file-input"
                        onChange={(e) => onChange(e.target.files?.[0]?.name ?? "")}
                        disabled={disabled}
                    />
                    <span className="form-file-label">
                        {value ? String(value) : "Click or drag file here"}
                    </span>
                </div>
            ) : (
                <ESInput appearance="unstyled"
                    type={field.type === "number" ? "number" : field.type === "date" ? "datetime-local" : isUrlLikeField(field.key, field.label) ? "url" : "text"}
                    className="form-input"
                    inputMode={isUrlLikeField(field.key, field.label) ? "url" : undefined}
                    autoComplete={isUrlLikeField(field.key, field.label) ? "off" : undefined}
                    value={value !== null && value !== undefined ? String(value) : ""}
                    onChange={(e) => onChange(field.type === "number" ? Number(e.target.value) : e.target.value)}
                    disabled={disabled}
                />
            )}
            {error ? (
                <div style={{ marginTop: 4, color: "var(--danger)", fontSize: 12, lineHeight: 1.4 }}>
                    {error}
                </div>
            ) : null}
        </div>
    )
}
