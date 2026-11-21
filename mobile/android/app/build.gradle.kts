import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// The release signing key. A phone installs an update only when it is signed with the same key as the installed app,
// so releases are signed with the owner's keystore: named in android/key.properties (never committed) on a
// developer's machine, or by the ANDROID_KEYSTORE_* environment in CI (.github/workflows/mobile-release.yml;
// docs/deploy.md, «The app's signing key»). With neither, a release build is signed with this machine's debug key:
// enough to try the app on a phone, but every machine has its own debug key, so such a build can never update an
// installed app or be updated by a release.
val keyProperties = Properties().apply {
    val file = rootProject.file("key.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

fun signing(property: String, variable: String): String? =
    (keyProperties.getProperty(property) ?: System.getenv(variable))?.trim()?.takeIf { it.isNotEmpty() }

// Passwords exactly as given, spaces included: deploy/app_release.py checks them with keytool the same way.
fun password(property: String, variable: String): String? =
    (keyProperties.getProperty(property) ?: System.getenv(variable))?.takeIf { it.isNotEmpty() }

val releaseKeystore = signing("storeFile", "ANDROID_KEYSTORE_PATH")

android {
    namespace = "kg.joop.joop_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "kg.joop.joop_mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        releaseKeystore?.let { keystore ->
            create("release") {
                storeFile = file(keystore)
                storePassword = password("storePassword", "ANDROID_KEYSTORE_PASSWORD")
                keyAlias = signing("keyAlias", "ANDROID_KEY_ALIAS") ?: "joop"  // the name the guide gives the key
                // A keystore made since Java 9 has one password for the file and the key.
                keyPassword = password("keyPassword", "ANDROID_KEY_PASSWORD") ?: storePassword
            }
        }
    }

    buildTypes {
        release {
            // Without the owner's key: the debug key, so `flutter run --release` works on any machine.
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
