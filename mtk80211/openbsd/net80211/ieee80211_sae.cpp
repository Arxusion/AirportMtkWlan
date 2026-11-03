//
//  ieee80211_sae.cpp
//  SimpleMtkWlan / AirportMtkWlan
//
//  WPA3-Personal SAE (Simultaneous Authentication of Equals / Dragonfly)
//  RFC 7664 / IEEE 802.11-2016 Section 12.4
//

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/mbuf.h>
#include <sys/malloc.h>
#include <sys/kernel.h>
#include <sys/endian.h>
#include <sys/_arc4random.h>

extern "C" {
#include <crypto/sha1.h>
#include <crypto/sha2.h>
#include <crypto/hmac.h>
}

#include <net80211/ieee80211_var.h>
#include <net80211/ieee80211_priv.h>
#include <net80211/ieee80211_sae.h>

// 256-bit unsigned integer (4 x 64-bit limbs, little-endian)
struct u256 {
    uint64_t w[4];
};

static const u256 p256 = {
    { 0xFFFFFFFFFFFFFFFFULL, 0x00000000FFFFFFFFULL, 0x0000000000000000ULL, 0xFFFFFFFF00000001ULL }
};

static const u256 q256 = {
    { 0xF3B9CAC2FC632551ULL, 0xBCE6FAADA7179E84ULL, 0xFFFFFFFFFFFFFFFFULL, 0xFFFFFFFF00000000ULL }
};

static const u256 b256 = {
    { 0x3BCE3C3E27D2604BULL, 0x651D06B0CC53B0F6ULL, 0xB3EBBD55769886BCULL, 0x5AC635D8AA3A93E7ULL }
};

static u256 u256_from_bytes(const uint8_t bytes[32]) {
    u256 r = {};
    for (int i = 0; i < 4; i++) {
        uint64_t w = 0;
        int byte_offset = 32 - (i + 1) * 8;
        for (int b = 0; b < 8; b++) {
            w = (w << 8) | bytes[byte_offset + b];
        }
        r.w[i] = w;
    }
    return r;
}

static void u256_to_bytes(const u256 &val, uint8_t bytes[32]) {
    for (int i = 0; i < 4; i++) {
        uint64_t w = val.w[i];
        int byte_offset = 32 - (i + 1) * 8;
        for (int b = 7; b >= 0; b--) {
            bytes[byte_offset + b] = (uint8_t)w;
            w >>= 8;
        }
    }
}

static int u256_cmp(const u256 &a, const u256 &b) {
    for (int i = 3; i >= 0; i--) {
        if (a.w[i] > b.w[i]) return 1;
        if (a.w[i] < b.w[i]) return -1;
    }
    return 0;
}

static bool u256_is_zero(const u256 &a) {
    return (a.w[0] | a.w[1] | a.w[2] | a.w[3]) == 0;
}

static u256 u256_add(const u256 &a, const u256 &b, uint64_t *carry_out) {
    u256 r;
    unsigned __int128 c = 0;
    for (int i = 0; i < 4; i++) {
        c += (unsigned __int128)a.w[i] + b.w[i];
        r.w[i] = (uint64_t)c;
        c >>= 64;
    }
    if (carry_out) *carry_out = (uint64_t)c;
    return r;
}

static u256 u256_sub(const u256 &a, const u256 &b, uint64_t *borrow_out) {
    u256 r;
    unsigned __int128 borrow = 0;
    for (int i = 0; i < 4; i++) {
        unsigned __int128 diff = (unsigned __int128)a.w[i] - b.w[i] - borrow;
        r.w[i] = (uint64_t)diff;
        borrow = (diff >> 127) & 1;
    }
    if (borrow_out) *borrow_out = (uint64_t)borrow;
    return r;
}

static u256 u256_mod_add(const u256 &a, const u256 &b, const u256 &mod) {
    uint64_t carry = 0;
    u256 r = u256_add(a, b, &carry);
    if (carry || u256_cmp(r, mod) >= 0) {
        r = u256_sub(r, mod, nullptr);
    }
    return r;
}

