#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建前 patch：给 AndroidManifest 模板加 usesCleartextTraffic。

背景：CookieCloud 走局域网 HTTP（http://192.168.x.x:10888），Android 9+ 默认禁明文，
不设 android:usesCleartextTraffic="true" 会报 ERR_CLEARTEXT_NOT_PERMITTED。
buildozer.spec 的 android.extra_manifest_application_arguments 在新版有加引号的 bug，
故直接在 p4a 生成的模板上改（幂等，多次构建安全）。
"""
import glob
import os

patches = 0
# p4a 首次解压后才会生成模板；这里扫描所有可能的模板位置
patterns = [
    ".buildozer/android/platform/build*/dists/*/templates/AndroidManifest.tmpl.xml",
    ".buildozer/android/platform/build*/dists/*/AndroidManifest.xml",
]
for pat in patterns:
    for path in glob.glob(pat):
        try:
            with open(path, encoding="utf-8") as fh:
                txt = fh.read()
            if 'usesCleartextTraffic' in txt:
                continue
            # 只改 <application 标签，加明文开关
            if '<application' in txt:
                new = txt.replace('<application', '<application android:usesCleartextTraffic="true"', 1)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(new)
                patches += 1
                print("PATCHED", path)
        except Exception as e:
            print("SKIP", path, e)

print("cleartext patches applied:", patches)
