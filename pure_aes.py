#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python AES-256-CBC 解密（仅供 CookieCloud 数据解密）。

为什么不用 cryptography：python-for-android 编译 cryptography 需要 NDK + OpenSSL，
在 GitHub Actions 上极易失败且拖慢构建。CookieCloud 只用到 AES-256-CBC 解密 +
MD5 EVP_BytesToKey，纯 Python 实现足够（数据仅几 KB，性能无所谓）。

S-box 由 GF(2^8) 求逆 + 仿射变换在 import 时生成，避免手写 512 字节表出错。
正确性已用本地 cryptography 库交叉验证（见 tests/test_pure_aes.py）。
"""


def _gf_mul(a, b):
    """GF(2^8) 乘法，模多项式 x^8+x^4+x^3+x+1 (0x11b)。"""
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _gf_inv(x):
    if x == 0:
        return 0
    for y in range(1, 256):
        if _gf_mul(x, y) == 1:
            return y
    return 0


def _rotl8(v, n):
    return ((v << n) | (v >> (8 - n))) & 0xFF


def _build_sboxes():
    sbox = [0] * 256
    for x in range(256):
        inv = _gf_inv(x)
        sbox[x] = (inv ^ _rotl8(inv, 1) ^ _rotl8(inv, 2)
                   ^ _rotl8(inv, 3) ^ _rotl8(inv, 4) ^ 0x63)
    inv_sbox = [0] * 256
    for x, s in enumerate(sbox):
        inv_sbox[s] = x
    return sbox, inv_sbox


SBOX, INV_SBOX = _build_sboxes()

RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]


def _sub_word(w):
    return [SBOX[b] for b in w]


def _rot_word(w):
    return [w[1], w[2], w[3], w[0]]


def _expand_key(key):
    """AES-256 密钥扩展 → 15 个 16 字节轮密钥（Nr=14）。"""
    assert len(key) == 32, "仅支持 AES-256"
    words = [list(key[i * 4:i * 4 + 4]) for i in range(8)]
    for i in range(8, 60):
        temp = list(words[i - 1])
        if i % 8 == 0:
            temp = _sub_word(_rot_word(temp))
            temp[0] ^= RCON[i // 8 - 1]
        elif i % 8 == 4:
            temp = _sub_word(temp)
        words.append([words[i - 8][j] ^ temp[j] for j in range(4)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(15)]


def _add_round_key(state, rk):
    for i in range(16):
        state[i] ^= rk[i]


def _inv_shift_rows(s):
    # state[r][c] = s[r + 4c]；第 r 行循环右移 r 字节
    old = list(s)
    for r in range(1, 4):
        for c in range(4):
            s[r + 4 * c] = old[r + 4 * ((c - r) % 4)]


def _inv_sub_bytes(s):
    for i in range(16):
        s[i] = INV_SBOX[s[i]]


def _inv_mix_columns(s):
    for c in range(4):
        i = 4 * c
        a0, a1, a2, a3 = s[i], s[i + 1], s[i + 2], s[i + 3]
        s[i] = (_gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9))
        s[i + 1] = (_gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13))
        s[i + 2] = (_gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11))
        s[i + 3] = (_gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14))


def decrypt_block(block, round_keys):
    """解密单个 16 字节分组，返回 16 字节明文。"""
    s = list(block)
    _add_round_key(s, round_keys[14])
    for rnd in range(13, 0, -1):
        _inv_shift_rows(s)
        _inv_sub_bytes(s)
        _add_round_key(s, round_keys[rnd])
        _inv_mix_columns(s)
    _inv_shift_rows(s)
    _inv_sub_bytes(s)
    _add_round_key(s, round_keys[0])
    return bytes(s)


def cbc_decrypt(data, key, iv):
    """AES-CBC 解密，data 长度须为 16 的整数倍。返回含 PKCS#7 padding 的明文。"""
    if len(data) % 16:
        raise ValueError("密文长度不是 16 的整数倍")
    rks = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        plain = decrypt_block(block, rks)
        out.extend(a ^ b for a, b in zip(plain, prev))
        prev = block
    return bytes(out)
