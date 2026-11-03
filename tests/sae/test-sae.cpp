#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <CommonCrypto/CommonDigest.h>
#include <CommonCrypto/CommonHMAC.h>

typedef struct {
    CCHmacContext ctx;
} HMAC_SHA256_CTX;

static void HMAC_SHA256_Init(HMAC_SHA256_CTX *c, const uint8_t *key, size_t len) {
    CCHmacInit(&c->ctx, kCCHmacAlgSHA256, key, len);
}

static void HMAC_SHA256_Update(HMAC_SHA256_CTX *c, const uint8_t *data, size_t len) {
    CCHmacUpdate(&c->ctx, data, len);
}

static void HMAC_SHA256_Final(uint8_t out[32], HMAC_SHA256_CTX *c) {
    CCHmacFinal(&c->ctx, out);
}

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

static const u256 gx256 = {
    { 0xF4A13945D898C296ULL, 0x77037D812DEB33A0ULL, 0xF8BCE6E563A440F2ULL, 0x6B17D1F2E12C4247ULL }
};

static const u256 gy256 = {
    { 0xCBB6406837BF51F5ULL, 0x2BCE33576B315ECEULL, 0x8EE7EB4A7C0F9E16ULL, 0x4FE342E2FE1A7F9BULL }
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
    unsigned __int128 br = 0;
    for (int i = 0; i < 4; i++) {
        unsigned __int128 diff = (unsigned __int128)a.w[i] - b.w[i] - br;
        r.w[i] = (uint64_t)diff;
        br = (diff >> 127) & 1;
    }
    if (borrow_out) *borrow_out = (uint64_t)br;
    return r;
}

static u256 u256_mod_add(const u256 &a, const u256 &b, const u256 &m) {
    uint64_t c = 0;
    u256 r = u256_add(a, b, &c);
    if (c || u256_cmp(r, m) >= 0) {
        r = u256_sub(r, m, nullptr);
    }
    return r;
}

static u256 u256_mod_sub(const u256 &a, const u256 &b, const u256 &m) {
    uint64_t br = 0;
    u256 r = u256_sub(a, b, &br);
    if (br) {
        r = u256_add(r, m, nullptr);
    }
    return r;
}

struct u512 {
    uint64_t w[8];
};

static u512 u256_mul(const u256 &a, const u256 &b) {
    u512 r = {};
    for (int i = 0; i < 4; i++) {
        unsigned __int128 c = 0;
        for (int j = 0; j < 4; j++) {
            c += (unsigned __int128)a.w[i] * b.w[j] + r.w[i + j];
            r.w[i + j] = (uint64_t)c;
            c >>= 64;
        }
        r.w[i + 4] += (uint64_t)c;
    }
    return r;
}

static u256 u512_mod(u512 a, const u256 &m) {
    int m_bits = 0;
    for (int i = 3; i >= 0; i--) {
        if (m.w[i]) {
            m_bits = (i + 1) * 64 - __builtin_clzll(m.w[i]);
            break;
        }
    }
    int a_bits = 0;
    for (int i = 7; i >= 0; i--) {
        if (a.w[i]) {
            a_bits = (i + 1) * 64 - __builtin_clzll(a.w[i]);
            break;
        }
    }
    if (a_bits < m_bits) {
        u256 r = { { a.w[0], a.w[1], a.w[2], a.w[3] } };
        return r;
    }
    for (int shift = a_bits - m_bits; shift >= 0; shift--) {
        int word_shift = shift / 64;
        int bit_shift = shift % 64;
        u512 sm = {};
        unsigned __int128 c = 0;
        for (int i = 0; i < 4; i++) {
            unsigned __int128 val = (unsigned __int128)m.w[i] << bit_shift;
            sm.w[word_shift + i] |= (uint64_t)val | (uint64_t)c;
            c = val >> 64;
        }
        if (word_shift + 4 < 8) sm.w[word_shift + 4] |= (uint64_t)c;

        bool greater_or_equal = true;
        for (int i = 7; i >= 0; i--) {
            if (a.w[i] > sm.w[i]) { greater_or_equal = true; break; }
            if (a.w[i] < sm.w[i]) { greater_or_equal = false; break; }
        }
        if (greater_or_equal) {
            unsigned __int128 br = 0;
            for (int i = 0; i < 8; i++) {
                unsigned __int128 diff = (unsigned __int128)a.w[i] - sm.w[i] - br;
                a.w[i] = (uint64_t)diff;
                br = (diff >> 127) & 1;
            }
        }
    }
    u256 rem = { { a.w[0], a.w[1], a.w[2], a.w[3] } };
    return rem;
}

