"""Help words per language, and finding them in what Whisper wrote."""

import re
import unicodedata
from collections.abc import Iterable

# Spoken Hindi and Urdu are one language, and Whisper writes it in Devanagari or Arabic script
# whichever of the two it is told (a Hindi "बचाओ" came back as "بچاو"), so both get both scripts.
HINDI_URDU_HELP_WORDS = ("बचाओ", "بچاؤ", "بچاو", "bachao", "मदद", "مدد", "madad")

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


def words(text: str) -> list[str]:
    """Lower-case words without surrounding punctuation.

    Splits on spaces rather than with \\w, which would cut Hindi words apart at their vowel signs.
    """
    found = []
    for token in unicodedata.normalize("NFKC", text).casefold().split():
        punctuation = "".join(char for char in token if unicodedata.category(char).startswith("P"))
        word = re.sub(r"(.)\1{2,}", r"\1", token.strip(punctuation))  # shouts get stretched: "aiutooo"
        if word:
            found.append(word)
    return found


def find_help_words(text: str, help_words: Iterable[str]) -> list[str]:
    """The help words, or phrases of several words, that appear as whole words in the text."""
    spoken = words(text)
    found = []
    for phrase in help_words:
        wanted = words(phrase)
        if wanted and any(spoken[i : i + len(wanted)] == wanted for i in range(len(spoken) - len(wanted) + 1)):
            found.append(phrase)
    return found
