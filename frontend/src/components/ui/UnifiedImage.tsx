import { forwardRef, useEffect, useState, type ImgHTMLAttributes } from "react"
import { ImageOff } from "lucide-react"

import "./UnifiedImage.css"

type UnifiedImageProps = ImgHTMLAttributes<HTMLImageElement> & {
    fallbackLabel?: string
}

export const UnifiedImage = forwardRef<HTMLImageElement, UnifiedImageProps>(
    function UnifiedImage(
        { src, alt, className, fallbackLabel = "Image unavailable", onError, ...props },
        ref,
    ) {
        const imageUrl = typeof src === "string" ? src.trim() : ""
        const [failed, setFailed] = useState(!imageUrl)

        useEffect(() => {
            setFailed(!imageUrl)
        }, [imageUrl])

        if (failed) {
            return (
                <div
                    className={`unified-image-fallback${className ? ` ${className}` : ""}`}
                    role="img"
                    aria-label={fallbackLabel}
                >
                    <ImageOff size={32} aria-hidden="true" />
                    <span>{fallbackLabel}</span>
                </div>
            )
        }

        return (
            <img
                {...props}
                ref={ref}
                src={imageUrl}
                alt={alt}
                className={className}
                onError={(event) => {
                    setFailed(true)
                    onError?.(event)
                }}
            />
        )
    },
)