static u256 u256_mod_sub(const u256 &a, const u256 &b, const u256 &mod) {
    uint64_t borrow = 0;
    u256 r = u256_sub(a, b, &borrow);
    if (borrow) {
        r = u256_add(r, mod, nullptr);
    }
    return r;
}

struct u512 {
    uint64_t w[8];
};

static u512 u256_mul(const u256 &a, const u256 &b) {
    u512 r = {};
    for (int i = 0; i < 4; i++) {
        unsigned __int128 carry = 0;
        for (int j = 0; j < 4; j++) {
            unsigned __int128 prod = (unsigned __int128)a.w[i] * b.w[j] + r.w[i + j] + carry;
            r.w[i + j] = (uint64_t)prod;
            carry = prod >> 64;
        }
        r.w[i + 4] = (uint64_t)carry;
    }
    return r;
}

// NIST P-256 reduction: p = 2^256 - 2^224 + 2^192 + 2^96 - 1
static u256 u512_reduce_p256(const u512 &val) {
    uint32_t c[16];
    for (int i = 0; i < 8; i++) {
        c[2 * i] = (uint32_t)(val.w[i] & 0xFFFFFFFFULL);
        c[2 * i + 1] = (uint32_t)(val.w[i] >> 32);
    }

    int64_t s[8];
    // T = (c7, c6, c5, c4, c3, c2, c1, c0)
    // S1 = (c15, c14, c13, c12, c11, 0, 0, 0)
    // S2 = (0, c15, c14, c13, c12, 0, 0, 0)
    // S3 = (c15, c14, 0, 0, 0, c10, c9, c8)
    // S4 = (c8, c13, c15, c14, c13, c11, c10, c9)
    // D1 = (c10, c8, 0, 0, 0, c13, c12, c11)
    // D2 = (c11, c9, 0, 0, c15, c14, c13, c12)
    // D3 = (c12, 0, c10, c9, c8, c15, c14, c13)
    // D4 = (c13, 0, c11, c10, c9, 0, c15, c14)

    s[0] = (int64_t)c[0] + 2 * (int64_t)c[8] + (int64_t)c[9] - (int64_t)c[11] - (int64_t)c[12] - (int64_t)c[13] - (int64_t)c[14];
    s[1] = (int64_t)c[1] + 2 * (int64_t)c[9] + (int64_t)c[10] - (int64_t)c[12] - (int64_t)c[13] - (int64_t)c[14] - (int64_t)c[15];
    s[2] = (int64_t)c[2] + 2 * (int64_t)c[10] + (int64_t)c[11] - (int64_t)c[13] - (int64_t)c[14] - (int64_t)c[15];
    s[3] = (int64_t)c[3] + (int64_t)c[11] + (int64_t)c[12] - (int64_t)c[8] - (int64_t)c[9] - (int64_t)c[14] - (int64_t)c[15];
    s[4] = (int64_t)c[4] + (int64_t)c[12] + (int64_t)c[13] - (int64_t)c[9] - (int64_t)c[10] - (int64_t)c[15];
    s[5] = (int64_t)c[5] + (int64_t)c[13] + (int64_t)c[14] - (int64_t)c[10] - (int64_t)c[11];
    s[6] = (int64_t)c[6] + (int64_t)c[13] + 2 * (int64_t)c[14] + (int64_t)c[15] - (int64_t)c[8] - (int64_t)c[9];
    s[7] = (int64_t)c[7] + 2 * (int64_t)c[15] + (int64_t)c[14] + (int64_t)c[13] + (int64_t)c[12] - (int64_t)c[11] - (int64_t)c[10] - (int64_t)c[8];

    int64_t carry = 0;
    uint32_t res32[8];
    for (int i = 0; i < 8; i++) {
        int64_t cur = s[i] + carry;
        res32[i] = (uint32_t)(cur & 0xFFFFFFFFULL);
        carry = cur >> 32;
    }

    u256 r;
    r.w[0] = ((uint64_t)res32[1] << 32) | res32[0];
    r.w[1] = ((uint64_t)res32[3] << 32) | res32[2];
    r.w[2] = ((uint64_t)res32[5] << 32) | res32[4];
    r.w[3] = ((uint64_t)res32[7] << 32) | res32[6];

    while (carry > 0) {
        r = u256_sub(r, p256, nullptr);
        carry--;
    }
    while (carry < 0) {
        r = u256_add(r, p256, nullptr);
        carry++;
    }
    while (u256_cmp(r, p256) >= 0) {
        r = u256_sub(r, p256, nullptr);
    }
    return r;
}

