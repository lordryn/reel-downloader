[app]

# (str) Title of your application
title = Reel Downloader

# (str) Package name
package.name = reeldownloader

# (str) Package domain (needed for android packaging)
package.domain = org.reeldownloader

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (must include xml for intent_filters.xml)
source.include_exts = py,png,jpg,kv,atlas,xml,json

# (list) List of inclusions using pattern matching
#source.include_patterns = assets/*,images/*.png

# (list) Source files to exclude (let empty to not exclude anything)
source.exclude_exts = spec

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests, bin, .git, .github

# (str) Application versioning (method 1)
version = 1.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3==3.11.9,hostpython3==3.11.9,kivy==2.3.1,kivymd==1.2.0,yt-dlp,pyjnius,android,certifi,urllib3,requests,charset-normalizer,idna,six

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,READ_MEDIA_VIDEO,ACCESS_NETWORK_STATE

# (int) Target Android API, should be as high as possible.
android.api = 34

# (int) Minimum API your APK / AAB will support.
android.minapi = 24

# (str) Android NDK version to use
android.ndk = 25b

# (bool) If True, then the app will use AndroidX support libraries instead of old support libraries
android.enable_androidx = True

# (list) List of Android architectures to build for
android.archs = arm64-v8a

# (str) Custom file to insert in the AndroidManifest.xml inside the <activity> tag
# This registers the app as a native Android Share Target for plain text and URL links
android.manifest_intent_filters = intent_filters.xml

# (bool) If True, then automatically accept SDK license agreements.
android.accept_sdk_license = True

# (bool) If True, then skip trying to update the Android sdk
android.skip_update = False

# (str) Logcat filters to use
android.logcat_filters = *:S python:D

# (bool) Copy library instead of making a libpymodules.so
android.copy_libs = 1

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
p4a.archs = arm64-v8a

# (str) python-for-android branch to use
p4a.branch = v2024.01.21

# (str) The format used to package the app for release mode (aab or apk)
android.release_artifact = apk

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
