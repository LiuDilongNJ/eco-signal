import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { AuthLoginHost } from "@/components/auth/AuthLoginHost"
import { AuthSessionWatcher } from "@/components/auth/AuthSessionWatcher"
import { CookieConsentBanner } from "@/components/cookie/CookieConsentBanner"
import { AppProviders } from "@/providers/AppProviders"
import { StageOverlayProvider, StageOverlayRoot } from "@/providers/StageOverlayContext"
import { AppRouter } from "@/router"
import { useAppStore } from "@/store/useAppStore"

const DESIGN_WIDTH = 1900
const DESIGN_HEIGHT = 900

const ZOOM_HOTKEY_CODES = new Set([
    "Equal",
    "Minus",
    "NumpadAdd",
    "NumpadSubtract",
    "Numpad0",
    "Digit0",
])

const OUTER_RESIZE_THRESHOLD_PX = 8

type ViewportSize = { width: number; height: number }

function readLayoutSize(): ViewportSize {
    return {
        width: window.innerWidth,
        height: window.innerHeight,
    }
}

function readVisibleViewport(): ViewportSize {
    return {
        width: window.innerWidth,
        height: window.innerHeight,
    }
}

/** 检测浏览器页面缩放（含 Chrome 工具栏 +/-） */
function readBrowserZoomScale(layoutBaseline: ViewportSize, dprBaseline: number): number {
    if (dprBaseline > 0) {
        const dprRatio = window.devicePixelRatio / dprBaseline
        if (Number.isFinite(dprRatio) && dprRatio > 0 && Math.abs(dprRatio - 1) > 0.005) {
            return dprRatio
        }
    }

    const vvScale = window.visualViewport?.scale
    if (typeof vvScale === "number" && Number.isFinite(vvScale) && Math.abs(vvScale - 1) > 0.005) {
        return vvScale
    }

    if (layoutBaseline.width > 0) {
        const ratio = layoutBaseline.width / window.innerWidth
        if (Number.isFinite(ratio) && ratio > 0 && Math.abs(ratio - 1) > 0.005) {
            return ratio
        }
    }

    return 1
}