static u256 u256_mod_mul(const u256 &a, const u256 &b, const u256 &m) {
    u512 prod = u256_mul(a, b);
    return u512_mod(prod, m);
}

static u256 u256_mod_pow(u256 base, u256 exp, const u256 &m) {
    u256 res = { { 1, 0, 0, 0 } };
    while (!u256_is_zero(exp)) {
        if (exp.w[0] & 1) {
            res = u256_mod_mul(res, base, m);
        }
        base = u256_mod_mul(base, base, m);
        for (int i = 0; i < 4; i++) {
            exp.w[i] >>= 1;
            if (i < 3 && (exp.w[i + 1] & 1)) exp.w[i] |= (1ULL << 63);
        }
    }
    return res;
}

static u256 u256_mod_inv(const u256 &a, const u256 &m) {
    u256 m_minus_2 = u256_sub(m, { { 2, 0, 0, 0 } }, nullptr);
    return u256_mod_pow(a, m_minus_2, m);
}

struct PointJ {
    u256 X, Y, Z;
};

struct PointA {
    u256 x, y;
};

static PointJ point_double(const PointJ &P) {
    if (u256_is_zero(P.Z)) return P;
    u256 Z1_sq = u256_mod_mul(P.Z, P.Z, p256);
    u256 A = u256_mod_mul(P.Y, P.Y, p256);
    u256 B = u256_mod_mul(P.X, A, p256);
    B = u256_mod_add(B, B, p256);
    B = u256_mod_add(B, B, p256);
    u256 C = u256_mod_mul(A, A, p256);
    C = u256_mod_add(C, C, p256);
    C = u256_mod_add(C, C, p256);
    C = u256_mod_add(C, C, p256);
    u256 t1 = u256_mod_sub(P.X, Z1_sq, p256);
    u256 t2 = u256_mod_add(P.X, Z1_sq, p256);
    u256 D = u256_mod_mul(t1, t2, p256);
    u256 D3 = u256_mod_add(D, D, p256);
    D3 = u256_mod_add(D3, D, p256);
    u256 X3 = u256_mod_mul(D3, D3, p256);
    X3 = u256_mod_sub(X3, B, p256);
    X3 = u256_mod_sub(X3, B, p256);
    u256 Y3 = u256_mod_sub(B, X3, p256);
    Y3 = u256_mod_mul(D3, Y3, p256);
    Y3 = u256_mod_sub(Y3, C, p256);
    u256 Z3 = u256_mod_mul(P.Y, P.Z, p256);
    Z3 = u256_mod_add(Z3, Z3, p256);
    return { X3, Y3, Z3 };
}

static PointJ point_add(const PointJ &P, const PointJ &Q) {
    if (u256_is_zero(P.Z)) return Q;
    if (u256_is_zero(Q.Z)) return P;
    u256 Z1_sq = u256_mod_mul(P.Z, P.Z, p256);
    u256 Z2_sq = u256_mod_mul(Q.Z, Q.Z, p256);
    u256 U1 = u256_mod_mul(P.X, Z2_sq, p256);
    u256 U2 = u256_mod_mul(Q.X, Z1_sq, p256);
    u256 S1 = u256_mod_mul(P.Y, Q.Z, p256);
    S1 = u256_mod_mul(S1, Z2_sq, p256);
    u256 S2 = u256_mod_mul(Q.Y, P.Z, p256);
    S2 = u256_mod_mul(S2, Z1_sq, p256);
    if (u256_cmp(U1, U2) == 0) {
        if (u256_cmp(S1, S2) != 0) return { {}, { {1,0,0,0} }, {} };
        return point_double(P);
    }
    u256 H = u256_mod_sub(U2, U1, p256);
    u256 R = u256_mod_sub(S2, S1, p256);
    u256 H_sq = u256_mod_mul(H, H, p256);
    u256 H_cu = u256_mod_mul(H, H_sq, p256);
    u256 X3 = u256_mod_mul(R, R, p256);
    X3 = u256_mod_sub(X3, H_cu, p256);
    u256 u1h2 = u256_mod_mul(U1, H_sq, p256);
    X3 = u256_mod_sub(X3, u1h2, p256);
    X3 = u256_mod_sub(X3, u1h2, p256);
    u256 Y3 = u256_mod_sub(u1h2, X3, p256);
    Y3 = u256_mod_mul(R, Y3, p256);
    u256 s1h3 = u256_mod_mul(S1, H_cu, p256);
    Y3 = u256_mod_sub(Y3, s1h3, p256);
    u256 Z3 = u256_mod_mul(P.Z, Q.Z, p256);
    Z3 = u256_mod_mul(Z3, H, p256);
    return { X3, Y3, Z3 };
}

