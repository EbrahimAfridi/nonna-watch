from nonna_hub.speech import Utterance
from nonna_hub.voice_check import answer, is_question

SENT_MS = 10_000  # when the hub sent the question
ENDED_MS = 13_000  # when the phone finished playing it


def said(start_ms, end_ms, help_words=(), **texts):
    return Utterance(start_ms, end_ms, texts, list(help_words))


def test_speech_that_ended_before_the_question_was_sent_is_not_the_question():
    assert not is_question(said(5_000, 9_000), SENT_MS, ENDED_MS)


def test_speech_while_the_question_plays_is_the_question():
    assert is_question(said(10_500, 12_800), SENT_MS, ENDED_MS)


def test_until_the_phone_reports_the_end_everything_after_sending_may_be_the_question():
    assert is_question(said(20_000, 21_000), SENT_MS, None)


def test_speech_starting_after_the_question_is_an_answer():
    assert not is_question(said(13_500, 14_500), SENT_MS, ENDED_MS)


def test_a_fine_word_is_a_reassuring_answer():
    assert answer(said(0, 1, it="Sì, sto bene.")) == ("fine", "sto bene")


def test_a_negation_is_never_a_reassuring_answer():
    assert answer(said(0, 1, it="Non sto bene")) is None
    assert answer(said(0, 1, en="I'm not okay")) is None
    assert answer(said(0, 1, en="I don't feel okay")) is None
    assert answer(said(0, 1, hi="ठीक नहीं हूँ")) is None


def test_the_italian_t_apostrophe_is_not_a_negation():
    assert answer(said(0, 1, it="Sto bene, t'ho detto!")) == ("fine", "sto bene")


def test_a_help_word_beats_a_fine_word():
    assert answer(said(0, 1, help_words=["aiuto"], it="Bene... no, aiuto!")) == ("help", "aiuto")


def test_speech_without_fine_or_help_words_is_no_answer():
    assert answer(said(0, 1, it="Chi è?", en="Who is it?")) is None
