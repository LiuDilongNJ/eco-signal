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
    onClick,
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
            onClick={(event) => {
                onClick?.(event)
                // 避免点击后残留 focus 导致控件被 focus 样式撑开
                if (variant === "zoom") {
                    event.currentTarget.blur()
                }
            }}
            {...buttonProps}
        >
            {icon}
        </ESButton>
    )

    return (
        <Tooltip title={getTooltipText(label)} mouseEnterDelay={0.5}>
            {buttonProps.disabled || variant === "zoom" ? (
                <span className="media-viewer-toolbar-tooltip-trigger">{button}</span>
            ) : (
                button
            )}
        </Tooltip>
    )
}
