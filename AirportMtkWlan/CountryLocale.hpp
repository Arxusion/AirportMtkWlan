/*
 * Regulatory country code selection and Apple80211 locale mapping.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef AIRPORT_COUNTRY_LOCALE_HPP
#define AIRPORT_COUNTRY_LOCALE_HPP

namespace mtkcc {

enum Source {
    kOverride = 1,
    kGeo = 2,
    kFirmware = 3,
    kBss11d = 4,
    kScan11d = 5,
};

inline char upperChar(char ch)
{
    return (ch >= 'a' && ch <= 'z') ? static_cast<char>(ch - ('a' - 'A')) : ch;
}

inline bool isUnset(const char *code)
{
    if (!code || !code[0] || !code[1])
        return true;
    char c0 = upperChar(code[0]);
    char c1 = upperChar(code[1]);
    return (c0 == '0' && c1 == '0') || (c0 == 'Z' && c1 == 'Z') || c0 == 'X';
}

inline const char *sourceLabel(Source src)
{
    switch (src) {
    case kOverride: return "override";
    case kGeo:      return "geoloc";
    case kBss11d:   return "11d-ap";
    case kScan11d:  return "11d-scan";
    default:        return "firmware";
    }
}

/*
 * Pick the highest-precedence regulatory domain string:
 *   1. User override (NVRAM / boot-arg)
 *   2. Explicit firmware domain (anything other than "00"/"ZZ"/"X?")
 *   3. macOS CoreLocation / airportd country update
 *   4. Joined AP's 802.11d Country element
 *   5. Modal 802.11d Country element observed across scans
 *   6. Raw firmware fallback
 */
inline const char *resolveCountry(const char *overrideCc, const char *fwCc,
                                  const char *geoCc, const char *ap11dCc,
                                  const char *scan11dCc, Source *outSource)
{
    Source src = kFirmware;
    const char *chosen = fwCc;
    if (overrideCc && overrideCc[0]) {
        src = kOverride;
        chosen = overrideCc;
    } else if (!isUnset(fwCc)) {
        src = kFirmware;
        chosen = fwCc;
    } else if (!isUnset(geoCc)) {
        src = kGeo;
        chosen = geoCc;
    } else if (!isUnset(ap11dCc)) {
        src = kBss11d;
        chosen = ap11dCc;
    } else if (!isUnset(scan11dCc)) {
        src = kScan11d;
        chosen = scan11dCc;
    }
    if (outSource)
        *outSource = src;
    return chosen;
}

inline void pickModalCountry(const char (*entries)[2], const unsigned *hits,
                             unsigned count, char outCc[3])
{
    unsigned top = 0;
    outCc[0] = '\0';
    outCc[1] = '\0';
    outCc[2] = '\0';
    for (unsigned idx = 0; idx < count; ++idx) {
        if (hits[idx] > top) {
            top = hits[idx];
            outCc[0] = entries[idx][0];
            outCc[1] = entries[idx][1];
        }
    }
}

inline bool matchesCode(const char *lhs, const char *rhs)
{
    return upperChar(lhs[0]) == rhs[0] && upperChar(lhs[1]) == rhs[1];
}

/* Converts an ISO alpha-2 domain into an Apple80211 locale constant. */
inline int appleLocaleForCountry(const char *cc)
{
    static const char *const kEtsiDomains[] = {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
        "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
        "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO", "CH", "GB", "EU",
    };
    if (isUnset(cc))
        return 1; /* APPLE80211_LOCALE_FCC */
    for (const char *domain : kEtsiDomains) {
        if (matchesCode(cc, domain))
            return 2; /* APPLE80211_LOCALE_ETSI */
    }
    if (matchesCode(cc, "JP"))
        return 3; /* APPLE80211_LOCALE_JAPAN */
    if (matchesCode(cc, "KR"))
        return 4; /* APPLE80211_LOCALE_KOREA */
    return 1;
}

} /* namespace mtkcc */

#endif /* AIRPORT_COUNTRY_LOCALE_HPP */
