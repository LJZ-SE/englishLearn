from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from tools.content_pipeline.models import QuestionVariant

_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "he",
    "her",
    "had",
    "has",
    "have",
    "him",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "may",
    "might",
    "must",
    "of",
    "on",
    "or",
    "ought",
    "she",
    "shall",
    "should",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "will",
    "with",
    "would",
    "you",
    "your",
}
_PHRASES = {
    "as a result",
    "at the same time",
    "because of",
    "by the way",
    "do not",
    "find out",
    "for example",
    "give up",
    "in order to",
    "in spite of",
    "look after",
    "look forward to",
    "make sure",
    "on the other hand",
    "point out",
    "put away",
    "set up",
    "take part in",
    "turn out",
    "work out",
}
_CONTRACTIONS = {
    "are not": "aren't",
    "can not": "can't",
    "cannot": "can't",
    "could not": "couldn't",
    "did not": "didn't",
    "do not": "don't",
    "does not": "doesn't",
    "had not": "hadn't",
    "has not": "hasn't",
    "have not": "haven't",
    "is not": "isn't",
    "should not": "shouldn't",
    "was not": "wasn't",
    "were not": "weren't",
    "will not": "won't",
    "would not": "wouldn't",
}
_NATURAL_PHRASE_STARTERS = {"a", "an", "the", "this", "that"}


@dataclass(frozen=True, slots=True)
class _Candidate:
    start: int
    end: int
    text: str
    score: float
    rationale: str


@lru_cache(maxsize=4096)
def _frequency_score(word: str) -> float:
    try:
        from wordfreq import zipf_frequency
    except ImportError:
        # 较长且含后缀的词在确定性回退中视为更难。
        lowered = word.casefold()
        suffix_bonus = 0.6 if lowered.endswith(("tion", "ment", "ous", "ive", "ly")) else 0.0
        return min(6.0, 1.5 + len(lowered) * 0.17 + suffix_bonus)
    frequency = zipf_frequency(word, "en")
    return max(0.5, 8.0 - frequency)


def _spacy_pos_bonus(sentence: str) -> dict[tuple[int, int], float]:
    try:
        import spacy

        pipeline = spacy.blank("en")
    except ImportError:
        return {}
    result: dict[tuple[int, int], float] = {}
    for token in pipeline(sentence):
        if token.is_alpha and not token.is_stop:
            result[(token.idx, token.idx + len(token.text))] = 0.15
    return result


def _all_candidates(sentence: str) -> list[_Candidate]:
    matches = list(_TOKEN.finditer(sentence))
    pos_bonus = _spacy_pos_bonus(sentence)
    candidates: list[_Candidate] = []
    for match in matches:
        lowered = match.group().casefold()
        if lowered in _STOP_WORDS or len(lowered) < 3:
            continue
        score = _frequency_score(lowered) + pos_bonus.get((match.start(), match.end()), 0.0)
        candidates.append(_Candidate(match.start(), match.end(), match.group(), score, "词频实词"))

    for size in range(2, 5):
        for index in range(len(matches) - size + 1):
            group = matches[index : index + size]
            between = sentence[group[0].start() : group[-1].end()]
            if "\n" in between or re.search(r"[,;:!?]", between):
                continue
            phrase = " ".join(match.group() for match in group)
            lowered = phrase.casefold()
            if len(between.split()) != size:
                continue
            meaningful = sum(match.group().casefold() not in _STOP_WORDS for match in group)
            if meaningful == 0:
                continue
            is_known = lowered in _PHRASES or lowered in _CONTRACTIONS
            if not is_known and (
                (
                    group[0].group().casefold() in _STOP_WORDS
                    and group[0].group().casefold() not in _NATURAL_PHRASE_STARTERS
                )
                or group[-1].group().casefold() in _STOP_WORDS
            ):
                continue
            # 多词答案自然比其中单个高频词难；固定搭配获得额外权重。
            base = sum(_frequency_score(match.group()) for match in group) / size
            score = base + 1.4 + size * 0.55 + (1.25 if is_known else 0.0)
            rationale = "固定搭配" if is_known else f"{size} 词语块"
            candidates.append(
                _Candidate(group[0].start(), group[-1].end(), between, score, rationale)
            )
    return candidates


def _aliases(answer: str) -> tuple[str, ...]:
    lowered = answer.casefold()
    aliases: set[str] = set()
    if lowered in _CONTRACTIONS:
        aliases.add(_CONTRACTIONS[lowered])
    reverse = {value: key for key, value in _CONTRACTIONS.items()}
    if lowered in reverse:
        aliases.add(reverse[lowered])
    return tuple(sorted(aliases))


def generate_variants(sentence: str) -> tuple[QuestionVariant, QuestionVariant, QuestionVariant]:
    candidates = _all_candidates(sentence)
    if len({candidate.text.casefold() for candidate in candidates}) < 3:
        raise ValueError("句子无法生成三个不同的答案")

    ordered = sorted(candidates, key=lambda item: (item.score, item.start, item.end))
    selected: list[_Candidate] = []
    used: set[str] = set()
    targets = (0.12, 0.52, 0.95)
    for target in targets:
        available = [item for item in ordered if item.text.casefold() not in used]
        index = round((len(available) - 1) * target)
        choice = available[index]
        selected.append(choice)
        used.add(choice.text.casefold())

    alias_candidates = [item for item in ordered if _aliases(item.text)]
    if alias_candidates and not any(_aliases(item.text) for item in selected):
        replacement = alias_candidates[-1]
        selected[-1] = replacement
        used = {item.text.casefold() for item in selected}
        if len(used) != 3:
            for candidate in reversed(ordered):
                if candidate.text.casefold() not in used:
                    selected[-2] = candidate
                    break

    selected.sort(key=lambda item: (item.score, item.start))
    # 极少数同分通过稳定微调表达相对层级，不改变候选本身的排序含义。
    scores: list[float] = []
    for item in selected:
        score = round(item.score, 4)
        if scores and score <= scores[-1]:
            score = round(scores[-1] + 0.0001, 4)
        scores.append(score)

    variants = []
    for difficulty, candidate, score in zip(
        ("easy", "medium", "hard"), selected, scores, strict=True
    ):
        variants.append(
            QuestionVariant(
                difficulty=difficulty,
                answer_start=candidate.start,
                answer_end=candidate.end,
                canonical_answer=candidate.text,
                blank_count=len(candidate.text.split()),
                score=score,
                rationale=candidate.rationale,
                aliases=_aliases(candidate.text),
            )
        )
    return tuple(variants)  # type: ignore[return-value]
