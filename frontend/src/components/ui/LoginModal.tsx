import { useState, type FormEvent } from "react"
import { apiClient } from '@/api/client';
import { authUtils, dispatchAuthChange } from '@/utils/auth';
import { Button } from "./Button"
import { Dialog } from "./Dialog"
import { Input } from "./FormField"
import './LoginModal.css';

interface LoginModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: (username: string) => void;
}

export function LoginModal({ isOpen, onClose, onSuccess }: LoginModalProps) {
    const [loginInput, setLoginInput] = useState("");
    const [passwordInput, setPasswordInput] = useState("");
    const [loginError, setLoginError] = useState("");
    const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({});
    const [isLoading, setIsLoading] = useState(false);

    const handleLoginSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setLoginError("");

        const nextFieldErrors = {
            username: loginInput.trim() ? undefined : "Username is required",
            password: passwordInput ? undefined : "Password is required",
        };
        if (nextFieldErrors.username || nextFieldErrors.password) {
            setFieldErrors(nextFieldErrors);
            return;
        }

        setFieldErrors({});
        setIsLoading(true);

        try {
            const formData = new URLSearchParams();
            formData.append('username', loginInput);
            formData.append('password', passwordInput);

            const raw = await apiClient.post<{
                access_token?: string
            }>("/v1/auth-tokens", formData)
            const accessToken = raw?.access_token

            if (!accessToken || typeof accessToken !== "string") {
                setLoginError("Invalid login response (missing access token).")
                return
            }

            authUtils.setToken(accessToken)
            let displayName = loginInput
            try {
                const me = await apiClient.get<{
                    code: number
                    message: string
                    data?: { name?: string | null; username?: string | null }
                }>("/v1/current-user")
                const name = me?.data?.name?.trim()
                const username = me?.data?.username?.trim()
                displayName = name || username || loginInput
            } catch (profileError) {
                console.error("Failed to fetch current user after login", profileError)
            }

            authUtils.setUser(displayName)
            dispatchAuthChange();

            onSuccess(displayName);
            setLoginInput("");
            setPasswordInput("");
            setFieldErrors({});
            onClose();
        } catch (error) {
            const message = error instanceof Error ? error.message : "An error occurred during login."
            setLoginError(message)
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <Dialog open={isOpen} onClose={onClose} title="Welcome Back" width={450} rootClassName="login-modal">
            <form className="login-form" onSubmit={handleLoginSubmit} noValidate>
                {loginError ? <div className="login-error" role="alert">{loginError}</div> : null}
                <div className="login-form-field">
                    <Input
                        appearance="unstyled"
                        type="text"
                        required
                        value={loginInput}
                        onChange={(e) => {
                            const value = e.target.value;
                            setLoginInput(value);
                            if (value.trim()) {
                                setFieldErrors((prev) => ({ ...prev, username: undefined }));
                            }
                        }}
                        disabled={isLoading}
                        placeholder="Username"
                        aria-label="Username"
                        aria-invalid={Boolean(fieldErrors.username)}
                        aria-describedby={fieldErrors.username ? "login-username-error" : undefined}
                        className={fieldErrors.username ? "login-form-input--error" : undefined}
                        autoComplete="username"
                    />
                    {fieldErrors.username ? <div id="login-username-error" className="login-field-error" role="alert">{fieldErrors.username}</div> : null}
                </div>
                <div className="login-form-field">
                    <Input
                        appearance="unstyled"
                        type="password"
                        required
                        value={passwordInput}
                        onChange={(e) => {
                            const value = e.target.value;
                            setPasswordInput(value);
                            if (value) {
                                setFieldErrors((prev) => ({ ...prev, password: undefined }));
                            }
                        }}
                        disabled={isLoading}
                        placeholder="Password"
                        aria-label="Password"
                        aria-invalid={Boolean(fieldErrors.password)}
                        aria-describedby={fieldErrors.password ? "login-password-error" : undefined}
                        className={fieldErrors.password ? "login-form-input--error" : undefined}
                        autoComplete="current-password"
                    />
                    {fieldErrors.password ? <div id="login-password-error" className="login-field-error" role="alert">{fieldErrors.password}</div> : null}
                </div>
                <Button
                    type="primary"
                    htmlType="submit"
                    className="login-modal-submit-btn"
                    disabled={isLoading}
                    loading={isLoading}
                    aria-busy={isLoading}
                >
                    LOGIN
                </Button>
            </form>
        </Dialog>
    )
}
