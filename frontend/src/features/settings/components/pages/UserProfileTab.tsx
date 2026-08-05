import { Input as ESInput, Button as ESButton, Label } from "@/components/ui"
import { CustomScrollArea } from "@/components/ui"
import { LoadingState } from "@/components/ui"
import { useState, useEffect } from "react"
import { message, Modal, Input } from "@/components/ui"
import { usersApi, UserPublic } from "../../../../api/endpoints/users"
import {
    validateHexColor,
    validateOptionalOrcid,
    validatePasswordField,
    validateRequiredEmail,
    validateRequiredName,
} from "../../utils/formValidation"
import { nullableTrimmedText, requiredTrimmedText } from "../../utils/settingsPayload"
import "../style/settings-forms.css"

type ProfileField = "name" | "email" | "orcid" | "color"
type PasswordField = "current_password" | "new_password"

export function UserProfileTab() {
    const [user, setUser] = useState<UserPublic | null>(null)
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)

    const [formData, setFormData] = useState({
        name: "",
        email: "",
        orcid: "",
        color: "#FFFFFF",
    })
    const [fieldErrors, setFieldErrors] = useState<Partial<Record<ProfileField, string>>>({})

    const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false)
    const [passwordData, setPasswordData] = useState({
        current_password: "",
        new_password: "",
    })
    const [passwordErrors, setPasswordErrors] = useState<Partial<Record<PasswordField, string>>>({})
    const [changingPassword, setChangingPassword] = useState(false)

    const fetchUser = async () => {
        try {
            setLoading(true)
            const res = await usersApi.getMe()
            setUser(res.data)
            setFormData({
                name: res.data.name || "",
                email: res.data.email || "",
                orcid: res.data.orcid || "",
                color: res.data.color || "#FFFFFF",
            })
            setFieldErrors({})
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "Failed to load user profile")
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchUser()
    }, [])

    const validateProfile = (): boolean => {
        const nextErrors: Partial<Record<ProfileField, string>> = {}
        const nameError = validateRequiredName(formData.name)
        const emailError = validateRequiredEmail(formData.email)
        const orcidError = validateOptionalOrcid(formData.orcid)
        const colorError = validateHexColor(formData.color)

        if (nameError) nextErrors.name = nameError
        if (emailError) nextErrors.email = emailError
        if (orcidError) nextErrors.orcid = orcidError
        if (colorError) nextErrors.color = colorError

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const handleSave = async () => {
        if (!user) return
        if (!validateProfile()) return

        try {
            setSaving(true)
            const color = formData.color.trim()
            await usersApi.updateMe({
                name: requiredTrimmedText(formData.name),
                email: requiredTrimmedText(formData.email),
                orcid: nullableTrimmedText(formData.orcid),
                color: color ? color.toUpperCase() : "",
            })
            message.success("Profile updated successfully!")
            await fetchUser()
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "Failed to update profile")
        } finally {
            setSaving(false)
        }
    }

    const validatePasswordForm = (): boolean => {
        const nextErrors: Partial<Record<PasswordField, string>> = {}
        const currentError = validatePasswordField(passwordData.current_password, "Current password")
        const newError = validatePasswordField(passwordData.new_password, "New password")
        if (currentError) nextErrors.current_password = currentError
        if (newError) nextErrors.new_password = newError
        setPasswordErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const handlePasswordChange = async () => {
        if (!validatePasswordForm()) return

        try {
            setChangingPassword(true)
            await usersApi.updateMyPassword({
                current_password: passwordData.current_password,
                new_password: passwordData.new_password,
            })
            message.success("Password changed successfully!")
            setIsPasswordModalOpen(false)
            setPasswordData({ current_password: "", new_password: "" })
            setPasswordErrors({})
        } catch (error: unknown) {
            message.error(error instanceof Error ? error.message : "Failed to change password")
        } finally {
            setChangingPassword(false)
        }
    }

    const updateProfileField = (field: ProfileField, value: string) => {
        setFormData((prev) => ({ ...prev, [field]: value }))
        if (fieldErrors[field]) {
            setFieldErrors((prev) => {
                const next = { ...prev }
                delete next[field]
                return next
            })
        }
    }

    if (loading && !user) {
        return <LoadingState label="Loading profile..." variant="inline" className="settings-form__status" />
    }

    if (!user) {
        return <div className="settings-form__status settings-form__status--error">Failed to load profile.</div>
    }

    return (
        <div className="settings-form">
            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="prof-name">
                    Name
                </Label>
                <ESInput appearance="unstyled"
                    id="prof-name"
                    className={`settings-form__input${fieldErrors.name ? " settings-form__input--error" : ""}`}
                    type="text"
                    value={formData.name}
                    onChange={(e) => updateProfileField("name", e.target.value)}
                    maxLength={100}
                />
                {fieldErrors.name ? <div className="settings-form__error">{fieldErrors.name}</div> : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="prof-email">
                    Email
                </Label>
                <ESInput appearance="unstyled"
                    id="prof-email"
                    className={`settings-form__input${fieldErrors.email ? " settings-form__input--error" : ""}`}
                    type="email"
                    value={formData.email}
                    onChange={(e) => updateProfileField("email", e.target.value)}
                    maxLength={100}
                />
                {fieldErrors.email ? <div className="settings-form__error">{fieldErrors.email}</div> : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="prof-orcid">
                    ORCID
                </Label>
                <ESInput appearance="unstyled"
                    id="prof-orcid"
                    className={`settings-form__input${fieldErrors.orcid ? " settings-form__input--error" : ""}`}
                    type="text"
                    value={formData.orcid}
                    onChange={(e) => updateProfileField("orcid", e.target.value)}
                    maxLength={100}
                />
                {fieldErrors.orcid ? <div className="settings-form__error">{fieldErrors.orcid}</div> : null}
            </div>

            <div className="settings-form__field">
                <Label className="settings-form__label" htmlFor="prof-color">
                    Color
                </Label>
                <div className="settings-form__color-row">
                    <ESInput appearance="unstyled"
                        id="prof-color"
                        className="settings-form__color-input"
                        type="color"
                        value={formData.color}
                        onChange={(e) => updateProfileField("color", e.target.value)}
                    />
                    <ESInput appearance="unstyled"
                        className={`settings-form__input settings-form__input--mono${fieldErrors.color ? " settings-form__input--error" : ""}`}
                        type="text"
                        value={formData.color}
                        onChange={(e) => updateProfileField("color", e.target.value)}
                        maxLength={7}
                    />
                </div>
                {fieldErrors.color ? <div className="settings-form__error">{fieldErrors.color}</div> : null}
            </div>

            <div className="settings-form__actions">
                <ESButton appearance="unstyled"
                    type="button"
                    className="settings-form__btn-primary"
                    onClick={handleSave}
                    disabled={saving}
                >
                    Save
                </ESButton>
                <ESButton appearance="unstyled"
                    type="button"
                    className="settings-form__btn-secondary"
                    onClick={() => setIsPasswordModalOpen(true)}
                >
                    Change Password
                </ESButton>
            </div>

            <Modal
                title="Change Password"
                rootClassName="settings-form-modal-root"
                open={isPasswordModalOpen}
                onOk={handlePasswordChange}
                onCancel={() => {
                    setIsPasswordModalOpen(false)
                    setPasswordData({ current_password: "", new_password: "" })
                    setPasswordErrors({})
                }}
                confirmLoading={changingPassword}
                okText="Save"
                okButtonProps={{ className: "settings-form-modal-ok" }}
                cancelButtonProps={{ className: "settings-form-modal-cancel" }}
            >
                <CustomScrollArea maxHeight={300}>
                    <div className="settings-form-modal-fields" style={{ padding: "0 4px" }}>
                        <div>
                            <div className="settings-form-modal-field-label">
                                Current Password
                            </div>
                            <Input.Password
                                className="settings-form-password-input"
                                value={passwordData.current_password}
                                status={passwordErrors.current_password ? "error" : undefined}
                                onChange={(e) => {
                                    setPasswordData((prev) => ({ ...prev, current_password: e.target.value }))
                                    if (passwordErrors.current_password) {
                                        setPasswordErrors((prev) => {
                                            const next = { ...prev }
                                            delete next.current_password
                                            return next
                                        })
                                    }
                                }}
                            />
                            {passwordErrors.current_password ? (
                                <div className="settings-form__error">{passwordErrors.current_password}</div>
                            ) : null}
                        </div>
                        <div>
                            <div className="settings-form-modal-field-label">
                                New Password
                            </div>
                            <Input.Password
                                className="settings-form-password-input"
                                value={passwordData.new_password}
                                status={passwordErrors.new_password ? "error" : undefined}
                                onChange={(e) => {
                                    setPasswordData((prev) => ({ ...prev, new_password: e.target.value }))
                                    if (passwordErrors.new_password) {
                                        setPasswordErrors((prev) => {
                                            const next = { ...prev }
                                            delete next.new_password
                                            return next
                                        })
                                    }
                                }}
                            />
                            {passwordErrors.new_password ? (
                                <div className="settings-form__error">{passwordErrors.new_password}</div>
                            ) : null}
                        </div>
                    </div>
                </CustomScrollArea>
            </Modal>
        </div>
    )
}
