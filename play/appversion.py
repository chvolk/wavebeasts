"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 5
VERSION_NAME = "0.5.0"
NOTES = ("The engine now runs as a background service, so sweeping stays available on this device — and in "
         "companion apps like Omnitool — even when WaveBeast is minimized (stop it any time from its "
         "notification). Also fixes the top nav being hidden behind the status bar on newer Android.")
