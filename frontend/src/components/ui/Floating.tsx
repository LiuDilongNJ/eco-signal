import { Popover as AntPopover, Tooltip as AntTooltip } from "antd"
import type { PopoverProps, TooltipProps } from "antd"
import { cn } from "@/lib/utils"

export function Tooltip({ mouseEnterDelay = 0.5, ...props }: TooltipProps) {
    const { overlayClassName, rootClassName, ...tooltipProps } = props
    return (
        <AntTooltip
            mouseEnterDelay={mouseEnterDelay}
            rootClassName={cn("es-tooltip", rootClassName, overlayClassName)}
            {...tooltipProps}
        />
    )
}

export function Popover({ overlayClassName, ...props }: PopoverProps) {
    const { rootClassName, ...popoverProps } = props
    return (
        <AntPopover
            rootClassName={cn("es-popover", rootClassName, overlayClassName)}
            {...popoverProps}
        />
    )
}
