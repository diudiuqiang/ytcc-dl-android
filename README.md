# ytcc-dl 手机版 (Android APK)

把桌面版 ytcc-dl 的视频下载能力搬到手机上：**从局域网 CookieCloud 拉已登录 cookie → 用内置 yt-dlp 下载国内四站视频 → 存到手机 Download 目录**。

## 支持平台

| 平台 | 短链 | 免 cookie 可下 |
|------|------|---------------|
| 抖音 (Douyin) | `v.douyin.com` ✅ | ✅（内置 x-secsdk 签名补丁） |
| B站 (Bilibili) | `b23.tv` ✅ | 公开视频可；高清需 cookie |
| 微博 (Weibo) | `t.cn` ✅ | 公开视频可 |
| 小红书 (Xiaohongshu) | `xhslink.com/.cn` ✅ | 部分需 cookie |

> 只做国内四站。没有 YouTube / X / TikTok（那些要代理和 deno，手机端不做）。

## 安装

1. 手机浏览器打开 APK 下载地址（GitHub Release `ytcc-android-latest` 或 Actions 构建产物）。
2. 下载 APK 后点击安装。OPPO（ColorOS）会提示「禁止安装未知来源应用」→ 按提示给浏览器/文件管理授权「安装未知应用」。
3. 首次打开会请求 **网络** 和 **存储** 权限，点允许。

## 使用

1. **同一 WiFi**：手机必须和 CookieCloud 服务器（NAS）在同一个局域网。
2. 填 CookieCloud 配置：
   - 地址：`http://192.168.31.116:10888`（按你的实际地址改，末尾不要带 `/`）
   - UUID / 密码：和桌面版 CookieCloud 相同
3. 选平台、画质，粘贴视频链接（长短链都行）。
4. 点「只测试拉取」验证 cookie 能拉到；确认后点「⬇ 开始下载」。
5. 视频存到手机 `Download/ytcc-dl/` 目录，用系统文件管理即可查看。

### 抖音小技巧

抖音已内置签名补丁，**可以取消勾选「拉取并使用 cookie」直接下**，省事。如果某个视频失败，再勾上 cookie 试。

## 画质说明

手机端为稳定性做了取舍：**单流直出 mp4，不做 ffmpeg 合并/重编码**（APK 不打包 ffmpeg，体积更小、构建更稳）。
- 「最佳(单流)」：拿到平台能提供的最高单流 mp4；
- B站部分 1080p 是音视频分离的 DASH 流，单流模式下会退到较低的合并流——这是已知限制，换取的是手机端稳定可用。

## 技术说明

- **纯 Python AES 解密**：不依赖 cryptography（p4a 编译极易失败），已用 NIST 向量 + cryptography 交叉验证。
- **yt-dlp 内置**：`vendor/yt_dlp` 是打了抖音签名补丁的版本，随 APK 一起打包，不联网拉包。
- **凭据存储**：CookieCloud 地址/UUID/密码保存在 app 私有目录 `config.json`（不加密，仅存在本机）。
- **局域网直连**：CookieCloud 请求强制绕过代理，确保内网地址可达。
- **明文 HTTP**：Android 9+ 默认禁明文，CookieCloud 是 `http://192.168.x.x` 会被拦。已通过 `extra_manifest.xml`（`usesCleartextTraffic="true"`）+ `pre_buildozer.py` 兜底解决。

## 云端构建

本机无需 Android SDK。推送代码到 GitHub 后，Actions 用 Buildozer 自动构建 APK：

- 普通 push → 构建产物在 Actions artifact（`ytcc-dl-android-apk`）；
- 打 `v*` tag → 额外发布/更新到 Release `ytcc-android-latest`，手机可直接下载。

本地开发测试（Windows/Mac/Linux，仅测逻辑不测 GUI 打包）：

```bash
python -m unittest discover -s tests -v   # 8 项核心测试
```

## 目录结构

```
ytcc-android/
├── main.py              # Kivy 手机界面
├── ytcc_core.py         # 核心逻辑（CookieCloud / 短链 / 下载）
├── pure_aes.py          # 纯 Python AES-256-CBC 解密
├── buildozer.spec       # Android 打包配置
├── vendor/yt_dlp/       # 内置 yt-dlp（含抖音签名补丁）
├── tests/               # 单元测试
└── .github/workflows/   # 云端构建
```

版本：`1.0.0`
