plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.compose")
    kotlin("plugin.serialization")
}

val repo = rootDir.parentFile
val generatedAssets = layout.buildDirectory.dir("generated/adapterAssets")

// The llama.cpp source the native library is built from (see tools/fetch_llama_cpp.sh).
val fetchLlamaCpp by tasks.registering(Exec::class) {
    commandLine("sh", "${rootDir}/tools/fetch_llama_cpp.sh")
    outputs.dir("${rootDir}/third_party/llama.cpp")
}

// The fine-tuned LoRA weights in finetune/adapters, as llama.cpp adapters, shipped in the app.
val makeAdapters by tasks.registering {
    dependsOn(fetchLlamaCpp)
    val out = generatedAssets.get().dir("adapters")
    inputs.dir("${repo}/finetune/adapters")
    inputs.file("${rootDir}/tools/peft_to_gguf.py")
    outputs.dir(out)
    doLast {
        for ((name, arch) in listOf("qwen3-1.7b" to "qwen3", "qwen3.5-4b" to "qwen35")) {
            project.exec {
                commandLine(
                    "python3", "${rootDir}/tools/peft_to_gguf.py",
                    "${repo}/finetune/adapters/$name", out.file("$name.gguf").asFile.path, "--arch", arch,
                )
            }
        }
    }
}

android {
    namespace = "io.github.qiaob.multivoice"
    compileSdk = 35
    ndkVersion = "27.2.12479018"

    defaultConfig {
        applicationId = "io.github.qiaob.multivoice"
        minSdk = 29
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.1"
        ndk { abiFilters += "arm64-v8a" }
        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DANDROID_STL=c++_static",
                    // Aligned for 16 KB memory pages, which newer Android phones use; 4 KB ones load it too.
                    "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
                )
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Until there is a release key, release builds are signed like debug ones so they install.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }
    sourceSets["main"].assets.srcDir(generatedAssets)
    // The Python reader's results (assets/golden/), for the self-check on the phone.
    sourceSets["main"].assets.srcDir("${rootDir}/core/src/test/resources")
    androidResources { noCompress += "gguf" }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
}

tasks.named("preBuild") { dependsOn(fetchLlamaCpp, makeAdapters) }

dependencies {
    implementation(project(":core"))
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
}
