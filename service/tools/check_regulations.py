"""Scheduled/manual source check. Uses the same durable lease and due date as the app."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import regulation_monitor

def main():
    p=argparse.ArgumentParser();p.add_argument('--due',action='store_true',help='Run only when the persisted schedule is due')
    p.add_argument('--force',action='store_true',help='Manual check (one-minute cooldown)');args=p.parse_args()
    result=regulation_monitor.run_due(force=args.force and not args.due)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 1 if result['status']=='failed' else 0

if __name__=='__main__':raise SystemExit(main())
