"""音声ファイルの読み込み (transcribe.py / diarize.py 共通)。

faster-whisper 内蔵のデコーダは PyAV のバージョン差で壊れることがあるので、
ここで 16kHz モノラル float32 に変換してから渡す。ffmpeg 不要。
"""

from pathlib import Path

import av
import numpy as np

SAMPLE_RATE = 16000


def load_audio(path: Path) -> np.ndarray:
    container = av.open(str(path))
    resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    for frame in container.decode(audio=0):
        for out in resampler.resample(frame):
            chunks.append(out.to_ndarray().reshape(-1))
    for out in resampler.resample(None):
        chunks.append(out.to_ndarray().reshape(-1))
    container.close()
    return np.concatenate(chunks).astype(np.float32)
