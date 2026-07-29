"""词条级听写的纯领域规则。"""

_APOSTROPHE_TRANSLATION = str.maketrans({"‘": "'", "’": "'"})


def normalize_vocabulary_answer(value: str) -> str:
    """只归一化大小写、空白和弯直撇号，保留连字符与全部拼写差异。"""
    return " ".join(value.translate(_APOSTROPHE_TRANSLATION).casefold().split())


def is_vocabulary_answer_correct(*, expected: str, submitted: str) -> bool:
    """词条听写不接受内容题库的 aliases，英美拼写必须与目标完全一致。"""
    return normalize_vocabulary_answer(expected) == normalize_vocabulary_answer(submitted)
