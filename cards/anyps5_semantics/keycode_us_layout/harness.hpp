// adapter: the export's character, or its error code, as one integer
static long long GetCharacter(long long keycode, long long state) {
    char16_t c = 0xFFFF;
    const int r = sceConvertKeycodeGetCharacter(static_cast<std::uint16_t>(keycode), static_cast<std::uint32_t>(state), 0, &c);
    return r != 0 ? r : static_cast<long long>(c);
}
