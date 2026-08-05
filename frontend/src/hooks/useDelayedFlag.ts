/**
 * Delay turning a boolean flag on, but turn it off immediately.
 *
 * Used to gate loading indicators: requests that finish within `delayMs`
 * never flash a spinner/overlay, which keeps fast interactions feeling instant.
 */

import { useEffect, useState } from "react"

export function useDelayedFlag(active: boolean, delayMs = 250): boolean {
    const [delayed, setDelayed] = useState(false)

    useEffect(() => {
        if (!active) {
            setDelayed(false)
            return
        }
        const timer = window.setTimeout(() => setDelayed(true), delayMs)
        return () => window.clearTimeout(timer)
    }, [active, delayMs])

    return delayed
}