static u256 u256_mod_mul(const u256 &a, const u256 &b) {
    return u512_reduce_p256(u256_mul(a, b));
}

static u256 u256_mod_sqr(const u256 &a) {
    return u256_mod_mul(a, a);
}

// Modular exponentiation under p256: base^exp mod p256
static u256 u256_mod_exp(u256 base, const u256 &exp) {
    u256 r = { { 1, 0, 0, 0 } };
    for (int i = 3; i >= 0; i--) {
        for (int b = 63; b >= 0; b--) {
            r = u256_mod_sqr(r);
            if ((exp.w[i] >> b) & 1) {
                r = u256_mod_mul(r, base);
            }
        }
    }
    return r;
}

// Fermat inversion: a^(p-2) mod p
static u256 u256_mod_inv_p(const u256 &a) {
    u256 p_minus_2 = p256;
    p_minus_2.w[0] -= 2;
    return u256_mod_exp(a, p_minus_2);
}

// Jacobian Point (X : Y : Z) representing Affine (X / Z^2, Y / Z^3)
struct PointJ {
    u256 x, y, z;
};

struct PointA {
    u256 x, y;
};

static bool point_is_infinity(const PointJ &p) {
    return u256_is_zero(p.z);
}

static PointJ point_double(const PointJ &p) {
    if (point_is_infinity(p) || u256_is_zero(p.y)) {
        return { { { 0, 0, 0, 0 } }, { { 1, 0, 0, 0 } }, { { 0, 0, 0, 0 } } };
    }
    u256 A = u256_mod_sqr(p.x);
    u256 B = u256_mod_sqr(p.y);
    u256 C = u256_mod_sqr(B);
    u256 X_plus_B = u256_mod_add(p.x, B, p256);
    u256 D = u256_mod_sub(u256_mod_sqr(X_plus_B), u256_mod_add(A, C, p256), p256);
    D = u256_mod_add(D, D, p256);

    // E = 3 * (X - Z^2) * (X + Z^2) for a = -3
    u256 Z2 = u256_mod_sqr(p.z);
    u256 E = u256_mod_mul(u256_mod_sub(p.x, Z2, p256), u256_mod_add(p.x, Z2, p256));
    E = u256_mod_add(E, u256_mod_add(E, E, p256), p256);

    u256 X3 = u256_mod_sub(u256_mod_sqr(E), u256_mod_add(D, D, p256), p256);
    u256 Y3 = u256_mod_sub(u256_mod_mul(E, u256_mod_sub(D, X3, p256)),
                           u256_mod_add(u256_mod_add(u256_mod_add(C, C, p256), u256_mod_add(C, C, p256), p256),
                                        u256_mod_add(u256_mod_add(C, C, p256), u256_mod_add(C, C, p256), p256), p256), p256);
    u256 Z3 = u256_mod_mul(u256_mod_add(p.y, p.y, p256), p.z);
    return { X3, Y3, Z3 };
}

static PointJ point_add(const PointJ &p, const PointJ &q) {
    if (point_is_infinity(p)) return q;
    if (point_is_infinity(q)) return p;

    u256 Z1_sq = u256_mod_sqr(p.z);
    u256 Z2_sq = u256_mod_sqr(q.z);
    u256 U1 = u256_mod_mul(p.x, Z2_sq);
    u256 U2 = u256_mod_mul(q.x, Z1_sq);
    u256 S1 = u256_mod_mul(u256_mod_mul(p.y, q.z), Z2_sq);
    u256 S2 = u256_mod_mul(u256_mod_mul(q.y, p.z), Z1_sq);

    if (u256_cmp(U1, U2) == 0) {
        if (u256_cmp(S1, S2) == 0) {
            return point_double(p);
        }
        return { { { 0, 0, 0, 0 } }, { { 1, 0, 0, 0 } }, { { 0, 0, 0, 0 } } };
    }

    u256 H = u256_mod_sub(U2, U1, p256);
    u256 R = u256_mod_sub(S2, S1, p256);
    u256 H_sq = u256_mod_sqr(H);
    u256 H_cu = u256_mod_mul(H, H_sq);
    u256 V = u256_mod_mul(U1, H_sq);

    u256 X3 = u256_mod_sub(u256_mod_sub(u256_mod_sqr(R), H_cu, p256), u256_mod_add(V, V, p256), p256);
    u256 Y3 = u256_mod_sub(u256_mod_mul(R, u256_mod_sub(V, X3, p256)), u256_mod_mul(S1, H_cu), p256);
    u256 Z3 = u256_mod_mul(u256_mod_mul(p.z, q.z), H);
    return { X3, Y3, Z3 };
}

