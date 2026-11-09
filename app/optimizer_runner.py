"""Process entry point; optimization executes the unchanged upstream main."""
def main():
    from native_autolens_runner import main as run
    return run()
if __name__=='__main__':raise SystemExit(main())
