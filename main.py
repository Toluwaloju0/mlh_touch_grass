"""Offline schedule reminder app (Kivy).

Schedule data is stored as JSON in App.user_data_dir. Model downloads happen only
when the required files are missing. Android packaging still needs microphone,
internet (first-run downloads), foreground-service, and exact-alarm declarations;
see the setup notes shown in the Usage page.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput


DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_SCHEDULE = {"mode": "daily", "daily": [], "weekly": {day: [] for day in DAYS}}
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
VOSK_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"


def classify_agreement(text: str) -> str:
    """Small, transparent offline classifier for simple acknowledgements."""
    normalized = re.sub(r"[^a-z ]", " ", text.lower())
    words = set(normalized.split())
    if not words:
        return "unclear"
    no_phrases = ("not now", "cannot", "cant", "do not", "dont", "wont", "will not", "skip", "later")
    if any(p in normalized for p in no_phrases) or words.intersection({"no", "nope", "decline", "stop"}):
        return "declined"
    yes_phrases = ("i will", "i agree", "i accept", "i can do", "i am doing", "i ll")
    if any(p in normalized for p in yes_phrases) or words.intersection({"yes", "yeah", "yep", "sure", "okay", "ok", "agreed", "accepted", "affirmative"}):
        return "agreed"
    return "unclear"


class ModelManager:
    """Downloads the Kokoro voice model and compact Vosk English model once."""
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.kokoro_model = root / "kokoro-v1.0.onnx"
        self.kokoro_voices = root / "voices-v1.0.bin"
        self.vosk_dir = root / "vosk-model-small-en-us-0.15"

    @staticmethod
    def _download(url: str, target: Path, progress=None):
        temp = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "ScheduleReminder/1.0"})
        with urllib.request.urlopen(request, timeout=90) as response, open(temp, "wb") as output:
            length = int(response.headers.get("Content-Length", "0"))
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
                if progress and length:
                    progress(total / length)
        temp.replace(target)

    def ensure(self, progress=None):
        if not self.kokoro_model.exists():
            self._download(KOKORO_MODEL_URL, self.kokoro_model, progress)
        if not self.kokoro_voices.exists():
            self._download(KOKORO_VOICES_URL, self.kokoro_voices, progress)
        if not self.vosk_dir.exists():
            archive = self.root / "vosk-model.zip"
            self._download(VOSK_MODEL_URL, archive, progress)
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(self.root)
            archive.unlink(missing_ok=True)


class OfflineVoice:
    def __init__(self, models: ModelManager):
        self.models = models
        self.tts = None

    def speak(self, text: str):
        try:
            if self.tts is None:
                from kokoro_onnx import Kokoro
                self.tts = Kokoro(str(self.models.kokoro_model), str(self.models.kokoro_voices))
            import sounddevice as sd
            samples, sample_rate = self.tts.create(text, voice="af_heart", speed=1.0, lang="en-us")
            sd.play(samples, sample_rate)
            sd.wait()
            return True
        except Exception as exc:
            print("Offline Kokoro playback unavailable:", exc)
            return False


class OfflineListening:
    """Vosk + local microphone backend, used when packaged audio dependencies exist."""
    def __init__(self, models: ModelManager):
        self.models = models

    def listen_for_one_minute(self, on_result):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer
            model = Model(str(self.models.vosk_dir))
            recognizer = KaldiRecognizer(model, 16000)
            start = time.monotonic()
            while time.monotonic() - start < 60:
                audio = sd.rec(8000, samplerate=16000, channels=1, dtype="int16")
                sd.wait()
                if recognizer.AcceptWaveform(audio.tobytes()):
                    result = json.loads(recognizer.Result()).get("text", "")
                    if result:
                        on_result(result)
                        if classify_agreement(result) != "unclear":
                            return
        except Exception as exc:
            message = "Listening needs Vosk and a microphone backend in the Android build: " + str(exc)
            Clock.schedule_once(lambda _dt, detail=message: App.get_running_app().set_status(detail))


class ScheduleReminderApp(App):
    title = "Voice Schedule"

    def build(self):
        self.data_dir = Path(self.user_data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.schedule_path = self.data_dir / "schedule.json"
        self.models = ModelManager(self.data_dir / "models")
        self.voice = OfflineVoice(self.models)
        self.listener = OfflineListening(self.models)
        self.schedule = self.load_schedule()
        self.fired = set()
        self.root_box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        self.content = BoxLayout(orientation="vertical", spacing=dp(8))
        self.root_box.add_widget(self.content)
        nav = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(6))
        for name, action in (("Home", self.show_home), ("Schedule", self.show_schedule), ("Usage", self.show_usage)):
            nav.add_widget(Button(text=name, on_release=lambda _btn, fn=action: fn()))
        self.root_box.add_widget(nav)
        self.show_home()
        Clock.schedule_interval(self.check_schedule, 10)
        # Best-effort process-local background thread. Android can stop this process;
        # production alarms require a native receiver/foreground service in the APK.
        self.background_thread = threading.Thread(target=self.background_watch, daemon=True)
        self.background_thread.start()
        Clock.schedule_once(self.start_model_download, 0.5)
        return self.root_box

    def load_schedule(self):
        try:
            with open(self.schedule_path, encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("mode", "daily")
            data.setdefault("daily", [])
            data.setdefault("weekly", {})
            for day in DAYS:
                data["weekly"].setdefault(day, [])
            return data
        except (OSError, ValueError):
            return json.loads(json.dumps(DEFAULT_SCHEDULE))

    def save_schedule(self):
        temp = self.schedule_path.with_suffix(".json.tmp")
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(self.schedule, f, indent=2, ensure_ascii=False)
        temp.replace(self.schedule_path)

    def clear_content(self):
        self.content.clear_widgets()

    def set_status(self, text):
        if hasattr(self, "status_label"):
            self.status_label.text = text

    def show_home(self):
        self.clear_content()
        self.content.add_widget(Label(text="VOICE SCHEDULE", font_size="24sp", size_hint_y=None, height=dp(48)))
        self.status_label = Label(text="Your reminders are stored on this device.", halign="left", valign="top")
        self.status_label.bind(size=lambda w, size: setattr(w, "text_size", size))
        self.content.add_widget(self.status_label)
        self.content.add_widget(Label(text=self.describe_schedules(), halign="left", valign="top"))
        self.content.add_widget(Button(text="Open schedule settings", size_hint_y=None, height=dp(48), on_release=lambda *_: self.show_schedule()))

    def describe_schedules(self):
        lines = ["Mode: same schedule every day" if self.schedule["mode"] == "daily" else "Mode: individual schedules by day"]
        source = self.schedule["daily"] if self.schedule["mode"] == "daily" else [entry for day in DAYS for entry in self.schedule["weekly"].get(day, [])]
        if not source:
            lines.append("No reminders saved yet.")
        else:
            lines.extend("• {} — {}".format(item["time"], item["activity"]) for item in source[:12])
        return "\n".join(lines)

    def show_schedule(self):
        self.clear_content()
        self.content.add_widget(Label(text="SCHEDULE", font_size="22sp", size_hint_y=None, height=dp(44)))
        mode = Spinner(text="Same schedule every day" if self.schedule["mode"] == "daily" else "Individual schedule by day",
                       values=("Same schedule every day", "Individual schedule by day"), size_hint_y=None, height=dp(46))
        def change_mode(_spinner, value):
            self.schedule["mode"] = "daily" if value.startswith("Same") else "weekly"
            self.save_schedule()
            self.show_schedule()
        mode.bind(text=change_mode)
        self.content.add_widget(mode)
        self.day_spinner = Spinner(text="Monday", values=DAYS, size_hint_y=None, height=dp(44))
        if self.schedule["mode"] == "weekly":
            self.day_spinner.bind(text=lambda *_: self.render_schedule_list())
            self.content.add_widget(self.day_spinner)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.time_input = TextInput(hint_text="Time (HH:MM)", multiline=False, input_filter=None)
        self.activity_input = TextInput(hint_text="Activity / reminder", multiline=False)
        row.add_widget(self.time_input)
        row.add_widget(self.activity_input)
        self.content.add_widget(row)
        self.content.add_widget(Button(text="Add reminder", size_hint_y=None, height=dp(46), on_release=self.add_reminder))
        self.listing = BoxLayout(orientation="vertical", spacing=dp(4))
        self.content.add_widget(self.listing)
        self.render_schedule_list()
        self.content.add_widget(Label(text="Use 24-hour time, for example 08:30.", size_hint_y=None, height=dp(28)))

    def add_reminder(self, *_):
        value = self.time_input.text.strip()
        activity = self.activity_input.text.strip()
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            self.message("Enter a valid time in HH:MM format.")
            return
        if not activity:
            self.message("Add an activity description.")
            return
        entry = {"time": value, "activity": activity}
        items = self.schedule["daily"] if self.schedule["mode"] == "daily" else self.schedule["weekly"][self.day_spinner.text]
        if any(item["time"] == value for item in items):
            self.message("There is already a reminder at that time in this schedule.")
            return
        items.append(entry)
        items.sort(key=lambda x: x["time"])
        self.save_schedule()
        self.time_input.text = ""
        self.activity_input.text = ""
        self.render_schedule_list()

    def render_schedule_list(self):
        self.listing.clear_widgets()
        items = self.schedule["daily"] if self.schedule["mode"] == "daily" else self.schedule["weekly"][self.day_spinner.text]
        for index, item in enumerate(items):
            row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(4))
            row.add_widget(Label(text=f"{item['time']}  {item['activity']}", halign="left"))
            row.add_widget(Button(text="Remove", size_hint_x=None, width=dp(78), on_release=lambda _btn, n=index: self.remove_reminder(n)))
            self.listing.add_widget(row)

    def remove_reminder(self, index):
        items = self.schedule["daily"] if self.schedule["mode"] == "daily" else self.schedule["weekly"][self.day_spinner.text]
        if index < len(items):
            items.pop(index)
        self.save_schedule()
        self.render_schedule_list()

    def show_usage(self):
        self.clear_content()
        self.content.add_widget(Label(text="HOW TO USE", font_size="22sp", size_hint_y=None, height=dp(44)))
        usage = ("1. Open Schedule and choose a schedule mode.\n\n"
                 "2. Add a reminder using 24-hour time and a short activity description. Daily mode repeats the list every day; individual mode has a separate list for each weekday.\n\n"
                 "3. Keep Voice Schedule running for its reminder checker. At a scheduled minute it speaks the activity and listens for up to one minute. Simple yes/no statements are classified locally.\n\n"
                 "Models are downloaded once on first launch (Kokoro ONNX and Vosk English); after that, inference is offline. The initial download is large and needs internet.\n\n"
                 "Android background reliability needs APK setup beyond this Python file: microphone and notification permissions, an exact-alarm receiver, reboot rescheduling, and a foreground service. Android may stop a plain Kivy process when it is backgrounded or force-stopped. Package audio/ONNX dependencies for the device ABI too.")
        label = Label(text=usage, halign="left", valign="top")
        label.bind(size=lambda w, size: setattr(w, "text_size", (size[0], None)))
        self.content.add_widget(label)

    def message(self, text):
        Popup(title="Voice Schedule", content=Label(text=text), size_hint=(.85, .3)).open()

    def start_model_download(self, _dt):
        if self.models.kokoro_model.exists() and self.models.kokoro_voices.exists() and self.models.vosk_dir.exists():
            return
        self.set_status("First launch: downloading offline voice and speech models…")
        def work():
            try:
                self.models.ensure()
                Clock.schedule_once(lambda _dt: self.set_status("Offline voice and speech models are ready."))
            except Exception as exc:
                error = str(exc)
                Clock.schedule_once(lambda _dt, message=error: self.set_status("Model download failed. Connect to internet and restart: " + message))
        threading.Thread(target=work, daemon=True).start()

    def background_watch(self):
        while True:
            try:
                self._check_due(datetime.now())
            except Exception as exc:
                print("Reminder check error:", exc)
            time.sleep(10)

    def check_schedule(self, _dt):
        self._check_due(datetime.now())

    def _check_due(self, now):
        today_key = now.strftime("%Y-%m-%d")
        minute = now.strftime("%H:%M")
        items = self.schedule["daily"] if self.schedule["mode"] == "daily" else self.schedule["weekly"].get(DAYS[now.weekday()], [])
        for item in items:
            key = f"{today_key}:{item['time']}:{item['activity']}"
            if item["time"] == minute and key not in self.fired:
                self.fired.add(key)
                activity = item["activity"]
                Clock.schedule_once(lambda _dt, task=activity: self.start_reminder(task))

    def start_reminder(self, activity):
        self.set_status("Reminder: " + activity + " — listening for your response for up to 1 minute.")
        threading.Thread(target=self.voice.speak, args=("It is time to " + activity,), daemon=True).start()
        threading.Thread(target=self.listener.listen_for_one_minute,
                         args=(lambda phrase: self.handle_response(phrase),), daemon=True).start()

    def handle_response(self, phrase):
        result = classify_agreement(phrase)
        Clock.schedule_once(lambda _dt: self.set_status(f'Heard: “{phrase}” — {result}.'))


if __name__ == "__main__":
    ScheduleReminderApp().run()
