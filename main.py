"""
Reel Downloader - Native Android Share Target & Auto-Reshare App
================================================================
Architecture:
- Inbound Share Target: Registers for android.intent.action.SEND (text/plain)
- Cold & Warm Intent Handling: Captures launch intent & on_new_intent
- Robust URL Extraction: Strips surrounding text/captions via regex
- Zero-Tap / Prompt Flow: Auto-populates and prompts or auto-starts download
- Auto-Reshare: Automatically invokes outbound Android share sheet upon completion
- Modern Scoped Storage: Uses getExternalCacheDir() + MediaStore / FileProvider content:// URIs
- SSL Verification Fix: Binds certifi CA bundle for yt_dlp on Android
- Cache Cleanup: Built-in storage management to prevent device storage bloat
"""

import os
import sys
import re
import json
import time
import threading

# ---------------------------------------------------------------------------
# 1. SSL Certificate Configuration for Android yt-dlp HTTPS Handshakes
# ---------------------------------------------------------------------------
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    pass

import yt_dlp
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.scrollview import ScrollView

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import (
    MDRaisedButton,
    MDFlatButton,
    MDFillRoundFlatIconButton,
    MDIconButton,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.dialog import MDDialog

try:
    from kivymd.uix.toolbar import MDTopAppBar
except ImportError:
    from kivymd.uix.toolbar import MDToolbar as MDTopAppBar


# ---------------------------------------------------------------------------
# 2. URL Extraction Regex Helper
# ---------------------------------------------------------------------------
URL_REGEX = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+', re.IGNORECASE)

def extract_first_url(text: str) -> str:
    """
    Extracts and sanitizes the first valid HTTP/HTTPS URL from a shared caption or message.
    Strips trailing sentence punctuation (dots, commas, quotes, parentheses, exclamation marks).
    """
    if not text:
        return ""
    match = URL_REGEX.search(text)
    if not match:
        return ""
    url = match.group(0).strip()
    # Strip common sentence punctuation that can stick to the end of URLs
    url = re.sub(r'[\s.,;:!?)\'"]+$', '', url)
    if url.startswith('www.'):
        url = 'https://' + url
    return url


# ---------------------------------------------------------------------------
# 3. Main Application Class
# ---------------------------------------------------------------------------
class ReelDownloaderApp(MDApp):
    dialog = None
    info_dialog = None
    last_downloaded_file = None
    _last_handled_url = None
    auto_download_reshare = False
    is_downloading = False

    def build(self):
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "DeepPurple"
        self.theme_cls.accent_palette = "Teal"

        root_screen = MDScreen()
        main_layout = MDBoxLayout(orientation="vertical")

        # Top Navigation Bar
        self.top_bar = MDTopAppBar(
            title="Reel Downloader",
            elevation=4,
            pos_hint={"top": 1},
        )
        self.top_bar.right_action_items = [
            ["trash-can-outline", lambda x: self.clear_cached_reels()],
            ["help-circle-outline", lambda x: self.show_info_dialog()],
        ]
        main_layout.add_widget(self.top_bar)

        # Scrollable container for responsive UI on all screen sizes
        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(4)
        )
        content_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(16),
            padding=[dp(16), dp(16), dp(16), dp(24)],
            adaptive_height=True
        )

        # -------------------------------------------------------------------
        # Card 1: Share Target Status Banner
        # -------------------------------------------------------------------
        banner_card = MDCard(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(6),
            radius=[dp(12), dp(12), dp(12), dp(12)],
            elevation=2,
            adaptive_height=True
        )
        banner_title = MDLabel(
            text="✨ Native Android Share Target Active",
            font_style="Subtitle2",
            theme_text_color="Primary",
            bold=True,
            adaptive_height=True
        )
        banner_desc = MDLabel(
            text="Tap 'Share' on any post or reel in Facebook, Instagram, TikTok, or YouTube Shorts and select 'Reel Downloader' to process automatically.",
            font_style="Caption",
            theme_text_color="Secondary",
            adaptive_height=True
        )
        banner_card.add_widget(banner_title)
        banner_card.add_widget(banner_desc)
        content_box.add_widget(banner_card)

        # -------------------------------------------------------------------
        # Card 2: Main Download & Share Controls
        # -------------------------------------------------------------------
        download_card = MDCard(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(16),
            radius=[dp(16), dp(16), dp(16), dp(16)],
            elevation=3,
            adaptive_height=True
        )

        self.url_input = MDTextField(
            hint_text="Video / Reel URL",
            helper_text="Paste URL manually or receive via system Share Sheet",
            helper_text_mode="on_focus",
            mode="rectangle",
            icon_right="link-variant",
            size_hint_x=1.0,
            multiline=False
        )
        download_card.add_widget(self.url_input)

        button_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True,
            pos_hint={"center_x": 0.5}
        )

        self.download_button = MDFillRoundFlatIconButton(
            icon="download",
            text="Download Reel",
            on_release=lambda x: self.start_download(),
            size_hint_x=0.5
        )

        self.share_button = MDFillRoundFlatIconButton(
            icon="share-variant",
            text="Share Video",
            on_release=lambda x: self.share_video(),
            disabled=True,
            size_hint_x=0.5
        )

        button_row.add_widget(self.download_button)
        button_row.add_widget(self.share_button)
        download_card.add_widget(button_row)

        # Indeterminate Progress Bar for download feedback
        self.progress_bar = MDProgressBar(
            type="indeterminate",
            size_hint_y=None,
            height=dp(4),
            opacity=0
        )
        download_card.add_widget(self.progress_bar)

        # Status Label
        self.status_label = MDLabel(
            text="Ready. Paste a link or share a reel to this app.",
            halign="center",
            theme_text_color="Secondary",
            font_style="Body2",
            adaptive_height=True
        )
        download_card.add_widget(self.status_label)
        content_box.add_widget(download_card)

        # -------------------------------------------------------------------
        # Card 3: Automation Preferences
        # -------------------------------------------------------------------
        settings_card = MDCard(
            orientation="vertical",
            padding=dp(16),
            spacing=dp(10),
            radius=[dp(14), dp(14), dp(14), dp(14)],
            elevation=2,
            adaptive_height=True
        )

        settings_header = MDLabel(
            text="Automation Settings",
            font_style="Subtitle2",
            theme_text_color="Primary",
            bold=True,
            adaptive_height=True
        )
        settings_card.add_widget(settings_header)

        switch_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(12),
            adaptive_height=True
        )

        switch_text_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(2),
            adaptive_height=True,
            size_hint_x=0.8
        )
        switch_label = MDLabel(
            text="Auto-download & reshare incoming links",
            font_style="Body2",
            theme_text_color="Primary",
            adaptive_height=True
        )
        switch_sublabel = MDLabel(
            text="Zero-tap mode: Instantly downloads shared link and pops outbound share chooser.",
            font_style="Caption",
            theme_text_color="Secondary",
            adaptive_height=True
        )
        switch_text_box.add_widget(switch_label)
        switch_text_box.add_widget(switch_sublabel)

        self.auto_switch = MDSwitch(
            pos_hint={"center_y": 0.5},
            size_hint_x=0.2
        )
        self.auto_switch.bind(active=self.on_auto_switch_toggled)

        switch_row.add_widget(switch_text_box)
        switch_row.add_widget(self.auto_switch)
        settings_card.add_widget(switch_row)
        content_box.add_widget(settings_card)

        # -------------------------------------------------------------------
        # Card 4: Local Cache & Scoped Storage Manager
        # -------------------------------------------------------------------
        storage_card = MDCard(
            orientation="horizontal",
            padding=dp(16),
            spacing=dp(12),
            radius=[dp(14), dp(14), dp(14), dp(14)],
            elevation=2,
            adaptive_height=True
        )

        storage_text_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(2),
            adaptive_height=True,
            size_hint_x=0.65
        )
        storage_title = MDLabel(
            text="Cached Reels Storage",
            font_style="Subtitle2",
            theme_text_color="Primary",
            bold=True,
            adaptive_height=True
        )
        self.storage_label = MDLabel(
            text="Storage: Calculating...",
            font_style="Caption",
            theme_text_color="Secondary",
            adaptive_height=True
        )
        storage_text_box.add_widget(storage_title)
        storage_text_box.add_widget(self.storage_label)

        self.clear_cache_btn = MDRaisedButton(
            text="Clear Cache",
            pos_hint={"center_y": 0.5},
            size_hint_x=0.35,
            on_release=lambda x: self.clear_cached_reels()
        )

        storage_card.add_widget(storage_text_box)
        storage_card.add_widget(self.clear_cache_btn)
        content_box.add_widget(storage_card)

        scroll.add_widget(content_box)
        main_layout.add_widget(scroll)
        root_screen.add_widget(main_layout)

        return root_screen

    # -----------------------------------------------------------------------
    # Lifecycle & Settings Management
    # -----------------------------------------------------------------------
    def on_start(self):
        """Called once Kivy UI is fully initialized."""
        self.load_settings()
        self.update_storage_stats()
        self.register_android_lifecycle()
        # Cold start check: Wait 0.5s for window hierarchy to be ready
        Clock.schedule_once(lambda dt: self.check_initial_cold_start_intent(), 0.5)

    def get_settings_path(self):
        try:
            return os.path.join(self.user_data_dir, "app_settings.json")
        except Exception:
            return "app_settings.json"

    def load_settings(self):
        """Loads persistent user preferences."""
        try:
            path = self.get_settings_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.auto_download_reshare = bool(data.get("auto_download_reshare", False))
                    self.auto_switch.active = self.auto_download_reshare
        except Exception as e:
            print(f"[Settings Load Warning]: {e}")

    def on_auto_switch_toggled(self, instance, value):
        """Persists auto-download setting changes."""
        self.auto_download_reshare = value
        try:
            path = self.get_settings_path()
            folder = os.path.dirname(path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"auto_download_reshare": self.auto_download_reshare}, f)
        except Exception as e:
            print(f"[Settings Save Warning]: {e}")

    # -----------------------------------------------------------------------
    # Inbound Android Share Intent Handling (Cold Start & Warm Resume)
    # -----------------------------------------------------------------------
    def register_android_lifecycle(self):
        """Binds warm resume on_new_intent callback via python-for-android."""
        try:
            from android.activity import bind as android_activity_bind
            android_activity_bind(on_new_intent=self.on_new_intent)
            print("[Android Lifecycle] Registered on_new_intent listener.")
        except ImportError:
            print("[Android Lifecycle] android.activity not available (non-Android environment).")
        except Exception as e:
            print(f"[Android Lifecycle Error]: {e}")

    def on_new_intent(self, intent=None, *args):
        """
        Invoked when the app is already open/backgrounded and receives a shared link
        from Facebook, Instagram, TikTok, etc. (Warm Resume).
        """
        try:
            if intent is None and len(args) > 0:
                intent = args[0]

            if intent is None:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                if PythonActivity.mActivity:
                    intent = PythonActivity.mActivity.getIntent()

            if intent:
                raw_text = self.extract_intent_payload(intent)
                if raw_text:
                    url = extract_first_url(raw_text)
                    if url:
                        # Schedule UI update strictly on Kivy main thread
                        Clock.schedule_once(lambda dt: self.handle_inbound_url(url), 0)
        except Exception as e:
            print(f"[on_new_intent Error]: {e}")

    def check_initial_cold_start_intent(self):
        """
        Checks PythonActivity.mActivity.getIntent() on initial launch (Cold Start).
        """
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            if activity:
                intent = activity.getIntent()
                if intent:
                    raw_text = self.extract_intent_payload(intent)
                    if raw_text:
                        url = extract_first_url(raw_text)
                        if url and url != self._last_handled_url:
                            self.handle_inbound_url(url)
        except Exception as e:
            print(f"[Cold Start Intent Check]: {e}")

    def extract_intent_payload(self, intent):
        """
        Safely extracts string content from an Android Intent (EXTRA_TEXT / EXTRA_SUBJECT / data).
        """
        if not intent:
            return ""
        try:
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')

            action = intent.getAction()
            if action == Intent.ACTION_SEND:
                # 1. Try getStringExtra(Intent.EXTRA_TEXT)
                text = intent.getStringExtra(Intent.EXTRA_TEXT)
                if text:
                    return str(text)

                # 2. Try getCharSequenceExtra(Intent.EXTRA_TEXT) for custom CharSequence types
                seq = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)
                if seq:
                    return str(seq.toString())

                # 3. Fallback to EXTRA_SUBJECT
                subj = intent.getStringExtra(Intent.EXTRA_SUBJECT)
                if subj:
                    return str(subj)

            elif action == Intent.ACTION_VIEW:
                data = intent.getDataString()
                if data:
                    return str(data)

        except Exception as e:
            print(f"[extract_intent_payload Error]: {e}")

        return ""

    def handle_inbound_url(self, url: str):
        """
        Thread-safe handler for incoming shared URLs.
        Populates input and triggers either confirmation dialog or zero-tap auto-download.
        """
        if not url:
            return

        self._last_handled_url = url
        self.url_input.text = url

        if self.auto_download_reshare:
            self.status_label.text = "Share detected: Initiating zero-tap download & reshare..."
            self.start_download(url=url, is_auto_reshare=True)
        else:
            self.show_share_prompt_dialog(url)

    def show_share_prompt_dialog(self, url: str):
        """
        Presents a clear MDDialog confirming whether the user wants to download and reshare.
        """
        self.dismiss_dialog()

        preview = url if len(url) <= 55 else (url[:52] + "...")

        self.dialog = MDDialog(
            title="Shared Reel Detected",
            text=f"Detected incoming link:\n{preview}\n\nDownload and immediately reshare this video?",
            buttons=[
                MDFlatButton(
                    text="CANCEL",
                    theme_text_color="Custom",
                    text_color=self.theme_cls.primary_color,
                    on_release=lambda x: self.dismiss_dialog()
                ),
                MDRaisedButton(
                    text="DOWNLOAD & RESHARE",
                    on_release=lambda x: self.on_dialog_confirm_download(url)
                ),
            ],
        )
        self.dialog.open()

    def on_dialog_confirm_download(self, url: str):
        self.dismiss_dialog()
        self.start_download(url=url, is_auto_reshare=True)

    def dismiss_dialog(self):
        if self.dialog:
            self.dialog.dismiss()
            self.dialog = None

    def show_info_dialog(self):
        """Displays app info and Android Share Target instructions."""
        if self.info_dialog:
            self.info_dialog.dismiss()

        info_text = (
            "How to use Reel Downloader:\n\n"
            "1. In Facebook, Instagram, TikTok, or YouTube, tap 'Share' on any reel.\n"
            "2. Select 'Reel Downloader' from the Android share sheet.\n"
            "3. The app extracts the video URL automatically.\n"
            "4. Enable 'Auto-download & reshare' for a 100% zero-tap workflow.\n\n"
            "Files are saved in your private app cache and won't clutter your gallery unless desired."
        )

        self.info_dialog = MDDialog(
            title="About Reel Downloader",
            text=info_text,
            buttons=[
                MDFlatButton(
                    text="GOT IT",
                    theme_text_color="Custom",
                    text_color=self.theme_cls.primary_color,
                    on_release=lambda x: self.info_dialog.dismiss()
                )
            ]
        )
        self.info_dialog.open()

    # -----------------------------------------------------------------------
    # Scoped Storage & Path Resolution (Android 10 - 15+ Compatible)
    # -----------------------------------------------------------------------
    def get_download_directory(self) -> str:
        """
        Returns a scoped storage directory compliant with Android 10, 11, 12, 13, 14, 15+.
        Uses context.getExternalCacheDir() / context.getExternalFilesDir(), which requires
        NO runtime storage permissions on Android 4.4+ and avoids FileUriExposedException.
        """
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            if activity:
                context = activity.getApplicationContext()

                # App external cache directory: Zero permissions required
                ext_cache = context.getExternalCacheDir()
                if ext_cache:
                    path = os.path.join(ext_cache.getAbsolutePath(), "reels")
                    os.makedirs(path, exist_ok=True)
                    return path

                ext_files = context.getExternalFilesDir(None)
                if ext_files:
                    path = os.path.join(ext_files.getAbsolutePath(), "reels")
                    os.makedirs(path, exist_ok=True)
                    return path
        except Exception as e:
            print(f"[Storage Directory Detection]: {e}")

        # Desktop / Local Testing fallback
        fallback = os.path.join(os.path.expanduser("~"), "Downloads", "ReelDownloader")
        os.makedirs(fallback, exist_ok=True)
        return fallback

    # -----------------------------------------------------------------------
    # Video Download Workflow
    # -----------------------------------------------------------------------
    def start_download(self, instance=None, url=None, is_auto_reshare=False):
        """Initiates background thread download."""
        if self.is_downloading:
            self.status_label.text = "Download already in progress. Please wait."
            return

        target_url = url or self.url_input.text.strip()
        if not target_url:
            self.status_label.text = "Please enter or share a valid URL."
            return

        # Determine if this run should automatically pop the share sheet
        should_auto_reshare = is_auto_reshare or self.auto_download_reshare

        self.is_downloading = True
        self.status_label.text = "Downloading reel... Please wait."
        self.download_button.disabled = True
        self.share_button.disabled = True
        self.progress_bar.opacity = 1
        self.progress_bar.start()

        threading.Thread(
            target=self.download_video,
            args=(target_url, should_auto_reshare),
            daemon=True
        ).start()

    def download_video(self, url: str, should_auto_reshare: bool):
        """
        Executes yt_dlp extraction in background thread.
        Preserves DummyLogger and specific error handling for private groups & login walls.
        """
        class DummyLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): pass

        reels_dir = self.get_download_directory()
        timestamp = int(time.time())
        safe_name = f"Reel_{timestamp}.%(ext)s"
        download_template = os.path.join(reels_dir, safe_name)

        ydl_opts = {
            'outtmpl': download_template,
            'format': 'best[ext=mp4]/best',
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
            'restrictfilenames': True,
            'noplaylist': True,  # Prevents crash if reel resolves to a playlist/gallery
            'logger': DummyLogger(),
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if not info:
                    raise Exception("Video is private or requires login.")

                if 'entries' in info:
                    info = info['entries'][0]

                # Fallback check if redirected to login page lacking video metadata
                if not info.get('ext') and not info.get('title'):
                    raise Exception("Redirected to login. Group or account is private.")

                downloaded_file = ydl.prepare_filename(info)
                if not downloaded_file or not os.path.exists(downloaded_file):
                    # Check directory for most recent video created with this timestamp
                    candidates = [
                        os.path.join(reels_dir, f) for f in os.listdir(reels_dir)
                        if f.startswith(f"Reel_{timestamp}") and f.endswith(('.mp4', '.mkv', '.webm'))
                    ]
                    if candidates:
                        downloaded_file = max(candidates, key=os.path.getmtime)
                    else:
                        raise Exception("Download completed but destination file was not found.")

                downloaded_file = os.path.abspath(downloaded_file)

            # Schedule success on UI thread
            Clock.schedule_once(
                lambda dt: self.on_download_success(downloaded_file, should_auto_reshare), 0
            )

        except Exception as e:
            err_str = str(e).lower()
            if any(w in err_str for w in ("private", "login", "group", "cookies", "restricted")):
                safe_msg = "Error: Video is in a private group/account or requires login."
            else:
                safe_msg = f"Download Error: {str(e)[:45]}"

            Clock.schedule_once(lambda dt: self.on_download_error(safe_msg), 0)

    def on_download_success(self, file_path: str, should_auto_reshare: bool):
        """UI updates on download success + auto-trigger outbound share sheet."""
        self.is_downloading = False
        self.last_downloaded_file = file_path
        file_name = os.path.basename(file_path)
        self.status_label.text = f"Download Complete!\nSaved: {file_name}"
        self.download_button.disabled = False
        self.share_button.disabled = False
        self.progress_bar.stop()
        self.progress_bar.opacity = 0
        self.update_storage_stats()

        if should_auto_reshare:
            self.status_label.text = f"Download Complete!\nLaunching system share sheet..."
            # Trigger outbound share immediately
            Clock.schedule_once(lambda dt: self.share_video(None), 0.3)

    def on_download_error(self, message: str):
        """UI updates on download failure."""
        self.is_downloading = False
        self.status_label.text = message
        self.download_button.disabled = False
        self.share_button.disabled = False
        self.progress_bar.stop()
        self.progress_bar.opacity = 0

    # -----------------------------------------------------------------------
    # Outbound Android Share Sheet (MediaStore / FileProvider / StrictMode)
    # -----------------------------------------------------------------------
    def share_video(self, instance=None):
        """
        Triggers Android system share chooser with the downloaded .mp4 file.
        Provides 3-tier compatibility:
          1. MediaStore Video Content URI
          2. AndroidX / Support FileProvider Content URI
          3. StrictMode VmPolicy fallback
        Always applies FLAG_GRANT_READ_URI_PERMISSION (1).
        """
        if not self.last_downloaded_file or not os.path.exists(self.last_downloaded_file):
            self.status_label.text = "File missing. Please download a reel first."
            return

        try:
            from jnius import autoclass, cast

            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Intent = autoclass('android.content.Intent')
            String = autoclass('java.lang.String')
            File = autoclass('java.io.File')

            currentActivity = cast('android.app.Activity', PythonActivity.mActivity)
            context = currentActivity.getApplicationContext()
            file_obj = File(self.last_downloaded_file)
            file_name = file_obj.getName()
            content_uri = None

            # Strategy 1: Insert into MediaStore Video Content Provider
            try:
                ContentValues = autoclass('android.content.ContentValues')
                MediaStoreVideoMedia = autoclass('android.provider.MediaStore$Video$Media')
                resolver = context.getContentResolver()

                values = ContentValues()
                values.put("_data", self.last_downloaded_file)
                values.put("mime_type", "video/mp4")
                values.put("_display_name", file_name)
                values.put("title", file_name)

                content_uri = resolver.insert(MediaStoreVideoMedia.EXTERNAL_CONTENT_URI, values)
            except Exception as ms_err:
                print(f"[MediaStore Insert Warning]: {ms_err}")
                content_uri = None

            # Strategy 2: FileProvider (Standard for scoped files)
            if not content_uri:
                for provider_class in (
                    'androidx.core.content.FileProvider',
                    'android.support.v4.content.FileProvider'
                ):
                    try:
                        FileProvider = autoclass(provider_class)
                        package_name = context.getPackageName()
                        authority = f"{package_name}.fileprovider"
                        content_uri = FileProvider.getUriForFile(context, authority, file_obj)
                        if content_uri:
                            break
                    except Exception:
                        continue

            # Strategy 3: StrictMode VmPolicy fallback (bypasses FileUriExposedException)
            if not content_uri:
                try:
                    StrictMode = autoclass('android.os.StrictMode')
                    builder = autoclass('android.os.StrictMode$VmPolicy$Builder')()
                    StrictMode.setVmPolicy(builder.build())

                    Uri = autoclass('android.net.Uri')
                    content_uri = Uri.fromFile(file_obj)
                except Exception as sm_err:
                    print(f"[StrictMode Fallback Warning]: {sm_err}")

            if not content_uri:
                self.status_label.text = "Share Error: Could not generate share URI."
                return

            # Construct ACTION_SEND Intent
            share_intent = Intent(Intent.ACTION_SEND)
            share_intent.setType("video/mp4")
            share_intent.putExtra(Intent.EXTRA_STREAM, cast('android.os.Parcelable', content_uri))
            # FLAG_GRANT_READ_URI_PERMISSION = 1
            share_intent.addFlags(1)

            chooser = Intent.createChooser(share_intent, String("Share Reel via..."))
            chooser.addFlags(1)
            currentActivity.startActivity(chooser)
            self.status_label.text = "System share sheet opened!"

        except ImportError:
            self.status_label.text = (
                f"Sharing requires Android.\nFile: {os.path.basename(self.last_downloaded_file)}"
            )
        except Exception as e:
            self.status_label.text = f"Share Error: {str(e)[:45]}"

    # -----------------------------------------------------------------------
    # Storage Cleanup Utility
    # -----------------------------------------------------------------------
    def clear_cached_reels(self, instance=None):
        """Removes downloaded reel files to keep cache size low."""
        reels_dir = self.get_download_directory()
        if not os.path.exists(reels_dir):
            self.status_label.text = "Cache is already empty."
            return

        deleted_count = 0
        freed_bytes = 0
        try:
            for fname in os.listdir(reels_dir):
                if fname.lower().endswith(('.mp4', '.mkv', '.webm', '.part', '.ytdl')):
                    fpath = os.path.join(reels_dir, fname)
                    try:
                        freed_bytes += os.path.getsize(fpath)
                        os.remove(fpath)
                        deleted_count += 1
                    except Exception:
                        pass

            self.last_downloaded_file = None
            self.share_button.disabled = True
            freed_mb = freed_bytes / (1024 * 1024)
            self.status_label.text = f"Cleared {deleted_count} video(s) ({freed_mb:.1f} MB freed)."
            self.update_storage_stats()
        except Exception as e:
            self.status_label.text = f"Cache clean error: {str(e)[:35]}"

    def update_storage_stats(self):
        """Calculates storage used by downloaded reels."""
        try:
            reels_dir = self.get_download_directory()
            if not os.path.exists(reels_dir):
                self.storage_label.text = "Storage: 0 MB (0 reels)"
                return

            total_bytes = 0
            count = 0
            for fname in os.listdir(reels_dir):
                if fname.lower().endswith(('.mp4', '.mkv', '.webm')):
                    fpath = os.path.join(reels_dir, fname)
                    total_bytes += os.path.getsize(fpath)
                    count += 1

            mb = total_bytes / (1024 * 1024)
            self.storage_label.text = f"Cached: {count} reel{'s' if count != 1 else ''} ({mb:.1f} MB)"
        except Exception:
            self.storage_label.text = "Storage: Ready"


if __name__ == "__main__":
    ReelDownloaderApp().run()
