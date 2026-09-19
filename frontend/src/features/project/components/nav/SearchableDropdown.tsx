import { Button as ESButton, Input as ESInput } from "@/components/ui"
/**
 * SearchableDropdown - 可搜索的下拉选择组件
 * 
 * 复用于 ProjectSelector 和 CollectionSelector
 */

import { useState, useRef, useEffect, useLayoutEffect } from "react"
import { Search, Check } from "lucide-react"
import { CustomScrollArea } from "@/components/ui"
import { EmptyState } from "@/components/ui"
import { StableText } from "@/components/ui"

interface DropdownItem {
    id: number | string
    label: string
    tag?: string
    tagVariant?: string
}

interface SearchableDropdownProps {
    items: DropdownItem[]
    selectedId: number | string | null
    onSelect: (id: number | string) => void
    onSearch: (query: string) => void
    searchQuery: string
    label: string
    /** 搜索框上方的角色说明（如 Administrator / Project manager），与逐条 MANAGER 标签互斥展示 */
    roleBanner?: string | null
    disabled?: boolean
    /** 仅禁用交互，不展示 disabled 外观（不加 .disabled wrapper class） */
    suppressDisabledStyle?: boolean
    customLabel?: string
    loading?: boolean
}

export function SearchableDropdown({
    items,
    selectedId,
    onSelect,
    onSearch,
    searchQuery,
    label,
    roleBanner,
    disabled,
    suppressDisabledStyle,
    customLabel,
    loading = false,
}: SearchableDropdownProps) {
    const [isOpen, setIsOpen] = useState(false)
    const wrapperRef = useRef<HTMLDivElement>(null)
    const selectedItemRef = useRef<HTMLDivElement>(null)

    const closeDropdown = () => {
        setIsOpen(false)
        onSearch("")
    }

    useEffect(() => {
        const handleClickOutside = (e: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
                closeDropdown()
            }
        }
        document.addEventListener("click", handleClickOutside)
        return () => document.removeEventListener("click", handleClickOutside)
    }, [])

    useLayoutEffect(() => {
        if (!isOpen) return
        let cancelled = false
        let innerFrame = 0
        const scrollSelectedIntoView = () => {
            if (cancelled) return
            const el = selectedItemRef.current
            if (!el) return
            const scrollParent = el.closest(".custom-scroll-area__body") as HTMLElement | null
            if (!scrollParent) {
                el.scrollIntoView({ block: "nearest", inline: "nearest" })
                return
            }
            if (getComputedStyle(scrollParent).overflowY === "hidden") {
                scrollParent.style.overflowY = "auto"
            }
            const parentRect = scrollParent.getBoundingClientRect()
            const elRect = el.getBoundingClientRect()
            if (parentRect.height < 1) return
            const above = elRect.top < parentRect.top
            const below = elRect.bottom > parentRect.bottom
            if (!above && !below) return
            scrollParent.scrollTop += above
                ? elRect.top - parentRect.top
                : elRect.bottom - parentRect.bottom
        }
        const frame = window.requestAnimationFrame(() => {
            innerFrame = window.requestAnimationFrame(scrollSelectedIntoView)
        })
        return () => {
            cancelled = true
            window.cancelAnimationFrame(frame)
            window.cancelAnimationFrame(innerFrame)
        }
    }, [isOpen, selectedId, items])

    const selectedItem = items.find(item => String(item.id) === String(selectedId))

    return (
        <div
            ref={wrapperRef}
            className={`crumb-wrapper ${isOpen ? "active" : ""} ${disabled && !suppressDisabledStyle ? "disabled" : ""} ${loading ? "loading" : ""}`}
        >
            <ESButton appearance="unstyled"
                className="crumb-btn"
                disabled={disabled || loading}
                aria-busy={loading}
                onClick={() => {
                    if (isOpen) {
                        closeDropdown()
                    } else {
                        setIsOpen(true)
                    }
                }}
            >
                <div className="crumb-btn-content">
                    <StableText className="block-anim crumb-btn-label">
                        {customLabel || selectedItem?.label || label}
                    </StableText>
                </div>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="m6 9 6 6 6-6" />
                </svg>
            </ESButton>
            <div className={`crumb-dropdown ${isOpen ? "" : ""}`}>
                {roleBanner ? (
                    <div className="crumb-role-banner"><StableText>{roleBanner}</StableText></div>
                ) : null}
                <div className="dropdown-search-box">
                    <div className="search-input-wrapper">
                        <Search className="search-icon-small" size={16} />
                        <ESInput appearance="unstyled"
                            className="dropdown-input"
                            type="text"
                            value={searchQuery}

                            onChange={(e) => onSearch(e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                        />
                    </div>
                </div>
                <CustomScrollArea variant="fill" className="dropdown-list-scroll">
                    {items.length === 0 ? (
                        <EmptyState className="empty-state" title={<StableText>No Data</StableText>} />
                    ) : (
                        items.map((item) => {
                            const isSelected = String(item.id) === String(selectedId)
                            return (
                                <div
                                    key={item.id}
                                    ref={isSelected ? selectedItemRef : undefined}
                                    className={`crumb-item ${isSelected ? "selected" : ""}`}
                                    onClick={() => {
                                        onSelect(item.id)
                                        closeDropdown()
                                    }}
                                >
                                    <div className="crumb-item-content">
                                        <StableText className="crumb-item-label">{item.label}</StableText>
                                        {item.tag && (
                                            <StableText className={`crumb-tag crumb-tag-${(item.tagVariant || item.tag).toLowerCase()}`}>
                                                {item.tag}
                                            </StableText>
                                        )}
                                    </div>
                                    {isSelected && (
                                        <Check className="check-icon" size={16} style={{ opacity: 1 }} />
                                    )}
                                </div>
                            )
                        })
                    )}
                </CustomScrollArea>
            </div>
        </div>
    )
}
