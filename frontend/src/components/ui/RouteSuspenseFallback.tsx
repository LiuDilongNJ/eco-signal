import { LoadingState } from "@/components/ui"

export function RouteSuspenseFallback() {
    return (
        <div className="route-suspense-fallback">
            <LoadingState label="Loading" variant="page" size="lg" className="route-suspense-fallback__state" />
        </div>
    )
}