static PointA to_affine(const PointJ &p) {
    if (point_is_infinity(p)) {
        return { { { 0, 0, 0, 0 } }, { { 0, 0, 0, 0 } } };
    }
    u256 z_inv = u256_mod_inv_p(p.z);
    u256 z_inv_sq = u256_mod_sqr(z_inv);
    u256 z_inv_cu = u256_mod_mul(z_inv, z_inv_sq);
    return { u256_mod_mul(p.x, z_inv_sq), u256_mod_mul(p.y, z_inv_cu) };
}

static PointJ point_mul(const u256 &k, const PointJ &p) {
    PointJ r = { { { 0, 0, 0, 0 } }, { { 1, 0, 0, 0 } }, { { 0, 0, 0, 0 } } };
    PointJ cur = p;
    for (int i = 0; i < 4; i++) {
        uint64_t w = k.w[i];
        for (int b = 0; b < 64; b++) {
            if ((w >> b) & 1) {
                r = point_add(r, cur);
            }
            cur = point_double(cur);
        }
    }
    return r;
}

static bool is_on_curve(const u256 &x, const u256 &y) {
    u256 lhs = u256_mod_sqr(y);
    u256 x3 = u256_mod_mul(x, u256_mod_sqr(x));
    u256 three_x = u256_mod_add(x, u256_mod_add(x, x, p256), p256);
    u256 rhs = u256_mod_add(u256_mod_sub(x3, three_x, p256), b256, p256);
    return u256_cmp(lhs, rhs) == 0;
}

static bool is_quadratic_residue(const u256 &val) {
    u256 p_minus_1_div_2 = p256;
    for (int i = 0; i < 4; i++) {
        p_minus_1_div_2.w[i] >>= 1;
        if (i < 3 && (p256.w[i + 1] & 1)) {
            p_minus_1_div_2.w[i] |= 0x8000000000000000ULL;
        }
    }
    u256 r = u256_mod_exp(val, p_minus_1_div_2);
    return r.w[0] == 1 && r.w[1] == 0 && r.w[2] == 0 && r.w[3] == 0;
}

static void sae_kdf_256(const uint8_t *key, const char *label, const uint8_t *context, uint8_t *out) {
    for (uint16_t counter = 1; counter <= 2; counter++) {
        HMAC_SHA256_CTX hctx;
        HMAC_SHA256_Init(&hctx, key, 32);
        HMAC_SHA256_Update(&hctx, (const uint8_t *)&counter, 2);
        HMAC_SHA256_Update(&hctx, (const uint8_t *)label, strlen(label));
        HMAC_SHA256_Update(&hctx, context, 32);
        uint16_t length_bits = 512;
        HMAC_SHA256_Update(&hctx, (const uint8_t *)&length_bits, 2);
        HMAC_SHA256_Final(out + (counter - 1) * 32, &hctx);
    }
}

