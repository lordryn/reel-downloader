# Reel Downloader - Native Android Share Target APK

A refactored, build-ready KivyMD Android application that acts as a **Native Android Share Target**. It intercepts incoming social media share links (Facebook, Instagram, TikTok, YouTube Shorts, etc.), extracts the video URL automatically, downloads the video using `yt-dlp`, and immediately triggers the Android outbound share chooser to re-share the downloaded `.mp4`.

---

## Key Features

1. **Native Android Share Target Registration (`intent_filters.xml`):**
   - Registered in the Android system share sheet for `android.intent.action.SEND` (`text/plain`).
   - App appears in the "Share to..." app list directly from Facebook, Instagram, TikTok, Twitter/X, and browsers.

2. **Cold Start & Warm Resume Intent Handling (`main.py`):**
   - Captures `PythonActivity.mActivity.getIntent()` on fresh app launch.
   - Binds `android.activity.bind(on_new_intent=self.on_new_intent)` for when the app is already running in background.
   - All intent-triggered UI operations are safely scheduled on Kivy's main thread via `Clock.schedule_once`.

3. **Smart Regex URL Parser:**
   - Social media apps prepend/append promotional text or captions (e.g. *"Check out this reel! https://www.facebook.com/reel/123456789/?s=cl Watch more on FB"*).
   - The regex engine extracts the first valid HTTP/HTTPS URL and strips trailing punctuation (dots, commas, quotes, parentheses) so `yt-dlp` receives a clean URL.

4. **Zero-Tap "Share-to-Reshare" Workflow:**
   - **Interactive Mode:** Shows a clean confirmation dialog (`MDDialog`) asking: *"Download and immediately reshare this video?"* with **[Download & Reshare]** and **[Cancel]**.
   - **Zero-Tap Mode:** Toggle the persistent switch `"Auto-download & reshare incoming links"` to make the entire process automatic. When you tap share from Instagram or Facebook, the app downloads in the background and immediately opens the Android share sheet with the downloaded `.mp4` attached.

5. **Modern Scoped Storage (Android 10 - 15+ Compatible):**
   - Saves files inside the app's external cache directory (`context.getExternalCacheDir()`).
   - Requires **0 runtime storage permissions** on Android 4.4 through Android 15+.
   - Outbound sharing uses a 3-tier URI resolution strategy:
     1. `MediaStore.Video.Media` insertion
     2. `androidx.core.content.FileProvider` (`content://` URI)
     3. `StrictMode.VmPolicy` fallback
   - Always applies `Intent.FLAG_GRANT_READ_URI_PERMISSION (1)` so WhatsApp, Messenger, SMS, and other apps can read the file without `FileUriExposedException`.

6. **SSL Handshake Fix on Android:**
   - Configures `os.environ['SSL_CERT_FILE'] = certifi.where()` and `os.environ['REQUESTS_CA_BUNDLE']` on startup, preventing SSL handshake failures in `yt-dlp`.

7. **Storage Cleanup Utility:**
   - In-app card and top toolbar button to clear downloaded reels, with real-time cache size metrics (e.g. *"Cached: 4 reels (28.4 MB)"*).

---

## File Structure

```
reel_downloader/
├── main.py              # Application source code & Android JNI lifecycle hooks
├── intent_filters.xml   # Custom AndroidManifest intent filter for incoming share target
├── buildozer.spec       # Complete Buildozer configuration for Android API 34 & AndroidX
└── README.md            # Documentation and build/test guide
```

---

## Building the APK with Buildozer

Buildozer requires a Linux environment (Ubuntu 22.04 LTS or WSL2 on Windows).

### 1. Prerequisites (on Ubuntu/WSL2):
```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev
pip3 install --upgrade pip buildozer cython
```

### 2. Build Debug APK:
Navigate to this directory and run:
```bash
buildozer -v android debug
```
The resulting APK will be saved in `bin/reeldownloader-1.0.0-arm64-v8a_armeabi-v7a-debug.apk`.

### 3. Deploy and Run via ADB:
```bash
buildozer android deploy run logcat
```

---

## Testing Inbound Share Intents via ADB

You can test both Cold Start and Warm Resume share intents directly from your terminal using ADB without needing another phone app:

### Test Case 1: Send a Facebook Reel URL (App Running or Closed)
```bash
adb shell am start -a android.intent.action.SEND \
  -t "text/plain" \
  --es android.intent.extra.TEXT "Check out this reel! https://www.facebook.com/reel/123456789/" \
  org.reeldownloader
```

### Test Case 2: Send an Instagram Reel URL with Surrounding Text
```bash
adb shell am start -a android.intent.action.SEND \
  -t "text/plain" \
  --es android.intent.extra.TEXT "Look at this https://www.instagram.com/reel/C3_abcde123/ Amazing video!" \
  org.reeldownloader
```

### Test Case 3: Test Zero-Tap Flow
1. Open the app and toggle **"Auto-download & reshare incoming links"** to ON.
2. Run the ADB command above.
3. The app will immediately begin downloading without any prompt, and automatically display the Android share chooser when finished.
