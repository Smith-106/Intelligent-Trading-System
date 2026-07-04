from pathlib import Path
from pprint import pprint
from quantflow.web.service import StationService, ValidationRequest
from quantflow.web.history import StationHistoryStore
store = StationHistoryStore(base_dir=Path('data')/'station_history_probe3')
service = StationService(history_store=store)
payload = service.validate(ValidationRequest(strategy='trend_following', symbol='BTC/USDT', method='gate', optimize_trials=2, n_trials=5, wfo_windows=2, groups=4, test_groups=1))
pprint(payload['result'])
