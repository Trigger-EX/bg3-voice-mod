from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from bg3vm.core.config import Settings
from bg3vm.core.pipeline import STAGES
from bg3vm.core.project import Project
from bg3vm.engines import ENGINES
from bg3vm.audio.vgmstream import find_vgmstream, install_vgmstream
from bg3vm.game.steam import GameInstall, find_bg3
from bg3vm.game.voicemeta import index_voice_paks, list_speakers
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

    def _scan(self):
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
            return list_speakers(index_voice_paks(paks))

        self._scan_thread = t = FuncThread(work)
        t.result.connect(self._scan_done)
        t.failed.connect(lambda m: (QMessageBox.warning(self, "Scan failed", m), self._scan_reset()))
        t.start()

    def _scan_reset(self):
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan game for characters")

    def _scan_done(self, speakers):
        self.speaker_box.clear()
        for sp in speakers:
            self.speaker_box.addItem(f"{sp.name} — {sp.lines} lines", sp.id)
        self._scan_reset()

    def _current_game(self) -> GameInstall | None:
        text = self.game_edit.text().strip()
        if not text:
            return None
        found = find_bg3()
        return GameInstall(Path(text), found.appdata_dir if found else None)

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
        self.speaker_box = QComboBox()
        self.speaker_box.setEditable(True)
        self.speaker_box.lineEdit().setPlaceholderText("Scan the game, or type a name (e.g. Astarion)")
        self.scan_btn = QPushButton("Scan game for characters")
        self.scan_btn.clicked.connect(self._scan)
        r2 = QHBoxLayout()
        r2.addWidget(self.speaker_box, 1)
        r2.addWidget(self.scan_btn)
        cl.addWidget(QLabel("Character to replace"))
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
        speaker = self.speaker_box.currentData() or self.speaker_box.currentText().split(" — ")[0].strip()
        if not speaker or not self.files:
            self.log.appendPlainText("Pick a character and add at least one recording first.")
            return
        if not self.ensure_vgmstream():
            self.log.appendPlainText("vgmstream is required to read game audio; install it and try again.")
            return
        s = self.settings
        s.game_dir = self.game_edit.text()
        g = find_bg3()
        s.bg3_appdata = str(g.appdata_dir) if g and g.appdata_dir else ""
        s.save()
        p = self.project
        p.speaker = speaker
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
