export function isSuccessfulDrawerResponse(code: number, messageText?: string) {
    if (code !== 0 && code !== 200 && code !== 201) {
        return false
    }

    const normalizedMessage = String(messageText ?? "").trim().toLowerCase()
    if (!normalizedMessage) {
        return true
    }

    return !/(fail|failed|error|invalid|unable|denied|not found)/i.test(normalizedMessage)
}
