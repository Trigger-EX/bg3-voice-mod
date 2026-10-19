from bg3vm.bootstrap import ensure_environment


def main() -> int:
    ensure_environment()  # may re-exec inside the app-local venv
    from bg3vm.app import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
