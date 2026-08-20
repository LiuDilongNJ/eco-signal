import { Button as ESButton, PageContainer, PageContent, Section, Skeleton } from "@/components/ui"
import { useEffect, useMemo, useState, type ReactNode } from "react"
import { ConfigProvider } from "@/components/ui"
import {
    Sliders,
    User,
    Settings as SettingsIcon,
    Moon,
    Sun,
    Info,
    Camera,
    Aperture,
    Cpu,
    GitBranch,
    Globe,
    Mic,
    Mic2,
    ScrollText,
    AudioLines,
} from "lucide-react"
import { Link, useSearchParams } from "react-router-dom"
import { UserPreferencesTab } from "../components/pages/UserPreferencesTab"
import { UserProfileTab } from "../components/pages/UserProfileTab"
import { FederationSettingsTab } from "../components/pages/FederationSettingsTab"
import { CameraSettingsTab } from "../components/pages/CameraSettingsTab"
import { LensSettingsTab } from "../components/pages/LensSettingsTab"
import { SensorSettingsTab } from "../components/pages/SensorSettingsTab"
import { TaxonSettingsTab } from "../components/pages/TaxonSettingsTab"
import { RecorderSettingsTab } from "../components/pages/RecorderSettingsTab"
import MicrophoneSettingsTab from "../components/pages/MicrophoneSettingsTab"
import { SystemLogsTab } from "../components/pages/SystemLogsTab"
import { SoundSettingsTab } from "../components/pages/SoundSettingsTab"
import { useAppStore } from "@/store/useAppStore"
import { usersApi } from "@/api/endpoints/users"
import { authUtils } from "@/utils/auth"
import { UserMenu } from "../../project/components/nav/UserMenu"
import { useAppDefaultAntdBrandConfig } from "../../project/hooks/useAntdBrandConfig"
import { NAV_BAR_ICON_SIZE } from "../../project/components/nav/navBarIconSize"
import { CustomScrollArea } from "@/components/ui"
import "../../project/project.css" // Import project CSS for top-nav styling on direct load
import "../../project/data-timeline.css"
import "../../project/components/data/styles/DataPageLayout.css"
import "../../project/components/modals/styles/FormDrawer.css"
import "./SettingsPage.css"

function SettingsNavBar() {
    const { effectiveTheme, toggleTheme } = useAppStore()

    return (
        <nav className="project-nav-bar">
            <div className="nav-left">
                <div className="nav-capsule-box">
                    <Link className="nav-logo" to="/">
                        <div className="logo-icon-box">
                            <img src="/images/biosounds_logo_small.png" alt="" aria-hidden="true" />
                        </div>
                        <span>ecoSound-web</span>
                    </Link>
                </div>
            </div>

            <div className="nav-right">
                <div className="nav-capsule-box">
                    <ESButton appearance="unstyled"
                        className="nav-btn-simple"
                        onClick={toggleTheme}
                        title="Switch Theme"
                        type="button"
                    >
                        {effectiveTheme === "dark" ? <Sun size={NAV_BAR_ICON_SIZE} /> : <Moon size={NAV_BAR_ICON_SIZE} />}
                    </ESButton>
                    <div className="nav-divider" />
                    <ESButton appearance="unstyled" className="nav-btn-simple" title="Information" type="button">
                        <Info size={NAV_BAR_ICON_SIZE} />
                    </ESButton>
                    <div className="nav-divider" />
                    <UserMenu />
                </div>
            </div>
        </nav>
    )
}

type SettingsTabId =
    | "preferences"
    | "profile"
    | "federation"
    | "camera"
    | "lenses"
    | "sensor"
    | "taxon"
    | "sounds"
    | "recorders"
    | "microphones"
    | "operation-logs"

type SettingsTabConfig = {
    id: SettingsTabId
    label: string
    icon: typeof Sliders
    adminOnly?: boolean
    tableFill?: boolean
    render: () => ReactNode
}

const SETTINGS_TABS: SettingsTabConfig[] = [
    {
        id: "profile",
        label: "Profile",
        icon: User,
        render: () => <UserProfileTab />,
    },
    {
        id: "preferences",
        label: "Preferences",
        icon: Sliders,
        render: () => <UserPreferencesTab />,
    },
    {
        id: "sensor",
        label: "Sensor",
        icon: Cpu,
        adminOnly: true,
        tableFill: true,
        render: () => <SensorSettingsTab />,
    },
    {
        id: "recorders",
        label: "Recorders",
        icon: Mic,
        adminOnly: true,
        tableFill: true,
        render: () => <RecorderSettingsTab />,
    },
    {
        id: "microphones",
        label: "Microphones",
        icon: Mic2,
        adminOnly: true,
        tableFill: true,
        render: () => <MicrophoneSettingsTab />,
    },
    {
        id: "camera",
        label: "Cameras",
        icon: Camera,
        adminOnly: true,
        tableFill: true,
        render: () => <CameraSettingsTab />,
    },
    {
        id: "lenses",
        label: "Lenses",
        icon: Aperture,
        adminOnly: true,
        tableFill: true,
        render: () => <LensSettingsTab />,
    },
    {
        id: "taxon",
        label: "Taxa",
        icon: GitBranch,
        adminOnly: true,
        tableFill: true,
        render: () => <TaxonSettingsTab />,
    },
    {
        id: "sounds",
        label: "Sounds",
        icon: AudioLines,
        adminOnly: true,
        tableFill: true,
        render: () => <SoundSettingsTab />,
    },
    {
        id: "federation",
        label: "Server",
        icon: Globe,
        adminOnly: true,
        render: () => <FederationSettingsTab />,
    },
    {
        id: "operation-logs",
        label: "System Logs",
        icon: ScrollText,
        adminOnly: true,
        tableFill: true,
        render: () => <SystemLogsTab />,
    },
]
const DEFAULT_SETTINGS_TAB = SETTINGS_TABS[0]!
const SETTINGS_TAB_IDS = new Set<SettingsTabId>(SETTINGS_TABS.map((tab) => tab.id))
const SETTINGS_GROUP_START_IDS = new Set<SettingsTabId>(["sensor", "taxon", "federation"])

