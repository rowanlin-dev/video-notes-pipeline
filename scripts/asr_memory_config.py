#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ASR 内存自适应配置模块。

自动检测硬件（CPU 核数、可用内存），选择最优模型尺寸 / 并行度 / 分块大小，
确保 ASR 运行时不因内存不足而崩溃，并为系统保留足够的余量。

用法:
    from asr_memory_config import get_asr_config
    cfg = get_asr_config()
    print(cfg.model_size, cfg.workers, cfg.chunk_minutes)

环境变量覆盖（优先级高于自动检测）:
    ASR_MODEL_SIZE   tiny | base | small（默认自动）
    ASR_WORKERS      整数（默认自动）
    ASR_CHUNK_MINUTES 整数，每块分钟数（默认自动）
    ASR_RESERVE_GB   浮点数，为系统保留的内存 GB（默认 4.0）
"""

import os, ctypes, struct
from dataclasses import dataclass, field
from typing import Optional

# ---------- 模型尺寸 → 模型目录名 / 预估内存 ----------

MODEL_SIZES = {
    "tiny":  {"dir": "models/faster-whisper-tiny", "ram_gb": 0.3},
    "base":  {"dir": "models/faster-whisper-base", "ram_gb": 0.6},
    "small": {"dir": "models/faster-whisper-small", "ram_gb": 2.0},
}

# 安装时 system 会下载模型到 models/ 目录下，目录名格式：
#   models/faster-whisper-tiny
#   models/faster-whisper-base
#   models/faster-whisper-small
# 如果目录不存在，faster-whisper 会自动下载，但需要网络。
# 优先使用本地已有模型，避免重复下载。


def _get_available_ram_gb() -> float:
    """获取当前可用物理内存（GB），纯 stdlib 实现。"""
    try:
        # Windows: Kernel32.GlobalMemoryStatusEx
        kernel32 = ctypes.windll.kernel32

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullAvailPhys / (1024 ** 3)
    except (AttributeError, OSError, ctypes.WinError):
        pass

    # Linux / macOS 回退：读取 /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except (FileNotFoundError, OSError, ValueError):
        pass

    # macOS 回退：sysctl
    try:
        import subprocess
        r = subprocess.run(["sysctl", "-n", "hw.memsize"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            total = int(r.stdout.strip()) / (1024 ** 3)
            # 粗略估计可用 40%
            return total * 0.4
    except (FileNotFoundError, OSError, ValueError):
        pass

    # 全部失败：保守返回 8GB
    return 8.0


def _get_cpu_count() -> int:
    """获取逻辑 CPU 核数（物理核数难以跨平台准确获取，用逻辑核保守减半）。"""
    return os.cpu_count() or 4


def _get_model_dir(model_size: str) -> str:
    """获取模型目录（优先本地，回退下载名）。"""
    candidate = MODEL_SIZES[model_size]["dir"]
    # 如果本地已有该目录，直接用
    if os.path.isdir(candidate):
        return candidate
    # 只有 small 是默认下载的，其他尺寸需要下载
    return candidate


def _list_local_models() -> list[str]:
    """列出本地已下载的模型尺寸列表（按优先级从低到高）。"""
    available = []
    for size in ["tiny", "base", "small"]:
        if os.path.isdir(MODEL_SIZES[size]["dir"]):
            available.append(size)
    return available


@dataclass
class ASRConfig:
    """ASR 运行时配置。"""
    model_size: str = "small"          # tiny / base / small
    workers: int = 1                   # 并行进程数
    chunk_minutes: int = 15            # 每块分钟数
    cpu_threads: int = 2               # 每个进程的 CPU 线程数
    reserve_gb: float = 4.0            # 为系统保留内存（GB）
    available_ram_gb: float = 0.0      # 检测到的可用内存
    total_ram_gb: float = 0.0          # 检测到的总内存
    cpu_count: int = 0                 # 检测到的 CPU 核数
    auto_mode: bool = True             # 是否自动检测
    # 供调用的提示信息
    warnings: list[str] = field(default_factory=list)


def get_asr_config(
    prefer_model: Optional[str] = None,
    prefer_workers: Optional[int] = None,
    prefer_chunk: Optional[int] = None,
    reserve_gb: Optional[float] = None,
) -> ASRConfig:
    """
    获取自适应 ASR 配置。

    参数:
        prefer_model:   强制指定模型尺寸（tiny/base/small），None=自动
        prefer_workers: 强制指定并行进程数，None=自动
        prefer_chunk:   强制指定每块分钟数，None=自动
        reserve_gb:     为系统保留的内存（GB），None=默认 4.0

    优先顺序：环境变量 > 函数参数 > 自动检测
    """
    cfg = ASRConfig()

    # 1. 检测硬件
    cfg.available_ram_gb = _get_available_ram_gb()
    cfg.cpu_count = _get_cpu_count()

    # 总内存
    try:
        kernel32 = ctypes.windll.kernel32
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            cfg.total_ram_gb = m.ullTotalPhys / (1024 ** 3)
    except:
        cfg.total_ram_gb = cfg.available_ram_gb  # fallback

    # 2. 保留余量
    cfg.reserve_gb = (
        float(os.environ.get("ASR_RESERVE_GB", "4.0"))
        if reserve_gb is None
        else reserve_gb
    )

    # 3. 选择模型尺寸
    # 环境变量 > 参数 > 自动
    env_model = os.environ.get("ASR_MODEL_SIZE", "").strip().lower()
    if env_model in MODEL_SIZES:
        cfg.model_size = env_model
    elif prefer_model and prefer_model in MODEL_SIZES:
        cfg.model_size = prefer_model
    else:
        cfg.model_size = _auto_select_model(cfg)

    # 4. 选择并行度
    env_workers = os.environ.get("ASR_WORKERS", "").strip()
    if env_workers.isdigit():
        cfg.workers = max(1, int(env_workers))
    elif prefer_workers is not None:
        cfg.workers = max(1, prefer_workers)
    else:
        cfg.workers = _auto_select_workers(cfg)

    # 5. 选择分块大小
    env_chunk = os.environ.get("ASR_CHUNK_MINUTES", "").strip()
    if env_chunk.isdigit():
        cfg.chunk_minutes = max(5, int(env_chunk))
    elif prefer_chunk is not None:
        cfg.chunk_minutes = max(5, prefer_chunk)
    else:
        cfg.chunk_minutes = _auto_select_chunk(cfg)

    # 6. CPU 线程数
    cfg.cpu_threads = max(1, min(4, cfg.cpu_count // 2)) if cfg.workers == 1 else 2

    # 7. 收集警告
    _collect_warnings(cfg)

    return cfg


def _auto_select_model(cfg: ASRConfig) -> str:
    """根据可用内存自动选择模型尺寸。"""
    local_models = _list_local_models()
    usable = cfg.available_ram_gb - cfg.reserve_gb

    # 按可用内存从大到小尝试
    candidates = ["small", "base", "tiny"]
    # 优先本地已有模型
    if local_models:
        candidates = [s for s in candidates if s in local_models]

    for size in candidates:
        need = MODEL_SIZES[size]["ram_gb"]
        # 如果有多 worker，需要预留每 worker 一份模型
        # 这里保守按单 worker 评估
        if usable >= need * 2:  # 模型 + 处理开销各一份
            return size

    # 全部不够就选最小的
    return candidates[-1] if candidates else "tiny"


def _auto_select_workers(cfg: ASRConfig) -> int:
    """根据 CPU 核数和可用内存选择并行度。"""
    model_ram = MODEL_SIZES[cfg.model_size]["ram_gb"]
    usable = cfg.available_ram_gb - cfg.reserve_gb

    # 每个 worker 约需：模型 + 1GB 处理缓冲
    per_worker = model_ram + 1.0

    # 按内存能支撑的最大 worker 数
    by_ram = max(1, int(usable // per_worker))

    # 按 CPU 核数
    by_cpu = max(1, cfg.cpu_count // 2)  # 留一半给系统

    # 取较小值，且不超过 4
    workers = min(by_ram, by_cpu, 4)

    # 保守：2 核机器强制 1 worker
    if cfg.cpu_count <= 2:
        workers = 1

    return workers


def _auto_select_chunk(cfg: ASRConfig) -> int:
    """根据可用内存选择分块大小（越小越省内存）。"""
    usable = cfg.available_ram_gb - cfg.reserve_gb
    model_ram = MODEL_SIZES[cfg.model_size]["ram_gb"]

    if usable < 4:
        return 10  # 内存紧张，小块
    elif usable < 8:
        return 15  # 适中
    else:
        return 20  # 内存充裕，大块提效


def _collect_warnings(cfg: ASRConfig) -> None:
    """收集配置警告。"""
    if cfg.available_ram_gb < cfg.reserve_gb + 2:
        cfg.warnings.append(
            f"可用内存仅 {cfg.available_ram_gb:.1f}GB，"
            f"系统余量 {cfg.reserve_gb:.1f}GB，"
            f"ASR 可用资源非常紧张，建议关闭其他应用程序"
        )
    if cfg.model_size != "small":
        cfg.warnings.append(
            f"使用 {cfg.model_size} 模型（{MODEL_SIZES[cfg.model_size]['ram_gb']:.1f}GB），"
            f"精度低于 small 但更省内存"
        )
    if cfg.workers == 1 and cfg.cpu_count > 2:
        cfg.warnings.append(
            f"CPU 有 {cfg.cpu_count} 核但受内存限制仅用 1 进程并行"
        )


def print_config(cfg: ASRConfig) -> None:
    """打印配置摘要。"""
    print(f"  [memory] 总内存: {cfg.total_ram_gb:.1f}GB, "
          f"可用: {cfg.available_ram_gb:.1f}GB, "
          f"系统余量: {cfg.reserve_gb:.1f}GB")
    print(f"  [memory] CPU: {cfg.cpu_count} 核")
    print(f"  [memory] ASR 配置: 模型={cfg.model_size} "
          f"({MODEL_SIZES[cfg.model_size]['ram_gb']:.1f}GB), "
          f"进程={cfg.workers}, "
          f"分块={cfg.chunk_minutes}min/块, "
          f"CPU线程={cfg.cpu_threads}")
    for w in cfg.warnings:
        print(f"  [warn] {w}")


if __name__ == "__main__":
    cfg = get_asr_config()
    print_config(cfg)