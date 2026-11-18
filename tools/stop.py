"""Stop only this package's BOPTEST Docker stack, without a dashboard."""
import sys
from support import ROOT, activity, compose, no_foreign_tests

def stop():
    with activity():
        release = ROOT/'runtime/project1-boptest-0.9.0/docker-compose.yml'
        if not release.exists():
            print('BOPTEST is not installed in this folder; nothing to stop.')
            return
        if compose('ps','-q','redis'):
            no_foreign_tests(None)
        compose('down')
    print('PASS: this package Docker project stopped; research outputs preserved')

if __name__ == '__main__':
    try: stop()
    except Exception as exc:
        print('FAIL: '+str(exc),file=sys.stderr)
        sys.exit(1)
