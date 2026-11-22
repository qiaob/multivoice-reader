pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
    }
}
rootProject.name = "multivoice-reader"

// What the reader does without models, in plain Kotlin: cutting text, the reading script,
// casting, and what the labelling model is asked and how its answers are read. The Android
// app (to come) builds on it; it is tested on any JVM against what the Python reader does.
include(":core")
