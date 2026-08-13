import { useEffect, useState } from "react"
import { LoginModal } from "@/components/ui"
import {
    AUTH_LOGIN_REQUIRED_EVENT,
    resetLoginRequiredDispatch,
    type LoginRequiredDetail,
    type LoginRequiredReason,
} from "@/utils/auth"

export function AuthLoginHost() {
    const [showLogin, setShowLogin] = useState(false)
    const [reason, setReason] = useState<LoginRequiredReason>("unauthorized")
    const [idleTimeoutSeconds, setIdleTimeoutSeconds] = useState(0)

    useEffect(() => {
        const onLoginRequired = (event: Event) => {
            const detail = (event as CustomEvent<LoginRequiredDetail>).detail
            setReason(detail?.reason ?? "unauthorized")
            setIdleTimeoutSeconds(detail?.idleTimeoutSeconds ?? 0)
            setShowLogin(true)
        }
        window.addEventListener(AUTH_LOGIN_REQUIRED_EVENT, onLoginRequired)
        return () => window.removeEventListener(AUTH_LOGIN_REQUIRED_EVENT, onLoginRequired)
    }, [])

    const handleClose = () => {
        setShowLogin(false)
        resetLoginRequiredDispatch()
    }

    return (
        <LoginModal
            isOpen={showLogin}
            sessionExpired={reason === "idle_timeout"}
            idleTimeoutSeconds={idleTimeoutSeconds}
            onClose={handleClose}
            onSuccess={() => {
                handleClose()
            }}
        />
    )
}
