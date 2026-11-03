//
//  ieee80211_sae.h
//  SimpleMtkWlan / AirportMtkWlan
//
//  WPA3-Personal SAE (Simultaneous Authentication of Equals / Dragonfly)
//  RFC 7664 / IEEE 802.11-2016 Section 12.4
//

#ifndef _NET80211_IEEE80211_SAE_H_
#define _NET80211_IEEE80211_SAE_H_

#define IEEE80211_SAE_GROUP_P256 19

enum sae_state {
    SAE_STATE_NOTHING = 0,
    SAE_STATE_COMMITTED = 1,
    SAE_STATE_CONFIRMED = 2,
    SAE_STATE_ACCEPTED = 3
};

struct ieee80211_sae {
    enum sae_state  state;
    uint16_t        group;
    uint16_t        send_confirm;
    uint16_t        sync;

    // Station values:
    uint8_t         scalar_sta[32];
    uint8_t         element_sta_x[32];
    uint8_t         element_sta_y[32];
    uint8_t         rand_sta[32];

    // Peer values:
    bool            have_peer_commit;
    uint8_t         scalar_peer[32];
    uint8_t         element_peer_x[32];
    uint8_t         element_peer_y[32];

    // Derived values:
    uint8_t         pwe_x[32];
    uint8_t         pwe_y[32];
    uint8_t         kck[32];
    uint8_t         pmk[32];
    uint8_t         pmkid[16];
};

struct ieee80211com;
struct ieee80211_node;

#ifdef __cplusplus
extern "C" {
#endif

int     ieee80211_sae_start(struct ieee80211com *ic, struct ieee80211_node *ni);
void    ieee80211_sae_free(struct ieee80211_node *ni);
mbuf_t  ieee80211_sae_build_commit(struct ieee80211com *ic, struct ieee80211_node *ni);
mbuf_t  ieee80211_sae_build_confirm(struct ieee80211com *ic, struct ieee80211_node *ni);
void    ieee80211_sae_rx_auth(struct ieee80211com *ic, mbuf_t m, struct ieee80211_node *ni,
                              uint16_t seq, uint16_t status);

#ifdef __cplusplus
}
#endif

#endif /* _NET80211_IEEE80211_SAE_H_ */
