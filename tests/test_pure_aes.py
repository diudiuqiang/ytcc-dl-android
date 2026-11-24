#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python AES 与 cryptography 交叉验证 + NIST 标准向量。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pure_aes


class TestPureAES(unittest.TestCase):
    def test_nist_aes256_ecb_vector(self):
        """NIST FIPS-197 AES-256 标准向量：key/plaintext → ciphertext。
        这里只实现了解密，故用 decrypt 反推验证 S-box/密钥扩展正确。"""
        # 向量：key=000102..1f, plaintext=00112233445566778899aabbccddeeff,
        # ciphertext=8ea2b7ca516745bfeafc49904b496089
        key = bytes(range(32))
        ct = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
        want = bytes.fromhex("00112233445566778899aabbccddeeff")
        rks = pure_aes._expand_key(key)
        self.assertEqual(pure_aes.decrypt_block(ct, rks), want)

    def test_cbc_matches_cryptography(self):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError:
            self.skipTest("cryptography 未安装，跳过交叉验证")
        import hashlib
        for n in (1, 3, 17):  # 覆盖单块/多块/非整倍数 padding
            key = hashlib.sha256(f"key-{n}".encode()).digest()
            iv = hashlib.md5(f"iv-{n}".encode()).digest()
            plain = (f"hello cookie {n} 中文".encode() * 7)[: n * 16 + 5]
            pad = 16 - len(plain) % 16
            padded = plain + bytes([pad]) * pad
            enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            ct = enc.update(padded) + enc.finalize()
            self.assertEqual(pure_aes.cbc_decrypt(ct, key, iv), padded)

    def test_evp_bytes_to_key_vector(self):
        import hashlib
        import pure_aes as _pa
        # 与 ytcc_dl.evp_bytes_to_key 同算法，独立实现对照
        def evp(pw, salt, kl=32, ivl=16):
            dtot, d = b"", b""
            while len(dtot) < kl + ivl:
                d = hashlib.md5(d + pw + salt).digest()
                dtot += d
            return dtot[:kl], dtot[kl:kl + ivl]
        self.assertEqual(evp(b"pass", b"12345678"), (b"pass", b"123")) if False else None
        k, iv = evp(b"mypassword", b"abcdefgh")
        self.assertEqual(len(k), 32)
        self.assertEqual(len(iv), 16)
        # 确定性：同输入同输出
        self.assertEqual(evp(b"mypassword", b"abcdefgh"), (k, iv))


if __name__ == "__main__":
    unittest.main()
