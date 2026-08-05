import { useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"
import type { RuleObject } from "@/components/ui"
import { Button, Form, Input, LoadingState, Select, Switch, ConfigProvider, Space } from "@/components/ui"
import { FormDrawer } from "@/components/ui"

import { CustomScrollArea } from "@/components/ui"
import { useAppStore } from "@/store/useAppStore"
import type { FormFieldDef } from "../data/DataPageLayout"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import "./styles/FormDrawer.css"

const SOUNDSCAPE_LABELS: Record<string, string> = {
    "": "Other / Unspecified",
    biophony: "Biophony",
    anthropophony: "Anthropophony",
    geophony: "Geophony",
    other: "Other",
}

import { taxonsApi, type SoundClassificationPublic } from "../../../../api/endpoints/taxons"
import { isSelectScrollNearBottom } from "@/hooks/usePagedSelectOptions"
import { useTaxonSearchOptions } from "@/hooks/useTaxonSearchOptions"

const BBOX_FIELD_KEYS = new Set(["min_x", "max_x", "min_y", "max_y"])
const REQUIRED_FIELD_KEYS = new Set(["min_x", "max_x", "min_y", "max_y", "soundscape", "sound_type"])
const SOUND_FIELD_DEPENDENCIES = ["soundscape", "sound_type"] as const

function isEmptyValue(value: unknown): boolean {
    return value === undefined || value === null || value === ""
}

function fieldShowsRequiredMark(field: FormFieldDef): boolean {
    return field.required || REQUIRED_FIELD_KEYS.has(field.key)
}

function renderFieldLabel(field: FormFieldDef) {
    const showStar = fieldShowsRequiredMark(field)
    return (
        <>
            {field.label}
            {showStar ? <span className="form-drawer-required-suffix">*</span> : null}
        </>
    )
}

function buildSoundscapeSelectOptions(rows: SoundClassificationPublic[]) {
    const keys = new Set<string>()
    for (const r of rows) {
        keys.add(r.soundscape_component ?? "")
    }
    const preferred = ["biophony", "anthropophony", "geophony", "other"]
    const first = preferred.filter((p) => keys.has(p))
    const rest = [...keys].filter((k) => !preferred.includes(k)).sort((a, b) => a.localeCompare(b))
    return [...first, ...rest].map((value) => ({
        value,
        label:
            SOUNDSCAPE_LABELS[value] ??
            (value === "" ? "Other / Unspecified" : value.replace(/_/g, " ")),
    }))
}

function buildAnimalSoundSelectOptions(rows: Array<{ name?: string | null }>) {
    const seen = new Set<string>()
    const options: Array<{ value: string; label: string }> = []
    for (const row of rows) {
        const name = String(row.name ?? "").trim()
        if (!name || seen.has(name)) continue
        seen.add(name)
        options.push({ value: name, label: name })
    }
    return options
}

export interface AnnotationFormDrawerProps {
    open: boolean
    mode: "add" | "edit"
    fields: FormFieldDef[]
    initialData?: Record<string, unknown>
    onClose: () => void
    onSubmit: (values: Record<string, unknown>) => void
    submitting?: boolean
}

export function AnnotationFormDrawer({
    open,
    mode,
    fields,
    initialData,
    onClose,
    onSubmit,
    submitting = false
}: AnnotationFormDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const [form] = Form.useForm()

    const [soundClassifications, setSoundClassifications] = useState<SoundClassificationPublic[]>([])
    const [animalSoundTypes, setAnimalSoundTypes] = useState<{ taxon_sound_type_id: number; name: string }[]>([])
    const taxonSearch = useTaxonSearchOptions()

    const currentSoundscape = Form.useWatch("soundscape", form)
    const distanceNotEstimable = Form.useWatch("distance_not_estimable", form)
    const isBiophony = (currentSoundscape || "").toLowerCase() === "biophony"
    const animalSoundSelectOptions = useMemo(
        () => buildAnimalSoundSelectOptions(animalSoundTypes),
        [animalSoundTypes],
    )

    const getInitialTaxonOption = () => {
        const rawId = initialData?.taxon ?? initialData?.taxon_id
        if (rawId == null || rawId === "") return null
        const id = Number(rawId)
        if (!Number.isFinite(id)) return null

        const commonName = typeof initialData?.taxon_common_name === "string"
            ? initialData.taxon_common_name.trim()
            : ""
        const scientificName = typeof initialData?.taxon_scientific_name === "string"
            ? initialData.taxon_scientific_name.trim()
            : ""
        const explicitLabel = typeof initialData?.taxon_name === "string"
            ? initialData.taxon_name.trim()
            : ""

        let label = explicitLabel || `Taxon ${id}`
        if (commonName && scientificName) label = `${commonName} - ${scientificName}`
        else if (scientificName) label = scientificName
        else if (commonName) label = commonName

        return {
            value: id,
            label,
            taxon: {
                taxon_id: id,
                cached_scientific_name: scientificName || null,
                cached_common_name: commonName || null,
            },
        }
    }

    useEffect(() => {
        taxonsApi.getSoundClassifications(true).then(res => {
            setSoundClassifications(res || [])
        }).catch(err => {
            console.error("Failed to fetch sound classifications:", err)
        })

        taxonsApi.getAnimalSoundTypes(undefined, true).then(res => {
            setAnimalSoundTypes(res || [])
        }).catch(err => {
            console.error("Failed to fetch animal sound types:", err)
        })
    }, [])

    useEffect(() => {
        if (!open) return
        if (mode === "add") {
            form.resetFields()
            taxonSearch.reset()
        } else if (mode === "edit" && initialData) {
            form.setFieldsValue({
                ...initialData,
                uncertain:
                    initialData.uncertain === true ||
                    initialData.uncertain === "True",
                reference:
                    initialData.reference === true ||
                    initialData.reference === "True",
                distance_not_estimable:
                    initialData.distance_not_estimable === true ||
                    initialData.distance_not_estimable === "True",
            })
            taxonSearch.reset(getInitialTaxonOption())
        }
        // Pagination state methods are stable and initialData is the drawer reset boundary.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, mode, initialData, form])

    const requiredNumberRule = useMemo((): RuleObject => ({
        validator: async (_, value) => {
            if (isEmptyValue(value)) return
            const n = Number(value)
            if (Number.isNaN(n)) {
                throw new Error("Please enter a valid number")
            }
        },
    }), [])

    const individualNumRule = useMemo((): RuleObject => ({
        validator: async (_, value) => {
            if (!isBiophony || isEmptyValue(value)) return
            const n = Number(value)
            if (!Number.isFinite(n) || !Number.isInteger(n) || n < 1) {
                throw new Error("Individual number must be at least 1")
            }
        },
    }), [isBiophony])

    const distanceRule = useMemo((): RuleObject => ({
        validator: async () => {
            const values = form.getFieldsValue(["distance_m", "distance_not_estimable"])
            if (values.distance_not_estimable === true || values.distance_not_estimable === "True") return
            if (isEmptyValue(values.distance_m)) return
            const n = Number(values.distance_m)
            if (!Number.isFinite(n) || n < 0) {
                throw new Error("Distance must be a non-negative number")
            }
        },
    }), [form])

    const fieldRules = (field: FormFieldDef): RuleObject[] => {
        const rules: RuleObject[] = []

        if (field.required || BBOX_FIELD_KEYS.has(field.key)) {
            rules.push({
                required: true,
                message:
                    field.key === "min_x" ? "Please enter Min X" :
                    field.key === "max_x" ? "Please enter Max X" :
                    field.key === "min_y" ? "Please enter Min Y" :
                    field.key === "max_y" ? "Please enter Max Y" :
                    `Please enter ${field.label}`,
            })
        }

        if (BBOX_FIELD_KEYS.has(field.key)) {
            rules.push(requiredNumberRule)
        }

        if (field.key === "soundscape") {
            rules.push({ required: true, message: "Please select Soundscape" })
        }

        if (field.key === "sound_type") {
            rules.push({ required: true, message: "Please select Sound Type" })
        }

        if (field.key === "individual_num") {
            rules.push(individualNumRule)
        }

        if (field.key === "distance_m" || field.key === "distance_not_estimable") {
            rules.push(distanceRule)
        }

        if (field.key === "comments") {
            rules.push({ max: 500, message: "Comments must be at most 500 characters" })
        }

        return rules
    }

    const fieldDependencies = (field: FormFieldDef): string[] | undefined => {
        if (field.key === "soundscape" || field.key === "sound_type") {
            return [...SOUND_FIELD_DEPENDENCIES]
        }
        if (field.key === "distance_m" || field.key === "distance_not_estimable") {
            return ["distance_m", "distance_not_estimable"]
        }
        return undefined
    }

    const renderFieldItem = (field: FormFieldDef): ReactNode => {
        let innerElement: ReactNode = <Input />

        const biophonyFields = ["taxon", "uncertain", "animal_sound", "distance_m", "individual_num"]
        if (biophonyFields.includes(field.key) && !isBiophony) {
            return null
        }

        if (field.key === "distance_not_estimable") {
            return null
        }

        if (field.key === "distance_m") {
            return (
                <div key="distance_m" className="form-drawer-distance-block">
                    <div className="form-drawer-distance-header">
                        <span className="form-drawer-distance-title">{renderFieldLabel(field)}</span>
                        <div className="form-drawer-distance-toggle-group">
                            <span className="form-drawer-distance-switch-text">Not Estimable</span>
                            <span className="form-drawer-link-sep" aria-hidden>
                                |
                            </span>
                            <ConfigProvider wave={{ disabled: true }}>
                                <Form.Item name="distance_not_estimable" valuePropName="checked" noStyle>
                                    <Switch
                                        size="small"
                                        onChange={(checked) => {
                                            if (checked) form.setFieldValue("distance_m", undefined)
                                        }}
                                    />
                                </Form.Item>
                            </ConfigProvider>
                        </div>
                    </div>
                    <Form.Item
                        name="distance_m"
                        rules={fieldRules(field)}
                        dependencies={fieldDependencies(field)}
                        validateTrigger={["onChange", "onBlur"]}
                        noStyle
                    >
                        <Input disabled={Boolean(distanceNotEstimable)} />
                    </Form.Item>
                </div>
            )
        }

        const itemProps = {
            name: field.key,
            label: renderFieldLabel(field),
            rules: fieldRules(field),
            dependencies: fieldDependencies(field),
            validateTrigger: fieldDependencies(field) ? ["onChange", "onBlur"] : undefined,
        }

        if (field.key === "uncertain" || field.key === "reference") {
            return (
                <Form.Item
                    key={field.key}
                    className="form-drawer-switch-row"
                    name={field.key}
                    label={renderFieldLabel(field)}
                    valuePropName="checked"
                    colon={false}
                    required={false}
                >
                    <Switch />
                </Form.Item>
            )
        }

        if (field.type === "number") {
            innerElement = <Input />
        } else if (field.type === "select") {
            let options = (field.options || []).map((opt) =>
                typeof opt === "string" ? { label: opt, value: opt } : { label: opt.label, value: String(opt.value) },
            )

            if (field.key === "soundscape") {
                options = buildSoundscapeSelectOptions(soundClassifications)
                return (
                    <Form.Item key={field.key} {...itemProps}>
                        <Select
                            className="form-drawer-select"
                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                            options={options}
                            allowClear
                            showSearch
                            filterOption={(input, option) =>
                                String(option?.label ?? "").toLowerCase().includes((input ?? "").toLowerCase())
                            }
                            onChange={() => {
                                form.setFieldValue("sound_type", undefined)
                                form.setFieldValue("taxon", undefined)
                                form.setFieldValue("animal_sound", undefined)
                                form.setFieldValue("distance_m", undefined)
                                form.setFieldValue("distance_not_estimable", false)
                                form.setFieldValue("individual_num", undefined)
                                form.setFieldValue("uncertain", undefined)
                            }}
                        />
                    </Form.Item>
                )
            } else if (field.key === "sound_type") {
                const filtered = soundClassifications.filter(c => (c.soundscape_component || "") === (currentSoundscape || ""))
                options = filtered.map(c => ({ value: String(c.sound_id), label: c.sound_type || "Unknown" }))
                return (
                    <Form.Item key={field.key} {...itemProps}>
                        <Select
                            className="form-drawer-select"
                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                            options={options}
                            allowClear
                            showSearch
                            disabled={isEmptyValue(currentSoundscape)}
                            filterOption={(input, option) =>
                                String(option?.label ?? "").toLowerCase().includes((input ?? "").toLowerCase())
                            }
                        />
                    </Form.Item>
                )
            } else if (field.key === "animal_sound") {
                options = animalSoundSelectOptions
            } else if (field.key === "taxon") {
                return (
                    <Form.Item key={field.key} {...itemProps}>
                        <Select
                            className="form-drawer-select"
                            classNames={{ popup: { root: "form-drawer-select-popup" } }}
                            showSearch
                            allowClear
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
            }

            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={options}
                    allowClear
                    showSearch
                    filterOption={(input, option) =>
                        String(option?.label ?? "")
                            .toLowerCase()
                            .includes((input ?? "").toLowerCase())
                    }
                />
            )
        } else if (field.type === "textarea") {
            const maxLength = field.key === "comments" ? 500 : undefined
            innerElement = (
                <Input.TextArea rows={4} maxLength={maxLength} />
            )
        }

        return (
            <Form.Item key={field.key} {...itemProps}>
                {innerElement}
            </Form.Item>
        )
    }

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={<span className="form-drawer-title">{mode === "edit" ? "Edit Annotation" : "New Annotation"}</span>}
                placement="right"
                onClose={onClose}
                open={open}
                styles={{
                    wrapper: {
                        width: mode === "add" ? 520 : 800,
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
                        requiredMark={false}
                        disabled={submitting}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        {mode === "add" ? (
                            <div className="form-drawer-main-col">
                                {fields.map(f => renderFieldItem(f))}
                            </div>
                        ) : (
                            <div className="form-drawer-layout">
                                <div className="form-drawer-main-col">
                                    {fields.map(f => renderFieldItem(f))}
                                </div>
                                <div className="form-drawer-side-col">
                                    {initialData && (
                                        <>
                                            <Form.Item label="ID" required={false}>
                                                <Input readOnly value={String(initialData.id ?? initialData.annotation_id ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="UUID" required={false}>
                                                <Input readOnly value={String(initialData.uuid ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="Media Name" required={false}>
                                                <Input readOnly value={String(initialData.media_name ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="Creator Type" required={false}>
                                                <Input readOnly value={String(initialData.creator_type ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="Creator" required={false}>
                                                <Input readOnly value={String(initialData.creator ?? initialData.creator_name ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="Created" required={false}>
                                                <Input readOnly value={String(initialData.creation_date ?? "")} />
                                            </Form.Item>
                                        </>
                                    )}
                                </div>
                            </div>
                        )}
                    </Form>
                </CustomScrollArea>
            </FormDrawer>
        </ConfigProvider>
    )
}
