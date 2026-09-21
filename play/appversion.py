"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 13
VERSION_NAME = "0.11.2"
NOTES = "Sensor toggles work now (WiFi/Location/Cell re-ask for permission), and off means off."
