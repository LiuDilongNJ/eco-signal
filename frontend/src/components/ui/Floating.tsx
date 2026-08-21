import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react"
import { Popover as AntPopover, Tooltip as AntTooltip } from "antd"
import type { PopoverProps, TooltipProps } from "antd"
import { cn } from "@/lib/utils"

function stripNativeTitles(node: ReactNode): ReactNode {
    if (isValidElement(node)) {
        const children = node.props?.children
            ? stripNativeTitles(node.props.children)
            : node.props?.children

        return cloneElement(
            node as ReactElement<{ title?: string; children?: ReactNode }>,
            { title: undefined, children },
        )
    }

    return Array.isArray(node) ? Children.map(node, stripNativeTitles) : node
}

export function Tooltip({ mouseEnterDelay = 0.5, ...props }: TooltipProps) {
    const { overlayClassName, rootClassName, ...tooltipProps } = props
    const trigger = tooltipProps.title ? stripNativeTitles(tooltipProps.children) : tooltipProps.children
    return (
        <AntTooltip
            mouseEnterDelay={mouseEnterDelay}
            rootClassName={cn("es-tooltip", "es-tooltip--surface", rootClassName, overlayClassName)}
            {...tooltipProps}
            title={tooltipProps.title}
        >
            {trigger}
        </AntTooltip>
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
