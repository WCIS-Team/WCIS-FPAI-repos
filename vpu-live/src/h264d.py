#!/usr/bin/env python3
# Board-side HLS packager for the VPU H.264 pump.
#
# Reads the pump's Annex-B segment files (segN.h264 + segN.info + state) from SRC,
# remuxes each one to MPEG-TS with the board ffmpeg, keeps a rolling
# window of KEEP segments and writes a hand-made index.m3u8 into WWW.
# PTS across segments are made continuous with -output_ts_offset so OBS
# does not re-sync on every segment join.
#
# fps comes from the pump's own state file, not from an env copy, so the
# playlist duration cannot disagree with what the encoder was told.
#
# usage (on board):
#   H264_SRC=/dev/shm/wcis-vpu-h264-<session> H264_WWW=.../www \
#     setsid python3 h264d.py > /tmp/h264d.log 2>&1 < /dev/null &
import os
import re
import subprocess
import sys
import time


def now():
    return int(time.time())


def read_info(path, fallback_frames):
    try:
        with open(path) as f:
            m = re.search(r"frames=(\d+)", f.read())
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return fallback_frames


def read_fps(path, fallback_fps):
    try:
        with open(path) as f:
            m = re.search(r"fps=(\d+)", f.read())
        if m and int(m.group(1)) > 0:
            return int(m.group(1))
    except Exception:
        pass
    return fallback_fps


def write_playlist(www, window, seq0, max_dur):
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:%d" % max(1, int(max_dur) + 1),
        "#EXT-X-MEDIA-SEQUENCE:%d" % seq0,
    ]
    for seq, dur in window:
        lines.append("#EXTINF:%.3f," % dur)
        lines.append("seg%d.ts" % seq)
    tmp = os.path.join(www, "index.m3u8.part")
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(www, "index.m3u8"))


def main():
    src = os.environ.get("H264_SRC", "/dev/shm/h264")
    www = os.environ.get("H264_WWW", "/dev/shm/h264www")
    fps = read_fps(os.path.join(src, "state"), int(os.environ.get("H264_FPS", "30")))
    keep = int(os.environ.get("H264_KEEP", "6"))
    pend_max = max(8, keep * 2)
    os.makedirs(www, exist_ok=True)

    print("packager src=%s www=%s fps=%d keep=%d pid=%d unix=%d" % (src, www, fps, keep, os.getpid(), now()), flush=True)

    window = []
    total_dur = 0.0
    done_thru = -1
    fails = 0

    while True:
        state = os.path.join(src, "state")
        if os.path.exists(state):
            fps = read_fps(state, fps)
        segs = []
        try:
            for name in os.listdir(src):
                m = re.match(r"seg(\d+)\.h264$", name)
                if m:
                    segs.append(int(m.group(1)))
        except Exception as e:
            print("listdir %s: %r" % (src, e), flush=True)
            time.sleep(0.5)
            continue
        segs.sort()

        if len(segs) > pend_max:
            drop = segs[: len(segs) - pend_max]
            for s in drop:
                for ext in (".h264", ".info"):
                    p = os.path.join(src, "seg%d%s" % (s, ext))
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            print("overflow: dropped %d oldest raw segs" % len(drop), flush=True)
            segs = segs[len(segs) - pend_max:]

        fresh = [s for s in segs if s > done_thru]
        if len(fresh) > 3:
            skip = fresh[:-3]
            for s in skip:
                for ext in (".h264", ".info"):
                    try:
                        os.remove(os.path.join(src, "seg%d%s" % (s, ext)))
                    except Exception:
                        pass
            print("lagging: skipped %d segs" % len(skip), flush=True)
            fresh = fresh[-3:]

        for s in fresh:
            raw = os.path.join(src, "seg%d.h264" % s)
            info = os.path.join(src, "seg%d.info" % s)
            if os.path.getsize(raw) < 64:
                done_thru = s
                continue
            frames = read_info(info, 1)
            dur = float(frames) / float(fps)
            out = os.path.join(www, "seg%d.ts" % s)
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "h264", "-framerate", str(fps), "-i", raw,
                "-c", "copy", "-output_ts_offset", "%.3f" % total_dur,
                "-mpegts_copyts", "0", "-f", "mpegts", out,
            ]
            t0 = time.time()
            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
            except subprocess.TimeoutExpired:
                print("seg%d ffmpeg timeout" % s, flush=True)
                r = None
            if r is None or r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 64:
                fails += 1
                print("seg%d remux FAILED rc=%s err=%s" % (
                    s, getattr(r, "returncode", None),
                    (r.stderr.decode("utf-8", "replace")[:200] if r and r.stderr else "")), flush=True)
                for p in (out, raw, info):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                done_thru = s
                continue
            spent = time.time() - t0
            os.remove(raw)
            try:
                os.remove(info)
            except Exception:
                pass
            window.append((s, dur))
            total_dur += dur
            while len(window) > keep:
                old, _ = window.pop(0)
                try:
                    os.remove(os.path.join(www, "seg%d.ts" % old))
                except Exception:
                    pass
            write_playlist(www, window, window[0][0], max(d for _, d in window))
            done_thru = s
            fails = 0
            if s % 30 == 0:
                print("seg%d dur=%.3f remux_ms=%d window=%d ts_bytes=%d cum_s=%.1f" % (
                    s, dur, int(spent * 1000), len(window), os.path.getsize(out), total_dur), flush=True)

        if fails and fails % 20 == 0:
            print("consecutive remux failures=%d" % fails, flush=True)
        time.sleep(0.05)


if __name__ == "__main__":
    sys.exit(main())
