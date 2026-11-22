plugins {
    kotlin("jvm")
}

// Android runs Java 17 bytecode; build it with whatever JDK is installed.
java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}
kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
    // The expected results are written by android/tools/make_golden.py from the Python reader.
    inputs.dir("src/test/resources/golden")
}
