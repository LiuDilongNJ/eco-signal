import { useEffect, useMemo, useState } from "react"
import { ArrowLeft, X } from "lucide-react"
import { Button, Label, Switch } from "@/components/ui"
import { cookiesForCategory, type CookieCategory } from "../cookieCatalog"
import {
    readCookiePreferences,
    saveCookieSettings,
    type CookieConsent,
} from "../cookieConsent"
import "./PrivacyPreferenceCenter.css"

type CookieSectionKey = "privacy" | "necessary" | "functional"

interface PrivacyPreferenceCenterProps {
    isOpen: boolean
    onClose: () => void
    onSaved?: (functional: boolean, consent: CookieConsent) => void
}

export function PrivacyPreferenceCenter({
    isOpen,
    onClose,
    onSaved,
}: PrivacyPreferenceCenterProps) {
    const [activeSection, setActiveSection] = useState<CookieSectionKey>("privacy")
    const [functionalCookiesEnabled, setFunctionalCookiesEnabled] = useState(false)
    const [detailsOpen, setDetailsOpen] = useState(false)
    const disclosureHost = useMemo(
        () => (typeof window !== "undefined" && window.location.host ? window.location.host : "localhost"),
        [],
    )

    useEffect(() => {
        if (!isOpen) return
        setActiveSection("privacy")
        setDetailsOpen(false)
        setFunctionalCookiesEnabled(readCookiePreferences().functional)
    }, [isOpen])

    useEffect(() => {
        if (!isOpen) return
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose()
        }
        document.addEventListener("keydown", handleKeyDown)
        return () => document.removeEventListener("keydown", handleKeyDown)
    }, [isOpen, onClose])

    const selectSection = (section: CookieSectionKey) => {
        setActiveSection(section)
        setDetailsOpen(false)
    }

    const persistChoice = (functional: boolean, consent: CookieConsent) => {
        saveCookieSettings(functional, consent)
        setFunctionalCookiesEnabled(functional)
        onSaved?.(functional, consent)
        onClose()
    }

    const renderCookieDetails = (category: CookieCategory) => {
        const items = cookiesForCategory(category)
        return (
            <div className="cookie-details">
                <Button
                    appearance="unstyled"
                    type="button"
                    className="cookie-preference-link cookie-details-back"
                    onClick={() => setDetailsOpen(false)}
                >
                    <ArrowLeft size={18} />
                    Back
                </Button>
                <h3 className="cookie-details-heading">First Party Cookies</h3>
                <div className="cookie-details-list">
                    {items.map((entry) => (
                        <article key={entry.name} className="cookie-details-card">
                            <dl className="cookie-details-grid">
                                <dt className="cookie-details-label">Name</dt>
                                <dd className="cookie-details-value">{entry.name}</dd>
                                <dt className="cookie-details-label">Host</dt>
                                <dd className="cookie-details-value">{disclosureHost}</dd>
                                <dt className="cookie-details-label">Duration</dt>
                                <dd className="cookie-details-value">{entry.duration}</dd>
                                <dt className="cookie-details-label">Type</dt>
                                <dd className="cookie-details-value">First Party</dd>
                                <dt className="cookie-details-label">Category</dt>
                                <dd className="cookie-details-value">{entry.category}</dd>
                                <dt className="cookie-details-label">Description</dt>
                                <dd className="cookie-details-value">{entry.description}</dd>
                            </dl>
                        </article>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div
            className={`cookie-preference-modal${isOpen ? " active" : ""}`}
            onClick={onClose}
            aria-hidden={!isOpen}
        >
            <div
                className="cookie-preference-panel"
                role="dialog"
                aria-modal="true"
                aria-labelledby="privacy-preference-center-title"
                onClick={(event) => event.stopPropagation()}
            >
                <div className="cookie-preference-top">
                    <h2 id="privacy-preference-center-title">Privacy Preference Center</h2>
                    <Button
                        appearance="unstyled"
                        className="cookie-preference-close"
                        onClick={onClose}
                        aria-label="Close cookie preferences"
                    >
                        <X size={20} />
                    </Button>
                </div>

                <div className="cookie-preference-body">
                    <div className="cookie-preference-menu" role="tablist" aria-label="Cookie preference sections">
                        <Button
                            appearance="unstyled"
                            type="button"
                            role="tab"
                            aria-selected={activeSection === "privacy"}
                            className={`cookie-preference-menu-item${activeSection === "privacy" ? " active" : ""}`}
                            onClick={() => selectSection("privacy")}
                        >
                            Your Privacy
                        </Button>
                        <Button
                            appearance="unstyled"
                            type="button"
                            role="tab"
                            aria-selected={activeSection === "necessary"}
                            className={`cookie-preference-menu-item${activeSection === "necessary" ? " active" : ""}`}
                            onClick={() => selectSection("necessary")}
                        >
                            Strictly Necessary Cookies
                        </Button>
                        <Button
                            appearance="unstyled"
                            type="button"
                            role="tab"
                            aria-selected={activeSection === "functional"}
                            className={`cookie-preference-menu-item${activeSection === "functional" ? " active" : ""}`}
                            onClick={() => selectSection("functional")}
                        >
                            Functional Cookies
                        </Button>
                    </div>

                    <div className="cookie-preference-content" role="tabpanel">
                        {activeSection === "privacy" ? (
                            <>
                                <div className="cookie-preference-title-row">
                                    <h3>Your Privacy</h3>
                                </div>
                                <p>
                                    When you visit any website, it may store or retrieve information on your browser,
                                    mostly in the form of cookies. This information may be about you, your preferences
                                    or your device and is mostly used to make the site work as you expect it to.
                                </p>
                                <p>
                                    Because we respect your right to privacy, you can choose not to allow some types
                                    of cookies. Click on the different category headings to find out more and change
                                    our default settings.
                                </p>
                            </>
                        ) : null}

                        {activeSection === "necessary" ? (
                            detailsOpen ? renderCookieDetails("Strictly Necessary Cookies") : (
                                <>
                                    <div className="cookie-preference-title-row">
                                        <h3>Strictly Necessary Cookies</h3>
                                        <span className="cookie-preference-state">Always Active</span>
                                    </div>
                                    <p>
                                        These cookies are necessary for the website to function and cannot be switched off
                                        in our systems. They are usually only set in response to actions made by you which
                                        amount to a request for services.
                                    </p>
                                    <p>
                                        You can set your browser to block or alert you about these cookies, but some parts
                                        of the site will not then work.
                                    </p>
                                    <Button
                                        appearance="unstyled"
                                        className="cookie-preference-link"
                                        type="button"
                                        onClick={() => setDetailsOpen(true)}
                                    >
                                        Cookies Details
                                    </Button>
                                </>
                            )
                        ) : null}

                        {activeSection === "functional" ? (
                            detailsOpen ? renderCookieDetails("Functional Cookies") : (
                                <>
                                    <div className="cookie-preference-title-row">
                                        <h3>Functional Cookies</h3>
                                        <Label className="cookie-toggle">
                                            <span>Active</span>
                                            <Switch
                                                checked={functionalCookiesEnabled}
                                                onChange={setFunctionalCookiesEnabled}
                                                aria-label="Enable functional cookies"
                                            />
                                        </Label>
                                    </div>
                                    <p>
                                        These cookies enable the website to provide enhanced functionality and
                                        personalization. They may be set by us or by third-party providers whose services
                                        we have added to our pages.
                                    </p>
                                    <p>
                                        If you do not allow these cookies then some or all of these services may not
                                        function properly.
                                    </p>
                                    <Button
                                        appearance="unstyled"
                                        className="cookie-preference-link"
                                        type="button"
                                        onClick={() => setDetailsOpen(true)}
                                    >
                                        Cookies Details
                                    </Button>
                                </>
                            )
                        ) : null}
                    </div>
                </div>

                <div className="cookie-preference-footer">
                    <Button
                        onClick={() => persistChoice(functionalCookiesEnabled, "customized")}
                    >
                        Confirm My Choices
                    </Button>
                    <div className="cookie-preference-footer-right">
                        <Button
                            type="primary"
                            onClick={() => persistChoice(true, "accepted")}
                        >
                            Accept All
                        </Button>
                        <Button
                            onClick={() => persistChoice(false, "rejected")}
                        >
                            Refuse All
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    )
}
