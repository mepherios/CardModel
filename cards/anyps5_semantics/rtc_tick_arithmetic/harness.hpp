// adapters: libSceRtc's tick arithmetic as functions of integers (one result per call); an error code is returned
// in place of the result, so a refused input shows as a disagreement with the derived value
#define APS5_RTC_ADD(NAME, EXPORT, COUNT)                                                     \
    static long long NAME(unsigned long long t, long long n) {                                \
        const RtcTick src{static_cast<std::uint64_t>(t)};                                     \
        RtcTick dst{0x5a5a5a5a5a5a5a5aull};                                                   \
        const int r = EXPORT(&dst, &src, static_cast<COUNT>(n));                              \
        return r != 0 ? r : static_cast<long long>(dst.tick);                                 \
    }
APS5_RTC_ADD(AddTicks, sceRtcTickAddTicks, std::int64_t)
APS5_RTC_ADD(AddMicroseconds, sceRtcTickAddMicroseconds, std::int64_t)
APS5_RTC_ADD(AddSeconds, sceRtcTickAddSeconds, std::int64_t)
APS5_RTC_ADD(AddMinutes, sceRtcTickAddMinutes, std::int64_t)
APS5_RTC_ADD(AddHours, sceRtcTickAddHours, std::int32_t)
APS5_RTC_ADD(AddDays, sceRtcTickAddDays, std::int32_t)
APS5_RTC_ADD(AddWeeks, sceRtcTickAddWeeks, std::int32_t)
APS5_RTC_ADD(AddMonths, sceRtcTickAddMonths, std::int32_t)
APS5_RTC_ADD(AddYears, sceRtcTickAddYears, std::int16_t)
#undef APS5_RTC_ADD
static long long Compare(unsigned long long a, unsigned long long b) {
    const RtcTick x{static_cast<std::uint64_t>(a)};
    const RtcTick y{static_cast<std::uint64_t>(b)};
    return sceRtcCompareTick(&x, &y);
}
static long long SetTimeT(long long seconds, long long field) {
    RtcDateTime t{};
    const int r = sceRtcSetTime_t(&t, static_cast<std::int64_t>(seconds));
    if (r != 0) return r;
    const long long fields[] = {t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond};
    return fields[field];
}
static long long SetWin32(unsigned long long filetime, long long field) {
    RtcDateTime t{};
    const int r = sceRtcSetWin32FileTime(&t, static_cast<std::uint64_t>(filetime));
    if (r != 0) return r;
    const long long fields[] = {t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond};
    return fields[field];
}
