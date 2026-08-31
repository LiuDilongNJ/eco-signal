import { Input as ESInput, Button as ESButton, Label } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useCallback, useEffect, useState } from "react"
import { message, Modal, Switch } from "@/components/ui"
import { HardDrive, RefreshCw } from "lucide-react"
import { ApiError } from "../../../../api/client"
import { networkApi, type NetworkSettings } from "../../../../api/endpoints/network"
import { systemApi, type StorageStatus } from "../../../../api/endpoints/system"
import {
    renderRequiredLabel,
    validateFederationUrl,
    validateRequiredFederationUrl,
    validateOptionalCoordRange,
    validateRequiredCoordRange,
} from "../../utils/formValidation"
import "../style/settings-forms.css"
import { formatStorageBytes, storageHealthLabel } from "../../utils/storageStatus"

type FederationField = "server_name" | "app_url" | "host_url" | "latStr" | "lonStr"

function parseOptionalCoord(s: string): number | null {
    const t = s.trim()
    if (t === "") return null
    const n = Number(t)
    return Number.isFinite(n) ? n : null
}

export function FederationSettingsTab() {
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [forbidden, setForbidden] = useState(false)
    const [storage, setStorage] = useState<StorageStatus | null>(null)
    const [storageLoading, setStorageLoading] = useState(true)
    const [storageError, setStorageError] = useState<string | null>(null)
    const [form, setForm] = useState({
        server_name: "",
        app_url: "",
        host_url: "",
        latStr: "",
        lonStr: "",
        shared: false,
        federation_secret: "",
    })
    const [fieldErrors, setFieldErrors] = useState<Partial<Record<FederationField, string>>>({})

    const applySettings = useCallback((d: NetworkSettings) => {
        setForm({
            server_name: d.server_name ?? "",
            app_url: d.app_url ?? "",
            host_url: d.host_url ?? "",
            latStr: d.latitude != null ? String(d.latitude) : "",
            lonStr: d.longitude != null ? String(d.longitude) : "",
            shared: Boolean(d.shared),
            federation_secret: d.federation_secret ?? "",
        })
    }, [])

    const load = useCallback(async () => {
        try {
            setLoading(true)
            setForbidden(false)
            const res = await networkApi.getSettings()
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Failed to load federation settings")
                return
            }
            if (res.data) applySettings(res.data)
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 403) {
                setForbidden(true)
                return
            }
            message.error(e instanceof Error ? e.message : "Failed to load federation settings")
        } finally {
            setLoading(false)
        }
    }, [applySettings])

    useEffect(() => {
        void load()
    }, [load])

    const loadStorage = useCallback(async () => {
        try {
            setStorageLoading(true)
            setStorageError(null)
            const res = await systemApi.getStorageStatus()
            if (res.code !== 0 && res.code !== 200) {
                setStorage(null)
                setStorageError(res.message || "Storage status is unavailable")
                return
            }
            setStorage(res.data ?? null)
        } catch {
            setStorage(null)
            setStorageError("Storage status is unavailable")
        } finally {
            setStorageLoading(false)
        }
    }, [])

    useEffect(() => {
        void loadStorage()
    }, [loadStorage])

    const validateForm = (): boolean => {
        const nextErrors: Partial<Record<FederationField, string>> = {}
        const serverNameError = form.server_name.trim() ? null : "Server name is required"
        const appUrlError = validateRequiredFederationUrl(form.app_url, "App URL")
        const hostUrlError = validateFederationUrl(form.host_url, "Host URL")
        const validateCoord = form.shared ? validateRequiredCoordRange : validateOptionalCoordRange
        const latError = validateCoord(form.latStr, "Latitude", -90, 90)
        const lonError = validateCoord(form.lonStr, "Longitude", -180, 180)

        if (serverNameError) nextErrors.server_name = serverNameError
        if (appUrlError) nextErrors.app_url = appUrlError
        if (latError) nextErrors.latStr = latError
        if (lonError) nextErrors.lonStr = lonError

        if (hostUrlError) nextErrors.host_url = hostUrlError

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const updateField = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => {
        setForm((p) => ({ ...p, [key]: value }))
        const errorKey = key as FederationField
        if (fieldErrors[errorKey]) {
            setFieldErrors((prev) => {
                const next = { ...prev }
                delete next[errorKey]
                return next
            })
        }
    }

    const handleSave = async () => {
        if (!validateForm()) return

        try {
            setSaving(true)
            const res = await networkApi.updateSettings({
                server_name: form.server_name.trim(),
                app_url: form.app_url.trim(),
                host_url: form.host_url.trim(),
                latitude: parseOptionalCoord(form.latStr),
                longitude: parseOptionalCoord(form.lonStr),
                shared: form.shared,
                federation_secret: form.federation_secret.trim(),
            })
            if (res.code !== 0 && res.code !== 200) {
                message.error(res.message || "Update failed")
                return
            }
            message.success("Federation settings saved")
            if (res.data) applySettings(res.data)
        } catch (e: unknown) {
            if (e instanceof ApiError && e.status === 403) {
                message.error("Administrator access required")
                return
            }
            message.error(e instanceof Error ? e.message : "Failed to save settings")
        } finally {
            setSaving(false)
        }
    }

    const handleGenerateSecret = () => {
        Modal.confirm({
            title: "Generate new federation secret?",
            content:
                "The current secret stops working immediately. All child nodes must use the new secret before they can register again.",
            okText: "Generate",
            cancelText: "Cancel",
            okButtonProps: { className: "settings-form-modal-ok" },
            cancelButtonProps: { className: "settings-form-modal-cancel" },
            onOk: async () => {
                try {
                    const res = await networkApi.generateFederationSecret()
                    if (res.code !== 0 && res.code !== 200) {
                        message.error(res.message || "Failed to generate secret")
                        return
                    }
                    message.success(res.message || "New federation secret generated")
                    if (res.data) applySettings(res.data)
                } catch (e: unknown) {
                    if (e instanceof ApiError && e.status === 403) {
                        message.error("Administrator access required")
                        return
                    }
                    message.error(e instanceof Error ? e.message : "Failed to generate secret")
                }
            },
        })
    }

    if (loading && !forbidden) {
        return <LoadingState label="Loading federation settings..." variant="inline" className="settings-form__status" />
    }

    if (forbidden) {
        return (
            <div className="settings-form__status settings-form__status--error">
                You do not have permission to view or edit federation settings (administrator required).
            </div>
        )
    }

    return (
        <div className="settings-form">
            <section className="settings-storage" aria-labelledby="server-storage-title">
                <div className="settings-storage__header">
                    <div className="settings-storage__title">
                        <HardDrive size={18} aria-hidden />
                        <h3 id="server-storage-title">Server Disk Space</h3>
                    </div>
                    <ESButton appearance="unstyled"
                        type="button"
                        className="settings-storage__refresh"
                        onClick={() => void loadStorage()}
                        disabled={storageLoading}
                    >
                        <RefreshCw size={15} aria-hidden />
                        Refresh
                    </ESButton>
                </div>

                {storageLoading ? (
                    <LoadingState label="Loading storage status..." variant="inline" size="sm" />
                ) : storageError || !storage ? (
                    <div className="settings-form__status settings-form__status--error" role="alert">
                        {storageError || "Storage status is unavailable"}
                    </div>
                ) : (
                    <div className="settings-storage__content">
                        <div className="settings-storage__summary">
                            <span>Used: {formatStorageBytes(storage.used_bytes)} / {formatStorageBytes(storage.total_bytes)}</span>
                            <span>Free: {formatStorageBytes(storage.free_bytes)}</span>
                        </div>
                        <div className="settings-storage__progress-row">
                            <div
                                className={`settings-storage__progress settings-storage__progress--${storage.status}`}
                                role="progressbar"
                                aria-label="Container disk usage"
                                aria-valuemin={0}
                                aria-valuemax={100}
                                aria-valuenow={storage.used_percent}
                            >
                                <span style={{ width: `${Math.min(Math.max(storage.used_percent, 0), 100)}%` }} />
                            </div>
                            <span className={`settings-storage__status settings-storage__status--${storage.status}`}>
                                {storageHealthLabel(storage.status)}
                            </span>
                        </div>
                        <div className="settings-storage__percent">{storage.used_percent.toFixed(1)}% full</div>
                    </div>
                )}
            </section>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="fed-server-name">
                    {renderRequiredLabel("Server name")}
                </Label>
                <ESInput appearance="unstyled"
                    id="fed-server-name"
                    className={`settings-form__input${
                        fieldErrors.server_name ? " settings-form__input--error" : ""
                    }`}
                    type="text"
                    value={form.server_name}
                    aria-required="true"
                    onChange={(e) => updateField("server_name", e.target.value)}
                />
                {fieldErrors.server_name ? (
                    <div className="settings-form__error">{fieldErrors.server_name}</div>
                ) : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="fed-app-url">
                    {renderRequiredLabel("App URL")}
                </Label>
                <ESInput appearance="unstyled"
                    id="fed-app-url"
                    className={`settings-form__input${fieldErrors.app_url ? " settings-form__input--error" : ""}`}
                    type="url"
                    value={form.app_url}
                    aria-required="true"
                    onChange={(e) => updateField("app_url", e.target.value)}
                />
                {fieldErrors.app_url ? <div className="settings-form__error">{fieldErrors.app_url}</div> : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="fed-host-url">
                    Host URL
                </Label>
                <ESInput appearance="unstyled"
                    id="fed-host-url"
                    className={`settings-form__input${fieldErrors.host_url ? " settings-form__input--error" : ""}`}
                    type="url"
                    value={form.host_url}
                    onChange={(e) => updateField("host_url", e.target.value)}
                />
                {fieldErrors.host_url ? <div className="settings-form__error">{fieldErrors.host_url}</div> : null}
            </div>

            <div className="settings-form__grid-2">
                <div className="settings-form__field">
                    <Label className="settings-form__label" htmlFor="fed-lat">
                        {form.shared ? renderRequiredLabel("Latitude") : "Latitude"}
                    </Label>
                    <ESInput appearance="unstyled"
                        id="fed-lat"
                        className={`settings-form__input${fieldErrors.latStr ? " settings-form__input--error" : ""}`}
                        type="number"
                        inputMode="decimal"
                        min={-90}
                        max={90}
                        step="any"
                        value={form.latStr}
                        aria-required={form.shared}
                        onChange={(e) => updateField("latStr", e.target.value)}
                    />
                    {fieldErrors.latStr ? <div className="settings-form__error">{fieldErrors.latStr}</div> : null}
                </div>
                <div className="settings-form__field">
                    <Label className="settings-form__label" htmlFor="fed-lon">
                        {form.shared ? renderRequiredLabel("Longitude") : "Longitude"}
                    </Label>
                    <ESInput appearance="unstyled"
                        id="fed-lon"
                        className={`settings-form__input${fieldErrors.lonStr ? " settings-form__input--error" : ""}`}
                        type="number"
                        inputMode="decimal"
                        min={-180}
                        max={180}
                        step="any"
                        value={form.lonStr}
                        aria-required={form.shared}
                        onChange={(e) => updateField("lonStr", e.target.value)}
                    />
                    {fieldErrors.lonStr ? <div className="settings-form__error">{fieldErrors.lonStr}</div> : null}
                </div>
            </div>

            <div className="settings-form__field">
                <div className="settings-form__switch-row">
                    <span className="settings-form__label">Public</span>
                    <Switch checked={form.shared} onChange={(checked) => updateField("shared", checked)} />
                </div>
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="fed-secret">
                    Federation secret
                </Label>
                <ESInput appearance="unstyled"
                    id="fed-secret"
                    className="settings-form__input settings-form__input--mono"
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    value={form.federation_secret}
                    onChange={(e) => updateField("federation_secret", e.target.value)}
                />
                <p className="settings-form__hint">
                    Used for HMAC registration headers. You can paste a shared secret or generate a new one.
                </p>
            </div>

            <div className="settings-form__actions">
                <ESButton appearance="unstyled"
                    type="button"
                    className="settings-form__btn-primary"
                    onClick={() => void handleSave()}
                    disabled={saving}
                >
                    Save
                </ESButton>
                <ESButton appearance="unstyled" type="button" className="settings-form__btn-secondary" onClick={handleGenerateSecret}>
                    Generate new secret
                </ESButton>
            </div>
        </div>
    )
}
