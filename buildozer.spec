[app]

title = ytcc-dl
package.name = ytccdl
package.domain = com.diudiuqiang
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt,json,ttc,ttf,otf
# vendor 的 yt-dlp 包（含抖音签名补丁）+ 中文字体，整个打进去
source.include_dirs = vendor, assets
source.exclude_dirs = tests, .git, __pycache__, .buildozer, bin
source.exclude_exts = spec, log, pyc

version = 1.0.0

# 只打国内四站，yt-dlp 走 vendor 本地包，不写 requirements（避免 pip 拉到无补丁版）
requirements = python3,kivy

orientation = portrait
fullscreen = 0
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 35
android.minapi = 24
android.ndk_api = 24
android.accept_sdk_license = True
# 局域网 HTTP 明文（CookieCloud http://192.168.x.x）：Android 9+ 默认禁明文，
# 通过 application 参数打开。若新版 buildozer 的引号 bug 触发，pre_buildozer.py 兜底。
android.extra_manifest_application_arguments = extra_manifest.xml

p4a.branch = develop

# 日志
log_level = 2

[buildozer]
log_level = 2
warn_on_root = 0
