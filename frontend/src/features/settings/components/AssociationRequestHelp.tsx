import { Tooltip } from "@/components/ui"
import { Info } from "lucide-react"

const ISSUES_URL = "https://github.com/LiuDilongNJ/eco-signal/issues"

export function AssociationRequestHelp({ subject }: { subject: string }) {
    const message = `If you want to add new, valid ${subject}, or their combinations to the ecoSignal database, please file an issue here: ${ISSUES_URL}`
    return (
        <Tooltip title={message}>
            <a
                className="settings-association-help"
                href={ISSUES_URL}
                target="_blank"
                rel="noreferrer"
                aria-label={message}
            >
                <Info size={15} aria-hidden="true" />
            </a>
        </Tooltip>
    )
}
