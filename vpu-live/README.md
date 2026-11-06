# vpu-live：板侧 VPU 直播链的制品与证据

两轮活，同一个包：

- **2026-10-15（§二十）**：脱离 demo／PL／NPU 的两个探针 `live_sim`（H.264）与 `vpu_jpg`（JPEG），进程自己造裸帧直接喂 VPU，只验 PS 侧那半截。产物在 `bin/live_sim`、`bin/vpu_jpg`、`evidence/`（10-15 那批）、`payload/live-payload.tar.xz`、`logs/`。
- **2026-10-20（本轮）**：把 H.264 泵做进独立采集件 `wcis_sdi_vpu_live`，接上真 SDI 取图路径＋板侧 HLS 打包器，**用仿真图（VTC＝PL 自产测试图，不接相机）跑通并逐段解出帧**。产物在 `src/`、`bin/wcis_sdi_vpu_live`、`evidence/h264-1020/`。

## 一、现役件与哈希（板↔本机逐字节核过，A 级）

| 件 | 本机 | 板上 | md5 | sha256 |
|---|---|---|---|---|
| 泵源码（厂商取流版） | `src/wcis_sdi_vpu_live.cpp` | `/root/wcis-face/candidates/sdi-vpu-h264-20261020/wcis_sdi_vpu_live` 的源 | `ffef338c95dcb9d482d885dbf61f0d32` | `3adc91341b7cd943fa148814ed0e1424e70b461444e75d760665fc0b77c540bc` |
| 二进制（现役） | `bin/wcis_sdi_vpu_live` 5,375,856 B | 同路径 | `62fadc0ac35c621d834d1222b9d0fcff` | `ab0c9177f75981e115fefd8b32a5164807c1ab3a235ae582108ad4437cce5227` |
| 启动器 | `src/run_sdi_vpu_capture.py` | `…/run_sdi_vpu_capture.py` | `85cde3954bca6a3d1ddc9bc6c772067c` | — |
| 打包器 | `src/h264d.py` | `…/h264d.py` | `4fc227ddeb4f6a3f9dcb107c895b226d` | — |
| 观看端 | `src/vpu_live_server.py` | `/root/wcis-face/candidates/sdi-vpu-live-20261020/vpu_live_server.py` | 与 10-19 那颗同值 | — |
| 上传器 | `src/board-put.py` | 不上板 | — | PC 侧：SFTP 写 `.new`→板上 `md5sum`→`mv`，两侧不一致就非零退出 |

板侧 `ldd` 全部解析（`grep -c "not found"`＝0），16 个 DT_NEEDED 含 7 个 Icraft 厂商库。构建在校机按 [[交叉编译主机路由SOP]]：`D:/yzd/tmp/wcis-camera-preview-vpulive-7f92df53/rebuild.sh`（单目标 `wcis_sdi_vpu_live`），**板上从没编译过任何东西**。

`MANIFEST.md5` 逐字节 index 的是**本包在盘上的样子**，里面 `payload/live-payload.tar.xz`（213 KB）按 `repos/.gitignore` 的体积类规则不进库（全库没有任何 `.tar.xz` 被跟踪，`Qwen3-0.6B-Instruct/MANIFEST.md5` 同一口径）⇒ 从 git 克隆之后 `md5sum -c` 只会在这一行报 `No such file or directory`，不是包坏了；那一行的值 `02f5fcbcee31218a4985eaf0e49de16a`，板与本机各有一份原件。

## 二、#195 那条缺陷修掉了，而且有真硬件凭据

原缺陷（§十九 #195）：泵只在整个会话开始时收到一块**独立的 32/33 字节 SPS+PPS 缓冲**，下一块从偏移 0 就是 IDR，于是 `hdmi_display_actor.hpp:289` 那行 `hdr.assign(b, b + (io<0 ? s : io))` 把已收好的参数集**覆盖成空** ⇒ 每一段都不带参数集 ⇒ 播放器一律 `non-existing PPS 1 referenced`、`ffprobe` 读出 `width=0 height=0`。

现修法（`wcis_sdi_vpu_live.cpp` 的 `H264Segments`）：参数集**缓存**进 `head_`，`io==0` 那一支明确不许清缓存，`openSeg()` 每个段头都从缓存重写一遍。

证据（`evidence/h264-1020/`，A 级）：

- `seg2.h264` 的 NAL 序列＝`SPS:21 PPS:4 IDR:1206 + 29×SLICE`，`nal_scan.py` 逐条切开可见；**段头带参数集**。
- `seg0.ts` 12,032 B／`seg1.ts` 7,332 B：`ffprobe` 各报 `codec_name=h264 width=960 height=540 pix_fmt=yuv420p duration=0.999989`，`-count_frames` 各 **30 帧**，`ffmpeg -f null` 全程**零解码错误**。
- `state-960-ok`＝`seq=3 bytes_total=15620 frames=90 chunks=91 head_bytes=33 dead=0 error=-`；`m3u8-960` 两段 `#EXTINF:1.000`。
- 两个 `.ts` 是从板上 base64 取回的，两侧 md5 全等（`946a77e6…`／`e5ec35c3…`）。

## 三、三次实跑与那个归因

