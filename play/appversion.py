"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 6
VERSION_NAME = "0.6.0"
NOTES = ("In-app updates: WaveBeast now downloads and installs updates itself — no more bouncing to the "
         "browser. Plus custom sensors are capped at 10 per device.")
