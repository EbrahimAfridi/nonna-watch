package app.nonnawatch.listener.voice

/**
 * The hub's built-in questions (QUESTIONS in hub/nonna_hub/voice_check.py), for the Test button:
 * it checks that this phone has a voice for each language before the demo. The hub still decides
 * what is asked for real.
 */
enum class QuestionLanguage(val label: String, val text: String, val tag: String) {
    ITALIAN("Italian", "Stai bene?", "it-IT"),
    ENGLISH("English", "Are you okay?", "en-US"),
    HINDI("Hindi", "क्या आप ठीक हैं?", "hi-IN"),
    URDU("Urdu", "کیا آپ ٹھیک ہیں؟", "ur-PK"),
    BOSNIAN("Bosnian", "Jesi li dobro?", "bs-BA"),
}
