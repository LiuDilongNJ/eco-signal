import { Button as ESButton, Label } from "@/components/ui"
import { useEffect, useState } from "react"
import { Select, message } from "@/components/ui"
import { ApiError } from "../../../../api/client"
import { userPreferenceApi } from "../../../../api/endpoints/users"
import { normalizeTheme, useAppStore } from "@/store/useAppStore"
import { validateFftSize } from "../../utils/formValidation"
import "../style/settings-forms.css"

const THEME_OPTIONS = [
    { value: "auto", label: "Auto" },
    { value: "light", label: "Light" },
    { value: "dark", label: "Dark" },
]

const LANGUAGE_OPTIONS = [{ value: "en", label: "English (en)" }]

const TIMEZONE_OPTIONS = [{ value: "UTC", label: "UTC" }]
const FFT_WINDOW_SIZE_OPTIONS = ["128", "256", "512", "1024", "2048", "4096"].map((value) => ({
    value,
    label: value,
}))

export function UserPreferencesTab() {
    const { theme, persistedTheme, setTheme, applyAccountTheme } = useAppStore()
    const [preferences, setPreferences] = useState({
        fftSize: "512",
        language: "en",
        timezone: "UTC",
    })
    const [fftError, setFftError] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        let cancelled = false

        ;(async () => {
            try {
                const pref = await userPreferenceApi.get()
                if (cancelled) return

                setPreferences({
                    fftSize: pref.fft != null ? String(pref.fft) : "512",
                    language: pref.language || "en",
                    timezone: pref.timezone || "UTC",
                })

                applyAccountTheme(normalizeTheme(pref.theme))
            } catch (error: unknown) {
                if (cancelled) return
                if (!(error instanceof ApiError && error.status === 401)) {
                    message.error(error instanceof Error ? error.message : "Failed to load preferences")
                }
            }
        })()

        return () => {
            cancelled = true
        }
    }, [applyAccountTheme])

    const handleSave = async () => {
        const fftValidationError = validateFftSize(preferences.fftSize)
        if (fftValidationError) {
            setFftError(fftValidationError)
            return
        }

        setFftError(null)
        try {
            setSaving(true)
            await userPreferenceApi.patch({
                fft: Number(preferences.fftSize),
                theme,
                language: preferences.language,
                timezone: preferences.timezone,
            })
            applyAccountTheme(theme)
            message.success("Preferences saved successfully!")
        } catch (error: unknown) {
            setTheme(persistedTheme)
            message.error(error instanceof Error ? error.message : "Failed to save preferences")
        } finally {
            setSaving(false)
        }
    }

    const selectPopupProps = {
        showSearch: true,
        optionFilterProp: "label" as const,
        classNames: { popup: { root: "form-drawer-select-popup" } },
    }

    return (
        <div className="settings-form">
            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="pref-fft-size">
                    FFT Window Size
                </Label>
                <Select
                    id="pref-fft-size"
                    className={`settings-form__select-control${fftError ? " settings-form__select-control--error" : ""}`}
                    {...selectPopupProps}
                    options={FFT_WINDOW_SIZE_OPTIONS}
                    value={preferences.fftSize}
                    onChange={(value) => {
                        setPreferences((prev) => ({ ...prev, fftSize: value }))
                        if (fftError) setFftError(null)
                    }}
                />
                {fftError ? <div className="settings-form__error">{fftError}</div> : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="pref-theme">
                    Theme
                </Label>
                <Select
                    id="pref-theme"
                    className="settings-form__select-control"
                    {...selectPopupProps}
                    options={THEME_OPTIONS}
                    value={theme}
                    onChange={(value) => setTheme(value)}
                />
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="pref-language">
                    Language
                </Label>
                <Select
                    id="pref-language"
                    className="settings-form__select-control"
                    {...selectPopupProps}
                    options={LANGUAGE_OPTIONS}
                    value={preferences.language}
                    onChange={(value) =>
                        setPreferences((prev) => ({ ...prev, language: value }))
                    }
                />
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="pref-timezone">
                    Timezone
                </Label>
                <Select
                    id="pref-timezone"
                    className="settings-form__select-control"
                    {...selectPopupProps}
                    options={TIMEZONE_OPTIONS}
                    value={preferences.timezone}
                    onChange={(value) =>
                        setPreferences((prev) => ({ ...prev, timezone: value }))
                    }
                />
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
            </div>
        </div>
    )
}
