# Bazzite HTPC ISO

面向 AMD 核显小主机的 Bazzite KDE Gaming Mode 安装镜像。保留官方基础系统，首次联网后自动安装 Moonlight、chiaki-ng、Kodi。没有自动分区、账号、配对密钥、NAS 凭据或来路不明的媒体 APK。

## 构建和下载

- GitHub：Actions → **Build Bazzite HTPC ISO** → **Run workflow**。对 main 的构建相关文件变更也会自动构建。成功后展开该次运行底部的 Artifacts，下载 **bazzite-htpc-amd64**。工作流不创建公开 Release，不发布 GHCR 容器，产物保留 2 天。
- 解压后执行 `sha256sum -c SHA256SUMS`（Windows 可用 `Get-FileHash .\bazzite-htpc-amd64.iso -Algorithm SHA256` 与 SHA256SUMS 对照）。`build-info.txt` 记录实际底座、构建器摘要和提交。
- 本地：在有 rootful Podman、联网且有足够磁盘空间的 **x86-64 Linux** 上运行 `./scripts/build-iso.sh`。脚本工作目录是仓库，仅产生本机 OCI 镜像和 ISO；不会访问目标机磁盘。可设 `BASE_IMAGE`、`BUILDER_IMAGE` 为已验证的摘要以固定输入。
- 如果私有仓库的 Actions 分钟、Artifact 存储或托管 runner 空间不足，不必开通付费：可以在本地 Linux 构建。没有把标准 runner 可用空间或账号额度当成保证。

## 改什么

- `Containerfile`：基础镜像是 `ghcr.io/ublue-os/bazzite-deck:stable`。系统文件改动放 `rootfs/`。
- `rootfs/usr/share/bazzite-htpc/flatpaks.list`：首启自动安装清单。离线安装不包含这些 Flatpak 和运行库。网络或商店暂时不可用，计时器会再试；安装成功后相同清单不会重复跑。
- `disk-config.toml`：ISO 参数。不配置无人值守安装或清盘指令。
- 游戏模式里可手动添加 Moonlight、chiaki-ng、Kodi；B 站、腾讯、YouTube、Netflix 用官方网页，或者独立测试 WayDroid-ATV。此版不会改 Steam 账户文件，不烘入浏览器状态或 Android TV 社区镜像。

## 试装和验收

1. 先在只有空白虚拟盘的 UEFI 虚拟机试 ISO；确认能进安装器、手动选盘、重启进入系统。实机首次试装请使用空白备用 SSD，建议断开原 Windows 盘；如果启用了磁盘加密，变更固件前确认能拿到恢复密钥。此项目没有宣称自定义 ISO 的 Secure Boot 可用。
2. 联网后检查 `systemctl status bazzite-htpc-flatpaks.timer` 和 `journalctl -u bazzite-htpc-flatpaks.service -b`；账户登录、PS5/Sunshine/手柄配对只在机器上做。
3. 实测 HDMI 出声、NAS、IPTV 和视频平台画质、双手柄独立输入及睡眠唤醒。虚拟机通过不代表 AMD 核显、硬解、HDR 或电视交互通过。
4. 默认 ISO 装的是本地构建镜像；**没有配置自定义系统 OTA 更新源**。需要持续更新时，选择经过验证的签名 OCI 仓库重新指向更新源，或者重新构建新版 ISO；不把上游 Bazzite 的更新当成会自动保留定制。未审核前不建议把首个构建直接作为长期唯一系统。

参考：[Bazzite 自定义镜像](https://docs.bazzite.gg/Advanced/creating_custom_image/) · [Universal Blue 模板](https://github.com/ublue-os/image-template) · [osbuild ISO 文档](https://osbuild.org/docs/developer-guide/projects/image-builder/advanced/bootc/isos/)

## Kodi 首次设置：中文海报墙

在 Steam 桌面模式添加 **Kodi · HTPC**，不要添加 Flatpak 的原始 Kodi 图标。包装器只给未初始化的 Flatpak 用户写入默认文件；已经创建的片库、键位或恢复的配置不会被覆盖。镜像安装 Fedora 的 Noto Sans SC 字体；包装器将匹配到的字体复制到 Kodi 用户目录供 SRT 等文本字幕使用，不修改 ASS 原样式或 PGS 图像字幕。若字幕字体列表未选中 Noto Sans SC，在设置 → 播放器 → 字幕中手动选一次。保留原声、优先中文字幕；如果字幕轨未加语言标签，要手动选轨。

1. Kodi 初次打开保留 Estuary 作为安全回退。打开 **Favourites / 收藏**，先选 **01 · Install Arctic Zephyr Reloaded**，在 Kodi 官方仓库确认安装及依赖。如果皮肤没有弹出切换提示，到 Settings → Interface → Skin 主动选择。进入 Fonts 选 **CJK - Spoqa + Inter**（取决于皮肤版本）或 **Arial**；先确认中文片名无方框，再安装或切换 **Chinese (Simple)**。如果收藏里内置命令不生效，从 Add-ons → Install from repository → Kodi Add-on repository 安装皮肤和语言包；不要求打开未知来源。未在实际 Kodi 中验证这个安装入口及字形。
2. 不把假地址、认证或数据库写进系统。实际添加 SMB 路径，电影和剧集分开，各自指定内容类型。电影用 **The Movie Database Python**，剧集用 **TMDb TV Shows**，源设置优先 **zh-CN**。对同名电影采用 `片名 (年份)/片名 (年份).mkv`；剧集采用 `剧名 (年份)/Season 01/剧名 S01E01.mkv`；纠错用本地 NFO 和海报，不批量重刮整个库。
3. 电影、剧集库各切一次海报视图；有内容后再启用近期加入/继续观看。视图和挂件由皮肤按用户保存，新空库不能事先验证，默认关闭开机扫库，也不配置自动清理。
4. 屏幕菜单保留 Kodi 手柄默认导航。视频中 A 暂停、B 返回、X 打开播放控制、Y 切字幕；默认停止等功能仍可用播放控制栏。若 Steam Input 将手柄变成键鼠，Kodi 快捷方式改用 Gamepad 模板再测。画质、刷新率、音频直通及字幕字体在实际电视上验收。

参考：[Arctic Zephyr Reloaded](https://kodi.wiki/view/Add-on:Arctic:_Zephyr_-_Reloaded) · [皮肤字体](https://kodi.wiki/view/Settings/Interface/Skin) · [Kodi 片库最佳实践](https://kodi.wiki/view/HOW-TO:Create_Video_Library) · [字幕设置](https://kodi.wiki/view/Settings/Player/Subtitles) · [手柄键位](https://kodi.wiki/view/HOW-TO:Modify_joystick.xml)
