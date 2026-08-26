import json
import os
import sys
from pathlib import Path

import render_and_upload_v2 as worker
import run_v6_dynamic as dynamic

claim_path = Path(os.environ.get('MSD_CLAIM_FILE') or 'worker/claimed_job.json')
if not claim_path.exists():
    print('Claim-Datei fehlt:', claim_path)
    sys.exit(2)

job = json.loads(claim_path.read_text(encoding='utf-8'))
original_get = worker.requests.get
served = {'done': False}


class ClaimedResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {'job': self._payload}


def get_with_claim(url, *args, **kwargs):
    if not served['done'] and str(url).rstrip('/') == str(worker.WORKER_URL).rstrip('/'):
        served['done'] = True
        return ClaimedResponse(job)
    return original_get(url, *args, **kwargs)


worker.requests.get = get_with_claim

if __name__ == '__main__':
    sys.exit(dynamic.main())