function App() {
    const dprBaselineRef = useRef(typeof window !== "undefined" ? window.devicePixelRatio : 1)
    const layoutBaselineRef = useRef({
        outerWidth: typeof window !== "undefined" ? window.outerWidth : 0,
        outerHeight: typeof window !== "undefined" ? window.outerHeight : 0,
        inner: {
            width: DESIGN_WIDTH,
            height: DESIGN_HEIGHT,
        } satisfies ViewportSize,
    })

    const [layoutViewport, setLayoutViewport] = useState<ViewportSize>(() => ({
        width: DESIGN_WIDTH,
        height: DESIGN_HEIGHT,
    }))
    const [visibleViewport, setVisibleViewport] = useState<ViewportSize>(() => ({
        width: DESIGN_WIDTH,
        height: DESIGN_HEIGHT,
    }))
    const [browserZoom, setBrowserZoom] = useState(1)

    useLayoutEffect(() => {
        document.documentElement.style.zoom = ""

        const syncViewport = () => {
            const outerWidth = window.outerWidth
            const outerHeight = window.outerHeight
            const baseline = layoutBaselineRef.current
            const visible = readVisibleViewport()
            const outerChanged =
                Math.abs(outerWidth - baseline.outerWidth) > OUTER_RESIZE_THRESHOLD_PX ||
                Math.abs(outerHeight - baseline.outerHeight) > OUTER_RESIZE_THRESHOLD_PX
            const zoom = outerChanged ? 1 : readBrowserZoomScale(baseline.inner, dprBaselineRef.current)
            const nextLayout = {
                width: visible.width * zoom,
                height: visible.height * zoom,
            }

            setVisibleViewport(visible)
            setLayoutViewport((prev) =>
                prev.width === nextLayout.width && prev.height === nextLayout.height ? prev : nextLayout,
            )

            if (outerChanged) {
                layoutBaselineRef.current = {
                    outerWidth,
                    outerHeight,
                    inner: nextLayout,
                }
                setBrowserZoom((prev) => (Math.abs(prev - 1) > 0.005 ? 1 : prev))
                return
            }

            setBrowserZoom((prev) => (Math.abs(prev - zoom) > 0.005 ? zoom : prev))
        }

        const initial = readLayoutSize()
        layoutBaselineRef.current = {
            outerWidth: window.outerWidth,
            outerHeight: window.outerHeight,
            inner: initial,
        }
        setLayoutViewport(initial)
        setVisibleViewport(readVisibleViewport())
        setBrowserZoom(1)

        syncViewport()
        window.addEventListener("resize", syncViewport)
        window.visualViewport?.addEventListener("resize", syncViewport)
        window.visualViewport?.addEventListener("scroll", syncViewport)

        return () => {
            window.removeEventListener("resize", syncViewport)
            window.visualViewport?.removeEventListener("resize", syncViewport)
            window.visualViewport?.removeEventListener("scroll", syncViewport)
            document.documentElement.style.zoom = ""
        }
    }, [])

    useEffect(() => {
        const preventBrowserZoomHotkeys = (event: KeyboardEvent) => {
            if (!(event.ctrlKey || event.metaKey)) return
            if (
                ZOOM_HOTKEY_CODES.has(event.code) ||
                event.key === "+" ||
                event.key === "-" ||
                event.key === "=" ||
                event.key === "_"
            ) {
                event.preventDefault()
                event.stopImmediatePropagation()
            }
        }

        const preventBrowserZoomWheel = (event: WheelEvent) => {
            if (event.ctrlKey || event.metaKey) {
                event.preventDefault()
            }
        }

        const preventGestureZoom = (event: Event) => {
            event.preventDefault()
        }

        window.addEventListener("keydown", preventBrowserZoomHotkeys, true)
        window.addEventListener("wheel", preventBrowserZoomWheel, { passive: false })
        window.addEventListener("gesturestart", preventGestureZoom as EventListener, { passive: false })
        window.addEventListener("gesturechange", preventGestureZoom as EventListener, { passive: false })
        window.addEventListener("gestureend", preventGestureZoom as EventListener, { passive: false })

        return () => {
            window.removeEventListener("keydown", preventBrowserZoomHotkeys, true)
            window.removeEventListener("wheel", preventBrowserZoomWheel)
            window.removeEventListener("gesturestart", preventGestureZoom as EventListener)
            window.removeEventListener("gesturechange", preventGestureZoom as EventListener)
            window.removeEventListener("gestureend", preventGestureZoom as EventListener)
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

    const browserZoomCompensation = Math.abs(browserZoom - 1) > 0.005 ? 1 / browserZoom : 1
    const visualStageWidth = stageWidth * browserZoomCompensation
    const visualStageHeight = stageHeight * browserZoomCompensation
    const neutralizerLeft = Math.max((visibleViewport.width - visualStageWidth) / 2, 0)
    const neutralizerTop = Math.max((visibleViewport.height - visualStageHeight) / 2, 0)

    useLayoutEffect(() => {
        const root = document.documentElement
        root.style.setProperty("--app-design-width", `${contentWidth}px`)
        root.style.setProperty("--app-design-height", `${contentHeight}px`)
        root.style.setProperty("--app-layout-vw", `${contentWidth / 100}px`)
        root.style.setProperty("--app-layout-vh", `${contentHeight / 100}px`)
        root.style.setProperty("--app-stage-scale", String(scale))
        root.style.setProperty("--app-stage-width", `${stageWidth}px`)
        root.style.setProperty("--app-stage-height", `${stageHeight}px`)
        root.style.setProperty("--app-viewport-width", `${visibleViewport.width}px`)
        root.style.setProperty("--app-viewport-height", `${visibleViewport.height}px`)
        root.style.setProperty("--app-browser-zoom", String(browserZoom))
        root.style.setProperty("--app-browser-zoom-compensation", String(browserZoomCompensation))
    }, [browserZoom, browserZoomCompensation, contentHeight, contentWidth, scale, stageHeight, stageWidth, visibleViewport.height, visibleViewport.width])

    return (
        <StageOverlayProvider>
            <div className="app-fixed-shell">
                <div
                    className="app-browser-zoom-neutralizer"
                    style={{
                        left: `${neutralizerLeft}px`,
                        top: `${neutralizerTop}px`,
                        width: `${stageWidth}px`,
                        height: `${stageHeight}px`,
                        transform: browserZoomCompensation !== 1 ? `scale(${browserZoomCompensation})` : undefined,
                    }}
                >
                    <div
                        className="app-fixed-stage-slot"
                        style={{ width: `${stageWidth}px`, height: `${stageHeight}px` }}
                    >
                        <div
                            className="app-fixed-viewport"
                            style={{ transform: `scale(${scale})` }}
                        >
                            <AppProviders>
                                <AppRouter />
                                <AuthLoginHost />
                                <AuthSessionWatcher />
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
