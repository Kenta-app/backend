import json
from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from app.ml.training.datasets import FNCDataset
from app.ml.training.train_stance import evaluate
from torch.utils.data import DataLoader

MODEL_DIRS = [
    Path('output/stance_bert/best_model'),
    Path('output/stance_mbert_weighted/best_model'),
    Path('output/stance_distilmbert_weighted/best_model'),
]
TEST_STANCES = 'data/fnc-1/competition_test_stances.csv'
TEST_BODIES = 'data/fnc-1/competition_test_bodies.csv'

results = {}
for mdir in MODEL_DIRS:
    key = str(mdir.parent)
    print('Evaluating', key)
    if not mdir.exists():
        results[key] = {'error':'best_model missing'}
        print('  missing best_model')
        continue
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(mdir))
        model = AutoModelForSequenceClassification.from_pretrained(str(mdir))
        device = torch.device('cpu')
        model.to(device)
        ds = FNCDataset(TEST_STANCES, TEST_BODIES, tokenizer, max_length=192)
        dl = DataLoader(ds, batch_size=32)
        metrics = evaluate(model, dl, device)
        sc_path = mdir / 'serving_config.json'
        if sc_path.exists():
            sc = json.loads(sc_path.read_text(encoding='utf-8'))
        else:
            sc = {}
        sc['test_metrics'] = metrics
        sc_path.write_text(json.dumps(sc, indent=2, ensure_ascii=False), encoding='utf-8')
        results[key] = metrics
        print('  done: macro_f1=', metrics.get('macro_f1'))
    except Exception as e:
        results[key] = {'error': str(e)}
        print('  error:', e)

print('\nSummary:')
for k,v in results.items():
    if 'error' in v:
        print(k, '-> ERROR:', v['error'])
    else:
        print(k, '-> macro_f1={:.4f} acc={:.4f}'.format(v.get('macro_f1',0), v.get('accuracy',0)))
