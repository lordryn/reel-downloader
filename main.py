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
# 1. SSL Certificate Configuration & Global Crash Interceptor
# ---------------------------------------------------------------------------
_CRASH_INFO = None

try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except ImportError:
    pass

# Lazy import yt_dlp so startup is instant and doesn't crash on splash screen
_yt_dlp_module = None

def get_yt_dlp():
    global _yt_dlp_module
    if _yt_dlp_module is None:
        import yt_dlp
        _yt_dlp_module = yt_dlp
    return _yt_dlp_module
try:
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
except Exception as e:
    import traceback
    _CRASH_INFO = traceback.format_exc()
    MDApp = object


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
    _last_shared_file = None
    _last_shared_uri = None
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
            helper_text="Tap 'Paste' or share from any app",
            helper_text_mode="on_focus",
            mode="rectangle",
            icon_right="link-variant",
            size_hint_x=1.0,
            multiline=False,
            use_bubble=True,
            use_handles=True,
        )
        download_card.add_widget(self.url_input)

        button_row = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            adaptive_height=True,
            pos_hint={"center_x": 0.5}
        )

        self.paste_button = MDFillRoundFlatIconButton(
            icon="content-paste",
            text="Paste",
            on_release=lambda x: self.paste_from_clipboard(),
            size_hint_x=0.3
        )

        self.download_button = MDFillRoundFlatIconButton(
            icon="download",
            text="Download",
            on_release=lambda x: self.start_download(),
            size_hint_x=0.4
        )

        self.share_button = MDFillRoundFlatIconButton(
            icon="share-variant",
            text="Share",
            on_release=lambda x: self.share_video(),
            disabled=True,
            size_hint_x=0.3
        )

        button_row.add_widget(self.paste_button)
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
    # Clipboard Helper (Native Android JNI + Kivy Core)
    # -----------------------------------------------------------------------
    def paste_from_clipboard(self, instance=None):
        """Reads text from system clipboard and populates the URL input."""
        try:
            text = self.get_clipboard_text()
            if text:
                url = extract_first_url(text)
                self.url_input.text = url if url else text.strip()
                self.status_label.text = "URL pasted from clipboard!"
            else:
                self.status_label.text = "Clipboard is empty or contains no text."
        except Exception as e:
            self.status_label.text = f"Clipboard Error: {e}"

    def get_clipboard_text(self) -> str:
        """Robust multi-tier clipboard reader for Android and desktop."""
        # Tier 1: Try Android Context CLIPBOARD_SERVICE via PyJNIus
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            activity = PythonActivity.mActivity
            if activity:
                clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE)
                if clipboard and clipboard.hasPrimaryClip():
                    clip_data = clipboard.getPrimaryClip()
                    if clip_data.getItemCount() > 0:
                        item = clip_data.getItemAt(0)
                        text = item.getText()
                        if text:
                            return str(text)
        except Exception as e:
            print(f"[Android Clipboard Warning]: {e}")

        # Tier 2: Try Kivy Core Clipboard
        try:
            from kivy.core.clipboard import Clipboard
            val = Clipboard.paste()
            if val:
                return str(val)
        except Exception as e:
            print(f"[Kivy Clipboard Warning]: {e}")

        return ""

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
        self.last_downloaded_file = None
        self._last_shared_file = None
        self._last_shared_uri = None
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
            ydl_module = get_yt_dlp()
            with ydl_module.YoutubeDL(ydl_opts) as ydl:
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
    # Outbound Android Share Sheet (MediaStore Video Stream Publisher)
    # -----------------------------------------------------------------------
    def share_video(self, instance=None):
        """
        Publishes the downloaded reel to Android's public MediaStore collection
        (Movies/ReelDownloader) via ContentResolver.openOutputStream, then triggers
        the Android system share sheet with a valid content:// URI.

        This guarantees full compatibility across Android 8 through 15+, allowing
        external apps (WhatsApp, Discord, Messenger, QuickShare, etc.) to read
        the video without hitting scoped storage EACCES permission errors.
        """
        if not self.last_downloaded_file or not os.path.exists(self.last_downloaded_file):
            self.status_label.text = "File missing. Please download a reel first."
            return

        self.status_label.text = "Preparing reel for sharing..."
        self.share_button.disabled = True

        threading.Thread(
            target=self._publish_and_share_thread,
            daemon=True
        ).start()

    def _publish_and_share_thread(self):
        """Worker thread that copies video into MediaStore and pops the share sheet."""
        try:
            content_uri = self._get_or_create_mediastore_uri()
            if content_uri:
                Clock.schedule_once(lambda dt: self._launch_share_intent(content_uri), 0)
            else:
                Clock.schedule_once(
                    lambda dt: self._on_share_failed("Could not obtain shareable content URI."), 0
                )
        except Exception as e:
            err_msg = str(e)
            print(f"[_publish_and_share_thread Error]: {err_msg}")
            Clock.schedule_once(
                lambda dt: self._on_share_failed(f"Share Error: {err_msg[:45]}"), 0
            )

    def _get_or_create_mediastore_uri(self):
        """
        Inserts video metadata into Android MediaStore, streams video bytes via
        resolver.openOutputStream, and returns the resulting content:// URI.
        Caches the URI so repeated shares of the same download are instantaneous.
        """
        # Return cached content URI if already published for this file
        if (
            self._last_shared_file == self.last_downloaded_file
            and self._last_shared_uri is not None
        ):
            return self._last_shared_uri

        try:
            from jnius import autoclass, cast

            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            if not activity:
                raise Exception("Android Activity not available")

            context = activity.getApplicationContext()
            resolver = context.getContentResolver()
            File = autoclass('java.io.File')
            file_obj = File(self.last_downloaded_file)
            file_name = file_obj.getName()

            ContentValues = autoclass('android.content.ContentValues')
            MediaStoreVideoMedia = autoclass('android.provider.MediaStore$Video$Media')
            MediaStoreMediaColumns = autoclass('android.provider.MediaStore$MediaColumns')
            BuildVERSION = autoclass('android.os.Build$VERSION')
            String = autoclass('java.lang.String')
            Integer = autoclass('java.lang.Integer')
            Environment = autoclass('android.os.Environment')

            values = ContentValues()
            values.put(MediaStoreMediaColumns.DISPLAY_NAME, String(file_name))
            values.put(MediaStoreMediaColumns.MIME_TYPE, String("video/mp4"))
            values.put(MediaStoreMediaColumns.TITLE, String(file_name))

            # Android 10+ (API 29+): Scoped storage relative path & pending state
            if BuildVERSION.SDK_INT >= 29:
                rel_path = Environment.DIRECTORY_MOVIES + "/ReelDownloader"
                values.put(MediaStoreMediaColumns.RELATIVE_PATH, String(rel_path))
                values.put(MediaStoreMediaColumns.IS_PENDING, Integer(1))

            content_uri = resolver.insert(MediaStoreVideoMedia.EXTERNAL_CONTENT_URI, values)
            if not content_uri:
                raise Exception("Failed to insert MediaStore record")

            # Stream video file bytes into MediaStore OutputStream
            out_stream = resolver.openOutputStream(content_uri)
            if not out_stream:
                raise Exception("Failed to open MediaStore output stream")

            try:
                with open(self.last_downloaded_file, 'rb') as src_file:
                    while True:
                        chunk = src_file.read(65536)
                        if not chunk:
                            break
                        out_stream.write(chunk)
                out_stream.flush()
            finally:
                out_stream.close()

            # Android 10+: Mark file ready (IS_PENDING = 0)
            if BuildVERSION.SDK_INT >= 29:
                finish_values = ContentValues()
                finish_values.put(MediaStoreMediaColumns.IS_PENDING, Integer(0))
                resolver.update(content_uri, finish_values, None, None)

            self._last_shared_file = self.last_downloaded_file
            self._last_shared_uri = content_uri
            return content_uri

        except ImportError:
            # Running on desktop / non-Android
            print("[Share]: PyJNIus not available (desktop environment)")
            return None
        except Exception as e:
            print(f"[MediaStore Publisher Error]: {e}")
            # StrictMode fallback
            try:
                from jnius import autoclass
                StrictMode = autoclass('android.os.StrictMode')
                builder = autoclass('android.os.StrictMode$VmPolicy$Builder')()
                StrictMode.setVmPolicy(builder.build())
                Uri = autoclass('android.net.Uri')
                File = autoclass('java.io.File')
                return Uri.fromFile(File(self.last_downloaded_file))
            except Exception as sm_err:
                print(f"[StrictMode Fallback Error]: {sm_err}")
                return None

    def _launch_share_intent(self, content_uri):
        """Constructs and fires the ACTION_SEND Intent with read permissions."""
        try:
            from jnius import autoclass, cast

            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            currentActivity = cast('android.app.Activity', PythonActivity.mActivity)
            Intent = autoclass('android.content.Intent')
            String = autoclass('java.lang.String')
            ClipData = autoclass('android.content.ClipData')

            share_intent = Intent(Intent.ACTION_SEND)
            share_intent.setType("video/mp4")
            share_intent.putExtra(Intent.EXTRA_STREAM, cast('android.os.Parcelable', content_uri))
            share_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

            # Explicit ClipData ensures permission flags propagate to target app
            clip_data = ClipData.newRawUri(String("Reel Video"), content_uri)
            share_intent.setClipData(clip_data)

            chooser = Intent.createChooser(share_intent, String("Share Reel via..."))
            chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

            currentActivity.startActivity(chooser)
            self.status_label.text = "System share sheet opened!"
        except ImportError:
            self.status_label.text = (
                f"Sharing requires Android.\nFile: {os.path.basename(self.last_downloaded_file)}"
            )
        except Exception as e:
            self._on_share_failed(f"Launch Error: {str(e)[:45]}")
        finally:
            self.share_button.disabled = False

    def _on_share_failed(self, error_message: str):
        self.status_label.text = error_message
        self.share_button.disabled = False

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
            self._last_shared_file = None
            self._last_shared_uri = None
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
    if _CRASH_INFO:
        from kivy.app import App
        from kivy.uix.label import Label
        from kivy.uix.scrollview import ScrollView

        class ErrorFallbackApp(App):
            def build(self):
                scroll = ScrollView()
                lbl = Label(
                    text=f"Reel Downloader Startup Error:\n\n{_CRASH_INFO}",
                    color=(1, 0.3, 0.3, 1),
                    font_size="13sp",
                    size_hint_y=None,
                    padding=(20, 20)
                )
                lbl.bind(texture_size=lbl.setter('size'))
                scroll.add_widget(lbl)
                return scroll

        ErrorFallbackApp().run()
    else:
        ReelDownloaderApp().run()
