from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from bg3vm.core.config import PROJECTS_DIR, Settings
from bg3vm.core.logs import LOG_FILE
from bg3vm.core.pipeline import STAGES
from bg3vm.core.project import Project
from bg3vm.core.voices import list_voices
from bg3vm.engines import ENGINES
from bg3vm.audio.vgmstream import find_vgmstream, install_vgmstream
from bg3vm.game.steam import GameInstall, find_bg3, search_appdata
from bg3vm.audio.pitch import median_f0
from bg3vm.core.audiocache import decode_to_cache
from bg3vm.game.voicemeta import index_voice_paks, lines_for_speaker, list_speakers, sample_lines
from bg3vm.core.background import BackgroundInstall
from bg3vm.gui.install_dialog import InstallWindow
from bg3vm.gui.player import Player
from bg3vm.gui.runner import JobRunner
from bg3vm.gui.workers import FuncThread


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(10)
    return f, lay


def heading(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    h = QLabel(text)
    h.setObjectName("h1")
    lay.addWidget(h)
    if sub:
        s = QLabel(sub)
        s.setObjectName("muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


def page_shell() -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    w.setObjectName("page")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(32, 28, 32, 28)
    lay.setSpacing(16)
    return w, lay


class DropLabel(QLabel):
    def __init__(self, on_paths):
        super().__init__("Drop your voice recordings (files or folders) here\nor click to browse")
        self.setObjectName("drop")
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self._on_paths = on_paths

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._on_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def mousePressEvent(self, e):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose recordings", "", "Audio (*.wav *.mp3 *.flac *.ogg *.m4a *.opus)")
        if files:
            self._on_paths(files)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BG3 Voice Forge")
        self.resize(1100, 720)
        self.settings = Settings.load()
        self.project = Project(name="", root=PROJECTS_DIR / "_none")
        self._stage_text = ""
        self.installer: BackgroundInstall | None = None
        self.install_window: InstallWindow | None = None
        self._voice_lines: list = []
        self._sample_idx: dict[str, int] = {}
        self.player = Player()
        self.runner = JobRunner()
        self.runner.progress.connect(self._on_progress)
        self.runner.stage.connect(self._on_stage)
        self.runner.failed.connect(self._on_failed)
        self.runner.done.connect(self._on_done)
        self.runner.cancelled.connect(lambda: self._finish("Cancelled. Progress is saved; run again to resume."))

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.stack = QStackedWidget()
        for title, builder in [("Setup", self._setup_page), ("Your Voice", self._voice_page), ("Make Mod", self._run_page)]:
            self.nav.addItem(title)
            self.stack.addWidget(builder())
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.engine_box.currentIndexChanged.connect(lambda _: self._refresh_voices())
        self._refresh_voices()
        self.nav.setCurrentRow(0)
        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._autodetect()
        QTimer.singleShot(300, self.ensure_vgmstream)

    # ---- tools
    def ensure_vgmstream(self, ask: bool = True) -> bool:
        """Offer to install vgmstream-cli when missing. Returns True if available afterwards."""
        if find_vgmstream():
            return True
        if ask:
            btn = QMessageBox.question(
                self, "vgmstream needed",
                "vgmstream-cli was not found. It is needed to read the game's .wem audio.\n\n"
                "Download and install it now into the app's own folder (about 8 MB)?")
            if btn != QMessageBox.Yes:
                return False
        dlg = QProgressDialog("Installing vgmstream…", None, 0, 100, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        self._vgm_thread = t = FuncThread(install_vgmstream)
        t.progress.connect(lambda f, m: (dlg.setValue(int(f * 100)), dlg.setLabelText(m)))
        outcome: dict = {}
        loop = QEventLoop()
        t.result.connect(lambda _: (outcome.update(ok=True), loop.quit()))
        t.failed.connect(lambda m: (outcome.update(err=m), loop.quit()))
        t.start()
        loop.exec()  # returns when the worker reports a result or an error
        t.wait()
        dlg.close()
        if outcome.get("ok"):
            self.log.appendPlainText("vgmstream installed.")
            return True
        QMessageBox.warning(self, "vgmstream", f"Install failed: {outcome.get('err', 'unknown error')}\n"
                            "You can install it manually and make sure `vgmstream-cli` is on PATH.")
        return False

    def _scan(self, _checked=False, then=None):
        g = self._current_game()
        if not g:
            QMessageBox.information(self, "Scan", "Choose the Baldur's Gate 3 folder first.")
            return
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")

        def work(_progress):
            paks = g.voice_paks()
            if not paks:
                raise RuntimeError("No Voice*.pak found under Data/Localization.")
            self._voice_lines = index_voice_paks(paks)
            return list_speakers(self._voice_lines)

        self._scan_thread = t = FuncThread(work)
        t.result.connect(lambda sp: (self._scan_done(sp), then() if then else None))
        t.failed.connect(lambda m: (QMessageBox.warning(self, "Scan failed", m), self._scan_reset()))
        t.start()

    def _selected_speaker(self) -> str:
        return (self.speaker_box.currentData()
                or self.speaker_box.currentText().split(" — ")[0].strip())

    def _sample(self, _checked=False, scanned=False):
        """Extract (cached) and play a mid-length line from the selected character."""
        if self.player.playing:
            self.player.stop()
            self.play_btn.setText("▶ Sample")
            return
        speaker = self._selected_speaker()
        if not speaker:
            self.sample_lbl.setText("Pick or type a character first.")
            return
        if not self._voice_lines:
            if scanned:
                return
            self.sample_lbl.setText("Scanning the game first…")
            self._scan(then=lambda: self._sample(scanned=True))
            return
        lines = lines_for_speaker(self._voice_lines, speaker)
        if not lines:
            self.sample_lbl.setText(f"No lines found for {speaker!r}.")
            return
        picks = sample_lines(lines)
        i = self._sample_idx.get(speaker, -1) + 1
        self._sample_idx[speaker] = i
        ln = picks[i % len(picks)]
        self.play_btn.setEnabled(False)
        self.sample_lbl.setText("Extracting sample…")

        def work(_progress):
            wav = decode_to_cache(ln.pak, ln.entry, ln.key)
            return wav, median_f0([wav])

        self._sample_thread = t = FuncThread(work)
        t.result.connect(self._sample_ready)
        t.failed.connect(lambda m: (self.sample_lbl.setText(f"Sample failed: {m}"), self.play_btn.setEnabled(True)))
        t.start()

    def _sample_ready(self, result):
        wav, f0 = result
        self.play_btn.setEnabled(True)
        hint = ("" if not f0 else
                f"pitch ≈ {f0:.0f} Hz — sounds {'higher (typically a female voice)' if f0 > 185 else 'lower (typically a male voice)'}")
        self.sample_lbl.setText(f"Playing a sample ({hint}). Press ■ to stop; press ▶ again for another line."
                                if hint else "Playing a sample.")
        try:
            self.player.play(wav)
            self.play_btn.setText("■ Stop")
            QTimer.singleShot(300, self._poll_player)
        except RuntimeError as e:
            self.sample_lbl.setText(str(e))

    def _poll_player(self):
        if self.player.playing:
            QTimer.singleShot(300, self._poll_player)
        else:
            self.play_btn.setText("▶ Sample")

    def _scan_reset(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan game for characters")

    def _scan_done(self, speakers):
        prev = self._selected_speaker().lower()
        self.speaker_box.clear()
        for sp in speakers:
            self.speaker_box.addItem(f"{sp.name} — {sp.lines} lines", sp.id)
        for i, sp in enumerate(speakers):  # keep whatever the user had picked or typed
            if prev and prev in (sp.id, sp.name.lower()):
                self.speaker_box.setCurrentIndex(i)
        self._scan_reset()

    def _current_game(self) -> GameInstall | None:
        text = self.game_edit.text().strip()
        if not text:
            return None
        return GameInstall.from_game_dir(Path(text))

    # ---- pages
    def _setup_page(self) -> QWidget:
        w, lay = page_shell()
        lay.addWidget(heading("Setup", "Point the app at your game and pick the character to replace."))
        c, cl = card()
        self.game_edit = QLineEdit(self.settings.game_dir)
        self.game_edit.setPlaceholderText("Baldur's Gate 3 install folder")
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self._pick_dir(self.game_edit))
        row = QHBoxLayout()
        row.addWidget(self.game_edit, 1)
        row.addWidget(b)
        cl.addWidget(QLabel("Game folder"))
        cl.addLayout(row)
        self.appdata_edit = QLineEdit(self.settings.bg3_appdata)
        self.appdata_edit.setPlaceholderText("BG3 user folder (auto-detected; contains Mods/ and PlayerProfiles/)")
        ab = QPushButton("Browse…")
        ab.clicked.connect(lambda: self._pick_dir(self.appdata_edit))
        self.find_btn = QPushButton("Find…")
        self.find_btn.setToolTip("Search your home folder for the game's user data (looks for modsettings.lsx)")
        self.find_btn.clicked.connect(self._find_appdata)
        arow = QHBoxLayout()
        arow.addWidget(self.appdata_edit, 1)
        arow.addWidget(self.find_btn)
        arow.addWidget(ab)
        cl.addWidget(QLabel("Mod install folder (the game's user data: contains Mods/ and PlayerProfiles/)"))
        cl.addLayout(arow)
        self.detect_lbl = QLabel("")
        self.detect_lbl.setObjectName("muted")
        cl.addWidget(self.detect_lbl)
        self.speaker_box = QComboBox()
        self.speaker_box.setEditable(True)
        self.speaker_box.lineEdit().setPlaceholderText("Scan the game, or type a name (e.g. Astarion)")
        self.scan_btn = QPushButton("Scan game for characters")
        self.scan_btn.clicked.connect(self._scan)
        self.play_btn = QPushButton("▶ Sample")
        self.play_btn.setToolTip("Extract and play a line from the selected character (click again for another line)")
        self.play_btn.clicked.connect(self._sample)
        r2 = QHBoxLayout()
        r2.addWidget(self.speaker_box, 1)
        r2.addWidget(self.play_btn)
        r2.addWidget(self.scan_btn)
        cl.addWidget(QLabel("Character to replace"))
        cl.addLayout(r2)
        self.sample_lbl = QLabel("")
        self.sample_lbl.setObjectName("muted")
        self.sample_lbl.setWordWrap(True)
        cl.addWidget(self.sample_lbl)
        self.engine_box = QComboBox()
        for k, cls in ENGINES.items():
            self.engine_box.addItem(cls.label, k)
        self.engine_box.setCurrentIndex(self.engine_box.findData(self.settings.engine))
        cl.addWidget(QLabel("Voice engine"))
        cl.addWidget(self.engine_box)
        self.preset_box = QComboBox()
        for label, key in [("Fast (quick test, lower quality)", "fast"), ("Good (recommended)", "good"),
                           ("Best (slowest)", "best")]:
            self.preset_box.addItem(label, key)
        self.preset_box.setCurrentIndex(1)
        cl.addWidget(QLabel("Training quality"))
        cl.addWidget(self.preset_box)
        self.auto_pitch = QCheckBox("Match pitch automatically (recommended)")
        self.auto_pitch.setChecked(True)
        self.pitch_spin = QSpinBox()
        self.pitch_spin.setRange(-24, 24)
        self.pitch_spin.setSuffix(" semitones")
        self.pitch_spin.setEnabled(False)
        self.auto_pitch.toggled.connect(lambda on: self.pitch_spin.setEnabled(not on))
        cl.addWidget(self.auto_pitch)
        cl.addWidget(QLabel("Manual pitch shift (e.g. +12 for a male original voice → female voice)"))
        cl.addWidget(self.pitch_spin)
        note = QLabel("Only use recordings of your own voice, or of someone who has given you permission. "
                      "The model is trained on your recordings alone; game audio is only used as input to convert.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        cl.addWidget(note)
        self.maxlines = QSpinBox()
        self.maxlines.setRange(0, 100000)
        self.maxlines.setSpecialValueText("All lines")
        cl.addWidget(QLabel("Limit lines (for a quick test)"))
        cl.addWidget(self.maxlines)
        lay.addWidget(c)
        lay.addStretch(1)
        return w

    def _voice_page(self) -> QWidget:
        w, lay = page_shell()
        lay.addWidget(heading("Your voice", "Add clean recordings of yourself speaking. 10+ minutes works best."))
        self.files: list[str] = []
        self.voice_box = QComboBox()
        self.voice_box.currentIndexChanged.connect(self._voice_choice_changed)
        lay.addWidget(QLabel("Voice model"))
        lay.addWidget(self.voice_box)
        self.drop = DropLabel(self._add_paths)
        lay.addWidget(self.drop)
        self.file_list = QListWidget()
        lay.addWidget(self.file_list, 1)
        return w

    def _run_page(self) -> QWidget:
        w, lay = page_shell()
        lay.addWidget(heading("Make my mod", "One click: extract → prepare → train → convert → package → install."))
        c, cl = card()
        self.stage_lbl = QLabel("Ready")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Mod name (default: <character>_voice). Each name keeps its own work.")
        self.fresh = QCheckBox("Start from scratch (ignore previous work for this mod name)")
        cl.addWidget(QLabel("Mod name"))
        cl.addWidget(self.name_edit)
        cl.addWidget(self.fresh)
        self.go = QPushButton("Make my mod")
        self.go.setObjectName("primary")
        self.go.clicked.connect(self._start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.runner.cancel)
        row = QHBoxLayout()
        row.addWidget(self.go)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        self.dl_btn = QPushButton("Show download")
        self.dl_btn.setVisible(False)
        self.dl_btn.clicked.connect(lambda: self.install_window and (self.install_window.show(),
                                                                      self.install_window.raise_()))
        row.addWidget(self.dl_btn)
        for label, target in [("Open mod folder", lambda: self._open(self.project.dir("out") if self.project.root.exists() else PROJECTS_DIR)),
                              ("Open logs", lambda: self._open(LOG_FILE.parent))]:
            b = QPushButton(label)
            b.clicked.connect(target)
            row.addWidget(b)
        cl.addWidget(self.stage_lbl)
        cl.addWidget(self.bar)
        cl.addLayout(row)
        lay.addWidget(c)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        return w

    # ---- saved voices
    def _refresh_voices(self):
        keep = self.voice_box.currentData()
        self.voice_box.blockSignals(True)
        self.voice_box.clear()
        self.voice_box.addItem("Train a new voice from my recordings", "")
        for v in list_voices(self.engine_box.currentData()):
            self.voice_box.addItem(f"Reuse saved voice: {v.label}", str(v.path))
        i = self.voice_box.findData(keep)
        self.voice_box.setCurrentIndex(max(i, 0))
        self.voice_box.blockSignals(False)
        self._voice_choice_changed()

    def _voice_choice_changed(self, _=None):
        train_new = not self.voice_box.currentData()
        self.drop.setEnabled(train_new)
        self.file_list.setEnabled(train_new)
        self.drop.setText("Drop your voice recordings (files or folders) here\nor click to browse" if train_new
                          else "Using a saved voice: no recordings or training needed.")

    # ---- helpers
    def _autodetect(self):
        g = find_bg3()
        if g and not self.game_edit.text():
            self.game_edit.setText(str(g.game_dir))
        if g and g.appdata_dir and not self.appdata_edit.text():
            self.appdata_edit.setText(str(g.appdata_dir))
        kind = "native Linux build" if g and g.native else "Windows build (Proton)"
        self.detect_lbl.setText(
            f"Game detected ({kind}); user data folder found." if g and g.appdata_dir
            else f"Game detected ({kind}), but its user data folder wasn't found. Use Find… or Browse… below "
                 "(run the game once first so it creates it)." if g
            else "Game not auto-detected; choose the folders.")

    def _find_appdata(self):
        self.find_btn.setEnabled(False)
        self.find_btn.setText("Searching…")
        self._find_thread = t = FuncThread(lambda _p: search_appdata())

        def done(hits):
            self.find_btn.setEnabled(True)
            self.find_btn.setText("Find…")
            if not hits:
                QMessageBox.information(self, "Not found",
                                        "No game user data found. Launch Baldur's Gate 3 once (so it creates it), "
                                        "then try again, or use Browse….")
                return
            choice = str(hits[0])
            if len(hits) > 1:
                choice, ok = QInputDialog.getItem(self, "Choose user data folder",
                                                  "Several were found (most recently used first):",
                                                  [str(h) for h in hits], 0, False)
                if not ok:
                    return
            self.appdata_edit.setText(choice)

        t.result.connect(done)
        t.failed.connect(lambda m: (self.find_btn.setEnabled(True), self.find_btn.setText("Find…"),
                                    QMessageBox.warning(self, "Search failed", m)))
        t.start()

    def _open(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _pick_dir(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
        if d:
            edit.setText(d)

    def _pick_file(self, edit, flt):
        f, _ = QFileDialog.getOpenFileName(self, "Choose file", edit.text(), flt)
        if f:
            edit.setText(f)

    def _add_paths(self, paths):
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.file_list.addItem(p)

    def _start(self):
        speaker = self.speaker_box.currentData() or self.speaker_box.currentText().split(" — ")[0].strip()
        voice_model = self.voice_box.currentData() or ""
        if not speaker or (not self.files and not voice_model):
            self.log.appendPlainText("Pick a character and add at least one recording first.")
            return
        if not self.ensure_vgmstream():
            self.log.appendPlainText("vgmstream is required to read game audio; install it and try again.")
            return
        s = self.settings
        s.game_dir = self.game_edit.text()
        s.bg3_appdata = self.appdata_edit.text().strip()
        s.engine = self.engine_box.currentData()
        s.save()
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.name_edit.text().strip() or f"{speaker}_voice").strip("_")
        root = PROJECTS_DIR / name
        p = Project.load(root) if (root / "project.json").exists() else Project.create(name)
        self.project = p
        p.speaker = speaker
        p.voice_inputs = list(self.files)
        p.voice_model = voice_model
        p.engine = self.engine_box.currentData()
        p.preset = self.preset_box.currentData()
        p.auto_pitch = self.auto_pitch.isChecked()
        p.transpose = self.pitch_spin.value()
        p.max_lines = self.maxlines.value()
        p.save()
        eng = ENGINES[p.engine]()
        installer = self.installer if (self.installer and self.installer.running
                                       and self.installer.engine.name == p.engine) else None
        if installer is None and not eng.available()[0] and eng.install_size_hint:
            ok = QMessageBox.question(
                self, "Download voice engine",
                f"{eng.label} needs a one-time download ({eng.install_size_hint}).\n\n"
                "It starts now, in the background. The steps that don't need it (finding and extracting "
                "voice lines, preparing your recordings) run meanwhile; training waits if needed. Continue?")
            if ok != QMessageBox.Yes:
                return
            installer = self.installer = BackgroundInstall(eng)
            self.install_window = InstallWindow(self, installer)
            self.install_window.show()
            installer.start()
        if installer is not None:
            self.dl_btn.setVisible(True)
        self.go.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.runner.start(p, s, {st.name for st in STAGES} if self.fresh.isChecked() else None, installer)

    def _on_progress(self, frac, msg):
        self.bar.setValue(int(frac * 1000))
        if re.search(r"\d+/\d+$", msg):  # per-file counter: show in the label, don't spam the log
            self.stage_lbl.setText(f"{self._stage_text}  ({msg.rsplit(' ', 1)[-1]})")
        else:
            self.log.appendPlainText(msg)

    def _on_stage(self, i, n, label):
        self._stage_text = f"Step {i + 1}/{n}: {label}"
        self.stage_lbl.setText(self._stage_text)
        self.log.appendPlainText(self._stage_text)

    def _on_failed(self, msg):
        self.log.appendPlainText(f"ERROR: {msg}\nDetails: {LOG_FILE}")
        self._finish("Failed. See log; fix the issue and run again to resume.")

    def _on_done(self):
        self._refresh_voices()
        out = self.project.dir("out")
        installed = (self.project.dir("state") / "install.done").exists()
        self._finish("Done! Launch the game and your voice is in." if installed
                     else f"Mod built but not installed. Find it in: {out}")

    def _finish(self, text):
        self.stage_lbl.setText(text)
        self.go.setEnabled(True)
        self.cancel_btn.setEnabled(False)
