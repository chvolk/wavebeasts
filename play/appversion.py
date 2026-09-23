"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 34
VERSION_NAME = "0.12.15"
NOTES = "Engine update checks and version reporting. Passive listeners now scan every 30 minutes, with server enforcement and restart-safe scheduling."
