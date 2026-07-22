from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest


def _write_medquad_xml(*, focus: str, question: str, answer: str = "版权答案不得进入题库") -> str:
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<Document>
  <Focus>{focus}</Focus>
  <QAPairs>
    <QAPair>
      <Question>{question}</Question>
      <Answer>{answer}</Answer>
    </QAPair>
  </QAPairs>
</Document>
"""


def _write_archive(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_medquad_emits_only_questions_with_explicit_collection_metadata_mapping(
    tmp_path: Path,
) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    archive_path = tmp_path / "medquad.zip"
    _write_archive(
        archive_path,
        {
            "MedQuAD-rev/11_MPlusDrugs_QA/1.xml": _write_medquad_xml(
                focus="Drugs, Herbs and Supplements",
                question="What should I know before taking aspirin?",
                answer="Aspirin answer must never be emitted.",
            ),
            "MedQuAD-rev/7_SeniorHealth_QA/2.xml": _write_medquad_xml(
                focus="Exercise and Physical Activity",
                question="How can I exercise safely?",
            ),
            "MedQuAD-rev/7_SeniorHealth_QA/3.xml": _write_medquad_xml(
                focus="Emotional Wellness",
                question="How can I manage stress?",
            ),
            "MedQuAD-rev/1_CancerGov_QA/4.xml": _write_medquad_xml(
                focus="Breast Cancer Treatment",
                question="What tests diagnose breast cancer?",
            ),
            "MedQuAD-rev/9_CDC_QA/5.xml": _write_medquad_xml(
                focus="General health information",
                question="This broad record must be skipped.",
            ),
        },
    )

    items = list(iter_medquad_questions(archive_path))

    assert [(item.text, item.source_item_id, item.top_scene, item.sub_scene) for item in items] == [
        (
            "What tests diagnose breast cancer?",
            "medquad:1_CancerGov_QA:4.xml:qa:0",
            "health",
            "health_clinic",
        ),
        (
            "How can I exercise safely?",
            "medquad:7_SeniorHealth_QA:2.xml:qa:0",
            "health",
            "health_fitness",
        ),
        (
            "How can I manage stress?",
            "medquad:7_SeniorHealth_QA:3.xml:qa:0",
            "health",
            "health_wellbeing",
        ),
        (
            "What should I know before taking aspirin?",
            "medquad:11_MPlusDrugs_QA:1.xml:qa:0",
            "health",
            "health_pharmacy",
        ),
    ]
    assert all(item.source_name == "medquad" for item in items)
    assert all(item.source_author == "" for item in items)
    assert all("answer" not in item.text.casefold() for item in items)


def test_medquad_requires_collection_metadata_and_nonempty_question(tmp_path: Path) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    archive_path = tmp_path / "invalid.xml.zip"
    _write_archive(
        archive_path,
        {
            "MedQuAD-rev/11_MPlusDrugs_QA/1.xml": _write_medquad_xml(
                focus=" ", question="What is aspirin?"
            ),
        },
    )

    with pytest.raises(ValueError, match="Focus.*非空"):
        list(iter_medquad_questions(archive_path))

    empty_question = tmp_path / "empty-question.zip"
    _write_archive(
        empty_question,
        {
            "MedQuAD-rev/11_MPlusDrugs_QA/1.xml": _write_medquad_xml(
                focus="Drugs, Herbs and Supplements", question=" "
            ),
        },
    )
    with pytest.raises(ValueError, match="Question.*非空"):
        list(iter_medquad_questions(empty_question))


def test_medquad_rejects_xml_schema_drift_and_malformed_xml(tmp_path: Path) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    missing_pairs = tmp_path / "missing-pairs.zip"
    _write_archive(
        missing_pairs,
        {"MedQuAD-rev/1_CancerGov_QA/1.xml": "<Document><Focus>Cancer</Focus></Document>"},
    )
    with pytest.raises(ValueError, match="QAPairs"):
        list(iter_medquad_questions(missing_pairs))

    malformed = tmp_path / "malformed.zip"
    _write_archive(
        malformed,
        {"MedQuAD-rev/1_CancerGov_QA/1.xml": "<Document><Focus>Cancer</Focus>"},
    )
    with pytest.raises(ValueError, match="XML 无效"):
        list(iter_medquad_questions(malformed))


def test_medquad_skips_documents_without_qa_pairs_but_keeps_valid_documents(
    tmp_path: Path,
) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    archive_path = tmp_path / "empty-pairs.zip"
    _write_archive(
        archive_path,
        {
            "MedQuAD-rev/1_CancerGov_QA/empty.xml": (
                "<Document><Focus>Cancer</Focus><QAPairs /></Document>"
            ),
            "MedQuAD-rev/1_CancerGov_QA/valid.xml": _write_medquad_xml(
                focus="Cancer", question="What is cancer?"
            ),
        },
    )

    [item] = list(iter_medquad_questions(archive_path))

    assert item.source_item_id == "medquad:1_CancerGov_QA:valid.xml:qa:0"


def test_medquad_supports_the_fixed_ninds_legacy_xml_schema(tmp_path: Path) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    archive_path = tmp_path / "ninds-legacy.zip"
    _write_archive(
        archive_path,
        {
            "MedQuAD-rev/6_NINDS_QA/legacy.xml": """
                <doc><doctitle-focus>Holmes-Adie syndrome</doctitle-focus><umls />
                <qaPairs><pair><question>What is Holmes-Adie syndrome?</question>
                <answer /></pair></qaPairs></doc>
            """,
        },
    )

    [item] = list(iter_medquad_questions(archive_path))

    assert (item.text, item.sub_scene) == (
        "What is Holmes-Adie syndrome?",
        "health_clinic",
    )


def test_medquad_rejects_invalid_archive_members_and_unknown_collections(tmp_path: Path) -> None:
    from tools.content_pipeline.medquad_source import iter_medquad_questions

    unsafe = tmp_path / "unsafe.zip"
    _write_archive(
        unsafe,
        {"../11_MPlusDrugs_QA/1.xml": _write_medquad_xml(
            focus="Drugs, Herbs and Supplements", question="What is aspirin?"
        )},
    )
    with pytest.raises(ValueError, match="不安全路径"):
        list(iter_medquad_questions(unsafe))

    special = tmp_path / "special.zip"
    info = zipfile.ZipInfo("MedQuAD-rev/1_CancerGov_QA/1.xml")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o644) << 16
    with zipfile.ZipFile(special, "w") as archive:
        archive.writestr(info, "target")
    with pytest.raises(ValueError, match="普通文件"):
        list(iter_medquad_questions(special))

    unknown = tmp_path / "unknown.zip"
    _write_archive(
        unknown,
        {"MedQuAD-rev/unknown/1.xml": _write_medquad_xml(
            focus="Drugs, Herbs and Supplements", question="What is aspirin?"
        )},
    )
    with pytest.raises(ValueError, match="结构漂移"):
        list(iter_medquad_questions(unknown))
