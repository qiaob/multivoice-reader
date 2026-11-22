pluginManagement {
    repositories {
        google()
        gradlePluginPortal()
        mavenCentral()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "multivoice-reader"

// What the reader does without models, in plain Kotlin: cutting text, the reading script,
// casting, and what the labelling model is asked and how its answers are read. Tested on any
// JVM against what the Python reader does.
include(":core")
// The Android app: the models run on the phone.
include(":app")
