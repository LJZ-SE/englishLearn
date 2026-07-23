from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_REVISION = "2c94ad3e1aafab77146f384e23536f97a4849815"
_SOURCE_URL = f"https://huggingface.co/datasets/allenai/sciq/tree/{_REVISION}"
_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/3.0/"
_REQUIRED_COLUMNS = {
    "question",
    "correct_answer",
    "distractor1",
    "distractor2",
    "distractor3",
    "support",
}


def iter_sciq_questions(parquet_path: Path) -> Iterator[CollectedSentence]:
    try:
        parquet = pq.ParquetFile(parquet_path)
    except (OSError, ValueError) as error:
        raise ValueError(f"SciQ 下载内容不是有效 Parquet: {parquet_path}") from error
    if not set(parquet.schema_arrow.names) >= _REQUIRED_COLUMNS:
        raise ValueError(f"SciQ Parquet schema 漂移: {parquet_path}")
    for column in sorted(_REQUIRED_COLUMNS):
        column_type = parquet.schema_arrow.field(column).type
        if not (pa.types.is_string(column_type) or pa.types.is_large_string(column_type)):
            raise ValueError(f"SciQ 必需列 {column} 必须是字符串: {parquet_path}")

    scene = scene_by_key("technology_science")
    emitted = 0
    row_index = 0
    for batch in parquet.iter_batches(columns=["question"], batch_size=2048):
        for question in batch.column(0).to_pylist():
            if not isinstance(question, str):
                raise ValueError(f"SciQ 第 {row_index} 行 question 必须是字符串")
            text = _normalize_question(question)
            if text:
                yield CollectedSentence(
                    text=text,
                    source_item_id=f"sciq:train:{row_index}",
                    source_author="",
                    source_url=_SOURCE_URL,
                    source_name="SciQ",
                    license_name="CC BY-NC 3.0",
                    license_url=_LICENSE_URL,
                    top_scene=scene.top_key,
                    sub_scene=scene.key,
                )
                emitted += 1
            row_index += 1
    if emitted == 0:
        raise ValueError(f"SciQ 没有有效问题: {parquet_path}")


def _normalize_question(text: str) -> str:
    stripped = " ".join(text.split())
    if not stripped:
        return ""
    if stripped[-1] not in ".?!":
        return f"{stripped}?"
    return stripped
