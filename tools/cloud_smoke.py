"""Run the same authenticated HTTP/persistence journey against a built container."""
import argparse
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--allow-dirty', action='store_true', help='Local development image only; CI uses a clean release.')
    args = parser.parse_args()
    os.environ['GONGMUDAM_TEST_IMAGE'] = args.image
    os.environ['GONGMUDAM_TEST_ALLOW_DIRTY_IMAGE'] = '1' if args.allow_dirty else '0'
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_cloud_runtime import CloudRuntimeTests
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CloudRuntimeTests))
    sys.exit(0 if result.wasSuccessful() else 1)