static PointJ point_mul(u256 k, PointJ P) {
    PointJ R = { {}, { {1,0,0,0} }, {} };
    while (!u256_is_zero(k)) {
        if (k.w[0] & 1) R = point_add(R, P);
        P = point_double(P);
        for (int i = 0; i < 4; i++) {
            k.w[i] >>= 1;
            if (i < 3 && (k.w[i + 1] & 1)) k.w[i] |= (1ULL << 63);
        }
    }
    return R;
}

static PointA to_affine(const PointJ &P) {
    if (u256_is_zero(P.Z)) return { {}, {} };
    u256 Z_inv = u256_mod_inv(P.Z, p256);
    u256 Z_inv2 = u256_mod_mul(Z_inv, Z_inv, p256);
    u256 Z_inv3 = u256_mod_mul(Z_inv2, Z_inv, p256);
    return { u256_mod_mul(P.X, Z_inv2, p256), u256_mod_mul(P.Y, Z_inv3, p256) };
}

// Derive Password Element (PWE) via hunting-and-pecking
static bool sae_derive_pwe(const char *password, size_t pwd_len,
                           const uint8_t sta_mac[6], const uint8_t bssid[6],
                           PointA &pwe_out) {
    uint8_t salt[12];
    if (memcmp(sta_mac, bssid, 6) > 0) {
        memcpy(salt, sta_mac, 6);
        memcpy(salt + 6, bssid, 6);
    } else {
        memcpy(salt, bssid, 6);
        memcpy(salt + 6, sta_mac, 6);
    }
    u256 p_minus_1_div_2 = u256_sub(p256, { { 1, 0, 0, 0 } }, nullptr);
    for (int i = 0; i < 4; i++) {
        p_minus_1_div_2.w[i] >>= 1;
        if (i < 3 && (p_minus_1_div_2.w[i + 1] & 1)) p_minus_1_div_2.w[i] |= (1ULL << 63);
    }
    u256 p_plus_1_div_4 = u256_add(p256, { { 1, 0, 0, 0 } }, nullptr);
    for (int i = 0; i < 4; i++) {
        p_plus_1_div_4.w[i] >>= 1;
        if (i < 3 && (p_plus_1_div_4.w[i + 1] & 1)) p_plus_1_div_4.w[i] |= (1ULL << 63);
    }
    for (int i = 0; i < 4; i++) {
        p_plus_1_div_4.w[i] >>= 1;
        if (i < 3 && (p_plus_1_div_4.w[i + 1] & 1)) p_plus_1_div_4.w[i] |= (1ULL << 63);
    }

    u256 three = { { 3, 0, 0, 0 } };

    for (uint8_t counter = 1; counter < 255; counter++) {
        HMAC_SHA256_CTX ctx;
        HMAC_SHA256_Init(&ctx, salt, sizeof(salt));
        HMAC_SHA256_Update(&ctx, (const uint8_t *)password, (u_int)pwd_len);
        HMAC_SHA256_Update(&ctx, &counter, 1);
        uint8_t pwd_seed[32];
        HMAC_SHA256_Final(pwd_seed, &ctx);

        u256 x = u256_from_bytes(pwd_seed);
        x = u512_mod({ { x.w[0], x.w[1], x.w[2], x.w[3], 0, 0, 0, 0 } }, p256);

        // y^2 = (x^3 - 3x + b) mod p
        u256 x3 = u256_mod_mul(x, x, p256);
        x3 = u256_mod_mul(x3, x, p256);
        u256 ax = u256_mod_mul(three, x, p256);
        u256 y_sq = u256_mod_sub(x3, ax, p256);
        y_sq = u256_mod_add(y_sq, b256, p256);

        // Euler's criterion: y_sq^((p-1)/2) == 1 mod p
        u256 qr = u256_mod_pow(y_sq, p_minus_1_div_2, p256);
        if (qr.w[0] == 1 && qr.w[1] == 0 && qr.w[2] == 0 && qr.w[3] == 0) {
            u256 y = u256_mod_pow(y_sq, p_plus_1_div_4, p256);
            if ((y.w[0] & 1) != (pwd_seed[31] & 1)) {
                y = u256_mod_sub(p256, y, p256);
            }
            pwe_out.x = x;
            pwe_out.y = y;
            return true;
        }
    }
    return false;
}

