import json
from collections import Counter
import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='Duplicate true items to balance a claims JSONL dataset')
    parser.add_argument('--factor', type=int, default=15, help='How many times to duplicate true items')
    args = parser.parse_args()

    input_path = Path('data/perucheck/claims.jsonl')
    output_path = Path('data/perucheck/claims_balanceado.jsonl')

    if not input_path.exists():
        raise FileNotFoundError(f'No existe el archivo de entrada: {input_path}')

    datos = []
    skipped_lines = 0
    with input_path.open('r', encoding='utf-8') as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                skipped_lines += 1
                continue

            try:
                datos.append(json.loads(line))
            except json.JSONDecodeError as exc:
                skipped_lines += 1
                print(
                    f'Advertencia: línea inválida en {input_path} ({line_number}): {exc}',
                    file=sys.stderr,
                )

    if skipped_lines:
        print(f'Advertencia: se omitieron {skipped_lines} líneas vacías o inválidas.', file=sys.stderr)

    false_items = [d for d in datos if d.get('label') == 'false']
    true_items = [d for d in datos if d.get('label') == 'true']

    print(f"Antes - False: {len(false_items)}, True: {len(true_items)}")

    true_items_duplicados = true_items * args.factor
    dataset_final = false_items + true_items_duplicados

    print(f"Después - False: {len(false_items)}, True: {len(true_items_duplicados)}")

    with output_path.open('w', encoding='utf-8') as f:
        for item in dataset_final:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()