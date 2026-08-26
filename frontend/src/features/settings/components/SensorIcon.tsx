import { forwardRef } from "react"
import type { LucideProps } from "lucide-react"

export const SensorIcon = forwardRef<SVGSVGElement, LucideProps>(function SensorIcon({ size = 24, style, ...props }, ref) {
    return (
        <svg
            ref={ref}
            {...props}
            width={size}
            height={size}
            viewBox="0 0 75 60"
            fill="none"
            focusable="false"
            style={{
                display: "inline-block",
                flex: "0 0 auto",
                backgroundColor: "currentColor",
                WebkitMaskImage: "url('/images/sensor.svg')",
                maskImage: "url('/images/sensor.svg')",
                WebkitMaskPosition: "center",
                maskPosition: "center",
                WebkitMaskRepeat: "no-repeat",
                maskRepeat: "no-repeat",
                WebkitMaskSize: "contain",
                maskSize: "contain",
                ...style,
            }}
        />
    )
})
