import logging
from pathlib import Path

from listening_cloze.infrastructure.logging_config import configure_logging


def test_rotating_local_log_contains_module_error_type_and_traceback(tmp_path: Path) -> None:
    log_path = configure_logging(tmp_path)
    logger = logging.getLogger("listening_cloze.test")

    try:
        raise ValueError("模拟故障")
    except ValueError:
        logger.exception("题库模块失败")

    content = log_path.read_text(encoding="utf-8")
    assert "listening_cloze.test" in content
    assert "ValueError" in content
    assert "Traceback" in content
    assert "题库模块失败" in content
