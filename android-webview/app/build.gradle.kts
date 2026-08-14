plugins {
    id("com.android.application")
}

fun asBuildConfigString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val smartTkbServerUrl = providers.gradleProperty("SMART_TKB_SERVER_URL")
    .orElse("https://yahoo-speech-radiation.ngrok-free.dev")
    .get()
    .trim()
    .trimEnd('/')

android {
    namespace = "vn.smarttkb.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "vn.smarttkb.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 4
        versionName = "1.1.0"

        buildConfigField("String", "SERVER_URL", asBuildConfigString(smartTkbServerUrl))
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        debug {
            isDebuggable = true
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
