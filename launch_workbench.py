"""Launch the exact V10 host only after a previously verified mode still passes."""
import subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from configure_runtime import main as verify

def main():
    result=verify(['--launch-check'])
    if result:return result
    executable=ROOT/'app/EXE/初始结构优化工作台-V10.0.0.exe'
    if not executable.is_file():print('Missing V10.0.0 EXE; clone or extract the complete repository.');return 2
    subprocess.Popen([str(executable)],cwd=str(executable.parent))
    return 0

if __name__=='__main__':raise SystemExit(main())
