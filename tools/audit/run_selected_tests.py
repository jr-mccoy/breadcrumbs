#!/usr/bin/env python3
"""Run the audit's explicitly selected upstream tests without altering them.

Run from a full Breadcrumbs checkout. In this audit only a release sdist was
available locally; the excluded fixtures were not shipped there. The startup
module assertion assumes a pristine interpreter, unlike this audit environment.
None of these exclusions claims that the corresponding product feature passed.
"""
import argparse, json, os, sys, unittest
from pathlib import Path

MODULES = ['test_parser', 'test_sections', 'test_naming', 'test_lock',
           'test_searchindex', 'test_aliases', 'test_handoffs', 'test_scope',
           'test_inbox', 'test_lifecycle', 'test_usage', 'test_hooklog']
EXCLUDED = {
 'test_parser.CommentOnlyValueTests.test_superseded_without_a_target_fails_validate': 'test data absent from release sdist',
 'test_parser.FenceAwareSectionsTests.test_validate_sees_no_next_action_in_a_fence': 'test data absent from release sdist',
 'test_parser.RecordModelTests.test_load_records_walks_type_dirs': 'test data absent from release sdist',
 'test_searchindex.FixtureEquivalenceTests.test_fixture_10_answers_the_same_through_the_index': 'fixture-10 absent from release sdist',
 'test_parser.StartupCostTests.test_version_is_not_resolved_while_building_the_parser': 'audit interpreter imports metadata/email/zipfile/csv before Breadcrumbs; separately verified',
}

def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,default=Path.cwd())
    ap.add_argument('--output',type=Path)
    args=ap.parse_args()
    sys.dont_write_bytecode=True
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    root=args.source.resolve()
    sys.path[:0]=[str(root), str(root/'tests')]
    tests=list(flatten(unittest.defaultTestLoader.loadTestsFromNames(MODULES)))
    selected=[t for t in tests if t.id() not in EXCLUDED]
    result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    report={'modules':MODULES,'excluded':EXCLUDED,'tests_run':result.testsRun,
            'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'successful':result.wasSuccessful(),
            'note':'Selected upstream tests only; not the complete repository test suite.'}
    if args.output:args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':
    raise SystemExit(main())
