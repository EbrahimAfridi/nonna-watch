from nonna_hub.help_words import DEFAULT_HELP_WORDS, find_phrases, words


def test_case_punctuation_and_stretched_shouts_do_not_matter():
    assert find_phrases("AIUTO!! Aiutooo...", DEFAULT_HELP_WORDS["it"]) == ["aiuto"]


def test_only_whole_words_match():
    assert find_phrases("That was really helpful, thanks.", DEFAULT_HELP_WORDS["en"]) == []


def test_bosnian_matches_with_or_without_the_accent():
    assert find_phrases("Upomoć!", DEFAULT_HELP_WORDS["bs"]) == ["upomoć"]
    assert find_phrases("upomoc", DEFAULT_HELP_WORDS["bs"]) == ["upomoc"]


def test_hindi_words_keep_their_vowel_signs():
    assert words("मैं ठीक हूँ।") == ["मैं", "ठीक", "हूँ"]
    assert find_phrases("बचाओ! बचाओ!", DEFAULT_HELP_WORDS["hi"]) == ["बचाओ"]


def test_urdu_matches_with_arabic_punctuation():
    assert find_phrases("مدد؟ بچاؤ!", DEFAULT_HELP_WORDS["ur"]) == ["بچاؤ", "مدد"]


def test_hindi_matches_when_whisper_writes_it_in_urdu_script():
    assert find_phrases("بچاو, بچاو", DEFAULT_HELP_WORDS["hi"]) == ["بچاو"]


def test_urdu_matches_when_whisper_adds_vowel_marks():
    assert find_phrases("بَچاؤ!", DEFAULT_HELP_WORDS["ur"]) == ["بچاؤ"]


def test_a_phrase_matches_only_as_a_whole():
    assert find_phrases("ok, I'm fine now", ["i'm fine"]) == ["i'm fine"]
    assert find_phrases("I'm not fine", ["i'm fine"]) == []
