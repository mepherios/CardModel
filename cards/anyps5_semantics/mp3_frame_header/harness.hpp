// adapters: both of AnyPS5's MPEG header readers on the four header bytes, one field per call
static long long Mp3Decoder(long long h, long long field) {
    const std::uint8_t b[4] = {static_cast<std::uint8_t>(h >> 24), static_cast<std::uint8_t>(h >> 16),
                               static_cast<std::uint8_t>(h >> 8), static_cast<std::uint8_t>(h)};
    Mp3Frame f{};
    if (!ParseMp3Frame(b, 4, f)) return -1;
    const long long fields[] = {static_cast<long long>(f.bytes), f.channels, f.samples, f.sampleRate, f.bitrate};
    return fields[field];
}
static long long Mp3Export(long long h, long long field) {
    const std::uint8_t b[4] = {static_cast<std::uint8_t>(h >> 24), static_cast<std::uint8_t>(h >> 16),
                               static_cast<std::uint8_t>(h >> 8), static_cast<std::uint8_t>(h)};
    AjmDecMp3ParseFrame f{};
    if (ParseMp3Header(b, 4, 0, &f) != 0) return -1;
    const long long fields[] = {static_cast<long long>(f.frame_size), f.num_channels, f.samples_per_channel,
                                f.sample_rate, f.bitrate};
    return fields[field];
}
