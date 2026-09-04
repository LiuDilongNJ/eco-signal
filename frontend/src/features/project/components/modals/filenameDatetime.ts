/** Keep this pattern aligned with backend/app/services/media_service.py. */
const FILENAME_DATETIME_PATTERN =
    /(?<!\d)(\d{4})[-_]?([0-9]{2})[-_]?([0-9]{2})[-_T]([0-9]{2})[-_:]?([0-9]{2})[-_:]?([0-9]{2})(?!\d)/

function isLeapYear(year: number): boolean {
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
}

function isValidDateTimeParts(year: number, month: number, day: number, hour: number, minute: number, second: number): boolean {
    if (year < 1 || year > 9999 || month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) {
        return false
    }

    const daysInMonth = [31, isLeapYear(year) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return day >= 1 && day <= (daysInMonth[month - 1] ?? 0)
}

/** Match the backend parser, including strict calendar/time validation. */
export function canParseFilenameDateTime(filename: string): boolean {
    const match = FILENAME_DATETIME_PATTERN.exec(filename)
    if (!match) return false

    const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match
    if (!yearText || !monthText || !dayText || !hourText || !minuteText || !secondText) return false

    const year = Number(yearText)
    const month = Number(monthText)
    const day = Number(dayText)
    const hour = Number(hourText)
    const minute = Number(minuteText)
    const second = Number(secondText)
    return isValidDateTimeParts(year, month, day, hour, minute, second)
}

export function getUnparseableFilenameDateTimes(filenames: string[]): string[] {
    return filenames.filter((filename) => !canParseFilenameDateTime(filename))
}
