/*
 * Minimal IEEE 802.11d Country Information Element vote tracker.
 * SPDX-License-Identifier: ISC
 */
#ifndef _NET80211_IEEE80211_11D_H_
#define _NET80211_IEEE80211_11D_H_

#include <stdint.h>

#define IEEE80211_11D_MAX_SLOTS 8

struct ieee80211_11d_tally {
	uint8_t		cc[2];
	uint16_t	count;
};

static inline int
ieee80211_parse_11d_country(const uint8_t *ie, uint8_t cc[2])
{
	uint8_t c0, c1;

	if (ie == 0 || ie[1] < 2)
		return 0;
	c0 = ie[2];
	c1 = ie[3];
	if (c0 >= 'a' && c0 <= 'z')
		c0 = (uint8_t)(c0 - ('a' - 'A'));
	if (c1 >= 'a' && c1 <= 'z')
		c1 = (uint8_t)(c1 - ('a' - 'A'));
	if (c0 < 'A' || c0 > 'Z' || c1 < 'A' || c1 > 'Z')
		return 0;
	if (c0 == 'X' || (c0 == 'Z' && c1 == 'Z'))
		return 0;
	cc[0] = c0;
	cc[1] = c1;
	return 1;
}

static inline void
ieee80211_record_11d_country(struct ieee80211_11d_tally *table,
    uint8_t cached_cc[2], const uint8_t new_cc[2])
{
	int i, found = -1, evict = 0;

	if (cached_cc[0] == new_cc[0] && cached_cc[1] == new_cc[1])
		return;

	if (cached_cc[0]) {
		for (i = 0; i < IEEE80211_11D_MAX_SLOTS; i++) {
			if (table[i].count > 0 &&
			    table[i].cc[0] == cached_cc[0] &&
			    table[i].cc[1] == cached_cc[1]) {
				table[i].count--;
				break;
			}
		}
	}

	for (i = 0; i < IEEE80211_11D_MAX_SLOTS; i++) {
		if (table[i].cc[0] == new_cc[0] &&
		    table[i].cc[1] == new_cc[1]) {
			found = i;
			break;
		}
		if (table[i].count < table[evict].count)
			evict = i;
	}

	if (found < 0) {
		found = evict;
		table[found].cc[0] = new_cc[0];
		table[found].cc[1] = new_cc[1];
		table[found].count = 0;
	}
	if (table[found].count < 0xffff)
		table[found].count++;
	cached_cc[0] = new_cc[0];
	cached_cc[1] = new_cc[1];
}

#endif /* _NET80211_IEEE80211_11D_H_ */
