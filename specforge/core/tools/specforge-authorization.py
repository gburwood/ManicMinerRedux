#!/usr/bin/env python3
from pathlib import Path
import argparse,json,sys
from specforge_project import discover_layout
from specforge_authority import evaluate,accept

def main():
    p=argparse.ArgumentParser(description="Check or advance durable SpecForge material authority.")
    p.add_argument("command",nargs="?",choices=("check","accept"),default="check")
    p.add_argument("--root",default=".")
    p.add_argument("--json",action="store_true")
    a=p.parse_args()
    try: layout=discover_layout(Path(a.root).resolve())
    except Exception as exc:
        out={"valid":False,"accepted":False,"blockers":[f"project_discovery_failed:{exc}"]}
        print(json.dumps(out,indent=2) if a.json else out); return 1
    out=accept(layout) if a.command=="accept" else evaluate(layout)
    ok=out.get("accepted",out.get("valid",False))
    print(json.dumps(out,indent=2) if a.json else ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1

if __name__=="__main__": sys.exit(main())
