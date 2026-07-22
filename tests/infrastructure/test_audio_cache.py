import wave
from dataclasses import replace
from pathlib import Path

from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile


def _write_wave(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\x00\x00" * 128)


def test_same_sentence_and_profile_share_cache_across_question_versions(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    profile = AudioProfile(
        sdk_version="1.3.1",
        model_revision="724fb5a",
        voice="F3",
        voice_sha256="voice-hash",
        language="en",
        steps=8,
        synthesis_speed=1.0,
        sample_rate=44_100,
    )

    first = cache.path_for("  You should take part in the meeting.  ", profile)
    second = cache.path_for("You should  take part in the meeting.", profile)

    assert first == second


def test_cache_accepts_complete_wave_and_rejects_partial_file(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    profile = AudioProfile.default()
    target = cache.path_for("A complete sentence.", profile)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"RIFF-partial")

    assert cache.valid_path("A complete sentence.", profile) is None

    temporary = cache.temporary_path(target)
    _write_wave(temporary)
    cache.commit(temporary, target)

    assert cache.valid_path("A complete sentence.", profile) == target
    assert not temporary.exists()


def test_target_loudness_change_invalidates_quieter_cached_audio(tmp_path: Path) -> None:
    cache = AudioCache(tmp_path)
    quiet_profile = replace(AudioProfile.default(), target_rms_dbfs=-17.0)
    louder_profile = replace(AudioProfile.default(), target_rms_dbfs=-11.0)

    assert cache.path_for("A sentence.", quiet_profile) != cache.path_for(
        "A sentence.", louder_profile
    )
