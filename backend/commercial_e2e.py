"""Temporary HTTP/SQLite operations, concurrency, dashboard, CSV and backup E2E."""
import argparse,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
from test_phase9d import OperationsTests
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--concurrency-only',action='store_true');args=p.parse_args()
 names=['test_concurrent_admin_writers_only_one_commits','test_two_http_admins_stale_write_is_rejected'] if args.concurrency_only else unittest.defaultTestLoader.getTestCaseNames(OperationsTests)
 result=unittest.TextTestRunner().run(unittest.TestSuite(OperationsTests(n) for n in names))
 args.output.write_text(json.dumps({'passed':result.wasSuccessful(),'checks':names,'storage':'temporary SQLite','providers':'synthetic'},indent=2),encoding='utf8');raise SystemExit(0 if result.wasSuccessful() else 1)
