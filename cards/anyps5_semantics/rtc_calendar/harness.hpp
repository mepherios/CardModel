// adapters: libSceRtc's pointer-based exports as functions of integers (one result per call)
static RtcDateTime DT(long long y, long long mo, long long d, long long h, long long mi, long long s, long long us) {
    RtcDateTime t{};
    t.year = static_cast<std::uint16_t>(y);
    t.month = static_cast<std::uint16_t>(mo);
    t.day = static_cast<std::uint16_t>(d);
    t.hour = static_cast<std::uint16_t>(h);
    t.minute = static_cast<std::uint16_t>(mi);
    t.second = static_cast<std::uint16_t>(s);
    t.microsecond = static_cast<std::uint32_t>(us);
    return t;
}
static long long CheckValid(long long y, long long mo, long long d, long long h, long long mi, long long s, long long us) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, us);
    return sceRtcCheckValid(&t);
}
static long long GetTick(long long y, long long mo, long long d, long long h, long long mi, long long s, long long us) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, us);
    RtcTick k{};
    const int r = sceRtcGetTick(&t, &k);
    return r != 0 ? r : static_cast<long long>(k.tick);
}
static long long GetTimeT(long long y, long long mo, long long d, long long h, long long mi, long long s, long long us) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, us);
    std::int64_t seconds = 0;
    const int r = sceRtcGetTime_t(&t, &seconds);
    return r != 0 ? r : static_cast<long long>(seconds);
}
static long long GetWin32(long long y, long long mo, long long d, long long h, long long mi, long long s, long long us) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, us);
    std::uint64_t filetime = 0;
    const int r = sceRtcGetWin32FileTime(&t, &filetime);
    return r != 0 ? r : static_cast<long long>(filetime);
}
static long long DosWritten(long long y, long long mo, long long d, long long h, long long mi, long long s) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, 0);
    std::uint32_t packed = 0x5a5a5a5au;
    sceRtcGetDosTime(&t, &packed);
    return packed;
}
static long long DosResult(long long y, long long mo, long long d, long long h, long long mi, long long s) {
    const RtcDateTime t = DT(y, mo, d, h, mi, s, 0);
    std::uint32_t packed = 0;
    return sceRtcGetDosTime(&t, &packed);
}
static long long SetDos(long long v, long long field) {
    RtcDateTime t{};
    sceRtcSetDosTime(&t, static_cast<std::uint32_t>(v));
    const long long fields[] = {t.year, t.month, t.day, t.hour, t.minute, t.second};
    return fields[field];
}
static long long FromTick(long long tick, long long field) {
    RtcDateTime t{};
    const RtcTick k{static_cast<std::uint64_t>(tick)};
    const int r = sceRtcSetTick(&t, &k);
    if (r != 0) return r;
    const long long fields[] = {t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond};
    return fields[field];
}
static long long Civil(long long n, long long field) {
    std::int64_t y = 0;
    unsigned m = 0, d = 0;
    civilFromDays(n, y, m, d);
    const long long fields[] = {y, m, d};
    return fields[field];
}
