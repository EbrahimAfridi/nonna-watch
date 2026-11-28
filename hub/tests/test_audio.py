import numpy as np

from nonna_hub.audio import CHUNK_SAMPLES, WindowSlicer, split_into_chunks


def test_windows_overlap_and_ignore_chunk_edges():
    stream = np.arange(3 * CHUNK_SAMPLES, dtype=np.float32)
    slicer = WindowSlicer(window=15_600, hop=8_000)

    windows = []
    for chunk in np.split(stream, [5_000, 21_000, 30_000]):
        windows += slicer.push(chunk)

    assert [start for start, _ in windows] == [0, 8_000, 16_000, 24_000, 32_000]
    for start, window in windows:
        np.testing.assert_array_equal(window, stream[start : start + 15_600])


def test_short_clip_becomes_one_chunk_padded_with_silence():
    chunks = split_into_chunks(np.ones(9_600, dtype=np.float32))

    assert len(chunks) == 1
    assert chunks[0][:9_600].all()
    assert not chunks[0][9_600:].any()


def test_clip_is_cut_into_whole_seconds():
    chunks = split_into_chunks(np.ones(int(2.5 * CHUNK_SAMPLES), dtype=np.float32))

    assert [len(chunk) for chunk in chunks] == [CHUNK_SAMPLES] * 3
