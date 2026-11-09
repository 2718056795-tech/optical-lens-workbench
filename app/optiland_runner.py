"""Independent Optiland entry; AutoLens imports are forbidden."""
from native_sources import configure_optiland_runtime
from engine_isolation import install
configure_optiland_runtime();install()
def main():
    from native_optiland_runner import main as native_main
    return native_main()
if __name__=='__main__':raise SystemExit(main())