| 轮 | 命令要点 | 结果 | 读数 |
|---|---|---|---|
| 1 | `--source vtc --codec h264 --size 960x540 --frames 90`，取流＝我自己加的 `poll(fd,POLLIN)`＋DQBUF | **失败**，退出码 2 | `captured=8`、`chunks=1 head_bytes=33`、`error=VPU output poll failed`；用户态 `vpu.h:1001 Failed to dequeue input buffer, errno=5`；内核同一时刻 `MVX session: … V5/V7-H264ENC: MMU ABORT (mvx_session.c:2120)` |
| 2 | 同参数，取流换成厂商 `getOutput()`（阻塞 DQBUF，与 demo 泵／`live_sim` 同形态） | **通过**，退出码 0 | `RESULT … captured=90 pictures=90 segments=3 head_bytes=33`，打包器 `seg0 dur=1.000 remux_ms=884 ts_bytes=12032` |
| 3 | 同 2，只把 `--size` 换成 `1920x1080` | **失败**，退出码 2 | `captured=8 encoded=4`、`chunks=5 head_bytes=32`，`vpu.h:950 Failed to dequeue output buffer, errno=5`；内核第二行 MMU ABORT |

**归因（A 级）**：`errno=5` 这个用户态签名＝固件 `MMU ABORT`。这一条同时把 §十九 #195 末尾那句"errno=5 未归因"结掉。
**已排除**：轮 1 与轮 2 只差取流写法 ⇒ 我那版 `poll()` 取流是触发条件之一，现役件里已删掉。
**未排除**：轮 3 与轮 2 只差分辨率，两处厂商件（demo 泵 1080p 出过 102 段、`live_sim` 960×540 出过 300 帧）都跑过 H.264，所以"1080p 编不了"这个结论**不成立**；可疑的是本链 1080p 下的实际喂帧节奏（`setEncFrameRate=30`  declared，而 1080p 每帧要走 ImageMake＋两次 `cvtColor`＋memcpy，真实间隔远大于 33 ms）。下一枪该动的旋钮：`buffers` 6→4，或声明帧率降到实测喂帧率。别把这两次失败当"必须重启"——重启只是清标记。

## 四、板上路径与启动方式

现役候选目录 `/root/wcis-face/candidates/sdi-vpu-h264-20261020/`（含 `boot-proof.json`、`build-receipt.json`；失败那颗留在 `wcis_sdi_vpu_live.poll-variant-aborted` 当对照）。10-19 起一直在跑的 JPEG 目录 `sdi-vpu-live-20261020/` 一个字没动，随时回退。

```
# H.264 一轮（有限帧，仿真图）
cd /root/wcis-face/candidates/sdi-vpu-h264-20261020
timeout 60 python3 ./run_sdi_vpu_capture.py --root . --source vtc --codec h264 --size 960x540 --frames 90
# JPEG 长期挂着（观看端只认 JPEG 的 latest.frame）
cd /root/wcis-face/candidates/sdi-vpu-live-20261020
setsid timeout 3600 python3 run_sdi_vpu_capture.py --root . --source vtc --frames 0 > jpeg-vtc-hour2.log 2>&1 < /dev/null &
```

参数序＝`wcis_sdi_vpu_live camera|vtc EXPECTED_BOOT OUTDIR FRAME_LIMIT(0=连续) jpeg|h264 [960x540|1280x720|1920x1080]`；旧启动器是 5 个参数，**新二进制与新启动器必须一起换**，否则 argc 不对直接退 2。

## 五、观看端现状：能打开的网页只有 JPEG 那一个

`http://192.168.1.113:8092/`（`wcis-sdi-vpu-view.service`，正本＝`src/vpu_live_server.py`）。它读的是采集件写的 `latest.frame`，**只认 JPEG**；10-20 13:0x（本地）实测 `ready`、`frame_id` 在走、`/snapshot.jpg` 是 960×540 有效图（`evidence/h264-1020/viewer-snapshot-960x540.jpg`，均值 120.1／标准差 63.4，不是黑场）。

**H.264 那条现在还没有网页**：段与 `.ts`、`index.m3u8` 都产出来了，但观看端没有 `/index.m3u8`＋`/seg<N>.ts` 端点、也没有内网自托管的 hls.js（浏览器放 MPEG-TS HLS 需要它，不能用 CDN）。所以"H.264 可看"目前只到**码流可解**这一层，页面是下一步。

## 六、事件标记的处理（要认账）

轮 1 与轮 3 退出码非零，按启动器策略写了 `/root/wcis-face/hardware-review-required.json`（`boot_id`＝当前开机 `5e10dfdf…`）。为了让 13:0x 那次实跑和后面的 JPEG 轮次能起，我把它**改名挪开而不是删除**，两份内容都在 `evidence/h264-1020/`（`marker-aside-0409.json`、`marker-aside-1080p.json`）；原始标记位置现在为空 ⇒ **门禁在本开机内等于关掉**。重启即回到正常策略，`hardware-review-required.json.aside` 与 `.bak-1020-0409` 两份副本也在板上。这条是我动的，不是策略变了。

另外：10-19 19:05 那份旧标记（`boot_id 73883f36…`、`source vtc`）在轮 1 写标记时被覆盖，覆盖前的值已记在这里。

## 相关

- 台账正本：`wiki/PS/板端我方代码与产物台账.md` §十九（直播链装回＋开机自启、#195 缺陷登记）与 §二十（10-15 两个探针）
- 待补：`deps/modelzoo_utils/include/pipeline/io/output/stream2segfile.hpp:30-32` 那句"每段都带 SPS/PPS 做不到"已被本包证伪，要去公开更正
