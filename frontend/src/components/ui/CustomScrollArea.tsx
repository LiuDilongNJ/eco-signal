import {
    useCallback,
    useLayoutEffect,
    useRef,
    useState,
    type CSSProperties,
    type HTMLAttributes,
    type KeyboardEvent,
    type MouseEvent,
    type PointerEvent,
    type ReactNode,
    type UIEvent,
} from "react"
import { cn } from "@/lib/utils"
import "./CustomScrollArea.css"

export type CustomScrollAreaProps = {
    children: ReactNode
    className?: string
    bodyClassName?: string
    contentFingerprint?: string
    maxHeight?: number | string
    variant?: "default" | "fill"
    style?: CSSProperties
    bodyStyle?: CSSProperties
    allowHorizontal?: boolean
    onScroll?: (e: UIEvent<HTMLDivElement>) => void
    onClick?: (e: MouseEvent<HTMLDivElement>) => void
    onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void
} & Omit<HTMLAttributes<HTMLDivElement>, "onScroll" | "onClick" | "onKeyDown" | "style" | "className" | "children">

export function CustomScrollArea({
    children,
    className,
    bodyClassName,
    contentFingerprint = "",
    maxHeight,
    variant = "default",
    style,
    bodyStyle,
    allowHorizontal = false,
    onScroll,
    onClick,
    onKeyDown,
    ...restProps
}: CustomScrollAreaProps) {
    const wrapRef = useRef<HTMLDivElement>(null)
    const bodyRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const verticalTrackRef = useRef<HTMLDivElement>(null)
    const horizontalTrackRef = useRef<HTMLDivElement>(null)

    const [verticalThumb, setVerticalThumb] = useState({ show: false, size: 0, offset: 0 })
    const [horizontalThumb, setHorizontalThumb] = useState({ show: false, size: 0, offset: 0 })
    const [canScrollY, setCanScrollY] = useState(false)
    const [canScrollX, setCanScrollX] = useState(false)
    const [verticalDragging, setVerticalDragging] = useState(false)
    const [horizontalDragging, setHorizontalDragging] = useState(false)

    const verticalDragRef = useRef<{
        pointerId: number
        startClient: number
        startScroll: number
        maxScroll: number
        maxOffset: number
    } | null>(null)

    const horizontalDragRef = useRef<{
        pointerId: number
        startClient: number
        startScroll: number
        maxScroll: number
        maxOffset: number
    } | null>(null)

    const updateThumbs = useCallback(() => {
        const body = bodyRef.current
        const verticalTrack = verticalTrackRef.current
        const content = contentRef.current
        const horizontalTrack = horizontalTrackRef.current

        if (body && verticalTrack) {
            const scrollSize = body.scrollHeight
            const clientSize = body.clientHeight
            const scrollOffset = body.scrollTop
            const trackSize = verticalTrack.clientHeight
            const isScrollable = scrollSize > clientSize + 3 && trackSize >= 4
            setCanScrollY(isScrollable)

            if (!isScrollable) {
                setVerticalThumb((prev) => (prev.show ? { show: false, size: 0, offset: 0 } : prev))
            } else {
                const thumbSize = Math.max(28, (clientSize / scrollSize) * trackSize)
                const maxScroll = scrollSize - clientSize
                const maxOffset = Math.max(0, trackSize - thumbSize)
                const thumbOffset = maxScroll > 0 ? (scrollOffset / maxScroll) * maxOffset : 0
                setVerticalThumb({ show: true, size: thumbSize, offset: thumbOffset })
            }
        } else {
            setCanScrollY(false)
        }

        if (!allowHorizontal || !content || !horizontalTrack) {
            setCanScrollX(false)
            setHorizontalThumb((prev) => (prev.show ? { show: false, size: 0, offset: 0 } : prev))
            return
        }

        const scrollSize = content.scrollWidth
        const clientSize = content.clientWidth
        const scrollOffset = content.scrollLeft
        const trackSize = horizontalTrack.clientWidth
        const isScrollable = scrollSize > clientSize + 3 && trackSize >= 4
        setCanScrollX(isScrollable)

        if (!isScrollable) {
            setHorizontalThumb((prev) => (prev.show ? { show: false, size: 0, offset: 0 } : prev))
            return
        }

        const thumbSize = Math.max(28, (clientSize / scrollSize) * trackSize)
        const maxScroll = scrollSize - clientSize
        const maxOffset = Math.max(0, trackSize - thumbSize)
        const thumbOffset = maxScroll > 0 ? (scrollOffset / maxScroll) * maxOffset : 0
        setHorizontalThumb({ show: true, size: thumbSize, offset: thumbOffset })
    }, [allowHorizontal])

    const forwardWheelToBody = useCallback((e: globalThis.WheelEvent) => {
        const body = bodyRef.current
        const content = contentRef.current
        if (!body) return

        const maxScrollTop = Math.max(0, body.scrollHeight - body.clientHeight)
        const maxScrollLeft = allowHorizontal && content
            ? Math.max(0, content.scrollWidth - content.clientWidth)
            : 0

        const canScrollY = maxScrollTop > 0
        const canScrollX = allowHorizontal && maxScrollLeft > 0
        if (!canScrollY && !canScrollX) return

        if (canScrollY && e.deltaY !== 0 && !e.shiftKey) {
            body.scrollTop = Math.min(maxScrollTop, Math.max(0, body.scrollTop + e.deltaY))
        }

        if (canScrollX && content) {
            const horizontalDelta = e.deltaX !== 0 ? e.deltaX : e.shiftKey ? e.deltaY : 0
            if (horizontalDelta !== 0) {
                content.scrollLeft = Math.min(maxScrollLeft, Math.max(0, content.scrollLeft + horizontalDelta))
            }
        }

        e.preventDefault()
        e.stopPropagation()
    }, [allowHorizontal])

    const endVerticalDrag = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = verticalDragRef.current
        if (!drag || e.pointerId !== drag.pointerId) return
        verticalDragRef.current = null
        setVerticalDragging(false)
        try {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
            }
        } catch {
            /* ignore */
        }
    }, [])

    const endHorizontalDrag = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = horizontalDragRef.current
        if (!drag || e.pointerId !== drag.pointerId) return
        horizontalDragRef.current = null
        setHorizontalDragging(false)
        try {
            if (e.currentTarget.hasPointerCapture(e.pointerId)) {
                e.currentTarget.releasePointerCapture(e.pointerId)
            }
        } catch {
            /* ignore */
        }
    }, [])

    const onVerticalThumbPointerDown = useCallback((e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return
        const body = bodyRef.current
        const track = verticalTrackRef.current
        if (!body || !track) return

        const maxScroll = Math.max(0, body.scrollHeight - body.clientHeight)
        if (maxScroll < 1 || track.clientHeight < 4) return

        const thumbSize = Math.max(28, (body.clientHeight / body.scrollHeight) * track.clientHeight)
        const maxOffset = Math.max(0, track.clientHeight - thumbSize)
        e.preventDefault()
        e.stopPropagation()
        e.currentTarget.setPointerCapture(e.pointerId)
        verticalDragRef.current = {
            pointerId: e.pointerId,
            startClient: e.clientY,
            startScroll: body.scrollTop,
            maxScroll,
            maxOffset: Math.max(maxOffset, 1e-6),
        }
        setVerticalDragging(true)
    }, [])

    const onHorizontalThumbPointerDown = useCallback((e: PointerEvent<HTMLDivElement>) => {
        if (e.button !== 0) return
        const content = contentRef.current
        const track = horizontalTrackRef.current
        if (!content || !track) return

        const maxScroll = Math.max(0, content.scrollWidth - content.clientWidth)
        if (maxScroll < 1 || track.clientWidth < 4) return

        const thumbSize = Math.max(28, (content.clientWidth / content.scrollWidth) * track.clientWidth)
        const maxOffset = Math.max(0, track.clientWidth - thumbSize)
        e.preventDefault()
        e.stopPropagation()
        e.currentTarget.setPointerCapture(e.pointerId)
        horizontalDragRef.current = {
            pointerId: e.pointerId,
            startClient: e.clientX,
            startScroll: content.scrollLeft,
            maxScroll,
            maxOffset: Math.max(maxOffset, 1e-6),
        }
        setHorizontalDragging(true)
    }, [])

    const onVerticalThumbPointerMove = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = verticalDragRef.current
        const body = bodyRef.current
        if (!drag || !body || e.pointerId !== drag.pointerId) return
        const delta = e.clientY - drag.startClient
        const ratio = drag.maxScroll / drag.maxOffset
        body.scrollTop = Math.min(drag.maxScroll, Math.max(0, drag.startScroll + delta * ratio))
    }, [])

    const onHorizontalThumbPointerMove = useCallback((e: PointerEvent<HTMLDivElement>) => {
        const drag = horizontalDragRef.current
        const content = contentRef.current
        if (!drag || !content || e.pointerId !== drag.pointerId) return
        const delta = e.clientX - drag.startClient
        const ratio = drag.maxScroll / drag.maxOffset
        content.scrollLeft = Math.min(drag.maxScroll, Math.max(0, drag.startScroll + delta * ratio))
    }, [])

    useLayoutEffect(() => {
        requestAnimationFrame(() => {
            requestAnimationFrame(updateThumbs)
        })
    }, [updateThumbs, contentFingerprint])

    // Content can change while the same scroll area instance is reused (e.g. switch records in a drawer).
    // Recompute scrollability immediately so old scrollbar state does not leak into the new content.
    useLayoutEffect(() => {
        requestAnimationFrame(() => {
            updateThumbs()
        })
    }, [children, updateThumbs])

    useLayoutEffect(() => {
        const wrap = wrapRef.current
        const body = bodyRef.current
        const content = contentRef.current
        if (!wrap && !body && !content) return
        const ro = new ResizeObserver(() => updateThumbs())
        if (wrap) ro.observe(wrap)
        if (body) ro.observe(body)
        if (content) ro.observe(content)
        return () => ro.disconnect()
    }, [updateThumbs, contentFingerprint])

    useLayoutEffect(() => {
        const body = bodyRef.current
        if (!body) return

        const mo = new MutationObserver(() => {
            requestAnimationFrame(updateThumbs)
        })

        mo.observe(body, {
            childList: true,
            subtree: true,
            attributes: true,
            characterData: true,
        })

        return () => mo.disconnect()
    }, [updateThumbs, contentFingerprint])

    useLayoutEffect(() => {
        const body = bodyRef.current
        const verticalTrack = verticalTrackRef.current
        const horizontalTrack = horizontalTrackRef.current
        if (!body && !verticalTrack && !horizontalTrack) return

        const options: AddEventListenerOptions = { passive: false }
        body?.addEventListener("wheel", forwardWheelToBody, options)
        verticalTrack?.addEventListener("wheel", forwardWheelToBody, options)
        horizontalTrack?.addEventListener("wheel", forwardWheelToBody, options)

        return () => {
            body?.removeEventListener("wheel", forwardWheelToBody, options)
            verticalTrack?.removeEventListener("wheel", forwardWheelToBody, options)
            horizontalTrack?.removeEventListener("wheel", forwardWheelToBody, options)
        }
    }, [forwardWheelToBody])

    const resolvedBodyStyle: CSSProperties = {
        ...(maxHeight != null && variant !== "fill"
            ? { maxHeight: typeof maxHeight === "number" ? `${maxHeight}px` : maxHeight }
            : {}),
        overflowY: canScrollY ? "auto" : "hidden",
        ...bodyStyle,
    }

    return (
        <div
            ref={wrapRef}
            className={cn("custom-scroll-area", variant === "fill" && "custom-scroll-area--fill", className)}
            style={style}
            onClick={onClick}
            onKeyDown={onKeyDown}
            {...restProps}
        >
            <div className="custom-scroll-area__main">
                <div
                    ref={bodyRef}
                    className={cn("custom-scroll-area__body", bodyClassName)}
                    style={resolvedBodyStyle}
                    onScroll={(e) => {
                        updateThumbs()
                        onScroll?.(e)
                    }}
                >
                    {allowHorizontal ? (
                        <div
                            ref={contentRef}
                            className="custom-scroll-area__content custom-scroll-area__content--allow-horizontal"
                            style={{ overflowX: canScrollX ? "auto" : "hidden" }}
                            onScroll={(e) => {
                                updateThumbs()
                                onScroll?.(e)
                            }}
                        >
                            {children}
                        </div>
                    ) : (
                        children
                    )}
                </div>

                {allowHorizontal ? (
                    <div
                        ref={horizontalTrackRef}
                        className="custom-scroll-area__track custom-scroll-area__track--horizontal"
                        aria-hidden
                        data-shown={horizontalThumb.show}
                    >
                        {horizontalThumb.show ? (
                            <div
                                className={cn(
                                    "custom-scroll-area__thumb custom-scroll-area__thumb--horizontal",
                                    horizontalDragging && "custom-scroll-area__thumb--dragging",
                                )}
                                style={{
                                    width: horizontalThumb.size,
                                    transform: `translateX(${horizontalThumb.offset}px)`,
                                }}
                                onPointerDown={onHorizontalThumbPointerDown}
                                onPointerMove={onHorizontalThumbPointerMove}
                                onPointerUp={endHorizontalDrag}
                                onPointerCancel={endHorizontalDrag}
                                onLostPointerCapture={() => {
                                    horizontalDragRef.current = null
                                    setHorizontalDragging(false)
                                }}
                            />
                        ) : null}
                    </div>
                ) : null}
            </div>

            <div
                ref={verticalTrackRef}
                className="custom-scroll-area__track"
                aria-hidden
                data-shown={verticalThumb.show}
            >
                {verticalThumb.show ? (
                    <div
                        className={cn(
                            "custom-scroll-area__thumb",
                            verticalDragging && "custom-scroll-area__thumb--dragging",
                        )}
                        style={{
                            height: verticalThumb.size,
                            transform: `translateY(${verticalThumb.offset}px)`,
                        }}
                        onPointerDown={onVerticalThumbPointerDown}
                        onPointerMove={onVerticalThumbPointerMove}
                        onPointerUp={endVerticalDrag}
                        onPointerCancel={endVerticalDrag}
                        onLostPointerCapture={() => {
                            verticalDragRef.current = null
                            setVerticalDragging(false)
                        }}
                    />
                ) : null}
            </div>
        </div>
    )
}
