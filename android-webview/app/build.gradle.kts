plugins {
    id("com.android.application")
}

fun asBuildConfigString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val appBaseUrl = "https://teacher-timetable-three.vercel.app"

require(appBaseUrl.startsWith("https://")) {
    "APP_BASE_URL must use HTTPS: $appBaseUrl"
}

android {
    namespace = "vn.smarttkb.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "vn.smarttkb.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 8
        versionName = "1.0.7"

        buildConfigField("String", "APP_BASE_URL", asBuildConfigString(appBaseUrl))
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
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
