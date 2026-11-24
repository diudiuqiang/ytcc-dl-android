#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心逻辑测试：平台识别 / URL 校验 / 画质格式 / 抖音补丁存在性。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
import ytcc_core as c


class TestCore(unittest.TestCase):
    def test_detect_platform(self):
        cases = {
            "https://www.bilibili.com/video/BV1xx411c7mD": "B站 (Bilibili)",
            "https://b23.tv/abc123": "B站 (Bilibili)",
            "https://v.douyin.com/-aK59AMZ0S8": "抖音 (Douyin)",
            "https://www.douyin.com/video/7123456789": "抖音 (Douyin)",
            "https://t.cn/A6xxxxx": "微博 (Weibo)",
            "https://weibo.com/123/456": "微博 (Weibo)",
            "https://xhslink.com/a/abc": "小红书 (Xiaohongshu)",
            "https://www.xiaohongshu.com/explore/abc": "小红书 (Xiaohongshu)",
        }
        for url, want in cases.items():
            self.assertEqual(c.detect_platform(url), want, url)
        self.assertIsNone(c.detect_platform("https://example.com/v"))

    def test_url_validation(self):
        self.assertFalse(c.is_valid_media_url("")[0])
        self.assertFalse(c.is_valid_media_url("C:\\a.mp4")[0])
        self.assertFalse(c.is_valid_media_url("file:///a.mp4")[0])
        self.assertFalse(c.is_valid_media_url("douyin.com/x")[0])
        ok, _ = c.is_valid_media_url("https://v.douyin.com/-aK59AMZ0S8")
        self.assertTrue(ok)

    def test_build_format(self):
        self.assertIn("height<=1080", c.build_format("1080p"))
        self.assertIn("height<=720", c.build_format("720p"))
        self.assertEqual(c.build_format("最佳(单流)"), "best[ext=mp4]/best")
        self.assertIn("bestaudio", c.build_format("仅音频"))

    def test_douyin_patch_vendored(self):
        p = os.path.join(ROOT, "vendor", "yt_dlp", "extractor", "tiktok.py")
        self.assertTrue(os.path.exists(p), "vendor 的 tiktok.py 不存在")
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("secsdk", src, "vendor yt-dlp 缺少抖音签名补丁")

    def test_douyin_share_url_normalized(self):
        """iesdouyin 分享页必须归一化成 DouyinIE 认的标准链接（Android UA 会 302 到这里）。"""
        share = ("https://www.iesdouyin.com/share/video/7711305629154989797/"
                 "?region=CN&mid=xxx&u_code=abc")
        self.assertEqual(c._normalize_douyin(share),
                         "https://www.douyin.com/video/7711305629154989797")
        # 已是标准链接则不变
        std = "https://www.douyin.com/video/7711305629154989797?previous_page=x"
        self.assertEqual(c._normalize_douyin(std), std)

    def test_domain_match_strict(self):
        self.assertTrue(c._domain_matches("www.douyin.com", ("douyin.com",)))
        self.assertTrue(c._domain_matches("douyin.com", ("douyin.com",)))
        self.assertFalse(c._domain_matches("notdouyin.com", ("douyin.com",)))
        self.assertFalse(c._domain_matches("douyin.com.evil.com", ("douyin.com",)))


if __name__ == "__main__":
    unittest.main()
