import { useEffect, useMemo, useRef } from "react"
import type { ReactNode } from "react"
import type { RuleObject } from "@/components/ui"
import { Button, Form, Input, LoadingState, Select, InputNumber, ConfigProvider, Space, Tooltip } from "@/components/ui"
import { FormDrawer } from "@/components/ui"
import { renderRequiredMark } from "@/components/ui"

import { useAppStore } from "@/store/useAppStore"
import type { FormFieldDef } from "../data/DataPageLayout"
import { useAntdBrandConfig } from "../../hooks/useAntdBrandConfig"
import { useGadm } from "../hooks/useGadm"
import { useGeoOptions, type GeoOptionsFilter } from "../hooks/useGeoOptions"
import { CustomScrollArea } from "@/components/ui"
import { isSelectScrollNearBottom } from "@/hooks/usePagedSelectOptions"
import { CircleHelp } from "lucide-react"
import "./styles/FormDrawer.css"

function gadmSelectOptions(opts: { gid?: string; name: string; name_zh?: string }[]) {
    return opts
        .filter(o => o.gid != null && o.gid !== "")
        .map(o => ({
            label: o.name_zh ? `${o.name} (${o.name_zh})` : o.name,
            value: String(o.gid),
        }))
}

function gadmToLabelValue(
    gid: string | number | null | undefined,
    opts: { gid?: string; name: string; name_zh?: string }[],
    fallbackName?: unknown,
): { value: string; label: string } | undefined {
    if (gid == null || gid === "") return undefined
    const v = String(gid).trim()
    if (!v) return undefined
    const o = opts.find(x => String(x.gid) === v)
    const fallback = typeof fallbackName === "string" ? fallbackName.trim() : ""
    const label = o ? (o.name_zh ? `${o.name} (${o.name_zh})` : o.name) : (fallback || v)
    return { value: v, label }
}

function gadmWatchToGid(val: unknown): string | null {
    if (val == null || val === "") return null
    if (typeof val === "object" && val !== null && "value" in val) {
        const v = (val as { value: unknown }).value
        if (v == null || v === "") return null
        return String(v)
    }
    return String(val)
}

function geoToLabelValue(
    id: string | number | null | undefined,
    opts: { id?: number; gid?: string; name: string }[],
    fallbackName?: unknown,
): { value: number; label: string } | undefined {
    if (id == null || id === "") return undefined
    const n = Number(id)
    if (!Number.isFinite(n)) return undefined
    const o = opts.find(x => Number(x.gid ?? x.id) === n)
    const fallback = typeof fallbackName === "string" ? fallbackName.trim() : ""
    return { value: n, label: o?.name ?? (fallback || String(n)) }
}

function hasCoordinatePair(values: Record<string, unknown>): boolean {
    const lat = values.latitude
    const lon = values.longitude
    const hasLat = lat !== null && lat !== undefined && lat !== ""
    const hasLon = lon !== null && lon !== undefined && lon !== ""
    return hasLat && hasLon
}

function hasPartialCoordinatePair(values: Record<string, unknown>): boolean {
    const lat = values.latitude
    const lon = values.longitude
    const hasLat = lat !== null && lat !== undefined && lat !== ""
    const hasLon = lon !== null && lon !== undefined && lon !== ""
    return hasLat !== hasLon
}

const SITE_LOCATION_DEPENDENCIES = [
    "latitude",
    "longitude",
    "gadm0_gid",
    "gadm1_gid",
    "gadm2_gid",
    "iho_id",
] as const

const LOCATION_REQUIRED_FIELD_KEYS = new Set(["latitude", "longitude", "gadm0_gid", "iho_id"])

const TOPOGRAPHY_MIN_METERS = -10900
const TOPOGRAPHY_MAX_METERS = 8849

const SITE_FIELD_HELP: Record<string, string> = {
    topography_m: "Negative or positive values for depth below sea level or altitude above sea level.",
    freshwater_depth_m: "Depth of sampling site within freshwater body.",
}

function hasRequiredFieldValue(value: unknown): boolean {
    if (value == null) return false
    if (typeof value === "object" && "value" in value) {
        return hasRequiredFieldValue((value as { value: unknown }).value)
    }
    if (typeof value === "string") return value.trim() !== ""
    return value !== ""
}

