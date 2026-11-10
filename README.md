View all repositories on one page: 
https://github.com/orgs/WCIS-Team/repositories

Other repositories not included in the organization’s repositories:
https://github.com/takomitkm/ekho-Linux

## 本库钉住的子模块（gitlink）

本库（`WCIS-FPAI-repos`）是代码归档根，只保存各项目的**指针**（gitlink），源码在各自独立仓库：

| 子模块路径 | 指向仓库（分支） | 内容 |
|---|---|---|
| `tkmFPGA/` | [WCIS-Team/tkmFPGA](https://github.com/WCIS-Team/tkmFPGA)（`main`） | tkm 的 FPGA 项目集合：`pl_eth_psgem1_emio`（PL 以太网 PS GEM1 EMIO 透传）、`sdi-psddr`（HD-SDI→PS DDR 采集）、`sdi2hdmi`（SDI→HDMI）、`vpu-live`（SDI+VPU 实时推流）。**2026-11-10** 这四个项目从本库的普通目录迁出、聚合为该子模块；原创硬件部分采用 Solderpad Hardware License 2.1 |
| `fmql30tai-sdi-npu-face-recognition/` | [WCIS-Team/fmql30tai-sdi-npu-face-recognition](https://github.com/WCIS-Team/fmql30tai-sdi-npu-face-recognition)（`main`） | SDI 采集＋NPU 人脸识别（上交参赛作品）；自研硬件 RTL `源码/fpga_source/rtl/wcis/` 为 `MIT OR Apache-2.0 WITH SHL-2.1` 双许可 |
| `loomos/` | [WCIS-Team/loomos](https://github.com/WCIS-Team/loomos)（`main`） | 详见其仓库 README |

## 视频交付子模块的来源与署名

- `fmql30tai-sdi-npu-face-recognition/` 是 Git 子模块（gitlink），指向公开仓 <https://github.com/WCIS-Team/fmql30tai-sdi-npu-face-recognition>（分支 `main`）；**本库只钉指针，不含其源码**。
- **原作者**：`anxianji11-pixel`（<https://github.com/anxianji11-pixel>），视频链路（SDI 采集＋FPGA 视觉＋NPU 人脸身份/PAD）原创部分的作者。**代上传**：该公开仓由 `takomitkm` 代其建仓并上传。
- **署名正本**：该仓 [`NOTICE.md`](https://github.com/WCIS-Team/fmql30tai-sdi-npu-face-recognition/blob/main/NOTICE.md) 与 [README「来源与署名」](https://github.com/WCIS-Team/fmql30tai-sdi-npu-face-recognition/blob/main/README.md#来源与署名)；第三方许可与例外见 `THIRD_PARTY_NOTICES.md`／`LICENSE_SCOPE.md`。
- **历史边界**：2026-11-06 三个组织库按文件快照重建根历史（D-1793967893），旧提交祖先被丢弃，故本库的贡献视图不含原作者对视频链路的旧提交；视频子模块仓自身历史不在重建范围内、署名完好（其根提交 `449bcf9` 的 author 即 `anxianji11-pixel`）。本轮以带 `Co-authored-by` 尾注的新提交补记署名，不改写历史、不恢复旧提交；口径见 D-1794150604。
