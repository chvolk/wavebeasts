"""Current published app version. Bump VERSION_CODE (and NAME/NOTES) whenever a new APK is released;
the app compares its installed versionCode against this and prompts to update. Keep VERSION_CODE in sync
with android/app/build.gradle's versionCode in the wavebeast repo."""

VERSION_CODE = 4
VERSION_NAME = "0.4.0"
NOTES = ("Cleaner scan screen: pick inputs from a dropdown (camera / import / sensor value) instead of "
         "loose buttons. Plus app integration — share a barcode/QR value into WaveBeast, or open it with a "
         "wavebeast:// deep link.")