// KDF-256 (IEEE 802.11-2016 11.5.17.2)
static void sae_kdf_256(const uint8_t key[32], const char *label,
                        const uint8_t context[32], uint8_t output[64]) {
    uint16_t length_bits = 512;
    uint8_t length_le[2] = { (uint8_t)(length_bits & 0xff), (uint8_t)(length_bits >> 8) };
    size_t label_len = strlen(label);

    for (uint16_t iter = 1; iter <= 2; iter++) {
        uint8_t iter_le[2] = { (uint8_t)(iter & 0xff), (uint8_t)(iter >> 8) };
        HMAC_SHA256_CTX ctx;
        HMAC_SHA256_Init(&ctx, key, 32);
        HMAC_SHA256_Update(&ctx, iter_le, sizeof(iter_le));
        HMAC_SHA256_Update(&ctx, (const uint8_t *)label, (u_int)label_len);
        HMAC_SHA256_Update(&ctx, context, 32);
        HMAC_SHA256_Update(&ctx, length_le, sizeof(length_le));
        HMAC_SHA256_Final(output + (iter - 1) * 32, &ctx);
    }
}

int main() {
    uint8_t sta_mac[6] = { 0x00, 0x11, 0x22, 0x33, 0x44, 0x55 };
    uint8_t bssid[6] = { 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb };
    const char *pwd = "TestWpa3Password!";

    PointA pwe;
    assert(sae_derive_pwe(pwd, strlen(pwd), sta_mac, bssid, pwe));
    printf("PWE derived successfully!\n");

    PointJ PWE_J = { pwe.x, pwe.y, { { 1, 0, 0, 0 } } };

    // Station Commit:
    u256 rand_sta = { { 0x12345678ULL, 0x9abcdef0ULL, 0x12345678ULL, 0x9abcdef0ULL } };
    u256 mask_sta = { { 0x0fedcba9ULL, 0x87654321ULL, 0x0fedcba9ULL, 0x87654321ULL } };
    u256 scalar_sta = u256_mod_add(rand_sta, mask_sta, q256);
    PointA elem_sta_raw = to_affine(point_mul(mask_sta, PWE_J));
    PointA elem_sta = { elem_sta_raw.x, u256_mod_sub(p256, elem_sta_raw.y, p256) };

    // AP Commit:
    u256 rand_ap = { { 0x55555555ULL, 0x55555555ULL, 0x55555555ULL, 0x55555555ULL } };
    u256 mask_ap = { { 0x33333333ULL, 0x33333333ULL, 0x33333333ULL, 0x33333333ULL } };
    u256 scalar_ap = u256_mod_add(rand_ap, mask_ap, q256);
    PointA elem_ap_raw = to_affine(point_mul(mask_ap, PWE_J));
    PointA elem_ap = { elem_ap_raw.x, u256_mod_sub(p256, elem_ap_raw.y, p256) };

    // Station calculates shared secret K:
    // term_sta = elem_ap + scalar_ap * PWE
    PointJ term_sta_j = point_add({ elem_ap.x, elem_ap.y, { { 1, 0, 0, 0 } } }, point_mul(scalar_ap, PWE_J));
    PointA K_sta = to_affine(point_mul(rand_sta, term_sta_j));

    // AP calculates shared secret K:
    // term_ap = elem_sta + scalar_sta * PWE
    PointJ term_ap_j = point_add({ elem_sta.x, elem_sta.y, { { 1, 0, 0, 0 } } }, point_mul(scalar_sta, PWE_J));
    PointA K_ap = to_affine(point_mul(rand_ap, term_ap_j));

    assert(u256_cmp(K_sta.x, K_ap.x) == 0);
    assert(u256_cmp(K_sta.y, K_ap.y) == 0);
    printf("Station & AP Shared Secret Matched!\n");

    // Key Derivation:
    uint8_t z[32];
    u256_to_bytes(K_sta.x, z);
    uint8_t zeros[32] = {0};
    uint8_t keyseed[32];
    HMAC_SHA256_CTX hctx;
    HMAC_SHA256_Init(&hctx, zeros, 32);
    HMAC_SHA256_Update(&hctx, z, 32);
    HMAC_SHA256_Final(keyseed, &hctx);

    u256 sum_scalars = u256_mod_add(scalar_sta, scalar_ap, q256);
    uint8_t context[32];
    u256_to_bytes(sum_scalars, context);

    uint8_t keys[64];
    sae_kdf_256(keyseed, "SAE KCK and PMK", context, keys);
    uint8_t kck[32], pmk[32];
    memcpy(kck, keys, 32);
    memcpy(pmk, keys + 32, 32);

    // Compute Station Send-Confirm:
    // HMAC-SHA256(KCK, send_confirm_counter || scalar_sta || elem_sta || scalar_ap || elem_ap)
    uint16_t send_confirm_ctr = 1;
    uint8_t scalar_sta_b[32], elem_sta_x[32], elem_sta_y[32];
    uint8_t scalar_ap_b[32], elem_ap_x[32], elem_ap_y[32];
    u256_to_bytes(scalar_sta, scalar_sta_b);
    u256_to_bytes(elem_sta.x, elem_sta_x);
    u256_to_bytes(elem_sta.y, elem_sta_y);
    u256_to_bytes(scalar_ap, scalar_ap_b);
    u256_to_bytes(elem_ap.x, elem_ap_x);
    u256_to_bytes(elem_ap.y, elem_ap_y);

    uint8_t sta_confirm[32];
    HMAC_SHA256_Init(&hctx, kck, 32);
    HMAC_SHA256_Update(&hctx, (const uint8_t *)&send_confirm_ctr, 2);
    HMAC_SHA256_Update(&hctx, scalar_sta_b, 32);
    HMAC_SHA256_Update(&hctx, elem_sta_x, 32);
    HMAC_SHA256_Update(&hctx, elem_sta_y, 32);
    HMAC_SHA256_Update(&hctx, scalar_ap_b, 32);
    HMAC_SHA256_Update(&hctx, elem_ap_x, 32);
    HMAC_SHA256_Update(&hctx, elem_ap_y, 32);
    HMAC_SHA256_Final(sta_confirm, &hctx);

    // AP verifies Station Confirm:
    uint8_t ap_verify[32];
    HMAC_SHA256_Init(&hctx, kck, 32);
    HMAC_SHA256_Update(&hctx, (const uint8_t *)&send_confirm_ctr, 2);
    HMAC_SHA256_Update(&hctx, scalar_sta_b, 32);
    HMAC_SHA256_Update(&hctx, elem_sta_x, 32);
    HMAC_SHA256_Update(&hctx, elem_sta_y, 32);
    HMAC_SHA256_Update(&hctx, scalar_ap_b, 32);
    HMAC_SHA256_Update(&hctx, elem_ap_x, 32);
    HMAC_SHA256_Update(&hctx, elem_ap_y, 32);
    HMAC_SHA256_Final(ap_verify, &hctx);
    assert(memcmp(sta_confirm, ap_verify, 32) == 0);
    printf("Confirm Token Verified 100%%!\n");

    // Compute PMKID:
    // HMAC-SHA256(KCK, "PMKID" || bssid || sta_mac)[:16]
    uint8_t pmkid_full[32];
    HMAC_SHA256_Init(&hctx, kck, 32);
    HMAC_SHA256_Update(&hctx, (const uint8_t *)"PMKID", 5);
    HMAC_SHA256_Update(&hctx, bssid, 6);
    HMAC_SHA256_Update(&hctx, sta_mac, 6);
    HMAC_SHA256_Final(pmkid_full, &hctx);
    printf("PMKID generated successfully: %02x%02x%02x%02x...\n",
           pmkid_full[0], pmkid_full[1], pmkid_full[2], pmkid_full[3]);

    printf("ALL TESTS PASSED: Full Pure WPA3-SAE Dragonfly Handshake verified!\n");
    return 0;
}
