"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 38
VERSION_NAME = "0.13.0"
NOTES = ("Sign in from the app, a new Account tab, and Google Play release preparation. "
         "Sideloaded builds before 0.13.0 use an old signing key: uninstall them once before installing this version.")
PLAY_URL = "https://play.google.com/store/apps/details?id=net.wavebeasts.app"
