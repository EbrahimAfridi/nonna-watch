package app.nonnawatch.listener.hub

/**
 * The phone's name for `hello`, such as "Nothing A001": the hub prints it when the phone connects,
 * and the experiment results are labelled with it.
 */
fun deviceModel(manufacturer: String, model: String): String {
    val name = if (model.startsWith(manufacturer, ignoreCase = true)) model else "$manufacturer $model"
    return printableAscii(name.trim())
}

/**
 * The hub accepts only printable ASCII, at most 80 characters, in `hello` (its console prints
 * them). Anything else would make the whole hello invalid, so other characters become "?".
 */
fun printableAscii(text: String, maxLength: Int = 80): String =
    text.map { if (it in ' '..'~') it else '?' }.joinToString("").take(maxLength)
