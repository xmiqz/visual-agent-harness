#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.py — visual-agent-harness 共享工具（零三方依赖）。

提供：
- 结构化事件输出（单行 JSON，便于调用方智能体解析末行终态）
- 退出码语义（与 SKILL.md 一致）
- DPI / 设备无关像素(dipx) / 物理像素(px) / 内容缩放(content%)换算
- PerMonitorV2 物理 DPI 推导
- 零依赖 PNG 编码/解码（仅用于自测；真实截图优先用 Pillow 或系统截图）

本模块不得硬编码任何真实项目路径、账号、手机号或 IP。
"""
import json
import os
import struct
import sys
import zlib

# ---------------------------------------------------------------------------
# 事件 / 退出码
# ---------------------------------------------------------------------------

EXIT_OK = 0          # 验收通过 / 任务完成
EXIT_UNVERIFIED = 2  # 证据存在但自动验收未通过（非失败，待人工复核）
EXIT_ENV = 3         # 环境不可用（进程找不到 / CDP 连不上 / 截图失败）
EXIT_INPUT = 4       # 输入参数非法（尺寸/缩放/路径）


def emit_event(event, **fields):
    """打印单行 JSON 事件。"""
    obj = {"event": event}
    obj.update(fields)
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()


def fail(message, code=EXIT_ENV, event="error", **fields):
    emit_event(event, error=message, **fields)
    sys.exit(code)


# ---------------------------------------------------------------------------
# DPI / 缩放换算
# ---------------------------------------------------------------------------

# Windows 标准基准 DPI：96 DPI = 100% 缩放。
SYSTEM_DPI = 96.0
# PerMonitorV2 下系统报告的逻辑 DPI（PPM -> 系统报告的整数 DPI）。
# 250% 以上 Windows 真实会把它限制在 192~384 区间；这里推导真实 DPI。
LOGICAL_DPI_TABLE = {
    1.0: 96, 1.25: 120, 1.5: 144, 1.75: 168, 2.0: 192, 2.25: 216,
    2.5: 240, 3.0: 288, 3.5: 336, 4.0: 384,
}


def logical_dpi(content_scale):
    """由内容缩放比例(content%)推导系统报告的逻辑 DPI（96 基准）。"""
    if content_scale <= 0:
        raise ValueError("content_scale 必须为正")
    if content_scale in LOGICAL_DPI_TABLE:
        return float(LOGICAL_DPI_TABLE[content_scale])
    # 非标准比例按线性换算（仍受 PerMonitorV2 上限约束，但通用换算足够）。
    return round(content_scale * SYSTEM_DPI)


def physical_dpi(content_scale, ppm_dpi_per_logical=None):
    """推导 PerMonitorV2 真实物理 DPI。

    ppm_dpi_per_logical: 每个逻辑 DPI 对应的物理 DPI（高分屏常见 1.0~2.0）。
    缺省按 1.0（逻辑即物理）。
    """
    ldpi = logical_dpi(content_scale)
    if ppm_dpi_per_logical is None:
        ppm_dpi_per_logical = 1.0
    return ldpi * float(ppm_dpi_per_logical)


def scale_factor(content_scale):
    """逻辑缩放因子（dippx / logical px）。"""
    return float(content_scale)


def logical_to_physical(logical_px, content_scale):
    """设备无关像素(logical px) -> 物理像素(px)。"""
    return int(round(logical_px * scale_factor(content_scale)))


def physical_to_logical(physical_px, content_scale):
    """物理像素(px) -> 设备无关像素(logical px)。"""
    return int(round(physical_px / scale_factor(content_scale)))


def expected_physical_size(logical_w, logical_h, content_scale):
    """给定逻辑窗口尺寸与内容缩放，返回期望物理像素尺寸（int, int）。"""
    return (logical_to_physical(logical_w, content_scale),
            logical_to_physical(logical_h, content_scale))


# ---------------------------------------------------------------------------
# 零依赖 PNG（仅自测；真实截图请优先 Pillow / 系统截图）
# ---------------------------------------------------------------------------

def _png_chunk(tag, data):
    chunk = tag + data
    return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)


def encode_png(width, height, pixels):
    """编码 8-bit RGB PNG。pixels 为长度 width*height*3 的 bytes。"""
    if len(pixels) != width * height * 3:
        raise ValueError("pixels 长度应为 width*height*3")
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        raw.extend(pixels[y * width * 3:(y + 1) * width * 3])
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 6)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def decode_png(data):
    """解码 8-bit RGB/RGBA PNG。返回 (width, height, mode, pixels_bytes)。

    pixels：RGB 为每像素 3 字节，RGBA 为 4 字节。
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("不是 PNG 文件")
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            (width, height, bit_depth, color_type,
             _, _, _) = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.extend(body)
        elif tag == b"IEND":
            break
        pos += 12 + length
    if width is None or bit_depth != 8:
        raise ValueError("仅支持 8-bit PNG")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise ValueError("不支持的颜色类型")
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        ftype = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if ftype == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                pp = a + b - c
                pa = abs(pp - a); pb = abs(pp - b); pc = abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        out.extend(line)
        prev = line
    mode = "RGB" if channels in (1, 3) else "RGBA"
    return width, height, mode, bytes(out)


def png_dimensions(path):
    """读取 PNG 宽高（仅解析 IHDR）。"""
    with open(path, "rb") as fh:
        head = fh.read(33)
    if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("不是 PNG 文件")
    (width, height) = struct.unpack(">II", head[16:24])
    return width, height


def png_dimensions_bytes(data):
    """从 PNG 字节解析宽高（仅 IHDR）。"""
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("不是 PNG 文件")
    (width, height) = struct.unpack(">II", data[16:24])
    return width, height
