from pathlib import Path
from pprint import pprint
from quantflow.web.service import StationService, ValidationRequest
from quantflow.web.history import StationHistoryStore
store = StationHistoryStore(base_dir=Path('data')/'station_history_probe2')
service = StationService(history_store=store)
for method in ['cpcv','wfo']:
    payload = service.validate(ValidationRequest(strategy='trend_following', symbol='BTC/USDT', method=method, optimize_trials=2, n_trials=5, wfo_windows=2, groups=4, test_groups=1))
    print('METHOD', method)
    result = payload['result']
    if method == 'cpcv':
        preview = result.get('path_results', [])[:2]
        pprint(preview)
    else:
        print('rolling window preview')
        pprint(result.get('rolling', {}).get('window_results', [])[:2])
        print('anchored window preview')
        pprint(result.get('anchored', {}).get('window_results', [])[:2])
    print()
