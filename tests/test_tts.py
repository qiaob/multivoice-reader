import numpy as np

from multivoice_reader.tts import REF_TAIL_SECONDS, without_long_tail

RATE = 16000


def tone(seconds: float) -> np.ndarray:
    return (0.5 * np.sin(np.arange(int(seconds * RATE)) * 0.3)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), dtype=np.float32)


def test_a_long_silent_tail_is_cut_to_a_short_one():
    cut = without_long_tail(np.concatenate([tone(1.0), silence(0.6)]), RATE)
    assert abs(len(cut) / RATE - (1.0 + REF_TAIL_SECONDS)) < 0.02


def test_a_recording_that_ends_on_sound_or_is_all_silence_is_left_alone():
    ends_on_sound = np.concatenate([silence(0.3), tone(1.0)])
    assert len(without_long_tail(ends_on_sound, RATE)) == len(ends_on_sound)
    assert len(without_long_tail(silence(1.0), RATE)) == RATE


def test_a_pause_in_the_middle_is_kept():
    spoken = np.concatenate([tone(0.5), silence(0.8), tone(0.5), silence(0.05)])
    assert len(without_long_tail(spoken, RATE)) == len(spoken)
