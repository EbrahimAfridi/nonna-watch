import numpy as np

from nonna_hub.protocol import FRAME_BYTES, encode_frame, parse_frame


def contract_example_samples():
    samples = np.zeros(16_000, dtype=np.float32)
    samples[1:3] = [1000 / 32768, -1000 / 32768]
    return samples


def test_frame_matches_the_worked_example_in_the_contract():
    frame = encode_frame(1_795_698_192_000, 42, contract_example_samples())

    assert len(frame) == FRAME_BYTES == 32_012
    assert frame[:18] == bytes.fromhex("80eef317a2010000" "2a000000" "0000e80318fc")


def test_frame_survives_a_round_trip():
    capture_ms, seq, samples = parse_frame(encode_frame(1_795_698_192_000, 42, contract_example_samples()))

    assert (capture_ms, seq) == (1_795_698_192_000, 42)
    np.testing.assert_array_equal(samples, contract_example_samples())
