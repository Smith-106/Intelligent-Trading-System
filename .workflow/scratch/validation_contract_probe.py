from pathlib import Path
from quantflow.web.service import StationService, ValidationRequest
from quantflow.web.history import StationHistoryStore
store = StationHistoryStore(base_dir=Path('data')/'station_history_probe')
service = StationService(history_store=store)
for method in ['gate','dsr','pbo','cpcv','wfo']:
    try:
        payload = service.validate(ValidationRequest(strategy='trend_following', symbol='BTC/USDT', method=method, optimize_trials=2, n_trials=5, wfo_windows=2, groups=4, test_groups=1))
        result = payload.get('result', {})
        print('METHOD', method)
        print('RESULT_KEYS', sorted(result.keys()) if isinstance(result, dict) else type(result).__name__)
        if method == 'gate':
            print('CHECK_KEYS', sorted(result.get('checks', {}).keys()))
        if method == 'dsr':
            print('BACKTEST_KEYS', sorted(payload.get('backtest', {}).keys())[:8], '...')
        if method == 'cpcv':
            print('PATH_RESULTS_LEN', len(result.get('path_results', [])))
        if method == 'wfo':
            print('ROLLING_KEYS', sorted(result.get('rolling', {}).keys()))
        print()
    except Exception as exc:
        print('METHOD', method, 'ERROR', type(exc).__name__, exc)
