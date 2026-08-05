import { Button as ESButton } from "@/components/ui"
/**
 * 与顶栏 SearchableDropdown 同构的下拉（无搜索），用于 Audio 详情工具栏等紧凑场景。
 */

import { useState, useRef, useEffect, type ReactNode } from "react"
import { Check, ChevronDown } from "lucide-react"

interface StudioCrumbDropdownItem {
    id: number | string
    label: string
}

interface StudioCrumbDropdownProps {
    items: StudioCrumbDropdownItem[]
    selectedId: number | string
    onSelect: (id: number | string) => void
    icon?: ReactNode
    title?: string
    labelWidth?: number
    dropdownMinWidth?: number
    tabularNums?: boolean
}

export function StudioCrumbDropdown({
    items,
    selectedId,
    onSelect,
    icon,
    title,
    labelWidth,
    dropdownMinWidth,
    tabularNums,
}: StudioCrumbDropdownProps) {
    const [isOpen, setIsOpen] = useState(false)
    const wrapperRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
                setIsOpen(false)
            }
        }
        document.addEventListener("click", handleClickOutside)
        return () => document.removeEventListener("click", handleClickOutside)
    }, [])

    const selectedItem = items.find((item) => String(item.id) === String(selectedId))
    const displayLabel = selectedItem?.label ?? String(selectedId)

    return (
        <div
            ref={wrapperRef}
            className={`crumb-wrapper crumb-wrapper--studio-toolbar${isOpen ? " active" : ""}`}
        >
            <ESButton appearance="unstyled"
                type="button"
                className="crumb-btn"
                title={title}
                onClick={() => setIsOpen((open) => !open)}
            >
                {icon}
                <div className="crumb-btn-content">
                    <span
                        className="block-anim"
                        style={{
                            ...(labelWidth != null
                                ? {
                                      width: labelWidth,
                                      textAlign: "center",
                                      display: "inline-block",
                                  }
                                : {}),
                            ...(tabularNums ? { fontVariantNumeric: "tabular-nums" } : {}),
                        }}
                    >
                        {displayLabel}
                    </span>
                </div>
                <ChevronDown size={14} className="crumb-btn-chevron" aria-hidden />
            </ESButton>
            <div
                className="crumb-dropdown crumb-dropdown--studio-toolbar"
                style={dropdownMinWidth != null ? { minWidth: dropdownMinWidth } : undefined}
            >
                <div className="dropdown-list-scroll">
                    {items.map((item) => {
                        const isSelected = String(item.id) === String(selectedId)
                        return (
                            <div
                                key={item.id}
                                className={`crumb-item${isSelected ? " selected" : ""}`}
                                role="option"
                                aria-selected={isSelected}
                                onClick={() => {
                                    onSelect(item.id)
                                    setIsOpen(false)
                                }}
                            >
                                <div className="crumb-item-content">
                                    <span className="crumb-item-label">{item.label}</span>
                                </div>
                                {isSelected ? (
                                    <Check className="check-icon" size={16} style={{ opacity: 1 }} />
                                ) : null}
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