static bool derive_pwe(const char *password, const uint8_t sta_mac[6], const uint8_t bssid[6], PointA &PWE_out) {
    uint8_t salt[12];
    if (memcmp(sta_mac, bssid, 6) > 0) {
        memcpy(salt, sta_mac, 6);
        memcpy(salt + 6, bssid, 6);
    } else {
        memcpy(salt, bssid, 6);
        memcpy(salt + 6, sta_mac, 6);
    }

    size_t pw_len = strlen(password);
    for (uint8_t counter = 1; counter <= 40; counter++) {
        uint8_t base[32];
        HMAC_SHA256_CTX hctx;
        HMAC_SHA256_Init(&hctx, salt, sizeof(salt));
        HMAC_SHA256_Update(&hctx, (const uint8_t *)password, pw_len);
        HMAC_SHA256_Update(&hctx, &counter, 1);
        HMAC_SHA256_Final(base, &hctx);

        uint8_t p_bytes[32];
        u256_to_bytes(p256, p_bytes);

        uint8_t x_cand_bytes[64];
        sae_kdf_256(base, "SAE Hunting and Pecking", p_bytes, x_cand_bytes);

        u256 x_cand = u256_from_bytes(x_cand_bytes);
        if (u256_cmp(x_cand, p256) >= 0) continue;

        u256 x3 = u256_mod_mul(x_cand, u256_mod_sqr(x_cand));
        u256 three_x = u256_mod_add(x_cand, u256_mod_add(x_cand, x_cand, p256), p256);
        u256 rhs = u256_mod_add(u256_mod_sub(x3, three_x, p256), b256, p256);

        if (is_quadratic_residue(rhs)) {
            u256 p_plus_1_div_4 = p256;
            p_plus_1_div_4.w[0] += 1;
            for (int i = 0; i < 4; i++) {
                p_plus_1_div_4.w[i] = (p_plus_1_div_4.w[i] >> 2);
                if (i < 3) {
                    p_plus_1_div_4.w[i] |= (p256.w[i + 1] & 3) << 62;
                }
            }

            u256 y_cand = u256_mod_exp(rhs, p_plus_1_div_4);

            uint8_t bit_hash[32];
            HMAC_SHA256_Init(&hctx, base, 32);
            HMAC_SHA256_Update(&hctx, (const uint8_t *)"SAE Hunting and Pecking", 23);
            HMAC_SHA256_Final(bit_hash, &hctx);
            int save_lsb = bit_hash[31] & 1;

            if ((y_cand.w[0] & 1) != (uint64_t)save_lsb) {
                y_cand = u256_mod_sub(p256, y_cand, p256);
            }

            PWE_out.x = x_cand;
            PWE_out.y = y_cand;
            return true;
        }
    }
    return false;
}

