import { useEffect, useLayoutEffect, useState } from "react"
import { AuthLoginHost } from "@/components/auth/AuthLoginHost"
import { AuthSessionWatcher } from "@/components/auth/AuthSessionWatcher"
import { PermissionDeniedWatcher } from "@/components/auth/PermissionDeniedWatcher"
import { CookieConsentBanner } from "@/components/cookie/CookieConsentBanner"
import { AppProviders } from "@/providers/AppProviders"
import { StageOverlayProvider, StageOverlayRoot } from "@/providers/StageOverlayContext"
import { AppRouter } from "@/router"
import { useAppStore } from "@/store/useAppStore"

const DESIGN_WIDTH = 1900
const DESIGN_HEIGHT = 900

type ViewportSize = { width: number; height: number }

function readLayoutSize(): ViewportSize {
    return {
        width: window.innerWidth,
        height: window.innerHeight,
    }
}

function App() {
    const [layoutViewport, setLayoutViewport] = useState<ViewportSize>(() => ({
        width: DESIGN_WIDTH,
        height: DESIGN_HEIGHT,
    }))

    useLayoutEffect(() => {
        const syncViewport = () => {
            setLayoutViewport((prev) =>
                prev.width === window.innerWidth && prev.height === window.innerHeight
                    ? prev
                    : readLayoutSize(),
            )
        }

        syncViewport()
        window.addEventListener("resize", syncViewport)

        return () => {
            window.removeEventListener("resize", syncViewport)
        }
    }, [])

    useEffect(() => {
        const media = window.matchMedia("(prefers-color-scheme: dark)")
        const syncTheme = () => useAppStore.getState().syncEffectiveTheme()

        syncTheme()
        media.addEventListener("change", syncTheme)

        return () => {
            media.removeEventListener("change", syncTheme)
        }
    }, [])

    const shouldScale =
        layoutViewport.width < DESIGN_WIDTH || layoutViewport.height < DESIGN_HEIGHT
    const fitScale = Math.min(
        layoutViewport.width / DESIGN_WIDTH,
        layoutViewport.height / DESIGN_HEIGHT,
        1,
    )
    const scale = shouldScale ? fitScale : 1

    const contentWidth = scale < 1 ? Math.max(DESIGN_WIDTH, layoutViewport.width / scale) : layoutViewport.width
    const contentHeight =
        scale < 1 ? Math.max(DESIGN_HEIGHT, layoutViewport.height / scale) : layoutViewport.height

    const stageWidth = contentWidth * scale
    const stageHeight = contentHeight * scale

    useLayoutEffect(() => {
        const root = document.documentElement
        root.style.setProperty("--app-design-width", `${contentWidth}px`)
        root.style.setProperty("--app-design-height", `${contentHeight}px`)
        root.style.setProperty("--app-layout-vw", `${contentWidth / 100}px`)
        root.style.setProperty("--app-layout-vh", `${contentHeight / 100}px`)
        root.style.setProperty("--app-stage-scale", String(scale))
        root.style.setProperty("--app-stage-width", `${stageWidth}px`)
        root.style.setProperty("--app-stage-height", `${stageHeight}px`)
        root.style.setProperty("--app-viewport-width", `${layoutViewport.width}px`)
        root.style.setProperty("--app-viewport-height", `${layoutViewport.height}px`)
    }, [contentHeight, contentWidth, layoutViewport.height, layoutViewport.width, scale, stageHeight, stageWidth])

    return (
        <StageOverlayProvider>
            <div className="app-fixed-shell">
                <div
                    className="app-browser-zoom-neutralizer"
                    style={{
                        left: "0px",
                        top: "0px",
                        width: `${stageWidth}px`,
                        height: `${stageHeight}px`,
                    }}
                >
                    <div
                        className="app-fixed-stage-slot"
                        style={{ width: `${stageWidth}px`, height: `${stageHeight}px` }}
                    >
                        <div
                            className="app-fixed-viewport"
                            style={{ zoom: scale }}
                        >
                            <AppProviders>
                                <AppRouter />
                                <AuthLoginHost />
                                <AuthSessionWatcher />
                                <PermissionDeniedWatcher />
                                <CookieConsentBanner />
                            </AppProviders>
                        </div>
                        <StageOverlayRoot />
                    </div>
                </div>
            </div>
        </StageOverlayProvider>
    )
}

export default App
