import { useEffect, useState } from "react"
import { Cookie } from "lucide-react"
import { Button } from "@/components/ui"
import { PrivacyPreferenceCenter } from "@/features/home/components/PrivacyPreferenceCenter"
import {
    COOKIE_CONSENT_KEY,
    COOKIE_PREFERENCES_OPEN_EVENT,
    openCookiePreferences,
    saveCookieSettings,
    subscribeCookiePreferencesChange,
} from "@/features/home/cookieConsent"
import "./CookieConsentBanner.css"

export function CookieConsentBanner() {
    const [visible, setVisible] = useState(false)
    const [preferencesOpen, setPreferencesOpen] = useState(false)

    useEffect(() => {
        const syncConsent = () => {
            setVisible(window.localStorage.getItem(COOKIE_CONSENT_KEY) == null)
        }

        syncConsent()
        const unsubscribe = subscribeCookiePreferencesChange(syncConsent)
        const handleOpenPreferences = () => setPreferencesOpen(true)
        window.addEventListener(COOKIE_PREFERENCES_OPEN_EVENT, handleOpenPreferences)

        return () => {
            unsubscribe()
            window.removeEventListener(COOKIE_PREFERENCES_OPEN_EVENT, handleOpenPreferences)
        }
    }, [])

    const handleConsent = (functional: boolean, consent: "accepted" | "rejected") => {
        saveCookieSettings(functional, consent)
        setVisible(false)
    }

    return (
        <>
            <div
                className={`cookie-consent-banner${visible ? " is-visible" : ""}`}
                role="dialog"
                aria-label="Cookie Settings"
                aria-hidden={!visible}
            >
                <div className="cookie-consent-banner__header">
                    <Cookie size={24} aria-hidden />
                    <span>Cookie Settings</span>
                </div>
                <p className="cookie-consent-banner__text">
                    We use cookies to improve your experience and analyze our traffic. By clicking "Accept", you consent to our use of cookies.
                </p>
                <div className="cookie-consent-banner__actions">
                    <Button type="primary" onClick={openCookiePreferences}>Manage Cookies</Button>
                    <Button onClick={() => handleConsent(false, "rejected")}>Reject</Button>
                    <Button type="primary" onClick={() => handleConsent(true, "accepted")}>Accept</Button>
                </div>
            </div>

            <PrivacyPreferenceCenter
                isOpen={preferencesOpen}
                onClose={() => setPreferencesOpen(false)}
                onSaved={() => {
                    setVisible(false)
                    setPreferencesOpen(false)
                }}
            />
        </>
    )
}
