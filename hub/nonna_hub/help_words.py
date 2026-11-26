"""Help words per language, and finding them in what Whisper wrote."""

import re
import unicodedata
from collections.abc import Iterable

# Spoken Hindi and Urdu are one language, and Whisper writes it in Devanagari or Arabic script
# whichever of the two it is told (a Hindi "बचाओ" came back as "بچاو"), so both get both scripts.
HINDI_URDU_HELP_WORDS = ("बचाओ", "بچاؤ", "بچاو", "bachao", "मदद", "مدد", "madad", "madat")

# Until E8 reads the home's helpWords from Firestore. Whisper may also drop the Bosnian ć or split
# "upomoć" into "u pomoć", hence the variants.
DEFAULT_HELP_WORDS = {
    "it": ("aiuto", "aiutami", "aiutatemi", "soccorso"),
    "en": ("help",),
    "hi": HINDI_URDU_HELP_WORDS,
    "ur": HINDI_URDU_HELP_WORDS,
    "bs": ("upomoć", "upomoc", "pomoć", "pomoc", "pomozite", "pomagajte"),
}
LANGUAGES = tuple(DEFAULT_HELP_WORDS)

# Short-vowel marks that Urdu normally leaves out but Whisper sometimes writes, as in "بَجَو".
ARABIC_VOWEL_MARKS = re.compile("[\u064b-\u065f\u0670]")


def words(text: str) -> list[str]:
    """Lower-case words without surrounding punctuation.

    Splits on spaces rather than with \\w, which would cut Hindi words apart at their vowel signs.
    """
    found = []
    for token in unicodedata.normalize("NFKC", text).casefold().split():
        punctuation = "".join(char for char in token if unicodedata.category(char).startswith("P"))
        word = ARABIC_VOWEL_MARKS.sub("", token.strip(punctuation))
        word = re.sub(r"(.)\1{2,}", r"\1", word)  # shouts get stretched: "aiutooo"
        if word:
            found.append(word)
    return found


def find_phrases(text: str, phrases: Iterable[str]) -> list[str]:
    """The phrases (help words, fine words, one word or several) that appear as whole words."""
    spoken = words(text)
    found = []
    for phrase in phrases:
        wanted = words(phrase)
        if wanted and any(spoken[i : i + len(wanted)] == wanted for i in range(len(spoken) - len(wanted) + 1)):
            found.append(phrase)
    return found