function parseSettingsTabParam(value: string | null): SettingsTabId | null {
    if (!value || !SETTINGS_TAB_IDS.has(value as SettingsTabId)) return null
    return value as SettingsTabId
}

export default function SettingsPage() {
    const [searchParams, setSearchParams] = useSearchParams()
    const tabParam = searchParams.get("tab")
    const isDark = useAppStore((s) => s.effectiveTheme === "dark")
    const settingsAntdTheme = useAppDefaultAntdBrandConfig(isDark)
    const [meIsAdmin, setMeIsAdmin] = useState(false)
    const [meLoaded, setMeLoaded] = useState(false)
    const [meFetchGen, setMeFetchGen] = useState(0)

    useEffect(() => {
        const onAuth = () => setMeFetchGen((n) => n + 1)
        window.addEventListener("eco-auth-change", onAuth)
        return () => window.removeEventListener("eco-auth-change", onAuth)
    }, [])

    useEffect(() => {
        const token = authUtils.getToken()
        if (!token) {
            setMeIsAdmin(false)
            setMeLoaded(true)
            return
        }
        let cancelled = false
        setMeLoaded(false)
        ;(async () => {
            try {
                const res = await usersApi.getMe({ ignoreUnauthorized: true })
                if (cancelled) return
                setMeIsAdmin(!!res.data?.is_admin)
            } catch {
                if (!cancelled) setMeIsAdmin(false)
            } finally {
                if (!cancelled) setMeLoaded(true)
            }
        })()
        return () => {
            cancelled = true
        }
    }, [meFetchGen])

    const visibleTabs = useMemo(
        () => SETTINGS_TABS.filter((tab) => meIsAdmin || !tab.adminOnly),
        [meIsAdmin],
    )
    const defaultTabId = visibleTabs[0]?.id ?? DEFAULT_SETTINGS_TAB.id

    const activeTabConfig = useMemo(() => {
        const parsed = parseSettingsTabParam(tabParam)
        if (parsed) {
            const tab = SETTINGS_TABS.find((item) => item.id === parsed)
            if (tab) return tab
        }
        return visibleTabs[0] ?? DEFAULT_SETTINGS_TAB
    }, [tabParam, visibleTabs])

    const ActiveTabIcon = activeTabConfig.icon

    const selectTab = (tabId: SettingsTabId) => {
        const next = new URLSearchParams(searchParams)
        if (tabId === defaultTabId) {
            next.delete("tab")
        } else {
            next.set("tab", tabId)
        }
        setSearchParams(next, { replace: true })
    }

    useEffect(() => {
        if (!meLoaded) return

        const parsed = parseSettingsTabParam(tabParam)
        const resolvedId = activeTabConfig.id
        if (parsed === resolvedId) return

        const next = new URLSearchParams(searchParams)
        if (resolvedId === defaultTabId) {
            next.delete("tab")
        } else {
            next.set("tab", resolvedId)
        }
        setSearchParams(next, { replace: true })
    }, [activeTabConfig.id, defaultTabId, meLoaded, searchParams, setSearchParams, tabParam])

    return (
        <ConfigProvider theme={settingsAntdTheme}>
        <PageContainer className="settings-page">
            <SettingsNavBar />

            <PageContent className="content-wrapper">
                <Section className="data-layout">
                <div className="data-nav">
                    <div className="data-nav-header">
                        <span className="data-nav-title">
                            <SettingsIcon size={18} className="data-nav-title__icon" aria-hidden />
                            Settings
                        </span>
                    </div>
                    <nav className="data-nav-list" aria-label="Settings sections">
                        {!meLoaded ? (
                            <Skeleton className="settings-page__nav-skeleton" lines={4} height={32} />
                        ) : visibleTabs.map((tab) => {
                            const Icon = tab.icon
                            const groupStartClass = SETTINGS_GROUP_START_IDS.has(tab.id)
                                ? " data-nav-item--group-start"
                                : ""
                            return (
                                <ESButton appearance="unstyled"
                                    key={tab.id}
                                    type="button"
                                    className={`data-nav-item${groupStartClass} ${activeTabConfig.id === tab.id ? "active" : ""}`}
                                    onClick={() => selectTab(tab.id)}
                                >
                                    <Icon size={16} aria-hidden />
                                    <span>{tab.label}</span>
                                </ESButton>
                            )
                        })}
                    </nav>
                </div>

                {!meLoaded ? (
                    <div className="data-content settings-page__content settings-page__content--form">
                        <Skeleton className="settings-page__content-skeleton" lines={6} height={32} />
                    </div>
                ) : activeTabConfig.tableFill ? (
                    activeTabConfig.render()
                ) : (
                    <div className="data-content settings-page__content settings-page__content--form">
                        <div className="data-toolbar">
                            <div className="data-toolbar-left">
                                <h2 className="data-table-title">
                                    <ActiveTabIcon size={20} aria-hidden />
                                    {activeTabConfig.label}
                                </h2>
                            </div>
                        </div>
                        <CustomScrollArea
                            variant="fill"
                            className="settings-page__content-inner"
                            bodyClassName="settings-page__content-scroll-body"
                            contentFingerprint={activeTabConfig.id}
                        >
                            {activeTabConfig.render()}
                        </CustomScrollArea>
                    </div>
                )}
                </Section>
            </PageContent>
        </PageContainer>
        </ConfigProvider>
    )
}
