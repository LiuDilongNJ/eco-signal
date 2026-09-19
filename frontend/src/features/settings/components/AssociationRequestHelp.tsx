import { FormHelpIcon, Tooltip } from "@/components/ui"

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
                <FormHelpIcon size={15} />
            </a>
        </Tooltip>
    )
}
