"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 3
VERSION_NAME = "0.3.0"
NOTES = ("Safe-area layout for notch/nav bars, cellular signal (3G/4G/5G + bars) as a scan input, and a "
         "more reliable download.")
