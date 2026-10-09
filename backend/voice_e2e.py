"""Temporary HTTP admin -> configuration -> new conversation -> speech adapter E2E."""
import argparse,json,sys,unittest,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
from test_phase9c import PersonalizationTests

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    names=['test_edge_sdk_receives_selected_parameters','test_voice_end_to_end_new_conversation_uses_selection','test_voice_snapshot_stable_and_legacy_preserved','test_voice_validation_and_fixed_preview_limit','test_branding_end_to_end_etag_public_whitelist_audit']
    start=time.perf_counter();result=unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(PersonalizationTests(n) for n in names))
    report={'passed':result.wasSuccessful(),'checks':names,'duration_ms':round((time.perf_counter()-start)*1000),'providers':'synthetic adapter; real HTTP/services/SQLite'}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf8');return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
