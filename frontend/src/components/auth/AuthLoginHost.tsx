import { useEffect, useState } from "react"
import { LoginModal } from "@/components/ui"
import { AUTH_LOGIN_REQUIRED_EVENT, resetLoginRequiredDispatch } from "@/utils/auth"

export function AuthLoginHost() {
    const [showLogin, setShowLogin] = useState(false)

    useEffect(() => {
        const onLoginRequired = () => {
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
            onClose={handleClose}
            onSuccess={() => {
                handleClose()
            }}
        />
    )
}
