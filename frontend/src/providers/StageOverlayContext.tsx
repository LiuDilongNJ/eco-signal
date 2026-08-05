import { createContext, useContext, useRef, type RefObject } from "react"

export const APP_OVERLAY_ROOT_ID = "app-overlay-root"

const StageOverlayContext = createContext<RefObject<HTMLDivElement> | null>(null)

export function StageOverlayProvider({ children }: { children: React.ReactNode }) {
    const overlayRef = useRef<HTMLDivElement>(null)

    return (
        <StageOverlayContext.Provider value={overlayRef}>
            {children}
        </StageOverlayContext.Provider>
    )
}

export function StageOverlayRoot() {
    const overlayRef = useContext(StageOverlayContext)

    return (
        <div
            id={APP_OVERLAY_ROOT_ID}
            ref={overlayRef}
            className="app-overlay-root"
        />
    )
}

export function useStageOverlayRoot(): HTMLElement | null {
    const overlayRef = useContext(StageOverlayContext)
    return overlayRef?.current ?? document.getElementById(APP_OVERLAY_ROOT_ID)
}

/** Mount Ant Design popups inside the scaled stage overlay (matches viewport scale). */
export function getStagePopupContainer(triggerNode?: HTMLElement): HTMLElement {
    const settingsRoot = triggerNode?.closest(".settings-page, .settings-stage-drawer")
    if (settingsRoot instanceof HTMLElement) return settingsRoot
    const overlayRoot = document.getElementById(APP_OVERLAY_ROOT_ID)
    if (overlayRoot) return overlayRoot
    return triggerNode?.parentElement ?? document.body
}
