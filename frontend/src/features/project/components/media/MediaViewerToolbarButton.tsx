import { Button as ESButton, Tooltip, getTooltipText } from "@/components/ui"
import type { ButtonHTMLAttributes, ReactNode } from "react"

type MediaViewerToolbarButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children" | "title"> & {
    icon: ReactNode
    label: string
    active?: boolean
    variant?: "toolbar" | "zoom"
}

export function MediaViewerToolbarButton({
    icon,
    label,
    active,
    variant = "toolbar",
    className = "",
    ...buttonProps
}: MediaViewerToolbarButtonProps) {
    const baseClass = variant === "zoom" ? "zoom-control-btn" : "btn-toolbar"
    const classes = [baseClass, active ? "active" : "", className].filter(Boolean).join(" ")

    const button = (
        <ESButton appearance="unstyled"
            type="button"
            className={classes}
            aria-label={label}
            aria-pressed={active}
            {...buttonProps}
        >
            {icon}
        </ESButton>
    )

    return (
        <Tooltip title={getTooltipText(label)}>
            {buttonProps.disabled ? <span className="media-viewer-toolbar-tooltip-trigger">{button}</span> : button}
        </Tooltip>
    )
}
