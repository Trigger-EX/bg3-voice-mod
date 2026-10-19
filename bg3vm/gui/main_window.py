from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from bg3vm.core.config import Settings
from bg3vm.core.pipeline import STAGES
from bg3vm.core.project import Project
from bg3vm.engines import ENGINES
from bg3vm.game.steam import find_bg3
from bg3vm.gui.runner import JobRunner


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
        self.project = Project(name="my_voice_mod", root=Path.home() / ".local/share/bg3vm/projects/my_voice_mod")
        self.runner = JobRunner()
        self.runner.progress.connect(self._on_progress)
        self.runner.stage.connect(self._on_stage)
        self.runner.failed.connect(self._on_failed)
        self.runner.done.connect(lambda: self._finish("Done! Launch the game and your voice is in."))
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
        self.nav.setCurrentRow(0)
        h.addWidget(self.nav)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._autodetect()

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
        self.detect_lbl = QLabel("")
        self.detect_lbl.setObjectName("muted")
        cl.addWidget(self.detect_lbl)
        self.speaker_edit = QLineEdit()
        self.speaker_edit.setPlaceholderText("Character name, e.g. Astarion")
        self.map_edit = QLineEdit()
        self.map_edit.setPlaceholderText("speakers.json (character → voice line handles)")
        mb = QPushButton("Browse…")
        mb.clicked.connect(lambda: self._pick_file(self.map_edit, "JSON (*.json)"))
        r2 = QHBoxLayout()
        r2.addWidget(self.map_edit, 1)
        r2.addWidget(mb)
        cl.addWidget(QLabel("Character"))
        cl.addWidget(self.speaker_edit)
        cl.addWidget(QLabel("Speaker map"))
        cl.addLayout(r2)
        self.engine_box = QComboBox()
        for k, cls in ENGINES.items():
            self.engine_box.addItem(cls.label, k)
        cl.addWidget(QLabel("Voice engine"))
        cl.addWidget(self.engine_box)
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
        lay.addWidget(DropLabel(self._add_paths))
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
        cl.addWidget(self.stage_lbl)
        cl.addWidget(self.bar)
        cl.addLayout(row)
        lay.addWidget(c)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
        return w

    # ---- helpers
    def _autodetect(self):
        g = find_bg3()
        if g and not self.game_edit.text():
            self.game_edit.setText(str(g.game_dir))
        self.detect_lbl.setText(
            f"Detected Proton prefix: {g.appdata_dir}" if g and g.appdata_dir
            else "Game found." if g else "Game not auto-detected; choose the folder.")

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
        if not self.speaker_edit.text().strip() or not self.files:
            self.log.appendPlainText("Pick a character and add at least one recording first.")
            return
        s = self.settings
        s.game_dir = self.game_edit.text()
        g = find_bg3()
        s.bg3_appdata = str(g.appdata_dir) if g and g.appdata_dir else ""
        s.save()
        p = self.project
        p.speaker = self.speaker_edit.text().strip()
        p.speaker_map = self.map_edit.text().strip()
        p.voice_inputs = list(self.files)
        p.engine = self.engine_box.currentData()
        p.max_lines = self.maxlines.value()
        p.save()
        self.go.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.runner.start(p, s)

    def _on_progress(self, frac, msg):
        self.bar.setValue(int(frac * 1000))
        self.log.appendPlainText(msg)

    def _on_stage(self, i, n, label):
        self.stage_lbl.setText(f"Step {i + 1}/{n}: {label}")

    def _on_failed(self, msg):
        self.log.appendPlainText(f"ERROR: {msg}")
        self._finish("Failed. See log; fix the issue and run again to resume.")

    def _finish(self, text):
        self.stage_lbl.setText(text)
        self.go.setEnabled(True)
        self.cancel_btn.setEnabled(False)
