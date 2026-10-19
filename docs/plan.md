# BG3 Voice Replacer: plan (summary)

- Engine: RVC v2 voice conversion via Applio (pinned tag, own venv), behind `VoiceEngine` interface.
  Conversion keeps timing/emotion of the original line, so lip-sync and lengths stay valid.
- Pure-Python LSPK v18 pak reader/writer and .loca reader; LSLib `divine` only as optional fallback.
- WEM output: Wwise-style PCM RIFF (primary, UNVERIFIED in-game); Wwise Vorbis via WwiseConsole under Proton as fallback.
- Character -> line mapping: RESOLVED from filenames. Voice wems are `v<speaker-uuid>_h<loca-handle>.wem`
  (BG3 Modding Community Wiki), so speaker = filename prefix; no LSF parsing needed. Known prefixes in `game/voicemeta.py`.
- Stages (resumable, `.done` markers): index, extract, dataset, train, convert, encode, package, install.
- GUI: PySide6 sidebar wizard + "Make my mod" one-click button.

## Unverified / needs game or GPU
PCM .wem playback in BG3; exact Voice.pak internal paths; VoiceMeta LSF format; modsettings handling after Patch 7;
Applio CLI flags; training quality on GPU/ROCm.
