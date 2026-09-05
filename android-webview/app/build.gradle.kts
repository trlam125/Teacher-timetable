plugins {
    id("com.android.application")
}

fun asBuildConfigString(value: String): String =
    "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

fun dotenvValue(name: String): String? {
    val envFile = rootProject.file("../.env")
    if (!envFile.isFile) return null
    return envFile.readLines()
        .asSequence()
        .map { it.trim() }
        .filter { it.isNotEmpty() && !it.startsWith("#") && it.contains("=") }
        .map { it.substringBefore("=").trim() to it.substringAfter("=").trim().trim('"', '\'') }
        .firstOrNull { it.first == name }
        ?.second
}

val appBaseUrl = sequenceOf(
    providers.gradleProperty("APP_BASE_URL").orNull,
    System.getenv("APP_BASE_URL"),
    dotenvValue("APP_BASE_URL"),
)
    .mapNotNull { value -> value?.trim()?.trimEnd('/')?.takeIf { it.isNotBlank() } }
    .firstOrNull()
    ?: error("Missing APP_BASE_URL. Set it in ../.env, environment, or -PAPP_BASE_URL=https://...")

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
