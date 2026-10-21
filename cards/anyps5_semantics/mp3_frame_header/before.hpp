// what the extracted functions need from the rest of Ajm.cpp: silence its trace macro, and the original
// file length reader (never reached: the checks pass parse_ofl = 0)
#include <cstddef>
#include "SceTypes.hpp"
#define AJM_TRACE(...) do {} while (0)
static void ParseMp3Ofl(const std::uint8_t*, std::uint32_t, std::uint32_t, AjmDecMp3ParseFrame*) {}
extern "C" [[noreturn]] void NotImplemented_nid_no_patch(const char* funcName);
