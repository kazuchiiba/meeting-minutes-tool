"""pyannote の工程別の処理時間の計測と、窓幅などの調整（ISSUE-018）。diarize.py / diar_step_eval.py 共通。

pyannote 3.x は各工程の終わりに hook(工程名, 結果) を呼ぶ。時間のかかる工程（区間検出・埋め込み）は
途中でも completed / total 付きで呼ぶので、それを使って進捗と残り時間の見込みをログに出す。
"""

import time

# pyannote の工程名 → ログ・記録用の名前
STAGE_NAMES = {
    "segmentation": "区間検出",
    "speaker_counting": "同時話者数の推定",
    "embeddings": "声の特徴量",
    "discrete_diarization": "クラスタリング・再構成",
}


DEFAULT_STEP = 0.1  # pyannote の既定。窓 10秒を 1秒ずつずらす
DEFAULT_MIN_CLUSTER_SIZE = 12  # pyannote 3.1 の既定。1話者として認めるのに必要な特徴量の最低数


def auto_min_cluster_size(step: float) -> int:
    """ずらし幅を広げると特徴量の数がほぼ反比例で減るので、最低数も同じ比率で減らす（2 未満にはしない）。"""
    return max(2, round(DEFAULT_MIN_CLUSTER_SIZE * DEFAULT_STEP / step))


def configure(pipeline, step: float = DEFAULT_STEP, min_cluster_size: int | None = None) -> int:
    """窓（10秒）をずらす幅を窓の長さに対する割合で、最低特徴量数を個数で設定する。
    min_cluster_size が None なら auto_min_cluster_size(step)。実際に使った最低数を返す。"""
    pipeline.segmentation_step = step
    pipeline._segmentation.step = step * pipeline._segmentation.duration
    if min_cluster_size is None:
        min_cluster_size = auto_min_cluster_size(step)
    params = pipeline.parameters(instantiated=True)
    params["clustering"]["min_cluster_size"] = min_cluster_size
    pipeline.instantiate(params)
    return min_cluster_size


class StageTimer:
    """pipeline(..., hook=StageTimer()) で渡す。終わると stages に {工程名: 秒} が入る。"""

    def __init__(self) -> None:
        self.started = self.last = time.time()
        self.stages: dict[str, float] = {}
        self._stage_started: dict[str, float] = {}
        self._next_pct: dict[str, int] = {}

    def __call__(self, step_name, step_artifact, file=None, total=None, completed=None) -> None:
        now = time.time()
        name = STAGE_NAMES.get(step_name, step_name)
        if completed is not None and total:
            self._stage_started.setdefault(name, now)
            pct = 100 * completed / total
            if pct >= self._next_pct.get(name, 10):
                spent = now - self._stage_started[name]
                eta = spent * (100 - pct) / pct if pct else 0
                print(f"  {name} {min(pct, 100):3.0f}%  経過 {spent / 60:.1f}分  残り見込み {eta / 60:.1f}分", flush=True)
                self._next_pct[name] = int(pct // 10 + 1) * 10
            return
        if step_artifact is None:
            return
        self.stages[name] = round(now - self.last, 1)
        self.last = now
        print(f"  {name} 終了：{self.stages[name] / 60:.1f}分", flush=True)
