plugins {
    id("com.android.application")
}

fun asBuildConfigString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

fun readRootEnvValue(key: String): String? {
    val envFile = rootProject.projectDir.parentFile.resolve(".env")
    if (!envFile.isFile) return null
    return envFile.useLines { lines ->
        lines.map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("#") && it.contains("=") }
            .map { it.substringBefore("=").trim() to it.substringAfter("=").trim() }
            .firstOrNull { it.first == key }
            ?.second
            ?.trim('\"', '\'')
    }
}

val appBaseUrl = (
    readRootEnvValue("APP_BASE_URL")
        ?.takeIf { it.isNotBlank() }
        ?: providers.environmentVariable("APP_BASE_URL").orNull?.takeIf { it.isNotBlank() }
        ?: error("Missing APP_BASE_URL. Set it in the project root .env before building the APK.")
).trim().trimEnd('/')

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
        versionCode = 5
        versionName = "1.0.4"

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
