import { Drawer, type DrawerProps } from "antd"
import { useLocation } from "react-router-dom"
import { useStageOverlayRoot } from "@/providers/StageOverlayContext"

export type StageDrawerProps = DrawerProps

export function StageDrawer({
    rootClassName,
    getContainer,
    destroyOnHidden = true,
    ...props
}: StageDrawerProps) {
    const overlayRoot = useStageOverlayRoot()
    const location = useLocation()
    const routeRootClassName = location.pathname.startsWith("/settings")
        ? "settings-stage-drawer"
        : ""

    const mergedRootClassName = [
        "app-stage-drawer",
        routeRootClassName,
        rootClassName,
    ].filter(Boolean).join(" ")

    return (
        <Drawer
            {...props}
            destroyOnHidden={destroyOnHidden}
            getContainer={getContainer ?? (() => overlayRoot ?? document.body)}
            rootClassName={mergedRootClassName}
        />
    )
}
