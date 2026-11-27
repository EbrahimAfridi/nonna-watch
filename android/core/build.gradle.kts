// Shared code for both apps: protocol messages, room ids, later the audio frame encoder.
plugins {
    alias(libs.plugins.android.library)
}

android {
    namespace = "app.nonnawatch.core"
    compileSdk = 37

    defaultConfig {
        minSdk = 26
    }
}

dependencies {
    testImplementation(libs.junit)
}