extern "C" {

void ieee80211_sae_free(struct ieee80211_node *ni) {
    if (ni && ni->ni_sae) {
        explicit_bzero(ni->ni_sae, sizeof(*ni->ni_sae));
        free(ni->ni_sae);
        ni->ni_sae = nullptr;
    }
}

int ieee80211_sae_start(struct ieee80211com *ic, struct ieee80211_node *ni) {
    if (!ni) return EINVAL;

    if (!ni->ni_sae) {
        ni->ni_sae = (struct ieee80211_sae *)malloc(sizeof(struct ieee80211_sae), 0, 0);
        if (!ni->ni_sae) {
            XYLog("%s: SAE memory allocation failed\n", ic->ic_if.if_xname);
            return ENOMEM;
        }
    }
    struct ieee80211_sae *sae = ni->ni_sae;
    memset(sae, 0, sizeof(*sae));
    sae->group = IEEE80211_SAE_GROUP_P256;
    sae->send_confirm = 1;

    const char *pw = ic->ic_sae_password;
    if (!pw || pw[0] == '\0') {
        XYLog("%s: SAE failed: empty password\n", ic->ic_if.if_xname);
        ieee80211_sae_free(ni);
        return EINVAL;
    }

    PointA PWE;
    if (!derive_pwe(pw, ic->ic_myaddr, ni->ni_bssid, PWE)) {
        XYLog("%s: SAE failed: PWE derivation failed\n", ic->ic_if.if_xname);
        ieee80211_sae_free(ni);
        return EINVAL;
    }

    u256_to_bytes(PWE.x, sae->pwe_x);
    u256_to_bytes(PWE.y, sae->pwe_y);

    // Generate random scalar and mask
    u256 rand_sta, mask_sta;
    do {
        arc4random_buf(&rand_sta, sizeof(rand_sta));
    } while (u256_is_zero(rand_sta) || u256_cmp(rand_sta, q256) >= 0);

    do {
        arc4random_buf(&mask_sta, sizeof(mask_sta));
    } while (u256_is_zero(mask_sta) || u256_cmp(mask_sta, q256) >= 0);

    u256_to_bytes(rand_sta, sae->rand_sta);

    // scalar_sta = (rand_sta + mask_sta) mod q
    u256 scalar_sta = u256_mod_add(rand_sta, mask_sta, q256);
    u256_to_bytes(scalar_sta, sae->scalar_sta);

    // element_sta = -(mask_sta * PWE)
    PointJ PWE_J = { PWE.x, PWE.y, { { 1, 0, 0, 0 } } };
    PointA elem_raw = to_affine(point_mul(mask_sta, PWE_J));
    u256 elem_y_neg = u256_mod_sub(p256, elem_raw.y, p256);

    u256_to_bytes(elem_raw.x, sae->element_sta_x);
    u256_to_bytes(elem_y_neg, sae->element_sta_y);

    sae->state = SAE_STATE_COMMITTED;
    sae->have_peer_commit = false;

    XYLog("%s: SAE start initialized Group 19 Commit\n", ic->ic_if.if_xname);
    return 0;
}

mbuf_t ieee80211_sae_build_commit(struct ieee80211com *ic, struct ieee80211_node *ni) {
    if (!ni || !ni->ni_sae) return nullptr;
    struct ieee80211_sae *sae = ni->ni_sae;

    size_t len = 2 * 3 + 2 + 32 + 64; // 104 bytes
    mbuf_t m;
    mbuf_gethdr(MBUF_DONTWAIT, MT_DATA, &m);
    if (!m) return nullptr;

    mbuf_align_32(m, len);
    mbuf_pkthdr_setlen(m, len);
    mbuf_setlen(m, len);

    uint8_t *frm = mtod(m, uint8_t *);
    LE_WRITE_2(frm, IEEE80211_AUTH_ALG_SAE); frm += 2;
    LE_WRITE_2(frm, 1); frm += 2; // Seq 1 (Commit)
    LE_WRITE_2(frm, IEEE80211_STATUS_SUCCESS); frm += 2;

    LE_WRITE_2(frm, sae->group); frm += 2;
    memcpy(frm, sae->scalar_sta, 32); frm += 32;
    memcpy(frm, sae->element_sta_x, 32); frm += 32;
    memcpy(frm, sae->element_sta_y, 32); frm += 32;

    return m;
}

mbuf_t ieee80211_sae_build_confirm(struct ieee80211com *ic, struct ieee80211_node *ni) {
    if (!ni || !ni->ni_sae) return nullptr;
    struct ieee80211_sae *sae = ni->ni_sae;

    // Confirm token: HMAC-SHA256(KCK, send_confirm || scalar_sta || elem_sta || scalar_peer || elem_peer)
    uint8_t confirm_token[32];
    HMAC_SHA256_CTX hctx;
    HMAC_SHA256_Init(&hctx, sae->kck, 32);
    HMAC_SHA256_Update(&hctx, (const uint8_t *)&sae->send_confirm, 2);
    HMAC_SHA256_Update(&hctx, sae->scalar_sta, 32);
    HMAC_SHA256_Update(&hctx, sae->element_sta_x, 32);
    HMAC_SHA256_Update(&hctx, sae->element_sta_y, 32);
    HMAC_SHA256_Update(&hctx, sae->scalar_peer, 32);
    HMAC_SHA256_Update(&hctx, sae->element_peer_x, 32);
    HMAC_SHA256_Update(&hctx, sae->element_peer_y, 32);
    HMAC_SHA256_Final(confirm_token, &hctx);

    size_t len = 2 * 3 + 2 + 32; // 40 bytes
    mbuf_t m;
    mbuf_gethdr(MBUF_DONTWAIT, MT_DATA, &m);
    if (!m) return nullptr;

    mbuf_align_32(m, len);
    mbuf_pkthdr_setlen(m, len);
    mbuf_setlen(m, len);

    uint8_t *frm = mtod(m, uint8_t *);
    LE_WRITE_2(frm, IEEE80211_AUTH_ALG_SAE); frm += 2;
    LE_WRITE_2(frm, 2); frm += 2; // Seq 2 (Confirm)
    LE_WRITE_2(frm, IEEE80211_STATUS_SUCCESS); frm += 2;

    LE_WRITE_2(frm, sae->send_confirm); frm += 2;
    memcpy(frm, confirm_token, 32); frm += 32;

    return m;
}

void ieee80211_sae_rx_auth(struct ieee80211com *ic, mbuf_t m, struct ieee80211_node *ni,
                           uint16_t seq, uint16_t status) {
    if (!ni || !ni->ni_sae) {
        XYLog("%s: SAE auth dropped: no active SAE session\n", ic->ic_if.if_xname);
        return;
    }
    struct ieee80211_sae *sae = ni->ni_sae;
    const struct ieee80211_frame *wh = mtod(m, struct ieee80211_frame *);
    const uint8_t *frm = (const uint8_t *)&wh[1] + 6; // past algo, seq, status
    size_t body_len = mbuf_len(m) - sizeof(*wh) - 6;

    if (status != IEEE80211_STATUS_SUCCESS) {
        XYLog("%s: SAE authentication failed status=%u seq=%u from %s\n",
              ic->ic_if.if_xname, status, seq, ether_sprintf((uint8_t *)wh->i_addr2));
        ic->ic_assoc_status = status;
        sae->state = SAE_STATE_NOTHING;
        return;
    }

    if (seq == 1) { // Peer Commit
        if (body_len < 2 + 32 + 64) {
            XYLog("%s: SAE Commit frame too short (%zu bytes)\n", ic->ic_if.if_xname, body_len);
            return;
        }

        uint16_t peer_group = LE_READ_2(frm); frm += 2;
        if (peer_group != IEEE80211_SAE_GROUP_P256) {
            XYLog("%s: SAE unsupported group %u\n", ic->ic_if.if_xname, peer_group);
            return;
        }

        memcpy(sae->scalar_peer, frm, 32); frm += 32;
        memcpy(sae->element_peer_x, frm, 32); frm += 32;
        memcpy(sae->element_peer_y, frm, 32); frm += 32;

        u256 peer_scalar = u256_from_bytes(sae->scalar_peer);
        u256 peer_x = u256_from_bytes(sae->element_peer_x);
        u256 peer_y = u256_from_bytes(sae->element_peer_y);

        if (u256_is_zero(peer_scalar) || u256_cmp(peer_scalar, q256) >= 0) {
            XYLog("%s: SAE invalid peer scalar\n", ic->ic_if.if_xname);
            return;
        }
        if (!is_on_curve(peer_x, peer_y)) {
            XYLog("%s: SAE peer element not on curve\n", ic->ic_if.if_xname);
            return;
        }

        // K = rand_sta * (element_peer + scalar_peer * PWE)
        PointA PWE = { u256_from_bytes(sae->pwe_x), u256_from_bytes(sae->pwe_y) };
        PointJ PWE_J = { PWE.x, PWE.y, { { 1, 0, 0, 0 } } };
        PointJ scalar_peer_PWE = point_mul(peer_scalar, PWE_J);
        PointJ elem_peer_J = { peer_x, peer_y, { { 1, 0, 0, 0 } } };
        PointJ term_sta_J = point_add(elem_peer_J, scalar_peer_PWE);

        u256 rand_sta = u256_from_bytes(sae->rand_sta);
        PointA K = to_affine(point_mul(rand_sta, term_sta_J));

        if (u256_is_zero(K.x) && u256_is_zero(K.y)) {
            XYLog("%s: SAE derived point at infinity\n", ic->ic_if.if_xname);
            return;
        }

        // Key Derivation:
        uint8_t z[32];
        u256_to_bytes(K.x, z);

        uint8_t zeros[32] = {0};
        uint8_t keyseed[32];
        HMAC_SHA256_CTX hctx;
        HMAC_SHA256_Init(&hctx, zeros, 32);
        HMAC_SHA256_Update(&hctx, z, 32);
        HMAC_SHA256_Final(keyseed, &hctx);

        u256 scalar_sta = u256_from_bytes(sae->scalar_sta);
        u256 sum_scalars = u256_mod_add(scalar_sta, peer_scalar, q256);
        uint8_t context[32];
        u256_to_bytes(sum_scalars, context);

        uint8_t keys[64];
        sae_kdf_256(keyseed, "SAE KCK and PMK", context, keys);
        memcpy(sae->kck, keys, 32);
        memcpy(sae->pmk, keys + 32, 32);

        sae->have_peer_commit = true;
        XYLog("%s: SAE Commit processed, shared secret derived\n", ic->ic_if.if_xname);

        // Send Confirm frame
        sae->state = SAE_STATE_CONFIRMED;
        IEEE80211_SEND_MGMT(ic, ni, IEEE80211_FC0_SUBTYPE_AUTH, 2);
    } else if (seq == 2) { // Peer Confirm
        if (!sae->have_peer_commit) {
            XYLog("%s: SAE Confirm received before Commit\n", ic->ic_if.if_xname);
            return;
        }
        if (body_len < 2 + 32) {
            XYLog("%s: SAE Confirm frame too short\n", ic->ic_if.if_xname);
            return;
        }

        uint16_t peer_send_confirm = LE_READ_2(frm); frm += 2;
        const uint8_t *peer_confirm = frm;

        // Verify AP Confirm: HMAC-SHA256(KCK, peer_send_confirm || scalar_peer || elem_peer || scalar_sta || elem_sta)
        uint8_t expected_confirm[32];
        HMAC_SHA256_CTX hctx;
        HMAC_SHA256_Init(&hctx, sae->kck, 32);
        HMAC_SHA256_Update(&hctx, (const uint8_t *)&peer_send_confirm, 2);
        HMAC_SHA256_Update(&hctx, sae->scalar_peer, 32);
        HMAC_SHA256_Update(&hctx, sae->element_peer_x, 32);
        HMAC_SHA256_Update(&hctx, sae->element_peer_y, 32);
        HMAC_SHA256_Update(&hctx, sae->scalar_sta, 32);
        HMAC_SHA256_Update(&hctx, sae->element_sta_x, 32);
        HMAC_SHA256_Update(&hctx, sae->element_sta_y, 32);
        HMAC_SHA256_Final(expected_confirm, &hctx);

        if (memcmp(peer_confirm, expected_confirm, 32) != 0) {
            XYLog("%s: SAE peer Confirm token mismatch!\n", ic->ic_if.if_xname);
            ic->ic_assoc_status = IEEE80211_STATUS_UNSPECIFIED;
            sae->state = SAE_STATE_NOTHING;
            return;
        }

        // Derive PMKID: HMAC-SHA256(KCK, "PMKID" || bssid || sta_mac)[0..15]
        uint8_t pmkid_full[32];
        HMAC_SHA256_Init(&hctx, sae->kck, 32);
        HMAC_SHA256_Update(&hctx, (const uint8_t *)"PMKID", 5);
        HMAC_SHA256_Update(&hctx, ni->ni_bssid, 6);
        HMAC_SHA256_Update(&hctx, ic->ic_myaddr, 6);
        HMAC_SHA256_Final(pmkid_full, &hctx);
        memcpy(sae->pmkid, pmkid_full, 16);

        // Copy keys to node and controller
        memcpy(ni->ni_pmk, sae->pmk, IEEE80211_PMK_LEN);
        memcpy(ic->ic_psk, sae->pmk, IEEE80211_PMK_LEN);
        memcpy(ni->ni_pmkid, sae->pmkid, IEEE80211_PMKID_LEN);
        ni->ni_flags |= IEEE80211_NODE_PMK | IEEE80211_NODE_PMKID | IEEE80211_NODE_MFP;
        ni->ni_rsngroupmgmtcipher = IEEE80211_CIPHER_BIP;
        ic->ic_rsngroupmgmtcipher = IEEE80211_CIPHER_BIP;
        ieee80211_pmksa_add(ic, (enum ieee80211_akm)ni->ni_rsnakms,
            ni->ni_bssid, sae->pmk, IEEE80211_PMK_INFINITE);

        sae->state = SAE_STATE_ACCEPTED;
        XYLog("%s: SAE Handshake 100%% VERIFIED! PMK and PMKID installed. Transitioning to ASSOC.\n",
              ic->ic_if.if_xname);

        ieee80211_new_state(ic, IEEE80211_S_ASSOC, 0);
    }
}

} // extern "C"
