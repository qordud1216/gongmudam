"""Register explicitly selected PDFs as full-page e-사람 usage references."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import manual_knowledge
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pdfs',nargs='+',type=Path);a=p.parse_args()
    def progress(v):print(json.dumps(dict(progress=v),ensure_ascii=False),flush=True)
    print(json.dumps(manual_knowledge.register_files(a.pdfs,progress),ensure_ascii=False,indent=2))