function validateCoordRange(value: unknown, label: string, min: number, max: number): string | null {
    if (value === null || value === undefined || value === "") return null
    const n = Number(value)
    if (!Number.isFinite(n)) return `${label} must be a valid number`
    if (n < min || n > max) return `${label} must be between ${min} and ${max}`
    return null
}

function renderFieldLabel(field: FormFieldDef) {
    const label = field.required || LOCATION_REQUIRED_FIELD_KEYS.has(field.key) ? (
        <>
            {field.label}
            {!field.required ? <span className="form-drawer-required-suffix">*</span> : null}
        </>
    ) : field.label
    const helpText = SITE_FIELD_HELP[field.key]
    if (!helpText) return label

    return (
        <span className="site-form-field-label-with-help">
            <span>{label}</span>
            <Tooltip title={helpText}>
                <CircleHelp size={14} strokeWidth={2} aria-label={`${field.label} information`} />
            </Tooltip>
        </span>
    )
}

export interface SiteFormDrawerProps {
    open: boolean
    mode: "add" | "edit"
    fields: FormFieldDef[]
    initialData?: Record<string, any>
    onClose: () => void
    onSubmit: (values: Record<string, any>) => void
    submitting?: boolean
}

export function SiteFormDrawer({
    open,
    mode,
    fields,
    initialData,
    onClose,
    onSubmit,
    submitting = false
}: SiteFormDrawerProps) {
    const isDark = useAppStore(s => s.effectiveTheme === "dark")
    const drawerTheme = useAntdBrandConfig(isDark)
    const isInitializing = useRef(false)
    /** Avoid resetFields on add when gadm1/2 options load after picking GADM0 (those deps would re-fire the effect). */
    const drawerWasOpenRef = useRef(false)
    /** Edit: full hydrate only when `initialData` ref from parent changes; later option loads only patch labels. */
    const lastEditInitialRef = useRef<Record<string, unknown> | undefined>(undefined)
    const [form] = Form.useForm()

    const gadm0FieldVal = Form.useWatch("gadm0_gid", form)
    const gadm1FieldVal = Form.useWatch("gadm1_gid", form)
    const realmIdWatch = Form.useWatch("realm_id", form)
    const biomeIdWatch = Form.useWatch("biome_id", form)
    const gadm0ParentGid = gadmWatchToGid(gadm0FieldVal)
    const gadm1ParentGid = gadmWatchToGid(gadm1FieldVal)

    const gadm0State = useGadm(0)
    const gadm1State = useGadm(1, gadm0ParentGid)
    const gadm2State = useGadm(2, gadm1ParentGid)
    const ihoState = useGeoOptions("iho")
    const realmState = useGeoOptions("realm")
    const { options: gadm0Options, loading: gadm0Loading } = gadm0State
    const { options: gadm1Options, loading: gadm1Loading } = gadm1State
    const { options: gadm2Options, loading: gadm2Loading } = gadm2State
    const { options: ihoOptions, loading: ihoLoading } = ihoState
    const { options: realmOptions, loading: realmLoading } = realmState

    const iucnBiomeFilter = useMemo(
        (): GeoOptionsFilter => ({ parentRealmId: realmIdWatch ?? null }),
        [realmIdWatch],
    )
    const iucnFunctionalFilter = useMemo(
        (): GeoOptionsFilter => ({ parentBiomeId: biomeIdWatch ?? null }),
        [biomeIdWatch],
    )
    const biomeState = useGeoOptions("biome", iucnBiomeFilter)
    const functionalTypeState = useGeoOptions(
        "functionalType",
        iucnFunctionalFilter,
    )
    const { options: biomeOptions, loading: biomeLoading } = biomeState
    const { options: functionalTypeOptions, loading: functionalTypeLoading } = functionalTypeState

    const hasRealm = realmIdWatch != null && realmIdWatch !== "" && !Number.isNaN(Number(realmIdWatch))
    const hasBiome = biomeIdWatch != null && biomeIdWatch !== "" && !Number.isNaN(Number(biomeIdWatch))

    /** New array every render makes rc-Select treat options as "replaced" and drop the shown value after sibling fetches. */
    const gadm0SelectOpts = useMemo(() => gadmSelectOptions(gadm0Options), [gadm0Options])
    const gadm1SelectOpts = useMemo(() => gadmSelectOptions(gadm1Options), [gadm1Options])
    const gadm2SelectOpts = useMemo(() => gadmSelectOptions(gadm2Options), [gadm2Options])

    useEffect(() => {
        if (!open || mode !== "edit" || !initialData) return
        const setGadmCurrent = (
            state: typeof gadm0State,
            idKey: "gadm0_gid" | "gadm1_gid" | "gadm2_gid",
            nameKey: "gadm0" | "gadm1" | "gadm2",
        ) => {
            const id = initialData[idKey]
            if (id == null || id === "") return
            state.setCurrentOption({
                gid: String(id),
                name: String(initialData[nameKey] || id),
            })
        }
        const setGeoCurrent = (
            state: typeof ihoState,
            idKey: "iho_id" | "realm_id" | "biome_id" | "functional_type_id",
            nameKey: "iho" | "realm" | "biome" | "functional_type",
            useGid = false,
        ) => {
            const rawId = initialData[idKey]
            const id = Number(rawId)
            if (!Number.isFinite(id)) return
            state.setCurrentOption({
                ...(useGid ? { gid: String(id) } : { id }),
                name: String(initialData[nameKey] || id),
            })
        }
        setGadmCurrent(gadm0State, "gadm0_gid", "gadm0")
        setGadmCurrent(gadm1State, "gadm1_gid", "gadm1")
        setGadmCurrent(gadm2State, "gadm2_gid", "gadm2")
        setGeoCurrent(ihoState, "iho_id", "iho", true)
        setGeoCurrent(realmState, "realm_id", "realm")
        setGeoCurrent(biomeState, "biome_id", "biome")
        setGeoCurrent(functionalTypeState, "functional_type_id", "functional_type")
    }, [
        biomeIdWatch,
        gadm0ParentGid,
        gadm1ParentGid,
        initialData,
        mode,
        open,
        realmIdWatch,
        // State methods are stable; parent values rerun this after cascade resets.
        biomeState.setCurrentOption,
        functionalTypeState.setCurrentOption,
        gadm0State.setCurrentOption,
        gadm1State.setCurrentOption,
        gadm2State.setCurrentOption,
        ihoState.setCurrentOption,
        realmState.setCurrentOption,
    ])

    // Add: reset only when drawer opens (never re-run on geo option loads).
    useEffect(() => {
        if (!open) {
            drawerWasOpenRef.current = false
            return
        }
        if (mode === "add") {
            if (!drawerWasOpenRef.current) {
                form.resetFields()
            }
            drawerWasOpenRef.current = true
        }
    }, [open, mode, form])

    // Edit: full hydrate only when parent gives a new `initialData` object; when only geo lists load, patch GADM labels only.
    useEffect(() => {
        if (!open || mode !== "edit" || !initialData?.site_id) {
            if (!open) lastEditInitialRef.current = undefined
            return
        }

        const fullHydrate = lastEditInitialRef.current !== initialData
        if (fullHydrate) {
            lastEditInitialRef.current = initialData
        }

        isInitializing.current = true

        if (fullHydrate) {
            const dataToSet = { ...initialData }

            if (!dataToSet.iho_id && dataToSet.iho && ihoOptions.length > 0) {
                const found = ihoOptions.find(o => o.name === dataToSet.iho)
                if (found) dataToSet.iho_id = Number(found.gid ?? found.id)
            }
            if (dataToSet.iho_id != null && typeof dataToSet.iho_id !== "object") {
                dataToSet.iho_id = geoToLabelValue(dataToSet.iho_id as string | number, ihoOptions, dataToSet.iho)
            }

            if (!dataToSet.gadm0_gid && dataToSet.gadm0 && gadm0Options.length > 0) {
                const found = gadm0Options.find(o => o.name === dataToSet.gadm0)
                if (found) dataToSet.gadm0_gid = found.gid
            }
            if (!dataToSet.gadm1_gid && dataToSet.gadm1 && gadm1Options.length > 0) {
                const found = gadm1Options.find(o => o.name === dataToSet.gadm1)
                if (found) dataToSet.gadm1_gid = found.gid
            }
            if (!dataToSet.gadm2_gid && dataToSet.gadm2 && gadm2Options.length > 0) {
                const found = gadm2Options.find(o => o.name === dataToSet.gadm2)
                if (found) dataToSet.gadm2_gid = found.gid
            }

            if (!dataToSet.realm_id && dataToSet.realm && realmOptions.length > 0) {
                const found = realmOptions.find(o => o.name === dataToSet.realm)
                if (found?.id != null) dataToSet.realm_id = found.id
            }
            if (dataToSet.realm_id) dataToSet.realm_id = Number(dataToSet.realm_id)

            if (!dataToSet.biome_id && dataToSet.biome && biomeOptions.length > 0) {
                const found = biomeOptions.find(o => o.name === dataToSet.biome)
                if (found?.id != null) dataToSet.biome_id = found.id
            }
            if (dataToSet.biome_id) dataToSet.biome_id = Number(dataToSet.biome_id)

            if (!dataToSet.functional_type_id && dataToSet.functional_type && functionalTypeOptions.length > 0) {
                const found = functionalTypeOptions.find(o => o.name === dataToSet.functional_type)
                if (found?.id != null) dataToSet.functional_type_id = found.id
            }
            if (dataToSet.functional_type_id) dataToSet.functional_type_id = Number(dataToSet.functional_type_id)

            if (dataToSet.gadm0_gid != null && typeof dataToSet.gadm0_gid !== "object") {
                dataToSet.gadm0_gid = gadmToLabelValue(dataToSet.gadm0_gid as string | number, gadm0Options, dataToSet.gadm0)
            }
            if (dataToSet.gadm1_gid != null && typeof dataToSet.gadm1_gid !== "object") {
                dataToSet.gadm1_gid = gadmToLabelValue(dataToSet.gadm1_gid as string | number, gadm1Options, dataToSet.gadm1)
            }
            if (dataToSet.gadm2_gid != null && typeof dataToSet.gadm2_gid !== "object") {
                dataToSet.gadm2_gid = gadmToLabelValue(dataToSet.gadm2_gid as string | number, gadm2Options, dataToSet.gadm2)
            }

            form.setFieldsValue(dataToSet)
        } else {
            const cur = form.getFieldsValue(true)
            const patch: Record<string, unknown> = {}
            const rawIho = cur.iho_id
            if (rawIho != null && typeof rawIho === "object" && "value" in rawIho) {
                const value = (rawIho as { value: unknown }).value
                const label = (rawIho as { label?: unknown }).label
                const valueText = value == null ? "" : String(value).trim()
                const labelText = typeof label === "string" ? label.trim() : ""
                if (valueText && (!labelText || labelText === valueText)) {
                    const lv = geoToLabelValue(valueText, ihoOptions, initialData?.iho)
                    if (lv && lv.label !== labelText) patch.iho_id = lv
                }
            } else if (rawIho != null && rawIho !== "") {
                const lv = geoToLabelValue(rawIho as string | number, ihoOptions, initialData?.iho)
                if (lv) patch.iho_id = lv
            } else if (initialData?.iho && ihoOptions.length > 0) {
                const found = ihoOptions.find(o => o.name === initialData.iho)
                const lv = found ? geoToLabelValue(found.gid ?? found.id, ihoOptions, initialData.iho) : undefined
                if (lv) patch.iho_id = lv
            }
            const maybePatchGadm = (
                key: "gadm0_gid" | "gadm1_gid" | "gadm2_gid",
                opts: typeof gadm0Options,
                fallbackKey: "gadm0" | "gadm1" | "gadm2",
            ) => {
                const raw = cur[key]
                if (raw != null && typeof raw === "object" && "value" in raw) {
                    const value = (raw as { value: unknown }).value
                    const label = (raw as { label?: unknown }).label
                    const valueText = value == null ? "" : String(value).trim()
                    const labelText = typeof label === "string" ? label.trim() : ""
                    if (valueText && (!labelText || labelText === valueText)) {
                        const lv = gadmToLabelValue(valueText, opts, initialData?.[fallbackKey])
                        if (lv && lv.label !== labelText) patch[key] = lv
                    }
                } else if (raw != null) {
                    const lv = gadmToLabelValue(raw as string | number, opts, initialData?.[fallbackKey])
                    if (lv) patch[key] = lv
                }
            }
            maybePatchGadm("gadm0_gid", gadm0Options, "gadm0")
            maybePatchGadm("gadm1_gid", gadm1Options, "gadm1")
            maybePatchGadm("gadm2_gid", gadm2Options, "gadm2")
            if (Object.keys(patch).length > 0) {
                form.setFieldsValue(patch)
            }
        }

        const timer = setTimeout(() => {
            isInitializing.current = false
        }, 200)
        drawerWasOpenRef.current = true
        return () => clearTimeout(timer)
    }, [
        open,
        mode,
        initialData,
        form,
        ihoOptions,
        realmOptions,
        biomeOptions,
        functionalTypeOptions,
        gadm0Options,
        gadm1Options,
        gadm2Options,
    ])

    const numberFieldProps = { style: { width: "100%" as const }, controls: false }

    const locationChoiceRule = useMemo((): RuleObject => {
        return {
            validator: async () => {
                const values = form.getFieldsValue(["latitude", "longitude", "gadm0_gid", "iho_id"])
                const hasCoords = hasCoordinatePair(values)
                const hasGadm0 = gadmWatchToGid(values.gadm0_gid) != null
                const hasIho = hasRequiredFieldValue(values.iho_id)
                if (hasCoords || hasGadm0 || hasIho) return
                throw new Error("Please enter Latitude and Longitude, or select GADM0, or select IHO")
            },
        }
    }, [form])

    const latitudePairRule = useMemo((): RuleObject => {
        return {
            validator: async () => {
                const values = form.getFieldsValue(["latitude", "longitude"])
                if (!hasPartialCoordinatePair(values)) return
                const hasLat = values.latitude !== null && values.latitude !== undefined && values.latitude !== ""
                if (!hasLat) throw new Error("Please enter latitude")
            },
        }
    }, [form])

    const longitudePairRule = useMemo((): RuleObject => {
        return {
            validator: async () => {
                const values = form.getFieldsValue(["latitude", "longitude"])
                if (!hasPartialCoordinatePair(values)) return
                const hasLon = values.longitude !== null && values.longitude !== undefined && values.longitude !== ""
                if (!hasLon) throw new Error("Please enter longitude")
            },
        }
    }, [form])

    const latitudeRangeRule = useMemo((): RuleObject => {
        return {
            validator: async (_, value) => {
                const error = validateCoordRange(value, "Latitude", -90, 90)
                if (error) throw new Error(error)
            },
        }
    }, [])

    const topographyRangeRule = useMemo((): RuleObject => {
        return {
            validator: async (_, value) => {
                const error = validateCoordRange(value, "Topography", TOPOGRAPHY_MIN_METERS, TOPOGRAPHY_MAX_METERS)
                if (error) throw new Error(error)
            },
        }
    }, [])

    const freshwaterDepthRule = useMemo((): RuleObject => {
        return {
            validator: async (_, value) => {
                const error = validateCoordRange(value, "Water depth", 0, Number.POSITIVE_INFINITY)
                if (error) throw new Error(error)
            },
        }
    }, [])

    const longitudeRangeRule = useMemo((): RuleObject => {
        return {
            validator: async (_, value) => {
                const error = validateCoordRange(value, "Longitude", -180, 180)
                if (error) throw new Error(error)
            },
        }
    }, [])

    const gadm0HierarchyRule = useMemo((): RuleObject => {
        return {
            validator: async () => {
                const values = form.getFieldsValue(["gadm0_gid", "gadm1_gid", "gadm2_gid"])
                const hasGadm0 = gadmWatchToGid(values.gadm0_gid) != null
                const hasChildGadm =
                    gadmWatchToGid(values.gadm1_gid) != null || gadmWatchToGid(values.gadm2_gid) != null
                if (hasChildGadm && !hasGadm0) {
                    throw new Error("GADM0 is required when GADM1 or GADM2 is selected")
                }
            },
        }
    }, [form])

    const fieldRules = (field: FormFieldDef): RuleObject[] => {
        const rules: RuleObject[] = field.required
            ? [{ required: true, message: `Please enter ${field.label}` }]
            : []

        if (field.key === "latitude") {
            rules.push(latitudePairRule)
            rules.push(latitudeRangeRule)
            rules.push(locationChoiceRule)
        } else if (field.key === "longitude") {
            rules.push(longitudePairRule)
            rules.push(longitudeRangeRule)
        } else if (field.key === "gadm0_gid") {
            rules.push(gadm0HierarchyRule)
        } else if (field.key === "gadm1_gid" || field.key === "gadm2_gid") {
            rules.push(gadm0HierarchyRule)
        } else if (field.key === "topography_m") {
            rules.push(topographyRangeRule)
        } else if (field.key === "freshwater_depth_m") {
            rules.push(freshwaterDepthRule)
        }

        return rules
    }

    const renderPagedPopup = (menu: ReactNode, loading: boolean) => (
        <>
            {menu}
            {loading ? (
                <div style={{ display: "flex", justifyContent: "center", padding: 8 }}>
                    <LoadingState size="sm" showLabel={false} />
                </div>
            ) : null}
        </>
    )

    const renderSiteFieldItem = (field: FormFieldDef): ReactNode => {
        let innerElement: ReactNode = <Input />

        if (field.type === "number") {
            // Keep out-of-range coordinates visible so the field validator can explain the error.
            innerElement = (
                <InputNumber
                    {...numberFieldProps}
                    min={field.key === "topography_m" ? TOPOGRAPHY_MIN_METERS : field.key === "freshwater_depth_m" ? 0 : undefined}
                    max={field.key === "topography_m" ? TOPOGRAPHY_MAX_METERS : undefined}
                />
            )
        } else if (field.key === "gadm0_gid") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    labelInValue
                    options={gadm0SelectOpts}
                    loading={gadm0Loading}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={gadm0State.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) gadm0State.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, gadm0Loading)}
                    onChange={(value) => {
                        const id = gadmWatchToGid(value)
                        gadm0State.setCurrentOption(
                            id ? gadm0Options.find((option) => option.gid === id) ?? null : null,
                        )
                        if (!isInitializing.current) {
                            form.setFieldsValue({ gadm1_gid: undefined, gadm2_gid: undefined })
                            gadm1State.reset()
                            gadm2State.reset()
                        }
                    }}
                />
            )
        } else if (field.key === "gadm1_gid") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    labelInValue
                    options={gadm1SelectOpts}
                    loading={gadm1Loading}
                    disabled={!gadm0ParentGid}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={gadm1State.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) gadm1State.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, gadm1Loading)}
                    onChange={(value) => {
                        const id = gadmWatchToGid(value)
                        gadm1State.setCurrentOption(
                            id ? gadm1Options.find((option) => option.gid === id) ?? null : null,
                        )
                        if (!isInitializing.current) {
                            form.setFieldsValue({ gadm2_gid: undefined })
                            gadm2State.reset()
                        }
                    }}
                />
            )
        } else if (field.key === "gadm2_gid") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    labelInValue
                    options={gadm2SelectOpts}
                    loading={gadm2Loading}
                    disabled={!gadm1ParentGid}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={gadm2State.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) gadm2State.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, gadm2Loading)}
                    onChange={(value) => {
                        const id = gadmWatchToGid(value)
                        gadm2State.setCurrentOption(
                            id ? gadm2Options.find((option) => option.gid === id) ?? null : null,
                        )
                    }}
                />
            )
        } else if (field.key === "iho_id") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    labelInValue
                    options={ihoOptions.map(opt => ({
                        label: opt.name,
                        value: Number(opt.gid ?? opt.id),
                    }))}
                    loading={ihoLoading}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={ihoState.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) ihoState.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, ihoLoading)}
                    onChange={(value) => {
                        const rawId =
                            value && typeof value === "object" && "value" in value
                                ? value.value
                                : value
                        const id = Number(rawId)
                        ihoState.setCurrentOption(
                            Number.isFinite(id)
                                ? ihoOptions.find((option) => Number(option.gid ?? option.id) === id) ?? null
                                : null,
                        )
                    }}
                />
            )
        } else if (field.key === "realm_id") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={realmOptions.map(opt => ({ label: opt.name, value: opt.id }))}
                    loading={realmLoading}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={realmState.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) realmState.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, realmLoading)}
                    onChange={(value) => {
                        realmState.setCurrentOption(
                            value == null
                                ? null
                                : realmOptions.find((option) => option.id === Number(value)) ?? null,
                        )
                        if (!isInitializing.current) {
                            form.setFieldsValue({
                                biome_id: undefined,
                                functional_type_id: undefined,
                            })
                            biomeState.reset()
                            functionalTypeState.reset()
                        }
                    }}
                />
            )
        } else if (field.key === "biome_id") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={biomeOptions.map(opt => ({ label: opt.name, value: opt.id }))}
                    loading={biomeLoading}
                    disabled={!hasRealm}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={biomeState.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) biomeState.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, biomeLoading)}
                    onChange={(value) => {
                        biomeState.setCurrentOption(
                            value == null
                                ? null
                                : biomeOptions.find((option) => option.id === Number(value)) ?? null,
                        )
                        if (!isInitializing.current) {
                            form.setFieldsValue({ functional_type_id: undefined })
                            functionalTypeState.reset()
                        }
                    }}
                />
            )
        } else if (field.key === "functional_type_id") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={functionalTypeOptions.map(opt => ({ label: opt.name, value: opt.id }))}
                    loading={functionalTypeLoading}
                    disabled={!hasBiome}
                    allowClear
                    showSearch
                    filterOption={false}
                    onSearch={functionalTypeState.search}
                    onPopupScroll={(event) => {
                        if (isSelectScrollNearBottom(event.currentTarget)) functionalTypeState.loadNext()
                    }}
                    popupRender={(menu) => renderPagedPopup(menu, functionalTypeLoading)}
                    onChange={(value) => {
                        functionalTypeState.setCurrentOption(
                            value == null
                                ? null
                                : functionalTypeOptions.find((option) => option.id === Number(value)) ?? null,
                        )
                    }}
                />
            )
        } else if (field.type === "select") {
            innerElement = (
                <Select
                    className="form-drawer-select"
                    classNames={{ popup: { root: "form-drawer-select-popup" } }}
                    options={(field.options || []).map((opt) =>
                        typeof opt === "string"
                            ? { label: opt, value: opt }
                            : { label: opt.label, value: String(opt.value) },
                    )}
                    allowClear
                />
            )
        }

        const needsLocationDeps = (
            field.key === "latitude" ||
            field.key === "longitude" ||
            field.key === "gadm0_gid" ||
            field.key === "gadm1_gid" ||
            field.key === "gadm2_gid" ||
            field.key === "iho_id"
        )

        return (
            <Form.Item
                key={field.key}
                name={field.key}
                label={renderFieldLabel(field)}
                dependencies={needsLocationDeps ? [...SITE_LOCATION_DEPENDENCIES] : undefined}
                validateTrigger={needsLocationDeps ? ["onChange", "onBlur"] : undefined}
                validateFirst={needsLocationDeps}
                rules={fieldRules(field)}
            >
                {innerElement}
            </Form.Item>
        )
    }

    const coordKeys = new Set(["latitude", "longitude"])
    const nameFields = fields.filter(f => f.key === "name")
    const coordFieldsOrdered = fields.filter(f => coordKeys.has(f.key))
    const remainingFields = fields.filter(f => f.key !== "name" && !coordKeys.has(f.key))
    const orderedFields = [...nameFields, ...coordFieldsOrdered, ...remainingFields]

    return (
        <ConfigProvider theme={drawerTheme}>
            <FormDrawer
                maskClosable={false}
                closable={false}
                title={mode === "edit" ? "Edit Site" : "New Site"}
                placement="right"
                onClose={onClose}
                open={open}
                styles={{
                    wrapper: {
                        width: mode === "add" ? 480 : 800,
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
                            Save
                        </Button>
                    </Space>
                }
            >
                <CustomScrollArea variant="fill">
                    <Form
                        form={form}
                        layout="vertical"
                        onFinish={onSubmit}
                        requiredMark={renderRequiredMark}
                        disabled={submitting}
                        className="shared-drawer-form"
                        style={{ padding: "24px" }}
                    >
                        {mode === "add" ? (
                            <div className="form-drawer-layout">
                                <div className="form-drawer-main-col">
                                    {orderedFields.map(f => renderSiteFieldItem(f))}
                                </div>
                            </div>
                        ) : (
                            <div className="form-drawer-layout">
                                <div className="form-drawer-main-col">
                                    {orderedFields.map(f => renderSiteFieldItem(f))}
                                </div>
                                <div className="form-drawer-side-col">
                                    {initialData && (
                                        <>
                                            <Form.Item label="ID" required={false}>
                                                <Input readOnly value={initialData.site_id} />
                                            </Form.Item>
                                            <Form.Item label="UUID" required={false}>
                                                <Input readOnly value={String(initialData.uuid ?? "")} />
                                            </Form.Item>
                                            <Form.Item label="Creator" required={false}>
                                                <Input
                                                    readOnly
                                                    value={
                                                        (initialData as { creator_name?: string }).creator_name ??
                                                        (initialData as { creator?: string }).creator ??
                                                        ""
                                                    }
                                                />
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
